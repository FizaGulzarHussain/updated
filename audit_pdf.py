from __future__ import annotations
import io, re, os, math, json, threading
from datetime import datetime
from html import escape as _esc
import urllib.request, urllib.error
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether, Image,
)
from reportlab.platypus.flowables import Flowable

# ─── LOGO ─────────────────────────────────────────────────────────────────────
_HERE     = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(_HERE, "fastsite_logo.png")

# ─── PALETTE ──────────────────────────────────────────────────────────────────
BLUE     = colors.HexColor("#1F62FF")
BLUE_DIM = colors.HexColor("#93B5FF")
BLUE_BG  = colors.HexColor("#EEF3FF")
DARK     = colors.HexColor("#1A1925")
GRAY     = colors.HexColor("#64748B")
RULE     = colors.HexColor("#E2E8F0")
LIGHT    = colors.HexColor("#F8FAFC")
WHITE    = colors.HexColor("#FFFFFF")
GREEN    = colors.HexColor("#059669")
GREEN_BG = colors.HexColor("#ECFDF5")
AMBER    = colors.HexColor("#D97706")
AMBER_BG = colors.HexColor("#FFFBEB")
RED      = colors.HexColor("#DC2626")
RED_BG   = colors.HexColor("#FEF2F2")
SKY      = colors.HexColor("#0284C7")
PAGE_W, PAGE_H = A4
L    = 20 * mm
R    = 20 * mm
T    = 22 * mm
B    = 20 * mm
CW   = PAGE_W - L - R
FPAD = 6

# ─── LANGUAGE ─────────────────────────────────────────────────────────────────
_LANG = "en"
def _t(en, de=None):
    if _LANG == "de" and de is not None:
        return de
    return en

_SEV_LABELS_DE = {"CRITICAL": "KRITISCH", "HIGH": "HOCH", "MEDIUM": "MITTEL", "LOW": "GERING"}
_CAT_LABELS_DE = {
    "SEO": "SEO", "Speed": "Geschwindigkeit", "Performance": "Leistung",
    "Mobile": "Mobil", "DDoS & Security": "DDoS & Sicherheit",
    "Page Ranking": "Seitenranking", "Client Reach": "Reichweite", "Trust": "Vertrauen",
}

def _sev_label(sev: str) -> str:
    if _LANG == "de":
        return _SEV_LABELS_DE.get(sev, sev)
    return sev

def _cat_label(en: str) -> str:
    if _LANG == "de":
        return _CAT_LABELS_DE.get(en, en)
    return en

CATS = [
    ("SEO", "seo", "#3B82F6"),
    ("Speed", "speed", "#8B5CF6"),
    ("Performance", "performance", "#EC4899"),
    ("Page Ranking", "page_ranking", "#F59E0B"),
    ("Mobile", "mobile", "#10B981"),
    ("DDoS & Security", "ddos_security", "#EF4444"),
    ("Client Reach", "client_reach", "#06B6D4"),
    ("Trust", "trust", "#6366F1"),
]

# ─── TINY HELPERS ────────────────────────────────────────────────────────────
def _fmt_s(v):
    """Format a millisecond value as '2.1s' or '921ms' depending on magnitude."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    return f"{v/1000:.1f}s" if v >= 1000 else f"{int(round(v))}ms"


def _sc(score: int):
    return GREEN if score >= 75 else (AMBER if score >= 60 else RED)

def _sc_bg(score: int):
    return GREEN_BG if score >= 75 else (AMBER_BG if score >= 60 else RED_BG)

def _status(score: int) -> str:
    if score >= 75: return _t("GOOD", "GUT")
    if score >= 60: return _t("FAIR", "BEFRIEDIGEND")
    if score >= 40: return _t("POOR", "SCHWACH")
    return _t("CRITICAL", "KRITISCH")

def _sev(issue: str) -> tuple:
    t = issue.lower()
    if any(w in t for w in ["no https", "no waf", "no ddos", "no cdn", "no clear", "volumetric",
         "lcp", "largest contentful", "no social proof", "noindex", "no cta", "unencrypted",
         "timed out", "mobile audit failed", "no title", "blocked by robots", "canonical",
         "no sitemap", "duplicate title", "keyword cannibali"]):
        return "CRITICAL", RED
    if any(w in t for w in ["poor", "slow", "fcp", "first contentful", "performance", "rate-limit",
         "hsts", "flood", "credential", "no privacy", "no contact", "accessibility"]):
        return "HIGH", AMBER
    if any(w in t for w in ["meta description", "title tag", "h1", "security header", "small tap",
         "multiple", "speed index", "limited social", "weak local", "missing"]):
        return "MEDIUM", SKY
    return "LOW", GREEN

def _opportunity_score(bd: dict) -> int:
    """
    Fast.site Opportunity Score — headline metric for the sales report.
    Weighted entirely from Speed (50%) and Performance (35%), with a small
    Page Ranking nudge (15%), then inverted so a HIGH score means the site
    is slow and needs fast.site Edge Cache. Mirrors lead_tools.opportunity_score.
    """
    speed   = (bd.get("speed") or {}).get("score", 50)
    perf    = (bd.get("performance") or {}).get("score", 50)
    ranking = (bd.get("page_ranking") or {}).get("score", 50)
    weighted = speed * 0.50 + perf * 0.35 + ranking * 0.15
    return max(0, min(100, round(100 - weighted)))

def _opportunity_label(score: int) -> str:
    if score >= 75: return _t("HIGH OPPORTUNITY", "HOHES POTENZIAL")
    if score >= 50: return _t("MEDIUM OPPORTUNITY", "MITTLERES POTENZIAL")
    if score >= 25: return _t("LOW OPPORTUNITY", "GERINGES POTENZIAL")
    return _t("ALREADY FAST", "BEREITS SCHNELL")


def _safe(t) -> str:
    t = str(t)
    t = t.replace('→', '->').replace('–', '-').replace('—', ' - ')
    # Preserve checkmark as XML entity before stripping non-ASCII
    t = t.replace('\u2713', '&#10003;').replace('✓', '&#10003;')
    # Strip characters that Helvetica/ReportLab cannot render
    # Both EN and DE use ASCII-only strings in this codebase
    t = re.sub(r'[^\x00-\x7F]', '', t)
    e = _esc(t, quote=False)
    # Restore the XML entity that html.escape may have mangled
    e = e.replace('&amp;#10003;', '&#10003;')
    e = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', e)
    return e.replace('\n\n', '<br/><br/>').replace('\n', '<br/>')

def _clean(issues: list) -> list:
    noise = ("timed out", "not installed", "playwright", "selenium", "webdriver", "chrome", "audit failed")
    return [i for i in issues if not any(n in i.lower() for n in noise)]

# ─── STYLES ───────────────────────────────────────────────────────────────────
def _styles():
    base = getSampleStyleSheet()
    def s(name, **kw):
        if name not in base:
            base.add(ParagraphStyle(name=name, **kw))
        return base[name]
    s("CardTitle", fontSize=9, leading=13, textColor=DARK, fontName="Helvetica-Bold")
    s("CardBody", fontSize=8, leading=12.5, textColor=GRAY, fontName="Helvetica")
    s("H2", fontSize=13, leading=17, textColor=DARK, fontName="Helvetica-Bold", spaceBefore=6, spaceAfter=3)
    s("H3", fontSize=10, leading=14, textColor=DARK, fontName="Helvetica-Bold", spaceBefore=4, spaceAfter=2)
    s("Body", fontSize=9, leading=13.5, textColor=DARK, fontName="Helvetica")
    s("BodyG", fontSize=9, leading=13.5, textColor=GRAY, fontName="Helvetica")
    s("Small", fontSize=8, leading=12, textColor=GRAY, fontName="Helvetica")
    s("SmallC", fontSize=8, leading=12, textColor=GRAY, fontName="Helvetica", alignment=TA_CENTER)
    s("Check", fontSize=9, leading=14, textColor=GREEN, fontName="Helvetica")
    return base

# ─── COVER FLOWABLE ──────────────────────────────────────────────────────────
class CoverPage(Flowable):
    def __init__(self, audit):
        super().__init__()
        self.audit = audit
        self.width = PAGE_W - L - R - 2 * FPAD
        self.height = PAGE_H - T - B - 2 * FPAD

    def draw(self):
        c = self.canv
        c.saveState()
        c.translate(-(L + FPAD), -(B + FPAD))
        _draw_cover(c, self.audit)
        c.restoreState()

def _draw_cover(c, audit):
    W, H = PAGE_W, PAGE_H
    score = audit.get("overall_score", 0)
    sc_col = _sc(score)
    st = _status(score)
    bd = audit.get("breakdown", {})

    c.setFillColor(DARK)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(BLUE)
    c.rect(0, H - 5, W, 5, fill=1, stroke=0)
    c.setStrokeColor(colors.HexColor("#1F1D2E"))
    c.setLineWidth(0.4)
    step = 28
    for xi in range(-int(H), int(W) + int(H), step):
        c.line(xi, H, xi + H, 0)

    logo_h = 20
    logo_w = logo_h * 2.0
    pad = 7
    bg_x = L - pad
    bg_y = H - 46
    bg_w = logo_w + pad * 2
    bg_h = logo_h + pad * 2 - 2
    c.setFillColor(WHITE)
    c.roundRect(bg_x, bg_y, bg_w, bg_h, 5, fill=1, stroke=0)
    if os.path.exists(LOGO_PATH):
        c.drawImage(LOGO_PATH, L, bg_y + pad - 1, width=logo_w, height=logo_h, preserveAspectRatio=True, mask='auto')

    c.setFillColor(colors.HexColor("#94A3B8"))
    c.setFont("Helvetica", 7.5)
    c.drawRightString(W - R, H - 22, _t("WEBSITE PERFORMANCE AUDIT", "WEBSITE LEISTUNGSANALYSE"))
    c.drawRightString(W - R, H - 33, _t("INDEPENDENT ANALYSIS · CONFIDENTIAL", "UNABHAENGIGE ANALYSE · VERTRAULICH"))

    score_cy = H * 0.76
    c.setFillColor(colors.HexColor("#1A2340"))
    c.circle(W / 2, score_cy, 82, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#1B2236"))
    c.circle(W / 2, score_cy, 62, fill=1, stroke=0)

    # ── Fast.site Opportunity Score — the headline sales metric ─────────────
    # Speed + Performance only (fast.site Edge Cache's direct levers), shown
    # as a bold badge above the overall score so it's the first number a
    # prospect sees.
    opp_score = _opportunity_score(bd)
    opp_label = _opportunity_label(opp_score)
    opp_col   = RED if opp_score >= 75 else (AMBER if opp_score >= 50 else (SKY if opp_score >= 25 else GREEN))

    opp_pill_w, opp_pill_h = 280, 34
    opp_pill_x = W / 2 - opp_pill_w / 2
    opp_pill_y = score_cy + 92
    c.setFillColor(opp_col)
    c.roundRect(opp_pill_x, opp_pill_y, opp_pill_w, opp_pill_h, 8, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(W / 2, opp_pill_y + 21, _t("FAST.SITE OPPORTUNITY SCORE", "FAST.SITE POTENZIAL-SCORE"))
    c.setFont("Helvetica-Bold", 15)
    c.drawCentredString(W / 2, opp_pill_y + 6, f"{opp_score}/100 · {opp_label}")

    pill_w, pill_h = 148, 21
    pill_x = W / 2 - pill_w / 2
    pill_y = score_cy + 52
    c.setFillColor(sc_col)
    c.roundRect(pill_x, pill_y, pill_w, pill_h, 10, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 8)
    c.drawCentredString(W / 2, pill_y + 7, f"* {st} {_t('PERFORMANCE', 'LEISTUNG')}")

    c.setFillColor(sc_col)
    c.setFont("Helvetica-Bold", 84)
    c.drawCentredString(W / 2, score_cy - 26, str(score))

    c.setFillColor(colors.HexColor("#64748B"))
    c.setFont("Helvetica", 10)
    c.drawCentredString(W / 2, score_cy - 44, _t("/ 100 OVERALL SCORE", "/ 100 GESAMTBEWERTUNG"))

    proj = audit.get("fastsite_projection") or {}
    cur = proj.get("current", {})
    ttfb_ms = cur.get("ttfb_ms", None)
    lcp_ms = cur.get("lcp_ms", None)
    perf_s = cur.get("perf_score", None)

    def _fmt_ms(v):
        if v is None: return "-"
        return f"{v/1000:.1f}s" if v >= 1000 else f"{v}ms"

    def _metric_col(mi, v):
        if mi == 0: return GREEN if v and v <= 800 else AMBER
        if mi == 1: return GREEN if v and v <= 2500 else (AMBER if v and v <= 4000 else RED)
        return _sc(int(v or 0))

    metrics_strip = [
        (_t("TTFB", "TTFB"), _fmt_ms(ttfb_ms), ttfb_ms, _t("Server response", "Server-Antwort")),
        (_t("LCP", "LCP"), _fmt_ms(lcp_ms), lcp_ms, _t("Largest Content Paint", "Groesster Inhalt")),
        (_t("PAGESPEED", "PAGESPEED"), f"{perf_s}/100" if perf_s is not None else "—", perf_s, _t("Google performance", "Google-Leistung")),
    ]

    strip_top_y = score_cy - 82 - 36
    card_h = 44
    strip_y = strip_top_y
    card_gap = 8
    card_w = (W - 2 * L - card_gap * 2) / 3

    for mi, (label, val, raw, sub) in enumerate(metrics_strip):
        mx = L + mi * (card_w + card_gap)
        m_col = _metric_col(mi, raw)
        c.setFillColor(colors.HexColor("#1E1C2D"))
        c.roundRect(mx, strip_y - card_h, card_w, card_h, 4, fill=1, stroke=0)
        c.setFillColor(m_col)
        c.roundRect(mx, strip_y - card_h, 3, card_h, 2, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#64748B"))
        c.setFont("Helvetica-Bold", 6.5)
        c.drawString(mx + 10, strip_y - 12, label)
        c.setFillColor(m_col)
        c.setFont("Helvetica-Bold", 16)
        c.drawString(mx + 10, strip_y - 30, val)
        c.setFillColor(colors.HexColor("#475569"))
        c.setFont("Helvetica", 6)
        c.drawString(mx + 10, strip_y - 41, sub)

    sep1_y = strip_y - card_h - 16
    c.setStrokeColor(colors.HexColor("#2D2B3D"))
    c.setLineWidth(0.75)
    c.line(L, sep1_y, W - R, sep1_y)

    biz = (audit.get("business_name") or "").strip()
    url = audit.get("url", "")
    date = datetime.now().strftime("%d %B %Y").lstrip("0")
    if not biz and url:
        m = re.search(r'https?://(?:www\.)?([^/]+)', url)
        biz = m.group(1) if m else url
    biz_txt = (biz[:44] + "…") if len(biz) > 44 else biz

    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 19)
    c.drawString(L, sep1_y - 30, biz_txt)
    c.setFillColor(BLUE_DIM)
    c.setFont("Helvetica", 9.5)
    c.drawString(L, sep1_y - 46, url[:72])
    c.setFillColor(colors.HexColor("#64748B"))
    c.setFont("Helvetica", 8)
    c.drawString(L, sep1_y - 59, f"{_t('Report Date', 'Berichtsdatum')}: {date}")

    sep2_y = sep1_y - 78
    c.setStrokeColor(colors.HexColor("#2D2B3D"))
    c.setLineWidth(0.5)
    c.line(L, sep2_y, W - R, sep2_y)

    all_issues = []
    sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    for _lbl, _key, _hex in CATS:
        cat_d = bd.get(_key) or {}
        for iss in _clean(cat_d.get("issues", [])):
            sev, _ = _sev(iss)
            all_issues.append((sev, _lbl, iss))
    all_issues.sort(key=lambda x: sev_order.get(x[0], 4))
    top_issues = all_issues[:4]

    sev_colors = {"CRITICAL": RED, "HIGH": AMBER, "MEDIUM": SKY, "LOW": GREEN}
    kh_y = sep2_y - 16
    c.setFillColor(BLUE_DIM)
    c.setFont("Helvetica-Bold", 7)
    c.drawString(L, kh_y, _t("KEY ISSUES IDENTIFIED", "WICHTIGSTE PROBLEME"))
    c.drawRightString(W - R, kh_y, _t(f"{len(all_issues)} total issues found", f"{len(all_issues)} Probleme gefunden"))

    col_gap = 8
    col_w = (W - L - R - col_gap) / 2
    row_h = 13
    badge_w = 48

    for idx, (sev, cat_lbl, iss_txt) in enumerate(top_issues):
        col = 0 if idx < 2 else 1
        row = idx if col == 0 else idx - 2
        ox = L + col * (col_w + col_gap)
        iy = kh_y - 18 - row * row_h
        dot_col = sev_colors.get(sev, GRAY)
        c.setFillColor(colors.HexColor("#1F1D2E"))
        c.roundRect(ox, iy - 4, col_w, row_h - 1, 2, fill=1, stroke=0)
        c.setFillColor(dot_col)
        c.roundRect(ox + 3, iy - 2, badge_w, 8, 2, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 5.5)
        c.drawCentredString(ox + 3 + badge_w / 2, iy + 0.5, _sev_label(sev))
        max_chars = 44
        translated = _translate_issue(iss_txt)
        short = translated[:max_chars] + "…" if len(translated) > max_chars else translated
        c.setFillColor(colors.HexColor("#CBD5E1"))
        c.setFont("Helvetica", 6)
        c.drawString(ox + badge_w + 8, iy, short)

    sep3_y = kh_y - 18 - 2 * row_h - 8
    c.setStrokeColor(colors.HexColor("#2D2B3D"))
    c.setLineWidth(0.5)
    c.line(L, sep3_y, W - R, sep3_y)

    grid_top = sep3_y - 12
    _draw_cat_grid(c, grid_top, bd)

    c.setFillColor(colors.HexColor("#12111E"))
    c.rect(0, 0, W, 28, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#475569"))
    c.setFont("Helvetica", 7)
    c.drawCentredString(W / 2, 10, _t("Prepared by fast.site · Independent Performance Analysis · Not for distribution", "Erstellt von fast.site · Unabhaengige Leistungsanalyse · Nicht zur Weitergabe"))

def _draw_cat_grid(c, y_top, bd):
    W = PAGE_W
    n_cols = 4
    gap = 8
    cell_h = 58
    cell_w = (W - 2 * L - gap * (n_cols - 1)) / n_cols
    for i, (label, key, hex_c) in enumerate(CATS):
        col = i % n_cols
        row = i // n_cols
        x = L + col * (cell_w + gap)
        y = y_top - row * (cell_h + gap) - cell_h
        score = (bd.get(key) or {}).get("score", 0)
        cat_col = colors.HexColor(hex_c)
        s_col = _sc(score)
        c.setFillColor(colors.HexColor("#252238"))
        c.roundRect(x, y, cell_w, cell_h, 4, fill=1, stroke=0)
        c.setFillColor(cat_col)
        c.roundRect(x, y, 4, cell_h, 2, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#94A3B8"))
        c.setFont("Helvetica", 6.5)
        c.drawString(x + 10, y + cell_h - 13, _cat_label(label).upper())
        c.setFillColor(s_col)
        c.setFont("Helvetica-Bold", 22)
        sc_str = str(score)
        c.drawString(x + 10, y + 10, sc_str)
        c.setFillColor(GRAY)
        c.setFont("Helvetica", 6.5)
        c.drawString(x + 10 + len(sc_str) * 13, y + 14, "/100")
        bar_x = x + 10
        bar_y = y + 34
        bar_w = cell_w - 22
        fill_w = max((score / 100) * bar_w, 3)
        c.setFillColor(colors.HexColor("#2D2B3D"))
        c.roundRect(bar_x, bar_y, bar_w, 5, 2, fill=1, stroke=0)
        c.setFillColor(cat_col)
        c.roundRect(bar_x, bar_y, fill_w, 5, 2, fill=1, stroke=0)

# ─── FLOWABLES ────────────────────────────────────────────────────────────────
class SectionBanner(Flowable):
    def __init__(self, title: str, score: int, accent_hex: str, width: float = CW):
        super().__init__()
        self.title = title
        self.score = score
        self.accent_hex = accent_hex
        self.width = width
        self.height = 46

    def draw(self):
        c = self.canv
        W = self.width
        H = self.height
        sc = _sc(self.score)
        ac = colors.HexColor(self.accent_hex)
        c.setFillColor(DARK)
        c.roundRect(0, 0, W, H, 4, fill=1, stroke=0)
        c.setFillColor(ac)
        c.roundRect(0, 0, 5, H, 2, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(18, H / 2 - 4, self.title.upper())
        cx, cy = W - 32, H / 2
        c.setFillColor(sc)
        c.circle(cx, cy, 15, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(cx, cy - 3.5, str(self.score))

class IssueCard(Flowable):
    PAD = 8
    BARW = 4
    LOGO_W = 46
    LOGO_H = 23

    def __init__(self, issue_text: str, impact_text: str, solution_text: str, severity: str, sev_col):
        super().__init__()
        self.issue_text = issue_text
        self.impact_text = impact_text
        self.solution_text = solution_text
        self.severity = severity.upper()
        self.sev_col = sev_col
        self._st = _styles()

    def wrap(self, aW, aH):
        self.width = aW
        inner = aW - self.BARW - self.PAD * 2
        pill_w = 68
        title_w = inner - pill_w - 8
        sol_w = inner - self.LOGO_W - 6
        self._p_title = Paragraph(f"<b>{_safe(self.issue_text[:200])}</b>", self._st["CardTitle"])
        self._p_impact = Paragraph(_safe(self.impact_text[:500]), self._st["CardBody"])
        self._p_sol = Paragraph(_safe(self.solution_text[:400]), self._st["CardBody"])
        _, ht = self._p_title.wrap(title_w, 10_000)
        _, himp = self._p_impact.wrap(inner, 10_000)
        _, hsol = self._p_sol.wrap(sol_w, 10_000)
        self._ht = max(ht, 16)
        self._himp = himp
        self._hsol = max(hsol, self.LOGO_H)
        self._pill_w = pill_w
        self._inner = inner
        self._height = self.PAD + self._ht + 6 + self._himp + 8 + self._hsol + self.PAD
        return (aW, self._height)

    def draw(self):
        c = self.canv
        H = self._height
        W = self.width
        c.setFillColor(LIGHT)
        c.roundRect(0, 0, W, H, 4, fill=1, stroke=0)
        c.setStrokeColor(RULE)
        c.setLineWidth(0.5)
        c.roundRect(0, 0, W, H, 4, fill=0, stroke=1)
        c.setFillColor(self.sev_col)
        c.roundRect(0, 0, self.BARW, H, 2, fill=1, stroke=0)
        pill_x = self.BARW + self.PAD
        pill_cy = H - self.PAD - self._ht / 2
        pill_h = 14
        c.setFillColor(self.sev_col)
        c.roundRect(pill_x, pill_cy - pill_h / 2, self._pill_w, pill_h, 3, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 6.5)
        c.drawCentredString(pill_x + self._pill_w / 2, pill_cy - 3.5, self.severity)
        title_x = pill_x + self._pill_w + 8
        title_y = H - self.PAD - self._ht
        c.saveState()
        c.translate(title_x, title_y)
        self._p_title.drawOn(c, 0, 0)
        c.restoreState()
        impact_y = H - self.PAD - self._ht - 6 - self._himp
        c.saveState()
        c.translate(pill_x, impact_y)
        self._p_impact.drawOn(c, 0, 0)
        c.restoreState()
        sep_y = self.PAD + self._hsol + 4
        c.setStrokeColor(RULE)
        c.setLineWidth(0.4)
        c.line(pill_x, sep_y, W - self.PAD, sep_y)
        logo_y = self.PAD + (self._hsol - self.LOGO_H) / 2
        if os.path.exists(LOGO_PATH):
            c.drawImage(LOGO_PATH, pill_x, logo_y, width=self.LOGO_W, height=self.LOGO_H, preserveAspectRatio=True, mask='auto')
        sol_x = pill_x + self.LOGO_W + 6
        c.saveState()
        c.translate(sol_x, self.PAD)
        self._p_sol.drawOn(c, 0, 0)
        c.restoreState()

class CoreWebVitalsPanel(Flowable):
    def __init__(self, proj: dict, width: float = CW):
        super().__init__()
        self.proj = proj or {}
        self.width = width
        self.height = 215

    def draw(self):
        c = self.canv
        p = self.proj
        W = self.width
        H = self.height
        cur = p.get("current", {})
        prj = p.get("projected", {})
        lcp_b = cur.get("lcp_ms", 4000); lcp_a = prj.get("lcp_ms", 1800)
        fcp_b = cur.get("fcp_ms", 3000); fcp_a = prj.get("fcp_ms", 1500)
        ttfb_b = cur.get("ttfb_ms", 800); ttfb_a = prj.get("ttfb_ms", 10)
        metrics = [
            (_t("LCP", "LCP"), _t("Largest Contentful Paint", "Groesster sichtbarer Inhalt"), lcp_b, lcp_a, 2500, 4000),
            (_t("FCP", "FCP"), _t("First Contentful Paint", "Erster sichtbarer Inhalt"), fcp_b, fcp_a, 1800, 3000),
            (_t("TTFB", "TTFB"), _t("Time to First Byte", "Zeit bis zum ersten Byte"), ttfb_b, ttfb_a, 800, 1800),
        ]
        def _cwv_status(val, good, fair):
            if val <= good: return _t("PASS", "OK"), GREEN, _t("Good", "Gut")
            if val <= fair: return _t("FAIL", "FAIL"), AMBER, _t("Needs improvement", "Verbesserungsbedarf")
            return _t("FAIL", "FAIL"), RED, _t("Poor", "Schlecht")
        def _fmt(ms):
            return f"{ms/1000:.1f}s" if ms >= 1000 else f"{ms}ms"
        c.setFillColor(DARK)
        c.roundRect(0, 0, W, H, 6, fill=1, stroke=0)
        c.setFillColor(BLUE)
        c.roundRect(0, H - 4, W, 4, 3, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(16, H - 24, _t("CORE WEB VITALS ASSESSMENT", "CORE WEB VITALS BEWERTUNG"))
        c.setFillColor(BLUE_DIM)
        c.setFont("Helvetica", 8)
        c.drawString(16, H - 36, _t("Google uses Core Web Vitals as a direct ranking factor. Sites that fail are deprioritised in search.", "Google nutzt Core Web Vitals als direkten Rankingfaktor."))
        card_gap = 8
        card_w = (W - 32 - card_gap * 2) / 3
        card_h = 110
        card_y = H - 50 - card_h
        for i, (lbl, full, cur_val, aft_val, good_t, fair_t) in enumerate(metrics):
            cx = 16 + i * (card_w + card_gap)
            status_txt, status_col, status_long = _cwv_status(cur_val, good_t, fair_t)
            _, aft_col, _ = _cwv_status(aft_val, good_t, fair_t)
            display_col = AMBER if lbl == _t("TTFB", "TTFB") and status_col == RED else status_col
            aft_col = GREEN if lbl == _t("LCP", "LCP") else aft_col
            c.setFillColor(colors.HexColor("#252238"))
            c.roundRect(cx, card_y, card_w, card_h, 4, fill=1, stroke=0)
            c.setFillColor(status_col)
            c.roundRect(cx, card_y + card_h - 4, card_w, 4, 2, fill=1, stroke=0)
            # Badge — top-right corner
            badge_w = 42
            badge_h = 13
            badge_x = cx + card_w - badge_w - 6
            badge_y = card_y + card_h - badge_h - 10
            c.setFillColor(status_col)
            c.roundRect(badge_x, badge_y, badge_w, badge_h, 3, fill=1, stroke=0)
            c.setFillColor(WHITE)
            c.setFont("Helvetica-Bold", 7)
            c.drawCentredString(badge_x + badge_w / 2, badge_y + badge_h / 2 - 2.5, status_txt)
            # Label and subtitle — top-left
            c.setFillColor(colors.HexColor("#94A3B8"))
            c.setFont("Helvetica-Bold", 8)
            c.drawString(cx + 8, card_y + card_h - 19, lbl)
            c.setFont("Helvetica", 6.5)
            c.drawString(cx + 8, card_y + card_h - 29, full)
            c.setFillColor(display_col)
            c.setFont("Helvetica-Bold", 26)
            c.drawString(cx + 8, card_y + 60, _fmt(cur_val))
            c.setFillColor(colors.HexColor("#94A3B8"))
            c.setFont("Helvetica", 7)
            c.drawString(cx + 8, card_y + 50, status_long)
            c.setFillColor(colors.HexColor("#475569"))
            c.setFont("Helvetica", 6.5)
            c.drawString(cx + 8, card_y + 38, _t(f"Google 'Good': <{_fmt(good_t)}", f"Google 'Gut': <{_fmt(good_t)}"))
            c.setStrokeColor(colors.HexColor("#2D2B3D"))
            c.setLineWidth(0.4)
            c.line(cx + 8, card_y + 30, cx + card_w - 8, card_y + 30)
            c.setFillColor(aft_col)
            c.setFont("Helvetica-Bold", 8)
            c.drawString(cx + 8, card_y + 18, _fmt(aft_val))
            c.setFillColor(colors.HexColor("#64748B"))
            c.setFont("Helvetica", 6.5)
            c.drawString(cx + 8, card_y + 8, _t("with fast.site", "mit fast.site"))
        note_y = card_y - 10
        c.setFillColor(colors.HexColor("#374151"))
        c.roundRect(16, note_y - 22, W - 32, 26, 3, fill=1, stroke=0)
        c.setFillColor(BLUE_DIM)
        c.setFont("Helvetica-Bold", 7)
        c.drawString(24, note_y - 4, _t("RANKING IMPACT:", "RANKING-AUSWIRKUNG:"))
        c.setFillColor(colors.HexColor("#94A3B8"))
        c.setFont("Helvetica", 6.5)
        c.drawString(24, note_y - 14, _t("Failing Core Web Vitals suppresses your site in mobile search.", "Core Web Vitals sind ein Google-Rankingfaktor."))

class ProjectionPanel(Flowable):
    def __init__(self, proj: dict, width: float = CW):
        super().__init__()
        self.proj = proj or {}
        self.width = width
        self.height = 335
    def draw(self):
        c = self.canv
        p = self.proj
        W = self.width
        H = self.height
        cur = p.get("current", {})
        prj = p.get("projected", {})
        imp = p.get("improvements", {})
        ttfb_b = cur.get("ttfb_ms", 800); ttfb_a = prj.get("ttfb_ms", 10); ttfb_p = imp.get("ttfb_speedup_pct", 0)
        lcp_b = cur.get("lcp_ms", 4000); lcp_a = prj.get("lcp_ms", 1800); lcp_p = imp.get("lcp_improvement_pct", 55)
        ps_b = cur.get("perf_score", 50); ps_lo = prj.get("perf_score_min", ps_b + 25); ps_hi = prj.get("perf_score_max", ps_b + 40)
        ps_g = imp.get("perf_score_gain_min", 25); bw_p = imp.get("bandwidth_saving_pct", 70); conv = imp.get("conversion_uplift_pct", 10); cache = p.get("cache_hit_rate_pct", 90)
        c.setFillColor(DARK)
        c.roundRect(0, 0, W, H, 6, fill=1, stroke=0)
        c.setFillColor(BLUE)
        c.roundRect(0, H - 4, W, 4, 3, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(16, H - 24, _t("FAST.SITE PERFORMANCE PROJECTION", "FAST.SITE LEISTUNGSPROGNOSE"))
        c.setFillColor(BLUE_DIM)
        c.setFont("Helvetica", 8)
        c.drawString(16, H - 36, _t("Fast Edge Cache estimates - based on your site's actual measured metrics", "Fast Edge Cache-Schaetzungen"))
        stats = [(f"{ttfb_p}%", _t("TTFB REDUCTION", "TTFB-REDUZIERUNG"), _t("Server response time", "Server-Antwortzeit")),
                 (f"+{ps_g} pts", _t("PAGESPEED GAIN", "PAGESPEED-GEWINN"), _t("Google performance score", "Google-Leistungsbewertung")),
                 (f"{cache}%", _t("CACHE HIT RATE", "CACHE-TREFFERRATE"), _t("Requests from edge cache", "Anfragen vom Edge-Cache"))]
        sw = (W - 32 - 12) / 3
        for i, (val, lbl, sub) in enumerate(stats):
            sx = 16 + i * (sw + 6); sy = H - 96
            c.setFillColor(colors.HexColor("#252238"))
            c.roundRect(sx, sy, sw, 50, 4, fill=1, stroke=0)
            c.setFillColor(BLUE_DIM)
            c.setFont("Helvetica-Bold", 20)
            c.drawCentredString(sx + sw / 2, sy + 28, val)
            c.setFillColor(WHITE)
            c.setFont("Helvetica-Bold", 7)
            c.drawCentredString(sx + sw / 2, sy + 17, lbl)
            c.setFillColor(GRAY)
            c.setFont("Helvetica", 6.5)
            c.drawCentredString(sx + sw / 2, sy + 8, sub)
        div_y = H - 104
        c.setStrokeColor(colors.HexColor("#2D2B3D"))
        c.setLineWidth(0.5)
        c.line(16, div_y, W - 16, div_y)
        rows = [(_t("Server Response (TTFB)", "Server-Antwort (TTFB)"), f"{ttfb_b:,}ms", f"{ttfb_a}ms", f"↓{ttfb_p}%"),
                (_t("Largest Content Paint", "Groesster Inhalt (LCP)"), f"{lcp_b/1000:.1f}s", f"{lcp_a/1000:.1f}s", f"↓{lcp_p}%"),
                (_t("PageSpeed Score", "PageSpeed-Bewertung"), f"{ps_b}/100", f"{ps_lo}-{ps_hi}/100", f"+{ps_g} pts"),
                (_t("Cache Hit Rate", "Cache-Trefferrate"), "~0%", f"{cache}%", "-"),
                (_t("Page Weight", "Seitengewicht"), "-", _t(f"down {bw_p}% smaller", f"down {bw_p}% kleiner"), "-"),
                (_t("Conversion Rate", "Konversionsrate"), "-", _t(f"up {conv}% est.", f"up {conv}% gesch."), "-")]
        col_xs = [16, W * 0.40, W * 0.63, W - 58]
        hdrs = [_t("Metric", "Metrik"), _t("Today", "Heute"), _t("With fast.site", "Mit fast.site"), _t("Uplift", "Verbesserung")]
        row_h = 14; ty = div_y - 10
        for j, hdr in enumerate(hdrs):
            c.setFillColor(BLUE_DIM); c.setFont("Helvetica-Bold", 7); c.drawString(col_xs[j], ty, hdr.upper())
        ty -= 5; c.line(16, ty, W - 16, ty); ty -= row_h
        for k, (metric, before, after, uplift) in enumerate(rows):
            if k % 2 == 0:
                c.setFillColor(colors.HexColor("#1F1D2E"))
                c.rect(16, ty - 2, W - 32, row_h, fill=1, stroke=0)
            c.setFillColor(colors.HexColor("#94A3B8")); c.setFont("Helvetica", 7.5); c.drawString(col_xs[0], ty + 3, metric)
            c.setFillColor(colors.HexColor("#64748B")); c.drawString(col_xs[1], ty + 3, before)
            c.setFillColor(GREEN); c.setFont("Helvetica-Bold", 7.5); c.drawString(col_xs[2], ty + 3, after)
            c.setFillColor(BLUE_DIM); c.drawString(col_xs[3], ty + 3, uplift)
            ty -= row_h
        chart_top = ty - 6
        c.setFillColor(BLUE_DIM); c.setFont("Helvetica-Bold", 6.5); c.drawString(16, chart_top, _t("BEFORE vs AFTER - PERFORMANCE IMPACT", "VORHER vs. NACHHER"))
        c.setFillColor(colors.HexColor("#475569")); c.roundRect(W - 120, chart_top + 1, 8, 5, 1, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#94A3B8")); c.setFont("Helvetica", 6); c.drawString(W - 110, chart_top + 1, _t("Today", "Heute"))
        c.setFillColor(GREEN); c.roundRect(W - 78, chart_top + 1, 8, 5, 1, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#94A3B8")); c.drawString(W - 68, chart_top + 1, _t("With fast.site", "Mit fast.site"))
        label_w = 55; badge_w = 52; bar_area_w = W - 32 - label_w - badge_w; bar_h = 6; row_gap = 20
        chart_metrics = [("TTFB", ttfb_b, ttfb_a, max(ttfb_b, 1), f"{ttfb_b:,}ms", f"{ttfb_a}ms", False),
                         ("LCP", lcp_b, lcp_a, max(lcp_b, 1), f"{lcp_b/1000:.1f}s", f"{lcp_a/1000:.1f}s", False),
                         ("PageSpeed", ps_b, ps_lo, 100, f"{ps_b}/100", f"{ps_lo}/100", True)]
        for mi, (lbl, bv, av, mv, bstr, astr, higher_better) in enumerate(chart_metrics):
            row_y = chart_top - 20 - mi * row_gap
            c.setFillColor(colors.HexColor("#94A3B8")); c.setFont("Helvetica", 6.5); c.drawString(16, row_y + 2, lbl)
            bx = 16 + label_w; b_norm = min(bv / mv, 1.0); a_norm = min(av / mv, 1.0)
            bw_px = max(b_norm * bar_area_w, 4); aw_px = max(a_norm * bar_area_w, 4)
            bar_before_y = row_y + 9; bar_after_y = row_y
            c.setFillColor(colors.HexColor("#374151")); c.roundRect(bx, bar_before_y, bw_px, bar_h, 2, fill=1, stroke=0)
            btxt_y = bar_before_y + bar_h / 2 - 2
            c.setFillColor(colors.HexColor("#94A3B8")); c.setFont("Helvetica", 5.5)
            bstr_w = c.stringWidth(bstr, "Helvetica", 5.5)
            if bw_px > bstr_w + 6: c.drawString(bx + bw_px - bstr_w - 3, btxt_y, bstr)
            else: c.drawString(bx + bw_px + 3, btxt_y, bstr)
            c.setFillColor(GREEN); c.roundRect(bx, bar_after_y, aw_px, bar_h, 2, fill=1, stroke=0)
            atxt_y = bar_after_y + bar_h / 2 - 2; c.setFont("Helvetica-Bold", 5.5)
            astr_w = c.stringWidth(astr, "Helvetica-Bold", 5.5)
            if aw_px > astr_w + 6: c.setFillColor(DARK); c.drawString(bx + aw_px - astr_w - 3, atxt_y, astr)
            else: c.setFillColor(GREEN); c.drawString(bx + aw_px + 3, atxt_y, astr)
            badge = f"+{av - bv} pts" if higher_better else _t(f"{round((bv - av) / bv * 100) if bv > 0 else 0}% faster", f"{round((bv - av) / bv * 100) if bv > 0 else 0}% schneller")
            badge_x = bx + bar_area_w + 6; badge_h = 16; badge_by = row_y - 2
            c.setFillColor(GREEN); c.roundRect(badge_x, badge_by, badge_w - 2, badge_h, 3, fill=1, stroke=0)
            c.setFillColor(DARK); c.setFont("Helvetica-Bold", 6.5)
            c.drawCentredString(badge_x + (badge_w - 2) / 2, badge_by + badge_h / 2 - 2.3, badge)
        c.setFillColor(BLUE); c.roundRect(0, 0, W, 24, 4, fill=1, stroke=0)
        c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(W / 2, 8, _t("fast.site · EUR80/month · No code changes · 99.9% uptime SLA · Active in 24 hours", "fast.site · EUR80/Monat"))

def _proposal_metrics(audit: dict):
    """Extract all dynamic values needed by both proposal pages.

    IMPORTANT: several fields here previously read keys that
    `compute_fastsite_projection()` (audit.py) never actually sets —
    e.g. "payload_kb" (real key is "page_size_kb"), "perf_score" on the
    projected dict (real keys are "perf_score_min"/"perf_score_max"),
    and "tbt_ms" / "cls" / "speed_index_ms" / "load_ms" on `current`
    (never set there at all). Those silently fell back to fixed
    reference-report numbers on *every* audit, which is why the first
    two pages of the PDF could look identical across different sites.
    This version reads the real keys (falling back to the Lighthouse
    details dict where the audit engine actually stores TBT/CLS) and
    only uses a fixed number when no measurement exists anywhere.
    """
    proj = audit.get("fastsite_projection") or {}
    cur  = proj.get("current",     {})
    prj  = proj.get("projected",   {})
    imp  = proj.get("improvements", {})
    bd   = audit.get("breakdown",  {})
    lh   = audit.get("lighthouse_details", {})
    speed_details = bd.get("speed", {}).get("details", {})
    seo_details   = bd.get("seo", {}).get("details", {})

    ttfb_b   = cur.get("ttfb_ms", speed_details.get("ttfb_ms", 412))
    ttfb_a   = prj.get("ttfb_ms", 162)
    ttfb_pct = imp.get("ttfb_speedup_pct",
                        round((ttfb_b - ttfb_a) / ttfb_b * 100) if ttfb_b else 0)

    lcp_b    = cur.get("lcp_ms",  1800)
    lcp_a    = prj.get("lcp_ms",  1500)
    lcp_pct  = round((lcp_b - lcp_a) / lcp_b * 100) if lcp_b else 0
    fcp_b    = cur.get("fcp_ms",  1400)
    fcp_a    = prj.get("fcp_ms",  1400)
    fcp_pct  = round((fcp_b - fcp_a) / fcp_b * 100) if fcp_b else 0

    # Full page "load" time isn't tracked as its own metric by the audit
    # engine (no "load_ms" key is ever produced) — approximate it from the
    # real TTFB + LCP for this site rather than a fixed constant.
    load_b   = cur.get("load_ms") or (ttfb_b + lcp_b)
    load_a   = prj.get("load_ms") or (ttfb_a + lcp_a)
    load_pct = imp.get("load_speedup_pct",
                        round((load_b - load_a) / load_b * 100) if load_b else 0)

    # TBT and CLS are real Lighthouse measurements, but they live in
    # breakdown.speed.details / lighthouse_details — NOT in
    # fastsite_projection.current, which never sets these keys.
    tbt_b    = cur.get("tbt_ms") or speed_details.get("tbt_ms") or lh.get("tbt_ms") or 253
    tbt_a    = prj.get("tbt_ms",  round(tbt_b * 0.3))
    tbt_pct  = round((tbt_b - tbt_a) / tbt_b * 100) if tbt_b else 0

    # Speed Index isn't measured by the current pipeline at all — approximate
    # it from this site's own FCP/LCP instead of a hardcoded constant so it
    # still varies per audit.
    si_b     = cur.get("speed_index_ms") or round((fcp_b + lcp_b) / 2 * 1.05)
    si_a     = prj.get("speed_index_ms", round(si_b * 0.55))
    si_pct   = round((si_b - si_a) / si_b * 100) if si_b else 0

    cls_b = cur.get("cls")
    if cls_b is None:
        cls_b = speed_details.get("cls")
    if cls_b is None:
        cls_b = lh.get("cls")
    if cls_b is None:
        cls_b = 0.01
    cls_a    = prj.get("cls", cls_b)

    # Real key is "page_size_kb", not "payload_kb" — this was always
    # silently returning the static fallback (26) before.
    payload  = cur.get("page_size_kb", speed_details.get("page_size_kb", 26))
    cache    = proj.get("cache_hit_rate_pct", 0)

    ps_b     = lh.get("performance", cur.get("perf_score", 99))
    # The projection stores a MIN/MAX uplift range ("perf_score_min" /
    # "perf_score_max"), never a single "perf_score" key — read the real
    # projected range instead of silently collapsing to ps_b + 1.
    ps_a     = prj.get("perf_score_max") or prj.get("perf_score_min") or min(100, ps_b + 1)
    ps_gain  = imp.get("perf_score_gain_min", ps_a - ps_b)
    edge     = proj.get("edge_regions", 6)
    perf_lh  = lh.get("performance",    ps_b)
    seo_lh   = lh.get("seo",            bd.get("seo", {}).get("score", 92))
    acc_lh   = lh.get("accessibility",  seo_details.get("lighthouse_accessibility", 98))
    bp_lh    = lh.get("best_practices", seo_details.get("lighthouse_best_practices", 96))
    # In the reference report, "Overall / Current / PageSpeed" score are the
    # same headline number (the lab Performance score), held constant
    # through accessibility/SEO/best-practices (those don't change with a CDN).
    overall_b = ps_b
    overall_a = ps_a

    url  = audit.get("url", "")
    biz  = (audit.get("business_name") or "").strip()
    if not biz and url:
        m = re.search(r'https?://(?:www\.)?([^/]+)', url)
        biz = m.group(1) if m else url
    # display domain without scheme
    disp = re.sub(r'^https?://', '', url).rstrip("/")

    opp_score = _opportunity_score(bd)
    opp_label = _opportunity_label(opp_score)
    opp_col   = (RED   if opp_score >= 75 else
                 AMBER if opp_score >= 50 else
                 SKY   if opp_score >= 25 else GREEN)
    date_str  = datetime.now().strftime("%d %B %Y").lstrip("0")

    return dict(
        ttfb_b=ttfb_b, ttfb_a=ttfb_a, ttfb_pct=ttfb_pct,
        load_b=load_b, load_a=load_a, load_pct=load_pct,
        lcp_b=lcp_b,   lcp_a=lcp_a,   lcp_pct=lcp_pct,
        fcp_b=fcp_b,   fcp_a=fcp_a,   fcp_pct=fcp_pct,
        tbt_b=tbt_b,   tbt_a=tbt_a,   tbt_pct=tbt_pct,
        si_b=si_b,     si_a=si_a,     si_pct=si_pct,
        cls_b=cls_b,   cls_a=cls_a,
        payload=payload, cache=cache,
        ps_b=ps_b, ps_a=ps_a, ps_gain=ps_gain,
        overall_b=overall_b, overall_a=overall_a,
        edge=edge,
        perf_lh=perf_lh, seo_lh=seo_lh, acc_lh=acc_lh, bp_lh=bp_lh,
        url=url, biz=biz, disp=disp,
        opp_score=opp_score, opp_label=opp_label, opp_col=opp_col,
        date_str=date_str,
    )


def _draw_page_header(c, W, H, logo_path, line1, line2):
    """White logo box top-left + two right-aligned grey label lines."""
    logo_h = 20; logo_w = logo_h * 2.0; pad = 7
    bg_x = L - pad; bg_y = H - 46
    bg_w = logo_w + pad * 2; bg_h = logo_h + pad * 2 - 2
    c.setFillColor(WHITE)
    c.roundRect(bg_x, bg_y, bg_w, bg_h, 5, fill=1, stroke=0)
    if os.path.exists(logo_path):
        c.drawImage(logo_path, L, bg_y + pad - 1,
                    width=logo_w, height=logo_h,
                    preserveAspectRatio=True, mask='auto')
    c.setFillColor(colors.HexColor("#94A3B8"))
    c.setFont("Helvetica", 7.5)
    c.drawRightString(W - R, H - 22, line1)
    c.drawRightString(W - R, H - 33, line2)


def _draw_dark_bg(c, W, H):
    """Full-page dark background + blue top bar + diagonal grid."""
    c.setFillColor(DARK)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(BLUE)
    c.rect(0, H - 5, W, 5, fill=1, stroke=0)
    c.setStrokeColor(colors.HexColor("#1F1D2E"))
    c.setLineWidth(0.4)
    step = 28
    for xi in range(-int(H), int(W) + int(H), step):
        c.line(xi, H, xi + H, 0)


def _draw_footer(c, W):
    """Dark footer bar with centred grey caption."""
    c.setFillColor(colors.HexColor("#12111E"))
    c.rect(0, 0, W, 22, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#475569"))
    c.setFont("Helvetica", 6.5)
    c.drawCentredString(W / 2, 7,
        "Prepared by fast.site · Independent performance analysis · Not for distribution")


class ProposalPage(Flowable):
    """
    Page 1 — matches sample PDF page 1 exactly:
    logo/header · opportunity pill · speed-gain circle · 3 metric cards ·
    domain/date · KEY FINDINGS rows · LIGHTHOUSE LAB SCORES cards · footer.
    """
    def __init__(self, audit: dict):
        super().__init__()
        self.audit  = audit
        self.width  = PAGE_W - L - R - 2 * FPAD
        self.height = PAGE_H - T - B - 2 * FPAD

    def draw(self):
        c = self.canv
        c.saveState()
        c.translate(-(L + FPAD), -(B + FPAD))
        self._render(c)
        c.restoreState()

    def _render(self, c):
        m  = _proposal_metrics(self.audit)
        W, H = PAGE_W, PAGE_H

        _draw_dark_bg(c, W, H)

        # ── Header ────────────────────────────────────────────────────────────
        _draw_page_header(c, W, H, LOGO_PATH,
                          "WEBSITE PERFORMANCE AUDIT",
                          "INDEPENDENT ANALYSIS · CONFIDENTIAL")

        cx = W / 2  # horizontal centre

        # ── CURRENT SCORE badge + circle ──────────────────────────────────────
        badge_w, badge_h = 170, 22
        badge_y = H - 86
        c.setFillColor(AMBER)
        c.roundRect(cx - badge_w / 2, badge_y, badge_w, badge_h, 6, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(cx, badge_y + 7, "CURRENT SCORE")

        circle_r  = 44
        circle_cy = badge_y - circle_r - 8
        c.setFillColor(colors.HexColor("#241F12"))
        c.circle(cx, circle_cy, circle_r, fill=1, stroke=0)
        c.setStrokeColor(AMBER)
        c.setLineWidth(1.4)
        c.circle(cx, circle_cy, circle_r, fill=0, stroke=1)
        c.setFillColor(AMBER)
        c.setFont("Helvetica-Bold", 30)
        c.drawCentredString(cx, circle_cy - 10, str(m['overall_b']))
        c.setFillColor(colors.HexColor("#94A3B8"))
        c.setFont("Helvetica", 8)
        c.drawCentredString(cx, circle_cy - circle_r - 14, "Where you are today")

        # ── SPEED GAIN badge + circle ─────────────────────────────────────────
        badge2_y = circle_cy - circle_r - 44
        c.setFillColor(GREEN)
        c.roundRect(cx - badge_w / 2, badge2_y, badge_w, badge_h, 6, fill=1, stroke=0)
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(cx, badge2_y + 7, "SPEED GAIN")

        circle2_r  = 64
        circle2_cy = badge2_y - circle2_r - 8
        c.setFillColor(colors.HexColor("#1B3A2E"))
        c.circle(cx, circle2_cy, circle2_r, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#0D2A1E"))
        c.circle(cx, circle2_cy, circle2_r - 16, fill=1, stroke=0)
        c.setFillColor(GREEN)
        c.setFont("Helvetica-Bold", 38)
        c.drawCentredString(cx, circle2_cy + 2, f"{m['lcp_pct']}%")
        c.setFillColor(colors.HexColor("#94A3B8"))
        c.setFont("Helvetica", 8)
        c.drawCentredString(cx, circle2_cy - 14, "Faster with Fast.site")
        c.setFillColor(GREEN)
        c.setFont("Helvetica-Bold", 7.5)
        c.drawCentredString(cx, circle2_cy - 26, f"Est. PageSpeed score: {m['ps_a']}/100")
        c.setFillColor(colors.HexColor("#64748B"))
        c.setFont("Helvetica", 6.5)
        c.drawCentredString(cx, circle2_cy - circle2_r - 12, "LARGEST CONTENTFUL PAINT")
        c.setFillColor(colors.HexColor("#94A3B8"))
        c.setFont("Helvetica-Bold", 7.5)
        c.drawCentredString(cx, circle2_cy - circle2_r - 23,
                            f"{_fmt_s(m['lcp_b'])} -> {_fmt_s(m['lcp_a'])}")

        # ── PAGESPEED SCORE gained bar ────────────────────────────────────────
        ps_bar_y = circle2_cy - circle2_r - 40
        ps_bar_h = 28
        c.setFillColor(colors.HexColor("#12111E"))
        c.roundRect(L, ps_bar_y - ps_bar_h, W - 2 * L, ps_bar_h, 4, fill=1, stroke=0)
        c.setFillColor(GREEN)
        c.roundRect(L, ps_bar_y - ps_bar_h, 3, ps_bar_h, 2, fill=1, stroke=0)
        gain = m['ps_a'] - m['ps_b']
        c.setFillColor(colors.HexColor("#64748B"))
        c.setFont("Helvetica-Bold", 6.5)
        c.drawString(L + 12, ps_bar_y - 11, "PAGESPEED SCORE")
        c.setFillColor(GREEN)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(L + 12, ps_bar_y - 23, f"{m['ps_b']} -> {m['ps_a']}/100  (+{gain} pts)")
        c.setFillColor(colors.HexColor("#64748B"))
        c.setFont("Helvetica", 7)
        c.drawRightString(W - R - 12, ps_bar_y - 17, "WITH FAST.SITE")

        # ── Domain / URL / date ───────────────────────────────────────────────
        sep1_y = ps_bar_y - ps_bar_h - 16
        c.setStrokeColor(colors.HexColor("#2D2B3D"))
        c.setLineWidth(0.75)
        c.line(L, sep1_y, W - R, sep1_y)

        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 18)
        c.drawString(L, sep1_y - 22, m['disp'][:50])
        c.setFillColor(BLUE_DIM)
        c.setFont("Helvetica", 8.5)
        c.drawString(L, sep1_y - 34, m['url'][:70])
        c.setFillColor(colors.HexColor("#64748B"))
        c.setFont("Helvetica", 8)
        c.drawRightString(W - R, sep1_y - 22, f"Report Date: {m['date_str']}")

        # ── KEY METRICS — NOW vs WITH FAST.SITE ───────────────────────────────
        km_y = sep1_y - 56
        c.setFillColor(colors.HexColor("#93B5FF"))
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(L, km_y, "KEY METRICS - NOW vs WITH FAST.SITE")

        km_top   = km_y - 12
        km_gap   = 8
        km_cw    = (W - 2 * L - km_gap * 2) / 3
        km_ch    = 76
        km_rows  = [
            [("LCP", "Largest Contentful Paint", _fmt_s(m['lcp_b']), _fmt_s(m['lcp_a']),
              f"-{m['lcp_pct']}%" if m['lcp_pct'] >= 0 else f"+{-m['lcp_pct']}%", BLUE),
             ("FCP", "First Contentful Paint", _fmt_s(m['fcp_b']), _fmt_s(m['fcp_a']),
              None, GREEN),
             ("TOTAL BLOCKING", "Total Blocking Time", f"{m['tbt_b']}ms", f"{m['tbt_a']}ms",
              f"-{m['tbt_pct']}%" if m['tbt_pct'] >= 0 else f"+{-m['tbt_pct']}%", AMBER)],
            [("SPEED INDEX", "Speed Index", _fmt_s(m['si_b']), _fmt_s(m['si_a']),
              None, colors.HexColor("#8B5CF6")),
             ("ACCESSIBILITY", "Accessibility score", f"{m['acc_lh']}/100", f"{m['acc_lh']}/100",
              None, SKY),
             ("SEO SCORE", "SEO score", f"{m['seo_lh']}/100", f"{m['seo_lh']}/100",
              None, colors.HexColor("#EC4899"))],
        ]
        for r, row in enumerate(km_rows):
            for col, (lbl, sub, now_v, after_v, badge, accent) in enumerate(row):
                bx = L + col * (km_cw + km_gap)
                by = km_top - (r + 1) * (km_ch + km_gap) + km_gap
                c.setFillColor(colors.HexColor("#12111E"))
                c.roundRect(bx, by, km_cw, km_ch, 4, fill=1, stroke=0)
                c.setFillColor(accent)
                c.roundRect(bx, by, 3, km_ch, 2, fill=1, stroke=0)
                # label
                c.setFillColor(WHITE)
                c.setFont("Helvetica-Bold", 7.5)
                c.drawString(bx + 10, by + km_ch - 14, lbl)
                c.setFillColor(colors.HexColor("#64748B"))
                c.setFont("Helvetica", 5.5)
                c.drawString(bx + 10, by + km_ch - 23, sub)
                # badge
                if badge:
                    bw = c.stringWidth(badge, "Helvetica-Bold", 6.5) + 8
                    c.setFillColor(GREEN)
                    c.roundRect(bx + km_cw - bw - 8, by + km_ch - 18, bw, 12, 3, fill=1, stroke=0)
                    c.setFillColor(WHITE)
                    c.setFont("Helvetica-Bold", 6.5)
                    c.drawCentredString(bx + km_cw - bw/2 - 8, by + km_ch - 14.5, badge)
                # now -> with fast.site
                c.setFillColor(colors.HexColor("#64748B"))
                c.setFont("Helvetica", 6)
                c.drawString(bx + 10, by + 30, "NOW")
                c.drawRightString(bx + km_cw - 10, by + 30, "WITH FAST.SITE")
                c.setFillColor(colors.HexColor("#94A3B8"))
                c.setFont("Helvetica-Bold", 12)
                c.drawString(bx + 10, by + 12, now_v)
                c.setFillColor(GREEN)
                c.setFont("Helvetica-Bold", 12)
                aft_w = c.stringWidth(after_v, "Helvetica-Bold", 12)
                c.drawString(bx + km_cw - 10 - aft_w, by + 12, after_v)

        # ── Footer ────────────────────────────────────────────────────────────
        _draw_footer(c, W)



class ProjectionPage(Flowable):
    """
    Page 2 — matches sample PDF page 2 exactly:
    logo/header · title+subtitle · 3 big stat boxes · metrics table ·
    Before vs after bar charts · Core Web Vitals cards · footer.
    """
    def __init__(self, audit: dict):
        super().__init__()
        self.audit  = audit
        self.width  = PAGE_W - L - R - 2 * FPAD
        self.height = PAGE_H - T - B - 2 * FPAD

    def draw(self):
        c = self.canv
        c.saveState()
        c.translate(-(L + FPAD), -(B + FPAD))
        self._render(c)
        c.restoreState()

    def _render(self, c):
        m  = _proposal_metrics(self.audit)
        W, H = PAGE_W, PAGE_H

        _draw_dark_bg(c, W, H)

        # ── Header ────────────────────────────────────────────────────────────
        _draw_page_header(c, W, H, LOGO_PATH,
                          "PERFORMANCE IMPACT",
                          "MEASURED · ORIGIN VS FAST.SITE EDGE")

        # ── Title + subtitle ──────────────────────────────────────────────────
        y = H - 58
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(L, y, "Performance Impact")
        c.setFillColor(colors.HexColor("#94A3B8"))
        c.setFont("Helvetica", 7.5)
        c.drawString(L, y - 13,
            "Core Web Vitals measured by api.fast.site - LCP, FCP, and TTFB scored "
            "against Google's Good thresholds.")

        # ── CORE WEB VITALS (3 cards) ───────────────────────────────────────────
        cwv_y = y - 30
        c.setFillColor(BLUE_DIM)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(L, cwv_y, "CORE WEB VITALS")
        c.setFillColor(colors.HexColor("#64748B"))
        c.setFont("Helvetica", 6.5)
        c.drawString(L + 95, cwv_y + 1, "(Google ranking signals)")

        cwv_card_gap = 10
        cwv_cw  = (W - 2*L - cwv_card_gap * 2) / 3
        cwv_ch  = 100
        cwv_by  = cwv_y - 14 - cwv_ch

        cwv_items = [
            ("LCP", "Largest Contentful Paint", m['lcp_b'], m['lcp_a'], 2500,
             _fmt_s(m['lcp_b']), _fmt_s(m['lcp_a']), "Google 'Good': <2.5s", True),
            ("FCP", "First Contentful Paint",   m['fcp_b'], m['fcp_a'], 1800,
             _fmt_s(m['fcp_b']), _fmt_s(m['fcp_a']), "Google 'Good': <1.8s", True),
            ("TTFB","Time to First Byte",        m['ttfb_b'], m['ttfb_a'], 800,
             _fmt_s(m['ttfb_b']) if m['ttfb_b'] else "--",
             _fmt_s(m['ttfb_a']) if m['ttfb_a'] else "--",
             "Google 'Good': <800ms", bool(m['ttfb_b'])),
        ]

        for i, (abbr, full, cur_v, aft_v, good_t, cur_s, aft_s, good_s, has_data) in enumerate(cwv_items):
            cx2 = L + i * (cwv_cw + cwv_card_gap)
            passing = has_data and cur_v <= good_t
            status_col = GREEN if passing else (AMBER if has_data else GRAY)
            status_txt = "PASS" if passing else ("NEEDS WORK" if has_data else "N/A")

            c.setFillColor(colors.HexColor("#12111E"))
            c.roundRect(cx2, cwv_by, cwv_cw, cwv_ch, 5, fill=1, stroke=0)
            c.setFillColor(status_col)
            c.roundRect(cx2, cwv_by + cwv_ch - 4, cwv_cw, 4, 3, fill=1, stroke=0)

            badge_font_size = 6.5
            badge_pad_x = 5
            badge_bw = c.stringWidth(status_txt, "Helvetica-Bold", badge_font_size) + badge_pad_x * 2
            badge_bh = 13
            bx2 = cx2 + cwv_cw - badge_bw - 6
            by2 = cwv_by + cwv_ch - badge_bh - 9
            c.setFillColor(status_col)
            c.roundRect(bx2, by2, badge_bw, badge_bh, 3, fill=1, stroke=0)
            c.setFillColor(WHITE)
            c.setFont("Helvetica-Bold", badge_font_size)
            c.drawCentredString(bx2 + badge_bw / 2, by2 + 4, status_txt)

            c.setFillColor(colors.HexColor("#94A3B8"))
            c.setFont("Helvetica-Bold", 9)
            c.drawString(cx2 + 9, cwv_by + cwv_ch - 22, abbr)
            c.setFillColor(colors.HexColor("#64748B"))
            c.setFont("Helvetica", 6.5)
            c.drawString(cx2 + 9, cwv_by + cwv_ch - 33, full)

            c.setFillColor(status_col if has_data else colors.HexColor("#475569"))
            c.setFont("Helvetica-Bold", 20)
            c.drawString(cx2 + 9, cwv_by + 48, cur_s)

            c.setFillColor(colors.HexColor("#475569"))
            c.setFont("Helvetica", 6.5)
            c.drawString(cx2 + 9, cwv_by + 36, good_s)

            c.setStrokeColor(colors.HexColor("#2D2B3D"))
            c.setLineWidth(0.4)
            c.line(cx2 + 9, cwv_by + 28, cx2 + cwv_cw - 9, cwv_by + 28)

            c.setFillColor(GREEN if has_data else colors.HexColor("#475569"))
            c.setFont("Helvetica-Bold", 9)
            c.drawString(cx2 + 9, cwv_by + 14, aft_s)
            c.setFillColor(colors.HexColor("#64748B"))
            c.setFont("Helvetica", 6.5)
            c.drawString(cx2 + 9 + c.stringWidth(aft_s, "Helvetica-Bold", 9) + 4,
                         cwv_by + 14, "with fast.site")

        # ── "Comparison with Fast.site" panel ─────────────────────────────────
        cmp_top = cwv_by - 14
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(L, cmp_top, "Comparison with Fast.site")
        c.setFillColor(colors.HexColor("#64748B"))
        c.setFont("Helvetica", 6.5)
        c.drawString(L, cmp_top - 11,
            "Side-by-side metrics: your site today vs. with fast.site Edge Cache active.")

        panel_top = cmp_top - 22
        panel_h   = 252
        panel_y   = panel_top - panel_h
        c.setFillColor(colors.HexColor("#100F1C"))
        c.roundRect(L, panel_y, W - 2*L, panel_h, 5, fill=1, stroke=0)
        c.setStrokeColor(colors.HexColor("#2D2B3D"))
        c.setLineWidth(0.5)
        c.roundRect(L, panel_y, W - 2*L, panel_h, 5, fill=0, stroke=1)

        # two overall-score circles — pulled toward the centre of the panel
        # (previously pinned near the far left/right edges) with extra
        # clearance below so their labels don't get painted over by the
        # metric table header bar drawn right after them.
        circ_r = 26
        circ_y = panel_top - circ_r - 14
        for i, (lbl, val, col) in enumerate([
            ("CURRENT",        m['overall_b'], AMBER),
            ("WITH FAST.SITE",  m['overall_a'], GREEN),
        ]):
            ccx = L + (W - 2*L) * (0.32 + i * 0.36)
            c.setFillColor(colors.HexColor("#1A1830"))
            c.circle(ccx, circ_y, circ_r, fill=1, stroke=0)
            c.setStrokeColor(col)
            c.setLineWidth(1.3)
            c.circle(ccx, circ_y, circ_r, fill=0, stroke=1)
            c.setFillColor(col)
            c.setFont("Helvetica-Bold", 18)
            c.drawCentredString(ccx, circ_y - 6, str(val))
            c.setFillColor(colors.HexColor("#94A3B8"))
            c.setFont("Helvetica-Bold", 6)
            c.drawCentredString(ccx, circ_y - circ_r - 14, "OVERALL SCORE")
            c.setFillColor(colors.HexColor("#64748B"))
            c.setFont("Helvetica", 6)
            c.drawCentredString(ccx, circ_y - circ_r - 25, lbl)

        # metric comparison table inside the panel
        tbl_top = circ_y - circ_r - 50
        tbl_row_h = 14.5
        pad_x = 14
        col_xs = [L + pad_x, L + (W - 2*L)*0.42, L + (W - 2*L)*0.62, L + (W - 2*L)*0.82]
        hdrs = ["METRIC", "CURRENT", "WITH FAST.SITE", "CHANGE"]
        c.setFillColor(colors.HexColor("#1A1830"))
        c.roundRect(L + 6, tbl_top - 3, W - 2*L - 12, tbl_row_h + 2, 3, fill=1, stroke=0)
        for j, hdr in enumerate(hdrs):
            c.setFillColor(BLUE_DIM)
            c.setFont("Helvetica-Bold", 6.5)
            c.drawString(col_xs[j], tbl_top + 2, hdr)

        gain = m['ps_a'] - m['ps_b']
        ps_gain_str = f"+{gain} pts" if gain else "-"
        rows = [
            ("Largest Contentful Paint (LCP)", _fmt_s(m['lcp_b']), _fmt_s(m['lcp_a']),
             f"{m['lcp_pct']}%" if m['lcp_pct'] >= 0 else f"+{-m['lcp_pct']}%", GREEN if m['lcp_pct'] >= 0 else AMBER),
            ("First Contentful Paint (FCP)",   _fmt_s(m['fcp_b']), _fmt_s(m['fcp_a']),
             f"{m['fcp_pct']}%" if m['fcp_pct'] >= 0 else f"+{-m['fcp_pct']}%", GREEN if m['fcp_pct'] >= 0 else AMBER),
            ("PageSpeed Score",                f"{m['ps_b']}/100", f"{m['ps_a']}/100", ps_gain_str, GREEN),
            ("Total Blocking Time (TBT)",      f"{m['tbt_b']}ms",  f"{m['tbt_a']}ms",
             f"{m['tbt_pct']}%" if m['tbt_pct'] >= 0 else f"+{-m['tbt_pct']}%", GREEN if m['tbt_pct'] >= 0 else AMBER),
            ("Speed Index",                    _fmt_s(m['si_b']), _fmt_s(m['si_a']),
             f"{m['si_pct']}%" if m['si_pct'] >= 0 else f"+{-m['si_pct']}%", GREEN if m['si_pct'] >= 0 else AMBER),
            ("Accessibility Score",            f"{m['acc_lh']}/100", f"{m['acc_lh']}/100", "+0 pts", GRAY),
            ("Best Practices Score",           f"{m['bp_lh']}/100", f"{m['bp_lh']}/100", "+0 pts", GRAY),
            ("SEO Score",                      f"{m['seo_lh']}/100", f"{m['seo_lh']}/100", "+0 pts", GRAY),
            ("Cumulative Layout Shift (CLS)",  f"{m['cls_b']:.3f}", f"{m['cls_a']:.3f}", "-", GRAY),
        ]
        for k, (metric, before, after, chg, ccol) in enumerate(rows):
            row_y = tbl_top - 12 - k * tbl_row_h
            bg = colors.HexColor("#13121F") if k % 2 == 0 else colors.HexColor("#0F0E1A")
            c.setFillColor(bg)
            c.rect(L + 6, row_y - 3, W - 2*L - 12, tbl_row_h, fill=1, stroke=0)
            c.setFillColor(colors.HexColor("#94A3B8"))
            c.setFont("Helvetica", 6.5)
            c.drawString(col_xs[0], row_y + 1, metric)
            c.setFillColor(colors.HexColor("#64748B"))
            c.drawString(col_xs[1], row_y + 1, before)
            c.setFillColor(WHITE)
            c.setFont("Helvetica-Bold", 6.5)
            c.drawString(col_xs[2], row_y + 1, after)
            c.setFillColor(ccol)
            c.drawString(col_xs[3], row_y + 1, chg)

        # ── Before vs after bars (LCP + PageSpeed) ─────────────────────────────
        bva_top = panel_y - 16
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(L, bva_top, "Before vs after — performance impact")

        bar_label_w = 70
        bar_area_w  = W - 2*L - bar_label_w - 50
        bar_h       = 9

        charts = [
            ("LCP", m['lcp_b'], m['lcp_a'], _fmt_s(m['lcp_b']), _fmt_s(m['lcp_a']), f"{m['lcp_pct']}% faster"),
            ("PAGESPEED", m['ps_b'], m['ps_a'], f"{m['ps_b']}/100", f"{m['ps_a']}/100", f"+{gain} pts"),
        ]
        cy_bar = bva_top - 18
        for sec_title, before_v, after_v, before_s, after_s, tag in charts:
            c.setFillColor(colors.HexColor("#64748B"))
            c.setFont("Helvetica-Bold", 6)
            c.drawString(L, cy_bar, sec_title)
            c.setFillColor(GREEN)
            c.setFont("Helvetica-Bold", 6)
            c.drawRightString(W - R, cy_bar, tag)
            cy_bar -= 12

            max_v = max(before_v, after_v, 1)
            for row_label, val, val_str, is_after in [
                ("Current",     before_v, before_s, False),
                ("With Fast.site", after_v,  after_s,  True),
            ]:
                c.setFillColor(colors.HexColor("#94A3B8"))
                c.setFont("Helvetica", 6.5)
                c.drawString(L, cy_bar + 1, row_label)
                bx_start = L + bar_label_w
                fill_ratio = val / max_v
                bw = max(fill_ratio * bar_area_w, 8)
                bar_col = BLUE if is_after else colors.HexColor("#374151")
                c.setFillColor(bar_col)
                c.roundRect(bx_start, cy_bar - 1, bw, bar_h, 2, fill=1, stroke=0)
                c.setFillColor(WHITE if is_after else colors.HexColor("#94A3B8"))
                c.setFont("Helvetica-Bold" if is_after else "Helvetica", 6)
                lbl_w = c.stringWidth(val_str,
                    "Helvetica-Bold" if is_after else "Helvetica", 6)
                if bw > lbl_w + 10:
                    c.drawString(bx_start + bw - lbl_w - 4, cy_bar + 1, val_str)
                else:
                    c.drawString(bx_start + bw + 3, cy_bar + 1, val_str)
                cy_bar -= bar_h + 5
            cy_bar -= 8

        # ── PREVIEW URL strip ────────────────────────────────────────────────
        prev_y = cy_bar - 6
        prev_h = 24
        c.setFillColor(colors.HexColor("#0E2A4D"))
        c.roundRect(L, prev_y - prev_h, W - 2*L, prev_h, 4, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#22C55E"))
        c.circle(L + 14, prev_y - prev_h/2, 3, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#94A3B8"))
        c.setFont("Helvetica-Bold", 6.5)
        c.drawString(L + 22, prev_y - prev_h/2 - 2, "PREVIEW URL · LIVE NOW")
        c.setFillColor(BLUE_DIM)
        c.setFont("Helvetica", 6.5)
        preview = m.get('disp', '')
        c.drawString(L + 22, prev_y - prev_h/2 - 11,
            f"https://{preview.split('/')[0]}-preview.fast.site"[:70] if preview else "")
        badges = ["EUR80/MONTH", "NO CODE CHANGES", "99.9% UPTIME SLA", "ACTIVE IN 24H"]
        bx = W - R
        for b in reversed(badges):
            bw = c.stringWidth(b, "Helvetica-Bold", 5.5) + 12
            bx -= bw
            c.setFillColor(colors.HexColor("#1E3A5F"))
            c.roundRect(bx, prev_y - prev_h/2 - 6, bw, 12, 3, fill=1, stroke=0)
            c.setFillColor(WHITE)
            c.setFont("Helvetica-Bold", 5.5)
            c.drawCentredString(bx + bw/2, prev_y - prev_h/2 - 2.5, b)
            bx -= 5

        # ── Footer ────────────────────────────────────────────────────────────
        _draw_footer(c, W)



class BusinessImpactPanel(Flowable):
    def __init__(self, proj: dict, audit: dict, width: float = CW):
        super().__init__()
        self.proj = proj or {}; self.audit = audit; self.width = width; self.height = 270
    def draw(self):
        c = self.canv; p = self.proj; a = self.audit; W = self.width; H = self.height
        cur = p.get("current", {}); imp = p.get("improvements", {})
        visitors = a.get("monthly_visitors", 5000); conv_pct = a.get("conversion_rate_pct", 2.5); aov = a.get("avg_order_value_eur", 120)
        conv_uplift = imp.get("conversion_uplift_pct", 10); ttfb_b = cur.get("ttfb_ms", 800); ps_b = cur.get("perf_score")
        monthly_rev = visitors * (conv_pct / 100) * aov
        delay_s = max(0, (ttfb_b - 1000) / 1000); spd_penalty = round(delay_s * 7)
        rev_at_risk_mo = round(monthly_rev * (spd_penalty / 100)); rev_at_risk_yr = rev_at_risk_mo * 12
        uplift_mo = round(monthly_rev * (conv_uplift / 100)); annual_uplift = uplift_mo * 12; annual_cost = 80 * 12
        net_annual = annual_uplift - annual_cost; roi_pct = min(999, round(net_annual / annual_cost * 100)) if annual_cost else 0
        payback_wks = max(1, round((80 / max(uplift_mo, 1)) * 4.3))
        payback_label = _t(f"{payback_wks} {'week' if payback_wks == 1 else 'weeks'}", f"{payback_wks} {'Woche' if payback_wks == 1 else 'Wochen'}")
        lcp_s = cur.get("lcp_ms", 4000) / 1000; bounce_est = min(90, round(32 + (lcp_s - 2.5) * 8)) if lcp_s > 2.5 else 32
        c.setFillColor(DARK); c.roundRect(0, 0, W, H, 6, fill=1, stroke=0)
        c.setFillColor(BLUE); c.roundRect(0, H - 4, W, 4, 3, fill=1, stroke=0)
        c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 11)
        c.drawString(16, H - 24, _t("BUSINESS IMPACT & ROI ANALYSIS", "GESCHAEFTSAUSWIRKUNG & ROI-ANALYSE"))
        c.setFillColor(BLUE_DIM); c.setFont("Helvetica", 8)
        c.drawString(16, H - 36, _t(f"Based on {visitors:,} estimated monthly visitors · {conv_pct}% conversion rate · EUR{aov} avg. order value", f"Basierend auf {visitors:,} Besuchern"))
        left_x = 16; block_w = (W - 40) / 2; top_y = H - 56
        c.setFillColor(colors.HexColor("#374151")); c.roundRect(left_x, top_y - 112, block_w, 108, 4, fill=1, stroke=0)
        c.setFillColor(RED); c.setFont("Helvetica-Bold", 7.5)
        c.drawString(left_x + 10, top_y - 16, _t("COST OF CURRENT SLOW SPEED", "KOSTEN DER AKTUELLEN LANGSAMEN LADEZEIT"))
        cost_stats = [(_t("Estimated conversion loss", "Gesch. Konversionsverlust"), f"~{spd_penalty}% {_t('from slow TTFB', 'durch langsamen TTFB')}", RED),
                      (_t("Monthly revenue at risk", "Monatl. Umsatz gefaehrdet"), f"EUR{rev_at_risk_mo:,.0f}", AMBER),
                      (_t("Annual revenue at risk", "Jaehrl. Umsatz gefaehrdet"), f"EUR{rev_at_risk_yr:,.0f}", AMBER),
                      (_t("Est. bounce from slow LCP", "Gesch. Absprungrate LCP"), f"~{bounce_est}% {_t('of visitors', 'der Besucher')}", RED)]
        for ki, (label, val, col) in enumerate(cost_stats):
            ky = top_y - 40 - ki * 20
            c.setFillColor(colors.HexColor("#94A3B8")); c.setFont("Helvetica", 7); c.drawString(left_x + 10, ky, label)
            c.setFillColor(col); c.setFont("Helvetica-Bold", 7.5); c.drawRightString(left_x + block_w - 10, ky, val)
        right_x = left_x + block_w + 8
        c.setFillColor(colors.HexColor("#1A2E1A")); c.roundRect(right_x, top_y - 112, block_w, 108, 4, fill=1, stroke=0)
        c.setFillColor(GREEN); c.setFont("Helvetica-Bold", 7.5)
        c.drawString(right_x + 10, top_y - 16, _t("ROI WITH FAST.SITE (EUR80/MO)", "ROI MIT FAST.SITE (EUR80/MO)"))
        roi_stats = [(_t("Monthly plan cost", "Monatl. Plankosten"), "EUR80", GRAY),
                     (_t("Est. monthly uplift", "Gesch. monatl. Mehrumsatz"), f"+EUR{uplift_mo:,}", GREEN),
                     (_t("Net annual gain", "Netto-Jahresgewinn"), f"+EUR{max(net_annual,0):,}", GREEN),
                     (_t("Return on investment up to", "Return on Investment upto"), f"{roi_pct}% {_t('annual', 'jaerl.')}", BLUE_DIM)]
        for ki, (label, val, col) in enumerate(roi_stats):
            ky = top_y - 40 - ki * 20
            c.setFillColor(colors.HexColor("#94A3B8")); c.setFont("Helvetica", 7); c.drawString(right_x + 10, ky, label)
            c.setFillColor(col); c.setFont("Helvetica-Bold", 7.5); c.drawRightString(right_x + block_w - 10, ky, val)
        pb_y = top_y - 126
        c.setFillColor(BLUE); c.roundRect(16, pb_y - 10, W - 32, 20, 4, fill=1, stroke=0)
        c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 8.5)
        c.drawCentredString(W / 2, pb_y - 3, _t(f"Estimated payback period: {payback_label} · fast.site pays for itself before your second invoice.", f"Gesch. Amortisationszeit: {payback_label}"))
        facts = [_t("53% of mobile visitors leave if a page takes >3s to load (Google)", "53% der mobilen Besucher verlassen eine Seite, die >3 Sek. laedt (Google)"),
                 _t("1s slower load time = 7% fewer conversions (Amazon & Akamai studies)", "1 Sek. laengere Ladezeit = 7% weniger Konversionen"),
                 _t("Core Web Vitals are a confirmed Google ranking signal since May 2021", "Core Web Vitals sind seit Mai 2021 ein bestaetiger Google-Rankingfaktor")]
        fact_y = pb_y - 32; fact_w = (W - 32 - 8 * 2) / 3
        for fi, fact in enumerate(facts):
            fx = 16 + fi * (fact_w + 8)
            c.setFillColor(colors.HexColor("#1F1D2E")); c.roundRect(fx, fact_y - 16, fact_w, 26, 3, fill=1, stroke=0)
            c.setFillColor(BLUE_DIM); c.setFont("Helvetica", 6)
            words = fact.split(); lines, line = [], ""
            for w in words:
                if len(line) + len(w) + 1 <= 54: line = (line + " " + w).strip()
                else: lines.append(line); line = w
            if line: lines.append(line)
            for li, ln in enumerate(lines[:2]): c.drawCentredString(fx + fact_w / 2, fact_y + 3 - li * 8, ln)

class BackCover(Flowable):
    def __init__(self):
        super().__init__()
        self.width = PAGE_W - L - R - 2 * FPAD; self.height = PAGE_H - T - B - 2 * FPAD
    def draw(self):
        c = self.canv; c.saveState(); c.translate(-(L + FPAD), -(B + FPAD)); self._full(c); c.restoreState()
    def _full(self, c):
        W, H = PAGE_W, PAGE_H
        c.setFillColor(DARK); c.rect(0, 0, W, H, fill=1, stroke=0)
        c.setFillColor(BLUE); c.rect(0, H - 5, W, 5, fill=1, stroke=0)
        c.setStrokeColor(colors.HexColor("#1F1D2E")); c.setLineWidth(0.4)
        for xi in range(-int(H), int(W) + int(H), 28): c.line(xi, H, xi + H, 0)
        glow_cy = H - 155
        c.setFillColor(colors.HexColor("#1A2340")); c.circle(W / 2, glow_cy, 82, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#1B2645")); c.circle(W / 2, glow_cy, 60, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#1E2E55")); c.circle(W / 2, glow_cy, 42, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#64748B")); c.setFont("Helvetica", 7)
        c.drawCentredString(W / 2, glow_cy + 92, _t("PERFORMANCE SOLUTION · POWERED BY", "PERFORMANCE-LOESUNG · ANGETRIEBEN VON"))
        fs = 36; fast_w = c.stringWidth("fast", "Helvetica-Bold", fs); site_w = c.stringWidth(".site", "Helvetica-Bold", fs)
        wm_x = W / 2 - (fast_w + site_w) / 2; wm_y = glow_cy - 13
        c.setFillColor(WHITE); c.setFont("Helvetica-Bold", fs); c.drawString(wm_x, wm_y, "fast")
        c.setFillColor(BLUE_DIM); c.drawString(wm_x + fast_w, wm_y, ".site")
        tag_y = glow_cy - 118
        c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 22)
        c.drawCentredString(W / 2, tag_y, _t("The CDN that fixes your audit.", "Das CDN, das Ihr Audit verbessert."))
        c.setFillColor(colors.HexColor("#94A3B8")); c.setFont("Helvetica", 9)
        c.drawCentredString(W / 2, tag_y - 19, _t("Fast Edge Cache · No code changes · Active within 24 hours", "Fast Edge Cache · Keine Code-Aenderungen"))
        c.setStrokeColor(colors.HexColor("#2D2B3D")); c.setLineWidth(0.75); c.line(W / 2 - 100, tag_y - 36, W / 2 + 100, tag_y - 36)
        c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 20); c.drawCentredString(W / 2, tag_y - 60, _t("EUR 80 / month", "EUR 80 / Monat"))
        c.setFillColor(colors.HexColor("#64748B")); c.setFont("Helvetica", 7.5)
        c.drawCentredString(W / 2, tag_y - 76, _t("Flat rate · Cancel anytime · No hidden fees", "Pauschaltarif · Jederzeit kuendbar"))
        c.setStrokeColor(colors.HexColor("#2D2B3D")); c.setLineWidth(0.5); c.line(L, tag_y - 93, W - R, tag_y - 93)
        ben_top = tag_y - 109
        left_items = _t(["Fast Edge Cache - 90%+ cache hit rate", "6 global edge nodes worldwide", "DDoS + WAF - included, no extra cost"], ["Fast Edge Cache - 90%+ Cache-Trefferrate", "6 globale Edge-Standorte weltweit", "DDoS + WAF - inklusive"])
        right_items = _t(["Free SSL/TLS · HTTP/3 · Brotli", "No code changes · DNS cutover only", "99.9% uptime SLA guaranteed"], ["Kostenloses SSL/TLS · HTTP/3 · Brotli", "Keine Code-Aenderungen · Nur DNS-Umstellung", "99,9% Uptime-SLA garantiert"])
        for ki, item in enumerate(left_items):
            iy = ben_top - ki * 18; c.setFillColor(GREEN); c.setFont("Helvetica-Bold", 8); c.drawString(L + 4, iy, "+")
            c.setFillColor(colors.HexColor("#94A3B8")); c.setFont("Helvetica", 8); c.drawString(L + 16, iy, item)
        for ki, item in enumerate(right_items):
            iy = ben_top - ki * 18; c.setFillColor(GREEN); c.setFont("Helvetica-Bold", 8); c.drawString(W / 2 + 10, iy, "+")
            c.setFillColor(colors.HexColor("#94A3B8")); c.setFont("Helvetica", 8); c.drawString(W / 2 + 22, iy, item)
        c.setStrokeColor(colors.HexColor("#2D2B3D")); c.line(L, ben_top - 50, W - R, ben_top - 50)
        edge_lbl_y = ben_top - 64; c.setFillColor(colors.HexColor("#475569")); c.setFont("Helvetica-Bold", 6.5)
        c.drawCentredString(W / 2, edge_lbl_y, _t("6 GLOBAL EDGE LOCATIONS", "6 GLOBALE EDGE-STANDORTE"))
        dots_y = edge_lbl_y - 16; locs = ["New York", "Frankfurt", "Singapore", "Hong Kong", "Istanbul", "Lima"]; spacing = (W - 2 * L) / len(locs)
        for li, loc in enumerate(locs):
            lx = L + li * spacing + spacing / 2; c.setFillColor(BLUE); c.circle(lx, dots_y, 3.5, fill=1, stroke=0)
            c.setFillColor(colors.HexColor("#94A3B8")); c.setFont("Helvetica", 6); c.drawCentredString(lx, dots_y - 12, loc)
        c.setStrokeColor(colors.HexColor("#2D2B3D")); c.setLineWidth(0.5); c.line(L, dots_y - 26, W - R, dots_y - 26)
        c.setFillColor(colors.HexColor("#94A3B8")); c.setFont("Helvetica", 7.5)
        c.drawCentredString(W / 2, dots_y - 40, _t("Start serving your site from the edge today", "Starten Sie noch heute mit Edge-Delivery"))
        cta_h = 44; cta_w = 200; cta_x = W / 2 - cta_w / 2; cta_y = dots_y - 40 - 14 - cta_h
        c.setFillColor(WHITE); c.roundRect(cta_x, cta_y, cta_w, cta_h, 22, fill=1, stroke=0)
        fs_btn = 16; fast_str = "fast"; site_str = ".site"
        fast_bw = c.stringWidth(fast_str, "Helvetica-Bold", fs_btn); site_bw = c.stringWidth(site_str, "Helvetica-Bold", fs_btn)
        wm_x = W / 2 - (fast_bw + site_bw) / 2; wm_y = cta_y + cta_h / 2 - 6
        c.setFillColor(DARK); c.setFont("Helvetica-Bold", fs_btn); c.drawString(wm_x, wm_y, fast_str)
        c.setFillColor(BLUE); c.drawString(wm_x + fast_bw, wm_y, site_str)
        c.setFillColor(BLUE_DIM); c.setFont("Helvetica", 8.5); c.drawCentredString(W / 2, cta_y - 12, "fast.site")
        trust_y = cta_y - 32; t_items = _t(["SSL / TLS", "DDoS Protected", "99.9% Uptime SLA"], ["SSL / TLS", "DDoS-Schutz", "99,9% Uptime-SLA"])
        c.setFont("Helvetica", 7)
        t_widths = [c.stringWidth(t, "Helvetica", 7) + 20 for t in t_items]; total_tw = sum(t_widths) + 14 * (len(t_items) - 1); tbx = W / 2 - total_tw / 2
        for ti, tb in enumerate(t_items):
            bw = t_widths[ti]; c.setFillColor(colors.HexColor("#1F1D2E")); c.roundRect(tbx, trust_y - 7, bw, 14, 3, fill=1, stroke=0)
            c.setStrokeColor(colors.HexColor("#374151")); c.setLineWidth(0.4); c.roundRect(tbx, trust_y - 7, bw, 14, 3, fill=0, stroke=1)
            c.setFillColor(colors.HexColor("#94A3B8")); c.setFont("Helvetica", 7); c.drawCentredString(tbx + bw / 2, trust_y - 2.5, tb); tbx += bw + 14
        c.setFillColor(colors.HexColor("#1E1C2D")); c.setFont("Helvetica-Bold", 72); c.drawCentredString(W / 2, trust_y - 86, "fast.site")
        c.setFillColor(colors.HexColor("#12111E")); c.rect(0, 0, W, 28, fill=1, stroke=0)
        c.setFillColor(colors.HexColor("#475569")); c.setFont("Helvetica", 7)
        c.drawCentredString(W / 2, 10, _t("This report is confidential and prepared exclusively for the recipient. · fast.site", "Dieser Bericht ist vertraulich. · fast.site"))

# ─── SMART FAST.SITE RECOMMENDATION ENGINE ───────────────────────────────────
# Replaces the Gemini API (which timed out, causing every card to show the same
# generic fallback line).  Instead we use a keyword-matched, data-driven local
# engine that generates a unique, issue-specific fast.site recommendation for
# every unmatched issue — no external API, no timeouts, no repeated lines.

_gemini_cache: dict[str, tuple[str, str]] = {}
_gemini_lock  = threading.Lock()

# ── fast.site feature catalogue (sourced from https://fast.site/en) ──────────
# Each entry: (keyword_triggers, impact_template, solution_template)
# Templates may use {vars} filled from context_vars.
_FS_FEATURE_MAP = [
    # Compression / assets
    (
        ["compress", "gzip", "brotli", "uncompressed", "asset"],
        (
            "Serving uncompressed assets inflates page weight and slows every load — "
            "directly hurting PageSpeed (currently **{perf}/100**) and increasing bounce rate.",
            "Nicht komprimierte Assets erhoehen das Seitengewicht und verlangsamen jeden Ladevorgang — "
            "direkte Auswirkung auf PageSpeed (aktuell **{perf}/100**) und Absprungrate."
        ),
        (
            "fast.site enables Brotli and gzip compression automatically at the edge, "
            "reducing page weight by up to **70%** with zero code or server changes — "
            "live via a single nameserver switch.",
            "fast.site aktiviert Brotli- und Gzip-Komprimierung automatisch am Edge, "
            "reduziert das Seitengewicht um bis zu **70%** ohne Code- oder Serveraenderungen — "
            "aktiv per einmaligem Nameserver-Wechsel."
        ),
    ),
    # Canonical / duplicate content
    (
        ["canonical", "duplicate", "duplicate content"],
        (
            "Without a canonical tag Google may index multiple versions of the same page, "
            "splitting ranking signals and diluting SEO authority — SEO score: **{seo}/100**.",
            "Ohne Canonical-Tag kann Google mehrere Versionen derselben Seite indexieren, "
            "was Ranking-Signale aufteilt und die SEO-Autoritaet schwaecht — SEO-Score: **{seo}/100**."
        ),
        (
            "fast.site's edge layer ensures canonical headers are consistently delivered "
            "to every crawler, protecting against duplicate-content penalties — "
            "active within **24 hours**, no code changes.",
            "Die Edge-Schicht von fast.site stellt sicher, dass Canonical-Header konsistent "
            "an jeden Crawler geliefert werden — aktiv innerhalb von **24 Stunden**, keine Code-Aenderungen."
        ),
    ),
    # Internal linking / PageRank
    (
        ["internal link", "pagerank", "link equity", "outbound link"],
        (
            "Poor internal linking means PageRank cannot flow efficiently across the site, "
            "leaving pages under-indexed — Page Ranking score: **{page_ranking}/100**.",
            "Schlechte interne Verlinkung verhindert effizienten PageRank-Fluss — "
            "Seitenranking-Score: **{page_ranking}/100**."
        ),
        (
            "fast.site's {cache}% cache hit rate ensures every internal page loads in <50ms, "
            "making crawlers index them faster and improving overall page authority distribution.",
            "Die {cache}% Cache-Trefferrate von fast.site stellt sicher, dass jede interne Seite "
            "in <50ms laedt, sodass Crawler sie schneller indexieren."
        ),
    ),
    # Heading hierarchy / content structure
    (
        ["heading", "h2", "h3", "hierarchy", "content structure"],
        (
            "A broken heading hierarchy prevents search engines from understanding page "
            "structure, suppressing rankings — PageSpeed score: **{perf}/100**.",
            "Eine fehlerhafte Ueberschriftenhierarchie verhindert, dass Suchmaschinen die "
            "Seitenstruktur verstehen — PageSpeed-Score: **{perf}/100**."
        ),
        (
            "fast.site delivers pages at edge speed (<50ms TTFB), so Googlebot crawls "
            "your full heading structure on every visit — paired with a **+{ps_gain_min}–{ps_gain_max} pt** "
            "PageSpeed uplift that signals content quality.",
            "fast.site liefert Seiten mit Edge-Geschwindigkeit (<50ms TTFB), damit Googlebot "
            "die gesamte Ueberschriftenstruktur erfasst — kombiniert mit **+{ps_gain_min}–{ps_gain_max} Punkte** "
            "PageSpeed-Verbesserung."
        ),
    ),
    # Thin / low word count content
    (
        ["thin content", "word count", "low content", "short content"],
        (
            "Thin content pages rank poorly — Google deprioritises pages without "
            "sufficient informational depth (overall score: **{overall}/100**).",
            "Duenner Content rankt schlecht — Google deprioritisiert Seiten ohne "
            "ausreichende Informationstiefe (Gesamt-Score: **{overall}/100**)."
        ),
        (
            "fast.site's edge speed ensures every content page is fully crawled, "
            "maximising the SEO value of your existing content — "
            "live within **24 hours**, no code changes.",
            "Die Edge-Geschwindigkeit von fast.site stellt sicher, dass jede Inhaltsseite "
            "vollstaendig gecrawlt wird — aktiv innerhalb von **24 Stunden**, keine Code-Aenderungen."
        ),
    ),
    # Structured data / schema
    (
        ["structured data", "json-ld", "schema", "rich snippet", "rich result"],
        (
            "No structured data means the site is ineligible for rich results in Google Search, "
            "losing significant SERP real-estate and CTR.",
            "Keine strukturierten Daten bedeutet, die Seite ist nicht berechtigt fuer "
            "Rich Results in der Google-Suche — erheblicher SERP-Verlust."
        ),
        (
            "fast.site's consistent, sub-50ms edge delivery maximises the chance that "
            "Googlebot fully renders and indexes your structured data on every crawl cycle.",
            "Die konsistente <50ms Edge-Auslieferung von fast.site maximiert die Chance, "
            "dass Googlebot strukturierte Daten bei jedem Crawl-Zyklus vollstaendig indexiert."
        ),
    ),
    # Sitemap / robots.txt
    (
        ["sitemap", "robots", "crawl", "search console"],
        (
            "Without a sitemap, crawlers navigate inefficiently and may miss key pages — "
            "compounding existing SEO weaknesses (SEO score: **{seo}/100**).",
            "Ohne Sitemap navigieren Crawler ineffizient und koennen wichtige Seiten uebersehen — "
            "SEO-Score: **{seo}/100**."
        ),
        (
            "fast.site routes sitemap.xml and robots.txt correctly at the edge, "
            "serving them at full speed from every node — active within **24 hours**, "
            "zero server configuration required.",
            "fast.site leitet sitemap.xml und robots.txt korrekt am Edge weiter — "
            "aktiv innerhalb von **24 Stunden**, keine Serverkonfiguration erforderlich."
        ),
    ),
    # Title tag / meta title
    (
        ["title tag", "<title>", "missing title", "page title"],
        (
            "A missing title tag is one of the most severe on-page SEO failures — "
            "search engines have no primary text signal for the page.",
            "Ein fehlender Title-Tag ist einer der schwersten On-Page-SEO-Fehler — "
            "Suchmaschinen haben kein primaeres Textsignal fuer die Seite."
        ),
        (
            "fast.site's edge delivery ensures title tags are consistently served to "
            "every crawler at <50ms, paired with a **+{ps_gain_min}–{ps_gain_max} pt** PageSpeed "
            "gain that amplifies your SEO recovery.",
            "Die Edge-Auslieferung von fast.site stellt sicher, dass Title-Tags konsistent "
            "bei <50ms an jeden Crawler geliefert werden — kombiniert mit **+{ps_gain_min}–{ps_gain_max} Punkte** "
            "PageSpeed-Gewinn."
        ),
    ),
    # Privacy / terms / trust
    (
        ["privacy", "terms", "trust signal", "policy", "gdpr"],
        (
            "Missing privacy or terms pages reduce visitor trust and may breach "
            "regulations — Trust score: **{trust}/100**.",
            "Fehlende Datenschutz- oder AGB-Seiten reduzieren das Vertrauen der Besucher "
            "und koennen gegen Vorschriften verstossen — Vertrauens-Score: **{trust}/100**."
        ),
        (
            "fast.site provides **99.9% uptime SLA** and auto-renewing SSL/TLS 1.3 — "
            "the technical trust baseline that complements your legal pages, "
            "served from the edge with zero downtime.",
            "fast.site bietet **99,9% Uptime-SLA** und automatisch erneuerndes SSL/TLS 1.3 — "
            "die technische Vertrauensbasis, die Ihre rechtlichen Seiten ergaenzt."
        ),
    ),
    # Security headers
    (
        ["security header", "x-frame", "csp", "content security", "x-content-type", "referrer-policy", "mime"],
        (
            "Missing security headers expose visitors to clickjacking and XSS attacks — "
            "security score: **{ddos}/100**.",
            "Fehlende Sicherheits-Header setzen Besucher Clickjacking- und XSS-Angriffen aus — "
            "Sicherheits-Score: **{ddos}/100**."
        ),
        (
            "fast.site injects X-Frame-Options, CSP, and Referrer-Policy at the edge "
            "via the dashboard — no server access needed, enforced globally across "
            "all **6 edge locations** within **24 hours**.",
            "fast.site setzt X-Frame-Options, CSP und Referrer-Policy am Edge ueber das Dashboard — "
            "kein Serverzugang noetig, global aktiv innerhalb von **24 Stunden**."
        ),
    ),
    # HSTS
    (
        ["hsts", "downgrade", "https redirect", "ssl redirect"],
        (
            "Without HSTS, users can be silently downgraded to HTTP — "
            "exposing sessions to interception and hurting security scores.",
            "Ohne HSTS koennen Nutzer stillschweigend auf HTTP herabgestuft werden — "
            "Sitzungen sind abhoergefaehrdet und Sicherheits-Scores sinken."
        ),
        (
            "fast.site enforces HSTS and provisions TLS 1.3 certificates automatically — "
            "protecting every visitor and strengthening Google's HTTPS ranking signal, "
            "live with a single nameserver switch.",
            "fast.site erzwingt HSTS und stellt TLS-1.3-Zertifikate automatisch bereit — "
            "aktiv per einmaligem Nameserver-Wechsel."
        ),
    ),
    # DDoS / WAF / rate limiting
    (
        ["ddos", "waf", "rate limit", "credential", "flood", "bot", "attack"],
        (
            "Without rate-limiting or WAF, login pages and forms are open to "
            "credential-stuffing and automated attacks — security score: **{ddos}/100**.",
            "Ohne Rate-Limiting oder WAF sind Login-Seiten und Formulare fuer "
            "Credential-Stuffing und automatisierte Angriffe anfaellig — Sicherheits-Score: **{ddos}/100**."
        ),
        (
            "fast.site's ML-based bot management and always-on WAF block malicious "
            "traffic at the network edge before it reaches your origin — included at "
            "no extra cost, active within **24 hours**.",
            "Das ML-basierte Bot-Management und der permanente WAF von fast.site blockieren "
            "boschaertigen Datenverkehr am Netzwerk-Edge — inklusive, aktiv innerhalb von **24 Stunden**."
        ),
    ),
    # CDN / no CDN
    (
        ["no cdn", "cdn not", "without cdn", "single origin", "origin server"],
        (
            "Without a CDN, every request travels to a single origin server — "
            "Speed score: **{speed}/100**. Latency scales with visitor distance.",
            "Ohne CDN reist jede Anfrage zu einem einzigen Ursprungsserver — "
            "Geschwindigkeits-Score: **{speed}/100**. Latenz steigt mit Besucherentfernung."
        ),
        (
            "fast.site's **6 global edge nodes** serve content in <50ms worldwide, "
            "achieving a **{cache}% cache hit rate** and cutting TTFB by up to **98%** — "
            "live via a single nameserver switch.",
            "**6 globale Edge-Knoten** von fast.site liefern Inhalte in <50ms weltweit, "
            "erzielen eine **{cache}% Cache-Trefferrate** und reduzieren TTFB um bis zu **98%**."
        ),
    ),
    # Page speed / performance score
    (
        ["pagespeed", "performance score", "core web vitals", "cwv"],
        (
            "A low PageSpeed score is a direct Google ranking signal — "
            "Performance score: **{perf}/100**. Poor Core Web Vitals reduce SERP visibility.",
            "Ein niedriger PageSpeed-Score ist ein direktes Google-Rankingsignal — "
            "Leistungs-Score: **{perf}/100**. Schlechte Core Web Vitals reduzieren die SERP-Sichtbarkeit."
        ),
        (
            "fast.site Fast Edge Cache™ projects PageSpeed from **{perf} to {ps_lo}–{ps_hi}/100** "
            "(+{ps_gain_min}–{ps_gain_max} pts) — delivered via nameserver switch, "
            "no code changes, active within 24 hours.",
            "fast.site Fast Edge Cache™ projiziert PageSpeed von **{perf} auf {ps_lo}–{ps_hi}/100** "
            "(+{ps_gain_min}–{ps_gain_max} Punkte) — per Nameserver-Wechsel, keine Code-Aenderungen, "
            "aktiv innerhalb von 24 Stunden."
        ),
    ),
    # Image optimisation / WebP
    (
        ["image", "webp", "image size", "large image", "unoptimised", "unoptimized"],
        (
            "Unoptimised images inflate page weight and slow LCP — "
            "a direct hit to PageSpeed and user experience.",
            "Nicht optimierte Bilder erhoehen das Seitengewicht und verlangsamen LCP — "
            "direkte Auswirkung auf PageSpeed und Nutzererlebnis."
        ),
        (
            "fast.site automatically converts images to WebP at the edge, "
            "reducing file sizes by up to **80%** and cutting LCP to **~1.8s** — "
            "zero code, zero plugins, just a nameserver switch.",
            "fast.site konvertiert Bilder automatisch in WebP am Edge, "
            "reduziert Dateigroessen um bis zu **80%** und senkt LCP auf **~1,8s** — "
            "kein Code, keine Plugins, nur ein Nameserver-Wechsel."
        ),
    ),
    # Conversion / CTA / revenue
    (
        ["conversion", "cta", "call-to-action", "call to action", "revenue", "sales"],
        (
            "Poor page speed directly reduces conversions — "
            "every 1s delay costs ~7% in conversions (Amazon/Akamai data).",
            "Schlechte Seitengeschwindigkeit reduziert Konversionen direkt — "
            "jede 1s Verzoegerung kostet ~7% Konversionen (Amazon/Akamai-Daten)."
        ),
        (
            "fast.site's edge delivery targets a **{conv}% conversion uplift** by "
            "cutting LCP to ~1.8s and TTFB to ~180ms — "
            "most sites see first results within **15 minutes** of going live.",
            "Die Edge-Auslieferung von fast.site zielt auf einen **{conv}% Konversionsanstieg** "
            "durch Reduzierung von LCP auf ~1,8s und TTFB auf ~180ms — "
            "die meisten Seiten sehen erste Ergebnisse innerhalb von **15 Minuten**."
        ),
    ),
]

_fs_rec_used: dict[str, int] = {}
_fs_rec_lock = threading.Lock()

def _smart_fastsite_rec(issue: str, ctx: dict) -> tuple[str, str]:
    t = issue.lower()
    overall      = ctx.get("overall", 50)
    perf         = ctx.get("perf", 50)
    seo          = ctx.get("seo", 50)
    speed        = ctx.get("speed", 50)
    ddos         = ctx.get("ddos", 50)
    trust        = ctx.get("trust", 25)
    page_ranking = ctx.get("page_ranking", 25)
    ps_gain_min  = ctx.get("ps_gain_min", 25)
    ps_gain_max  = ctx.get("ps_gain_max", 40)
    ps_lo        = ctx.get("ps_lo", perf + ps_gain_min)
    ps_hi        = ctx.get("ps_hi", perf + ps_gain_max)
    cache        = ctx.get("cache", 90)
    conv         = ctx.get("conv", 18)

    fmt_vars = dict(
        overall=overall, perf=perf, seo=seo, speed=speed,
        ddos=ddos, trust=trust, page_ranking=page_ranking,
        ps_gain_min=ps_gain_min, ps_gain_max=ps_gain_max,
        ps_lo=ps_lo, ps_hi=ps_hi, cache=cache, conv=conv,
    )

    matches = [
        (imp_tpl, sol_tpl)
        for (kws, imp_tpl, sol_tpl) in _FS_FEATURE_MAP
        if any(kw in t for kw in kws)
    ]

    # General rotating pool — bilingual tuples (en, de)
    general_pool = [
        (
            (f"This issue directly contributes to a site health score of **{overall}/100**, reducing organic visibility and user trust.",
             f"Dieses Problem traegt zu einem Website-Gesundheits-Score von **{overall}/100** bei und reduziert organische Sichtbarkeit."),
            (f"fast.site Fast Edge Cache™ lifts PageSpeed by +{ps_gain_min}–{ps_gain_max} pts and achieves a {cache}% cache hit rate — live via nameserver switch, no code changes.",
             f"fast.site Fast Edge Cache™ steigert PageSpeed um +{ps_gain_min}–{ps_gain_max} Punkte und erzielt eine {cache}% Cache-Trefferrate — per Nameserver-Wechsel."),
        ),
        (
            (f"Unresolved, this issue compounds the site's existing weaknesses (overall score: **{overall}/100**) and limits organic growth.",
             f"Ungeklaert verstaerkt dieses Problem die bestehenden Schwaechen der Seite (Gesamt-Score: **{overall}/100**)."),
            (f"fast.site serves content from 6 global edge nodes in <50ms worldwide, cutting TTFB to ~180ms and LCP to ~1.8s — active within 24 hours.",
             f"fast.site liefert Inhalte von 6 globalen Edge-Knoten in <50ms weltweit, reduziert TTFB auf ~180ms und LCP auf ~1,8s."),
        ),
        (
            (f"This gap reduces the site's competitiveness in search and conversion (overall score: **{overall}/100**).",
             f"Diese Luecke reduziert die Wettbewerbsfaehigkeit der Seite bei Suche und Konversion (Gesamt-Score: **{overall}/100**)."),
            (f"fast.site's always-on DDoS protection, free SSL, and {cache}% cache hit rate deliver the performance and security foundation needed — €80/month flat, cancel anytime.",
             f"Der permanente DDoS-Schutz, kostenloses SSL und {cache}% Cache-Trefferrate von fast.site liefern die noetige Leistungs- und Sicherheitsbasis — 80€/Monat, jederzeit kuendbar."),
        ),
        (
            (f"Leaving this unaddressed keeps the site below competitors with a **{overall}/100** overall score.",
             f"Ohne Behebung bleibt die Seite mit einem Gesamt-Score von **{overall}/100** hinter Wettbewerbern zurueck."),
            (f"Automatic Brotli compression and HTTP/3 at the edge reduce page weight by up to 70%, delivering a +{ps_gain_min}–{ps_gain_max} pt PageSpeed gain — zero code changes required.",
             f"Automatische Brotli-Komprimierung und HTTP/3 am Edge reduzieren das Seitengewicht um bis zu 70% — +{ps_gain_min}–{ps_gain_max} Punkte PageSpeed-Gewinn."),
        ),
        (
            (f"This issue suppresses user engagement and signals poor site quality to search engines (score: **{overall}/100**).",
             f"Dieses Problem unterdrueckt das Nutzerengagement und signalisiert Suchmaschinen schlechte Seitenqualitaet (Score: **{overall}/100**)."),
            (f"fast.site's ML-based bot management and 99.9% uptime SLA ensure the site stays fast and protected — estimated **{conv}% conversion uplift** from faster loads.",
             f"Das ML-basierte Bot-Management und 99,9% Uptime-SLA von fast.site halten die Seite schnell und geschuetzt — geschaetzter **{conv}% Konversionsanstieg**."),
        ),
        (
            (f"Without addressing this, the site's **{overall}/100** score continues to drag down rankings and revenue.",
             f"Ohne Behebung zieht der **{overall}/100** Score der Seite weiterhin Rankings und Umsatz nach unten."),
            (f"fast.site's WebP image pipeline shrinks assets by up to 80%, and edge caching achieves a {cache}% hit rate — most sites go live within 15 minutes of the nameserver switch.",
             f"Die WebP-Bild-Pipeline von fast.site verkleinert Assets um bis zu 80%, Edge-Caching erzielt eine {cache}% Trefferrate."),
        ),
    ]

    pool = matches if matches else general_pool

    issue_key = t[:80]
    with _fs_rec_lock:
        idx = _fs_rec_used.get(issue_key, abs(hash(issue_key)) % len(pool))
        imp_tpl, sol_tpl = pool[idx % len(pool)]
        _fs_rec_used[issue_key] = (idx + 1) % len(pool)

    # Each tpl is now a (en, de) tuple — pick the right language
    imp_en, imp_de = imp_tpl if isinstance(imp_tpl, tuple) else (imp_tpl, imp_tpl)
    sol_en, sol_de = sol_tpl if isinstance(sol_tpl, tuple) else (sol_tpl, sol_tpl)
    imp_raw = imp_de if _LANG == "de" else imp_en
    sol_raw = sol_de if _LANG == "de" else sol_en

    try:
        impact   = imp_raw.format(**fmt_vars)
        solution = sol_raw.format(**fmt_vars)
    except KeyError:
        impact   = imp_raw
        solution = sol_raw

    return impact, solution


def _gemini_fallback_rec(issue: str, context_vars: dict) -> tuple[str, str]:
    """
    Wrapper kept for API compatibility with _rec().
    Uses the local smart engine — no external API call, no timeouts,
    always returns a unique, issue-matched fast.site recommendation.
    Cache key includes language so EN and DE are stored separately.
    """
    cache_key = f"{_LANG}:{issue.lower().strip()}"
    with _gemini_lock:
        if cache_key in _gemini_cache:
            return _gemini_cache[cache_key]

    result = _smart_fastsite_rec(issue, context_vars)

    with _gemini_lock:
        _gemini_cache[cache_key] = result
    return result



def _rec(issue: str, bd: dict, proj: dict) -> tuple:
    t = issue.lower(); p = proj or {}; cur = p.get("current", {}); prj = p.get("projected", {}); imp = p.get("improvements", {})
    perf = (bd.get("performance") or {}).get("score", 50); seo = (bd.get("seo") or {}).get("score", 50); speed = (bd.get("speed") or {}).get("score", 50)
    mob = (bd.get("mobile") or {}).get("score", 50); ddos = (bd.get("ddos_security") or {}).get("score", 50); trust = (bd.get("trust") or {}).get("score", 50)
    ttfb_b = cur.get("ttfb_ms", 800); ttfb_a = prj.get("ttfb_ms", 10); ttfb_p = imp.get("ttfb_speedup_pct", 0)
    lcp_b = cur.get("lcp_ms", 4000); lcp_a = prj.get("lcp_ms", 1800); lcp_p = imp.get("lcp_improvement_pct", 55)
    fcp_b = cur.get("fcp_ms", 3000); fcp_a = prj.get("fcp_ms", 1500); fcp_p = imp.get("fcp_improvement_pct", 50)
    bw_p = imp.get("bandwidth_saving_pct", 70); conv = imp.get("conversion_uplift_pct", 0); cache = p.get("cache_hit_rate_pct", 90)
    # Use the actual measured performance score; fall back to breakdown score, never hardcode 50
    _proj_perf = cur.get("perf_score")
    ps_b = _proj_perf if _proj_perf is not None else perf
    ps_lo = prj.get("perf_score_min", ps_b + 25); ps_hi = prj.get("perf_score_max", ps_b + 40)

    if "ttfb" in t or ("server" in t and "response" in t):
        return (_t(f"Server response is **{ttfb_b:,}ms** — every user and every crawler waits this long.", f"Die Server-Antwortzeit betraegt **{ttfb_b:,}ms**."), _t(f"Fast Edge Cache reduces this to ~{ttfb_a}ms (**{ttfb_p}% improvement**).", f"Fast Edge Cache reduziert dies auf ~{ttfb_a}ms (**{ttfb_p}% Verbesserung**)."))
    if "lcp" in t or "largest contentful" in t:
        return (_t(f"Largest Contentful Paint is failing Google's 2,500ms 'Good' threshold.", f"Der Largest Contentful Paint unterschreitet Googles 2.500ms-Grenzwert."), _t(f"Edge delivery projects LCP from {lcp_b/1000:.1f}s to **~{lcp_a/1000:.1f}s** ({lcp_p}% improvement).", f"Edge-Delivery projiziert LCP von {lcp_b/1000:.1f}s auf **~{lcp_a/1000:.1f}s** ({lcp_p}% Verbesserung)."))
    if "fcp" in t or "first contentful" in t:
        return (_t(f"First Contentful Paint is slow — users see a blank screen.", f"Der First Contentful Paint ist zu langsam."), _t(f"Edge caching projects FCP from {fcp_b/1000:.1f}s to **~{fcp_a/1000:.1f}s** ({fcp_p}% improvement).", f"Edge-Caching projiziert FCP von {fcp_b/1000:.1f}s auf **~{fcp_a/1000:.1f}s** ({fcp_p}% Verbesserung)."))
    if "cdn" in t and ("no" in t or "detect" in t):
        return (_t(f"No CDN detected — every request travels to a single origin server. Speed score: **{speed}/100**.", f"Kein CDN erkannt. Geschwindigkeits-Score: **{speed}/100**."), _t(f"6 global edge nodes deliver content in <50ms worldwide.", f"6 globale Edge-Knoten liefern Inhalte in <50ms weltweit."))
    if "cache" in t and "control" in t:
        return (_t(f"No Cache-Control headers — browsers cannot cache assets.", f"Keine Cache-Control-Header — Browser koennen keine Assets zwischenspeichern."), _t(f"Optimal caching policies applied automatically, achieving a **{cache}% cache hit rate**.", f"Optimale Caching-Regeln werden automatisch angewendet, mit einer **{cache}% Cache-Trefferrate**."))
    if "pagespeed" in t or ("performance" in t and "score" in t):
        return (_t(f"PageSpeed score is critically low. Performance score: **{perf}/100**.", f"Der PageSpeed-Wert ist kritisch niedrig. Leistungs-Score: **{perf}/100**."), _t(f"Fast Edge Cache projects the score from **{ps_b} -> {ps_lo}-{ps_hi}/100**.", f"Fast Edge Cache projiziert den Score von **{ps_b} auf {ps_lo}-{ps_hi}/100**."))
    if "ddos" in t or "waf" in t or "volumetric" in t:
        return (_t(f"No DDoS protection or WAF detected. Security score: **{ddos}/100**.", f"Kein DDoS-Schutz oder WAF erkannt. Sicherheits-Score: **{ddos}/100**."), _t(f"DDoS mitigation and WAF are included at the network edge.", f"DDoS-Abwehr und WAF sind am Netzwerk-Edge inklusive."))
    if "rate-limit" in t or "rate limit" in t or "credential" in t:
        return (_t(f"No rate-limiting — bots can hit login forms without restriction.", f"Kein Rate-Limiting — Bots koennen Login-Formulare ohne Einschraenkung treffen."), _t(f"ML-based bot management blocks abuse before it reaches your origin.", f"ML-basiertes Bot-Management blockiert Missbrauch."))
    if "hsts" in t:
        return (_t(f"HTTPS present but HSTS not enforced. Security score: **{ddos}/100**.", f"HTTPS vorhanden, aber HSTS nicht durchgesetzt. Sicherheits-Score: **{ddos}/100**."), _t(f"HSTS is enforced and TLS 1.3 certificates provisioned.", f"HSTS wird durchgesetzt und TLS-1.3-Zertifikate bereitgestellt."))
    if "security header" in t or "x-frame" in t or "csp" in t or "content-security" in t:
        return (_t(f"Critical security headers are missing. Security score: **{ddos}/100**.", f"Kritische Sicherheits-Header fehlen. Sicherheits-Score: **{ddos}/100**."), _t(f"X-Frame-Options, CSP, and Referrer-Policy can be set from the dashboard.", f"X-Frame-Options, CSP und Referrer-Policy koennen im Dashboard gesetzt werden."))
    if "meta description" in t:
        return (_t(f"Missing or overlong meta description. SEO score: **{seo}/100**.", f"Fehlende oder zu lange Meta-Beschreibung. SEO-Score: **{seo}/100**."), _t(f"Edge delivery ensures metadata propagates to crawlers consistently.", f"Edge-Delivery stellt sicher, dass Metadaten konsistent an Crawler uebertragen werden."))
    if "h1" in t:
        return (_t(f"H1 tag issues — primary content signal is missing. SEO score: **{seo}/100**.", f"H1-Tag-Probleme. SEO-Score: **{seo}/100**."), _t(f"Fast delivery ensures semantic HTML is parsed correctly.", f"Schnelle Auslieferung stellt sicher, dass HTML korrekt verarbeitet wird."))
    if "alt text" in t or "alt attribute" in t:
        return (_t(f"Images missing alt attributes. SEO score: **{seo}/100**.", f"Bilder ohne Alt-Attribute. SEO-Score: **{seo}/100**."), _t(f"Image pipeline auto-converts assets to WebP ({bw_p}% smaller).", f"Die Bild-Pipeline konvertiert Assets automatisch in WebP ({bw_p}% kleiner)."))
    if "tap target" in t:
        return (_t(f"Tap targets too small for reliable mobile interaction. Mobile score: **{mob}/100**.", f"Touch-Ziele zu klein. Mobil-Score: **{mob}/100**."), _t(f"Edge delivery improves mobile Core Web Vitals.", f"Edge-Delivery verbessert die mobilen Core Web Vitals."))
    if "privacy" in t or "terms" in t:
        return (_t(f"Privacy policy or terms not found. Trust score: **{trust}/100**.", f"Datenschutzerklaerung oder AGB nicht gefunden. Vertrauens-Score: **{trust}/100**."), _t(f"99.9% uptime SLA and auto-renewing SSL provide the technical trust baseline.", f"99,9% Uptime-SLA und SSL liefern die technische Vertrauensbasis."))
    if "sitemap" in t:
        return (_t(f"No sitemap detected — crawlers navigate inefficiently.", f"Kein Sitemap erkannt."), _t(f"Sitemap and robots.txt are routed correctly at the edge.", f"Sitemap und robots.txt werden am Edge korrekt weitergeleitet."))
    if "social proof" in t or "testimonial" in t:
        return (_t(f"Limited social proof signals reduce trust and conversion.", f"Begrenzte Social-Proof-Signale reduzieren Vertrauen."), _t(f"Faster loads reduce abandonment — estimated **{conv}% conversion uplift**.", f"Schnellere Ladezeiten reduzieren Abbrueche — geschaetzter **{conv}% Konversionsanstieg**."))
    if "cta" in t or ("call" in t and "action" in t):
        return (_t(f"Insufficient calls-to-action detected.", f"Ungenuegend Handlungsaufforderungen erkannt."), _t(f"Faster loads directly improve CTA visibility — estimated **{conv}% conversion uplift**.", f"Schnellere Ladezeiten verbessern die CTA-Sichtbarkeit — geschaetzter **{conv}% Konversionsanstieg**."))
    if "open graph" in t or "og:" in t:
        return (_t(f"Open Graph tags missing — social platforms generate poor previews.", f"Open-Graph-Tags fehlen."), _t(f"Edge caching ensures social crawlers always receive accurate OG data.", f"Edge-Caching stellt sicher, dass soziale Crawler korrekte OG-Daten erhalten."))
    if "structured data" in t or "json-ld" in t or "schema" in t:
        return (_t(f"No structured data — not eligible for rich results in Google Search.", f"Keine strukturierten Daten — nicht berechtigt fuer Rich Results."), _t(f"Consistent delivery maximises structured data crawl reliability.", f"Konsistente Auslieferung maximiert die Crawler-Zuverlaessigkeit."))
    # ── Gemini AI fallback for unmatched issues ────────────────────────────────
    overall = round(perf*0.18 + seo*0.20 + speed*0.18 + mob*0.10 + ddos*0.08 + trust*0.04)
    ps_gain_min = imp.get("perf_score_gain_min", 25)
    ps_gain_max = imp.get("perf_score_gain_max", 40)
    ai_impact, ai_solution = _gemini_fallback_rec(issue, {
        "overall":     overall,
        "perf":        perf,
        "seo":         seo,
        "speed":       speed,
        "ps_gain_min": ps_gain_min,
        "ps_gain_max": ps_gain_max,
        "conv":        conv,
        "cache":       cache,
    })
    return ai_impact, ai_solution

_ISSUE_TRANSLATIONS_DE = {
    # ── CDN / Speed ───────────────────────────────────────────────────────────
    "no cdn detected":
        "Kein CDN erkannt — alle Anfragen treffen den Ursprungsserver direkt",
    "no cdn":
        "Kein CDN erkannt",
    "critical ttfb":
        "Kritische Server-Antwortzeit (TTFB)",
    "very slow server response":
        "Sehr langsame Server-Antwortzeit",
    "slow server response":
        "Langsame Server-Antwortzeit",
    "ttfb":
        "Server-Antwortzeit zu langsam",
    # ── Performance / PageSpeed ───────────────────────────────────────────────
    "performance needs work":
        "Leistungs-Score verbesserungsbeduerftig",
    "below google":
        "Unter dem von Google empfohlenen Schwellenwert",
    "pagespeed":
        "PageSpeed-Score niedrig",
    "performance":
        "Leistungs-Score niedrig",
    # ── Core Web Vitals ───────────────────────────────────────────────────────
    "largest contentful paint":
        "Largest Contentful Paint zu langsam",
    "lcp":
        "LCP zu langsam",
    "first contentful paint":
        "First Contentful Paint zu langsam",
    "fcp":
        "FCP zu langsam",
    # ── Security / DDoS ──────────────────────────────────────────────────────
    "no ddos protection layer detected":
        "Kein DDoS-Schutz erkannt — Website hat keinen WAF- oder CDN-Schutz",
    "no waf":
        "Kein WAF erkannt",
    "no ddos":
        "Kein DDoS-Schutz erkannt",
    "volumetric attack":
        "Volumetrischer Angriff kann die Website in Minuten offline nehmen",
    "no rate-limiting headers detected":
        "Kein Rate-Limiting erkannt — Login-Seiten anfaellig fuer Credential-Stuffing",
    "rate-limit":
        "Kein Rate-Limiting",
    "hsts header missing":
        "HSTS-Header fehlt — Downgrade-Angriffe moeglich",
    "hsts":
        "HSTS nicht durchgesetzt",
    "no security headers":
        "Sicherheits-Header fehlen (Clickjacking-Schutz, CSP, MIME-Schutz)",
    "security header":
        "Sicherheits-Header fehlt",
    "no https":
        "Kein HTTPS aktiviert",
    # ── SEO ──────────────────────────────────────────────────────────────────
    "no sitemap link":
        "Keine Sitemap-Verknuepfung — sitemap.xml bei Google Search Console einreichen",
    "no sitemap":
        "Keine Sitemap erkannt",
    "sitemap":
        "Sitemap-Problem",
    "meta description too short":
        "Meta-Beschreibung zu kurz — niedrige Klickrate",
    "meta description":
        "Meta-Beschreibung fehlt oder zu kurz",
    "no h1 tag found":
        "Kein H1-Tag gefunden — Suchmaschinen koennen das Hauptthema nicht erkennen",
    "h1":
        "H1-Tag-Problem",
    "missing alt text":
        "Fehlende Alt-Texte — schadet Bild-SEO und Barrierefreiheit",
    "alt text":
        "Alt-Text fehlt",
    "weak internal linking":
        "Schwache interne Verlinkung — schlechte PageRank-Verteilung",
    "poor pagerank":
        "Schlechte PageRank-Verteilung ueber die Website",
    "noindex":
        "Seite auf noindex gesetzt",
    "canonical":
        "Kanonisches Tag-Problem",
    "no title":
        "Kein Title-Tag",
    "duplicate title":
        "Doppelter Title-Tag",
    "keyword cannibali":
        "Keyword-Kannibalisierung erkannt",
    "blocked by robots":
        "Durch robots.txt blockiert",
    # ── Page Ranking / Content ────────────────────────────────────────────────
    "poor heading hierarchy":
        "Fehlerhafte Ueberschriftenhierarchie — Suchmaschinen verstehen die Seitenstruktur nicht",
    "heading hierarchy":
        "Ueberschriftenhierarchie-Problem",
    "thin content":
        "Duenner Inhalt — Google koennte die Seite als minderwertig einstufen",
    "few/no outbound links":
        "Wenige oder keine ausgehenden Links — verpasste Chance zur Expertensignalisierung",
    "outbound links":
        "Fehlende ausgehende Links",
    "pagerank won":
        "PageRank fliesst nicht effektiv durch die Website",
    # ── Client Reach / Trust ─────────────────────────────────────────────────
    "no clear calls-to-action detected":
        "Keine klaren Handlungsaufforderungen erkannt — Besucher haben keinen Weg zum Kunden",
    "no clear calls":
        "Keine klaren Handlungsaufforderungen",
    "no cta":
        "Keine Handlungsaufforderung",
    "only 1 contact channel":
        "Nur 1 Kontaktkanal gefunden — stark eingeschraenkte Reichweite",
    "contact channel":
        "Zu wenige Kontaktkanaele",
    "no social proof detected":
        "Kein Social Proof erkannt — keine Bewertungen, Testimonials oder Logos",
    "no social proof":
        "Kein Social Proof vorhanden",
    # ── Mobile ───────────────────────────────────────────────────────────────
    "tap target":
        "Tipp-Ziele zu klein (<44px) — beeintraechtigt Usability und Google-Mobile-Ranking",
    "small tap":
        "Tipp-Ziele zu klein",
    "mobile audit failed":
        "Mobil-Audit fehlgeschlagen",
    # ── Privacy / Trust ──────────────────────────────────────────────────────
    "no privacy":
        "Datenschutzseite fehlt",
    "privacy":
        "Datenschutzseite fehlt",
}


def _translate_issue(text: str) -> str:
    """For German mode, return a fully translated issue title.

    Matching order:
    1. Longest-key substring match (most specific wins).
    2. Fallback — return the original text unchanged.
    """
    if _LANG != "de":
        return text
    tl = text.strip().lower()
    # Longest key first so more specific phrases beat shorter ones
    for en_key in sorted(_ISSUE_TRANSLATIONS_DE, key=len, reverse=True):
        if en_key in tl:
            return _ISSUE_TRANSLATIONS_DE[en_key]
    return text


# ─── STRENGTH TRANSLATIONS (DE) ───────────────────────────────────────────────
_STRENGTH_TRANSLATIONS_DE = {
    # ── SEO ──────────────────────────────────────────────────────────────────
    "title tag present":
        "Titel-Tag vorhanden",
    "meta description present":
        "Meta-Beschreibung vorhanden",
    "canonical url set":
        "Kanonische URL gesetzt",
    "canonical url tag present":
        "Kanonischer URL-Tag vorhanden",
    "open graph tags present":
        "Open-Graph-Tags vorhanden",
    "schema markup present":
        "Schema-Markup vorhanden",
    "structured data (json-ld) present":
        "Strukturierte Daten (JSON-LD) vorhanden — berechtigt fuer Rich Snippets",
    "structured data present":
        "Strukturierte Daten vorhanden — berechtigt fuer Rich-Ergebnisse in SERPs",
    "single h1 tag":
        "Einzelner H1-Tag vorhanden",
    "https enabled":
        "HTTPS aktiviert",
    "https":
        "HTTPS aktiviert — bestaetiges Google-Rankingsignal",
    "sitemap present":
        "Sitemap vorhanden",
    "robots.txt found and appears valid":
        "robots.txt gefunden und gueltig",
    "robots.txt present":
        "robots.txt vorhanden",
    "robots meta tag present":
        "Robots-Meta-Tag vorhanden (kein noindex)",
    "hreflang tags present":
        "hreflang-Tags vorhanden",
    "lighthouse":
        "Guter Lighthouse-Score",
    # ── Performance / Speed ───────────────────────────────────────────────────
    "lightweight page":
        "Leichtgewichtige Seite — schnelle Ladezeit",
    "fast page load":
        "Schnelle Seitenladezeit",
    "good lcp":
        "Guter LCP-Wert",
    "good fcp":
        "Guter FCP-Wert",
    "low cls":
        "Niedriger CLS-Wert",
    "low tbt":
        "Niedriger TBT-Wert",
    "images optimised":
        "Bilder optimiert",
    "images optimized":
        "Bilder optimiert",
    "browser caching enabled":
        "Browser-Caching aktiviert",
    "cache-control header present":
        "Cache-Control-Header vorhanden",
    "gzip/brotli":
        "Gzip/Brotli-Komprimierung aktiviert",
    "gzip":
        "Gzip/Brotli-Komprimierung aktiviert",
    "brotli":
        "Brotli-Komprimierung aktiviert",
    "minified css":
        "CSS und JavaScript minifiziert",
    "minified javascript":
        "JavaScript minifiziert",
    # ── Mobile ────────────────────────────────────────────────────────────────
    "page loads successfully on mobile":
        "Seite wird auf Mobilgeraeten erfolgreich geladen",
    "viewport meta tag present":
        "Viewport-Meta-Tag vorhanden",
    "no horizontal overflow":
        "Kein horizontales Ueberlaufen — passt auf Mobilbildschirm",
    "mobile-friendly":
        "Mobilfreundliches Design",
    "responsive design":
        "Responsives Design",
    "tap targets":
        "Tipp-Ziele korrekt dimensioniert",
    # ── Security / DDoS ──────────────────────────────────────────────────────
    "ddos protection":
        "DDoS-Schutz vorhanden",
    "waf enabled":
        "WAF aktiviert",
    "ssl certificate":
        "SSL-Zertifikat gueltig",
    "security headers present":
        "Sicherheits-Header vorhanden",
    "hsts enabled":
        "HSTS aktiviert",
    # ── Trust / Content / Design ─────────────────────────────────────────────
    "privacy/terms links found":
        "Datenschutz-/AGB-Links vorhanden — staerkt Nutzer- und Suchmaschinenvertrauen",
    "privacy":
        "Datenschutzseite vorhanden",
    "social proof present":
        "Social Proof vorhanden",
    "clear calls to action":
        "Klare Handlungsaufforderungen vorhanden",
    "contact form present":
        "Kontaktformular vorhanden",
    "good content quality":
        "Gute Inhaltsqualitaet",
    "consistent branding":
        "Einheitliches Branding",
    "accessibility score":
        "Guter Barrierefreiheitswert",
    "visible headline":
        "Sichtbare Ueberschrift/Wertversprechen — erster Eindruck kommuniziert Zweck klar",
    "value proposition":
        "Wertversprechen in Ueberschriften sichtbar",
    # ── Client Reach ─────────────────────────────────────────────────────────
    "good local presence signals":
        "Gute lokale Praesenz-Signale — unterstuetzt lokale Suchauffindbarkeit und Reichweite",
    "local presence":
        "Lokale Praesenz-Signale vorhanden",
    "local seo":
        "Lokale SEO-Signale vorhanden",
    "google business profile":
        "Google-Unternehmensprofil verknuepft",
    "social media profiles":
        "Social-Media-Profile verknuepft",
    # ── PageSpeed / Lighthouse ────────────────────────────────────────────────
    "good pagespeed":
        "Guter PageSpeed-Score",
    "good performance score":
        "Guter Leistungs-Score",
}


def _translate_strength(text: str) -> str:
    """Return the German translation of a strength string when in DE mode.

    Strategy:
    1. Exact match on lowercased full string.
    2. Substring match — longest key first to prefer the most specific hit.
    3. Fallback — return the original text unchanged.
    """
    if _LANG != "de":
        return text
    tl = text.strip().lower()
    if tl in _STRENGTH_TRANSLATIONS_DE:
        return _STRENGTH_TRANSLATIONS_DE[tl]
    for en_key in sorted(_STRENGTH_TRANSLATIONS_DE, key=len, reverse=True):
        if en_key in tl:
            return _STRENGTH_TRANSLATIONS_DE[en_key]
    return text


# ─── HEADER / FOOTER CALLBACK ─────────────────────────────────────────────────
def _make_callbacks(audit):
    biz = (audit.get("business_name") or audit.get("url", ""))[:46]
    def on_first(canvas, doc): pass
    def on_later(canvas, doc):
        W = PAGE_W; canvas.saveState()
        canvas.setStrokeColor(RULE); canvas.setLineWidth(0.5)
        canvas.line(L, PAGE_H - T, W - R, PAGE_H - T)
        if os.path.exists(LOGO_PATH):
            canvas.drawImage(LOGO_PATH, L, PAGE_H - T + 2, width=42, height=21,
                             preserveAspectRatio=True, mask='auto')
        canvas.setFillColor(GRAY); canvas.setFont("Helvetica", 7)
        canvas.drawRightString(W - R, PAGE_H - T + 9, biz)
        canvas.drawRightString(W - R, PAGE_H - T + 1,
                               _t("WEBSITE PERFORMANCE AUDIT", "WEBSITE LEISTUNGSANALYSE"))
        canvas.line(L, B - 5, W - R, B - 5); canvas.setFont("Helvetica", 7)
        canvas.drawString(L, B - 14,
            _t("fast.site · Independent Performance Analysis · Confidential",
               "fast.site · Unabhaengige Leistungsanalyse · Vertraulich"))
        canvas.drawRightString(W - R, B - 14,
            _t(f"Page {doc.page}", f"Seite {doc.page}"))
        canvas.restoreState()
    return on_first, on_later


# ─── SMART LAYOUT HELPERS ─────────────────────────────────────────────────────
# Available content height on a normal (non-cover) page
_CONTENT_H = PAGE_H - T - B          # ~257 mm  ≈ 729 pt

# Minimum space we require at the bottom of a page before we allow a heading
# to sit there without its section content.  If less than this remains, we
# push the whole section to the next page.
_MIN_HEADING_GUARD = 130             # points — banner(46) + heading(14) + spacers + first card stub

class _SpaceGuard(Flowable):
    """
    A zero-height flowable that forces a page-break when the remaining space
    on the current page is less than `min_space` points.
    Placed *before* a heading so the heading never appears alone at the
    bottom of a page.
    """
    def __init__(self, min_space: float):
        super().__init__()
        self.min_space = min_space
        self.width = 0
        self.height = 0

    def wrap(self, aW, aH):
        return (0, 0)

    def draw(self):
        pass

    def splitOn(self, availWidth, availHeight):
        # Called by the layout engine when it tries to split us.
        # We never split — always keep whole (zero height, nothing to split).
        return [self]

    # The magic: if available height is less than min_space, report that we
    # need more space than available so the engine breaks to the next page.
    def wrap(self, aW, aH):         # noqa: F811  (intentional redefinition)
        self._available = aH
        if aH < self.min_space:
            return (0, aH + 1)      # triggers a page break
        return (0, 0)


def _estimate_height(flowables) -> float:
    """Rough height estimate for a list of flowables (no actual layout)."""
    total = 0.0
    for f in flowables:
        if isinstance(f, Flowable):
            try:
                w, h = f.wrap(CW, 9999)
                total += h
            except Exception:
                total += 20
        else:
            total += 20
    return total


def _section_fits_on_one_page(flowables) -> bool:
    """Return True if the section's estimated height fits in one page."""
    return _estimate_height(flowables) <= _CONTENT_H - 30  # 30pt safety margin


# ─── CONTACT INFO PANEL ───────────────────────────────────────────────────────
class ContactInfoPanel(Flowable):
    """
    Renders extracted contact info (email, phone, contact page, CDN status)
    as a styled dark card matching the report palette.
    """
    _ROW_H  = 22   # height per data row
    _PAD    = 14   # internal padding
    _ICON_W = 18   # icon column width

    def __init__(self, contact: dict, cdn: dict, width: float = CW):
        super().__init__()
        self.contact = contact or {}
        self.cdn     = cdn     or {}
        self.width   = width
        # Calculate height from actual rows
        rows = self._rows()
        self.height = self._PAD * 2 + max(len(rows) * self._ROW_H, self._ROW_H) + 36

    def _rows(self) -> list[tuple[str, str, bool]]:
        """Return list of (icon_char, value_text, is_good) tuples."""
        rows: list[tuple[str, str, bool]] = []
        c = self.contact
        d = self.cdn

        emails = c.get("emails") or []
        phones = c.get("phones") or []
        contact_page = c.get("contact_page")
        has_cdn = d.get("has_cdn", False)
        cdn_name = d.get("cdn_name") or "None detected"

        if emails:
            for e in emails[:2]:
                rows.append(("@", e, True))
        else:
            rows.append(("@", "No email found", False))

        if phones:
            for p in phones[:2]:
                rows.append(("T", p, True))
        else:
            rows.append(("T", "No phone found", False))

        if contact_page:
            rows.append(("W", contact_page[:70], True))
        else:
            rows.append(("W", "No contact page detected", False))

        if has_cdn:
            rows.append(("C", f"CDN detected: {cdn_name}", False))
        else:
            rows.append(("C", "No CDN detected - fast.site opportunity", True))

        return rows

    def draw(self):
        c    = self.canv
        W, H = self.width, self.height
        rows = self._rows()

        # Card background
        c.setFillColor(DARK)
        c.roundRect(0, 0, W, H, 6, fill=1, stroke=0)
        c.setFillColor(BLUE)
        c.roundRect(0, H - 4, W, 4, 3, fill=1, stroke=0)

        # Header
        c.setFillColor(WHITE)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(self._PAD, H - 24, _t("CONTACT INFORMATION", "KONTAKTINFORMATIONEN"))
        c.setFillColor(BLUE_DIM)
        c.setFont("Helvetica", 7.5)
        c.drawString(self._PAD, H - 36,
            _t("Extracted from website · Used to reach out with audit results",
               "Von der Website extrahiert · Fuer die Kontaktaufnahme"))

        # Rows
        row_start_y = H - 36 - self._PAD
        icon_labels = {"@": "EMAIL", "T": "PHONE", "W": "CONTACT PAGE", "C": "CDN STATUS"}
        for i, (icon, value, is_good) in enumerate(rows):
            ry = row_start_y - i * self._ROW_H
            val_col  = GREEN  if is_good else (RED if not is_good and icon != "C" else AMBER)
            if icon == "C":
                val_col = AMBER if is_good else RED
                # invert: no CDN = good lead (green-ish opportunity label)
                val_col = GREEN if is_good else RED

            # Row separator
            if i > 0:
                c.setStrokeColor(colors.HexColor("#2D2B3D"))
                c.setLineWidth(0.4)
                c.line(self._PAD, ry + self._ROW_H - 2, W - self._PAD, ry + self._ROW_H - 2)

            # Icon/label badge
            badge_w = 82
            c.setFillColor(colors.HexColor("#1F1D2E"))
            c.roundRect(self._PAD, ry, badge_w, 14, 3, fill=1, stroke=0)
            c.setFillColor(BLUE_DIM)
            c.setFont("Helvetica-Bold", 6)
            c.drawString(self._PAD + 5, ry + 4, icon_labels.get(icon, icon))

            # Value
            c.setFillColor(val_col)
            c.setFont("Helvetica-Bold" if is_good else "Helvetica", 8)
            c.drawString(self._PAD + badge_w + 8, ry + 4, _safe(value[:80]))


# ─── BUILD STORY ──────────────────────────────────────────────────────────────
def _build_category_block(cat_label: str, cat_key: str, cat_hex: str,
                           bd: dict, proj: dict, st: dict) -> list:
    """
    Return the flowables for one audit category section.
    Uses KeepTogether on the banner + first card so the header never
    strands alone at the bottom of a page.
    """
    cat_data  = bd.get(cat_key) or {}
    issues    = _clean(cat_data.get("issues", []))
    strengths = cat_data.get("strengths", [])
    score     = cat_data.get("score", 0)

    if not issues and not strengths:
        return []

    block: list = []

    # Banner + "Issues Identified" heading kept together
    header_group = [
        SectionBanner(_cat_label(cat_label), score, cat_hex),
        Spacer(1, 6),
    ]
    if issues:
        header_group.append(
            Paragraph(_t("<b>Issues Identified</b>", "<b>Erkannte Probleme</b>"), st["H3"])
        )
        header_group.append(Spacer(1, 4))
        # Include first issue card in the KeepTogether so the banner is
        # never printed alone at the very bottom of a page.
        first_sev, first_col = _sev(issues[0])
        first_impact, first_solution = _rec(issues[0], bd, proj)
        header_group.append(
            IssueCard(issues[0], first_impact, first_solution, first_sev, first_col)
        )
        header_group.append(Spacer(1, 5))

    block.append(KeepTogether(header_group))

    # Remaining issue cards — each wrapped in KeepTogether so a card is
    # never split mid-card across pages.
    for iss in issues[1:]:
        sev, sev_col = _sev(iss)
        impact, solution = _rec(iss, bd, proj)
        block.append(KeepTogether([
            IssueCard(iss, impact, solution, sev, sev_col),
            Spacer(1, 5),
        ]))

    # Strengths
    if strengths:
        block.append(Spacer(1, 4))
        block.append(KeepTogether([
            Paragraph(_t("<b>Strengths</b>", "<b>Staerken</b>"), st["H3"]),
            Spacer(1, 4),
            Paragraph(
                f'<font color="#059669">&#10003;</font> {_safe(_translate_strength(strengths[0]))}',
                st["Check"],
            ),
        ]))
        block.append(Spacer(1, 3))
        for s in strengths[1:]:
            block.append(
                Paragraph(
                    f'<font color="#059669">&#10003;</font> {_safe(_translate_strength(s))}',
                    st["Check"],
                )
            )
            block.append(Spacer(1, 3))

    block.append(Spacer(1, 10))
    return block


def _story(audit: dict) -> list:
    """
    Build the full PDF story matching the shared PDF format:
      Page 1  — Proposal / speed-gain cover
      Page 2  — Performance projection (Core Web Vitals + comparison table)
      Pages 3+— Category detail sections (packed, no forced blank pages)
      Next    — Business Impact & ROI
      Next    — Priority Action Plan (ranked issue table)
      Next    — Contact Information (if extracted)
      Last    — Back cover / CTA
    """
    st      = _styles()
    bd      = audit.get("breakdown", {})
    proj    = audit.get("fastsite_projection") or {}
    contact = audit.get("contact_info") or {}
    cdn     = audit.get("cdn_info")    or {}
    story   = []

    # ── Page 1: Proposal cover ────────────────────────────────────────────────
    story.append(ProposalPage(audit))
    story.append(PageBreak())

    # ── Page 2: Performance projection ───────────────────────────────────────
    story.append(ProjectionPage(audit))
    story.append(PageBreak())

    # ── Pages 3+: Category detail sections (no forced page breaks) ────────────
    # Categories flow continuously; KeepTogether prevents orphan headers.
    for cat_label, cat_key, cat_hex in CATS:
        block = _build_category_block(cat_label, cat_key, cat_hex, bd, proj, st)
        story.extend(block)

    # ── Business Impact & ROI ─────────────────────────────────────────────────
    story.append(Spacer(1, 6))
    roi_group = [
        Paragraph(
            _t("<b>Business Impact &amp; ROI Analysis</b>",
               "<b>Geschaeftsauswirkung &amp; ROI-Analyse</b>"),
            st["H2"],
        ),
        Spacer(1, 8),
        BusinessImpactPanel(proj, audit),
        Spacer(1, 10),
    ]
    story.append(KeepTogether(roi_group))

    # ── Priority Action Plan ──────────────────────────────────────────────────
    story.append(Spacer(1, 10))
    story.append(KeepTogether([
        Paragraph(_t("<b>Priority Action Plan</b>", "<b>Prioritaets-Aktionsplan</b>"), st["H2"]),
        Spacer(1, 4),
        Paragraph(
            _t(
                "All issues ranked by severity. Resolve CRITICAL items first — "
                "they cause the most ranking and revenue damage.",
                "Alle Probleme nach Schweregrad sortiert. Kritische Probleme zuerst beheben.",
            ),
            st["BodyG"],
        ),
        Spacer(1, 8),
    ]))

    sev_order      = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    sev_colors_map = {"CRITICAL": RED, "HIGH": AMBER, "MEDIUM": SKY, "LOW": GREEN}
    all_ranked: list = []
    for cat_l, cat_k, _ in CATS:
        for iss in _clean((bd.get(cat_k) or {}).get("issues", [])):
            sev, _ = _sev(iss)
            all_ranked.append((sev_order.get(sev, 4), sev, _cat_label(cat_l), iss))
    all_ranked.sort(key=lambda x: x[0])

    col_widths = [8*mm, 22*mm, 32*mm, CW - 8*mm - 22*mm - 32*mm]
    tbl_data = [[
        Paragraph(_t("<b>#</b>",        "<b>#</b>"),        st["Small"]),
        Paragraph(_t("<b>Severity</b>", "<b>Schweregrad</b>"), st["Small"]),
        Paragraph(_t("<b>Category</b>", "<b>Kategorie</b>"),   st["Small"]),
        Paragraph(_t("<b>Issue</b>",    "<b>Problem</b>"),     st["Small"]),
    ]]
    tbl_styles = [
        ("BACKGROUND",    (0, 0), (-1, 0),  colors.HexColor("#1A1925")),
        ("TEXTCOLOR",     (0, 0), (-1, 0),  WHITE),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",      (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1),
         [colors.HexColor("#F8FAFC"), colors.HexColor("#EEF3FF")]),
        ("GRID",          (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
    ]
    for idx, (_, sev, cat_l, iss) in enumerate(all_ranked, 1):
        # Darker, higher-contrast severity shade (white text) instead of the
        # very pale tint previously used — makes the severity column read
        # like a proper badge rather than a faint background wash.
        _bg = colors.HexColor(
            "#B91C1C" if sev == "CRITICAL" else
            "#C2670C" if sev == "HIGH"     else
            "#1D4ED8" if sev == "MEDIUM"   else "#15803D"
        )
        row = [
            Paragraph(str(idx), st["Small"]),
            Paragraph(f'<font color="#FFFFFF"><b>{_sev_label(sev)}</b></font>', st["Small"]),
            Paragraph(_safe(cat_l), st["Small"]),
            Paragraph(_safe(iss),   st["Small"]),
        ]
        tbl_data.append(row)
        tbl_styles.append(("BACKGROUND", (1, idx), (1, idx), _bg))

    priority_tbl = Table(tbl_data, colWidths=col_widths, repeatRows=1)
    priority_tbl.setStyle(TableStyle(tbl_styles))
    story.append(priority_tbl)

    # ── Contact Information (if extracted) ────────────────────────────────────
    has_contact = bool(
        contact.get("emails") or contact.get("phones") or contact.get("contact_page")
    )
    if has_contact or cdn:
        story.append(Spacer(1, 14))
        story.append(KeepTogether([
            Paragraph(
                _t("<b>Contact Information</b>", "<b>Kontaktinformationen</b>"),
                st["H2"],
            ),
            Spacer(1, 6),
            ContactInfoPanel(contact, cdn),
            Spacer(1, 10),
        ]))

    # ── Back cover ────────────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(BackCover())

    return story


# ─── PUBLIC API ───────────────────────────────────────────────────────────────
def generate_audit_pdf(audit: dict, lang: str = "en",
                       run_contact_extract: bool = False) -> bytes:
    """
    Generate the full audit PDF.

    Args:
        audit:               The audit result dict (must contain 'url', 'breakdown', etc.)
        lang:                'en' or 'de'
        run_contact_extract: If True, automatically call contact_extractor on audit['url']
                             and embed the results.  The caller can also pre-populate
                             audit['contact_info'] and audit['cdn_info'] themselves.
    """
    global _LANG
    _LANG = lang if lang in ("en", "de") else "en"

    # ── Auto-run contact extractor if requested ───────────────────────────────
    if run_contact_extract and audit.get("url"):
        try:
            from contact_extractor import extract_contact_info, detect_cdn
            url = audit["url"]
            if "contact_info" not in audit:
                audit["contact_info"] = extract_contact_info(url)
            if "cdn_info" not in audit:
                audit["cdn_info"] = detect_cdn(url)
        except Exception:
            pass  # never block PDF generation

    buf = io.BytesIO()
    on_first, on_later = _make_callbacks(audit)
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=L, rightMargin=R, topMargin=T, bottomMargin=B,
        onFirstPage=on_first,
        onLaterPages=on_later,
        title=f"fast.site Audit — {audit.get('url', '')}",
        author="fast.site",
        subject=_t("Website Performance Audit", "Website-Leistungsanalyse"),
        allowSplitting=1,
    )
    doc.build(_story(audit))
    return buf.getvalue()


def _auto_recommendation(issue: str, breakdown: dict) -> str:
    proj = breakdown.get("fastsite_projection") or {}
    impact, solution = _rec(issue, breakdown, proj)
    return f"{impact}\n\n{solution}"