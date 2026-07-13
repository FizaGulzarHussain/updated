"""
store.py — SQLite-backed persistent, shared store for the fast.site Lead Finder.
────────────────────────────────────────────────────────────────────────────────
Replaces the per-session, in-memory st.session_state data with a single SQLite
file so leads, audits, contacts, contacted-status, ownership and history persist
across sessions and are SHARED across everyone hitting the same server instance.

This is deliberately a small, explicit FUNCTION API (not an ORM) so it can be
swapped for Postgres / Supabase later by re-implementing these same functions
against a different connection — the rest of the app only ever calls these names.

Model: one table, `leads`, keyed by url. The complex audit / cdn / tech / contact
structures are stored as JSON blobs; the handful of fields we filter, sort and
display (scores, status, owner, contacted) live in real columns.

Scope (SQLite-first): persists + shares across sessions on ONE running instance.
Not multi-instance cloud storage — that's the Postgres/Supabase upgrade, which
this API is shaped to allow without touching call sites.
"""
from __future__ import annotations
import re
import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

_DB_PATH = Path(__file__).parent / "leadfinder.db"
_LOCK = threading.Lock()          # serialize writes (SQLite is single-writer)

# Status lifecycle a rep moves a lead through. Kept here so the UI and store
# agree on the vocabulary.
STATUSES = ["new", "contacted", "replied", "booked", "won", "lost"]


def _domain(url: str) -> str:
    m = re.search(r"https?://(?:www\.)?([^/]+)", url or "")
    return m.group(1) if m else (url or "")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _dumps(x):
    return json.dumps(x) if x is not None else None


def _loads(s):
    try:
        return json.loads(s) if s else None
    except Exception:
        return None


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")   # concurrent reads while writing
    except Exception:
        pass
    return c


def init_db() -> None:
    """Create the leads table if it doesn't exist. Safe to call on every run."""
    with _LOCK, _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                url            TEXT PRIMARY KEY,
                business_name  TEXT,
                domain         TEXT,
                opportunity    INTEGER,
                speed          INTEGER,
                overall        INTEGER,
                status         TEXT DEFAULT 'new',
                owner          TEXT,
                contacted_by   TEXT,
                contacted_at   TEXT,
                first_seen     TEXT,
                last_updated   TEXT,
                check_count    INTEGER DEFAULT 0,
                audit_json     TEXT,
                cdn_json       TEXT,
                tech_json      TEXT,
                contact_json   TEXT
            )
        """)


def upsert_lead(url: str, *, business_name=None, audit=None, cdn=None, tech=None,
                contact=None, opportunity=None, speed=None, overall=None,
                owner=None, bump_check: bool = False) -> None:
    """Insert or update a lead. Only non-None arguments overwrite existing values
    (JSON blobs are replaced only when provided), so a contact-only update never
    wipes the stored audit and vice-versa. `owner` is set-once — the first rep to
    touch a lead owns it; later audits by anyone else don't steal ownership.
    `bump_check` increments the re-check counter (used when an audit runs)."""
    if not url:
        return
    now = _now()
    with _LOCK, _conn() as c:
        row = c.execute("SELECT * FROM leads WHERE url=?", (url,)).fetchone()
        if row is None:
            c.execute("""INSERT INTO leads
                (url, business_name, domain, opportunity, speed, overall,
                 status, owner, first_seen, last_updated, check_count,
                 audit_json, cdn_json, tech_json, contact_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (url, business_name, _domain(url), opportunity, speed, overall,
                 "new", owner, now, now, 1 if bump_check else 0,
                 _dumps(audit), _dumps(cdn), _dumps(tech), _dumps(contact)))
        else:
            keep = lambda new, col: new if new is not None else row[col]
            keep_json = lambda new, col: _dumps(new) if new is not None else row[col]
            c.execute("""UPDATE leads SET
                    business_name=?, domain=?, opportunity=?, speed=?, overall=?,
                    owner=COALESCE(owner, ?), last_updated=?, check_count=?,
                    audit_json=?, cdn_json=?, tech_json=?, contact_json=?
                WHERE url=?""",
                (keep(business_name, "business_name"), _domain(url),
                 keep(opportunity, "opportunity"), keep(speed, "speed"),
                 keep(overall, "overall"),
                 owner, now,
                 (row["check_count"] or 0) + (1 if bump_check else 0),
                 keep_json(audit, "audit_json"), keep_json(cdn, "cdn_json"),
                 keep_json(tech, "tech_json"), keep_json(contact, "contact_json"),
                 url))


def set_contacted(url: str, by: str) -> None:
    """Record that `by` emailed this lead now, and advance a still-'new' lead to
    'contacted' (never downgrades a lead already further along the pipeline)."""
    now = _now()
    with _LOCK, _conn() as c:
        c.execute("""UPDATE leads SET
                contacted_by=?, contacted_at=?, last_updated=?,
                status=CASE WHEN status='new' OR status IS NULL THEN 'contacted' ELSE status END
            WHERE url=?""", (by, now, now, url))


def set_status(url: str, status: str) -> None:
    with _LOCK, _conn() as c:
        c.execute("UPDATE leads SET status=?, last_updated=? WHERE url=?",
                  (status, _now(), url))


def claim_lead(url: str, owner: str) -> None:
    """Explicitly (re)assign ownership — the one place owner is allowed to change."""
    with _LOCK, _conn() as c:
        c.execute("UPDATE leads SET owner=?, last_updated=? WHERE url=?",
                  (owner, _now(), url))


def _rowdict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["audit"]   = _loads(d.pop("audit_json"))
    d["cdn"]     = _loads(d.pop("cdn_json"))
    d["tech"]    = _loads(d.pop("tech_json"))
    d["contact"] = _loads(d.pop("contact_json"))
    return d


def get_lead(url: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM leads WHERE url=?", (url,)).fetchone()
    return _rowdict(row) if row else None


def all_leads() -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM leads ORDER BY last_updated DESC").fetchall()
    return [_rowdict(r) for r in rows]


def counts() -> dict:
    """Team-wide roll-up for the Settings dashboard."""
    with _conn() as c:
        total     = c.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        contacted = c.execute("SELECT COUNT(*) FROM leads WHERE contacted_at IS NOT NULL").fetchone()[0]
        by_status = dict(c.execute(
            "SELECT COALESCE(status,'new'), COUNT(*) FROM leads GROUP BY status").fetchall())
        by_owner  = dict(c.execute(
            "SELECT COALESCE(owner,'unassigned'), COUNT(*) FROM leads GROUP BY owner").fetchall())
    return {"total": total, "contacted": contacted,
            "by_status": by_status, "by_owner": by_owner}


def clear_all() -> None:
    """Wipe the shared store. Destructive — the UI gates this behind a confirm."""
    with _LOCK, _conn() as c:
        c.execute("DELETE FROM leads")
