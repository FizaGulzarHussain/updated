"""
preview_api.py
──────────────
Fast.site Preview Measurement API client.

Wraps the async POST /preview → poll GET /preview/{id} workflow.
All calls are synchronous (for Streamlit compatibility) with a configurable
poll interval and timeout.

Usage:
    from preview_api import run_preview_measurement, PreviewResult

    result = run_preview_measurement("https://example.com", api_key="...")
    if result.ok:
        print(result.ttfb_improvement_pct)
        print(result.preview_url)
"""
from __future__ import annotations

import time
import os
from dataclasses import dataclass, field
from typing import Optional

import requests

# ─────────────────────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────────────────────
BASE_URL       = "https://api.fast.site"
POLL_INTERVAL  = 5      # seconds between polls
MAX_WAIT       = 120    # seconds before giving up
REQUEST_TIMEOUT = 15    # seconds for each HTTP call


# ─────────────────────────────────────────────────────────────────────────────
# DATA MODELS
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class PageSpeedData:
    score: int = 0
    accessibility: int = 0
    best_practices: int = 0
    seo: int = 0
    speed_index_ms: Optional[int] = None
    fcp_ms: Optional[int] = None
    lcp_ms: Optional[int] = None
    tbt_ms: Optional[int] = None
    cls: Optional[float] = None

    @classmethod
    def from_dict(cls, d: dict) -> "PageSpeedData":
        if not d:
            return cls()
        return cls(
            score=d.get("score", 0),
            accessibility=d.get("accessibility", 0),
            best_practices=d.get("best_practices", 0),
            seo=d.get("seo", 0),
            speed_index_ms=d.get("speed_index_ms"),
            fcp_ms=d.get("fcp_ms"),
            lcp_ms=d.get("lcp_ms"),
            tbt_ms=d.get("tbt_ms"),
            cls=d.get("cls"),
        )


@dataclass
class ComparisonData:
    ttfb_improvement_pct: int = 0
    ttlb_improvement_pct: int = 0
    response_bytes_savings_pct: int = 0
    inconclusive: bool = False
    inconclusive_reason: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "ComparisonData":
        if not d:
            return cls()
        return cls(
            ttfb_improvement_pct=d.get("ttfb_improvement_pct", 0),
            ttlb_improvement_pct=d.get("ttlb_improvement_pct", 0),
            response_bytes_savings_pct=d.get("response_bytes_savings_pct", 0),
            inconclusive=d.get("inconclusive", False),
            inconclusive_reason=d.get("inconclusive_reason"),
        )


@dataclass
class PreviewResult:
    """Fully resolved result from the Preview Measurement API."""
    ok: bool                               # True = status "done" with usable data
    job_id: str = ""
    url: str = ""
    preview_url: str = ""
    status: str = ""                       # "done" | "error" | "timeout" | "api_error"
    error_message: str = ""

    # Populated when ok=True
    origin: PageSpeedData = field(default_factory=PageSpeedData)
    preview: PageSpeedData = field(default_factory=PageSpeedData)
    score_improvement: int = 0
    comparison: ComparisonData = field(default_factory=ComparisonData)

    # ── Convenience shortcuts ──────────────────────────────────────────────────
    @property
    def ttfb_improvement_pct(self) -> int:
        return self.comparison.ttfb_improvement_pct

    @property
    def inconclusive(self) -> bool:
        return self.comparison.inconclusive

    @property
    def has_improvement(self) -> bool:
        """True when real (non-inconclusive) improvement data is available."""
        return self.ok and not self.inconclusive

    @property
    def perf_score_origin(self) -> int:
        return self.origin.score

    @property
    def perf_score_preview(self) -> int:
        return self.preview.score


# ─────────────────────────────────────────────────────────────────────────────
# LOW-LEVEL API CALLS
# ─────────────────────────────────────────────────────────────────────────────
def _auth_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _start_job(url: str, api_key: str) -> tuple[str | None, str | None, str]:
    """
    POST /preview — start (or reuse) a measurement job.

    Returns (job_id, preview_url, error_message).
    On success: error_message is "".
    On failure: job_id and preview_url are None.
    """
    try:
        resp = requests.post(
            f"{BASE_URL}/preview",
            json={"url": url},
            headers=_auth_headers(api_key),
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.ConnectionError:
        return None, None, "Cannot reach api.fast.site — check network connectivity."
    except requests.exceptions.Timeout:
        return None, None, "api.fast.site did not respond in time."
    except Exception as e:
        return None, None, f"Unexpected error starting job: {e}"

    if resp.status_code == 401:
        return None, None, "Invalid PREVIEW_SERVICE_KEY — check your secrets.toml."
    if resp.status_code == 503:
        return None, None, "Preview service not configured on server."
    if resp.status_code == 400:
        body = resp.json() if resp.content else {}
        return None, None, body.get("error", "Invalid URL supplied.")
    if resp.status_code not in (200, 202):
        return None, None, f"Unexpected response {resp.status_code}: {resp.text[:200]}"

    body = resp.json()
    return body.get("id"), body.get("preview_url"), ""


def _poll_job(job_id: str, api_key: str) -> tuple[dict | None, str]:
    """
    GET /preview/{id} — poll once.

    Returns (body_dict, error_message).
    """
    try:
        resp = requests.get(
            f"{BASE_URL}/preview/{job_id}",
            headers=_auth_headers(api_key),
            timeout=REQUEST_TIMEOUT,
        )
    except requests.exceptions.Timeout:
        return None, "Poll request timed out."
    except Exception as e:
        return None, f"Poll error: {e}"

    if resp.status_code == 401:
        return None, "Invalid PREVIEW_SERVICE_KEY."
    if resp.status_code == 404:
        return None, f"Job {job_id} not found."
    if resp.status_code != 200:
        return None, f"Unexpected poll response {resp.status_code}."

    return resp.json(), ""


# ─────────────────────────────────────────────────────────────────────────────
# HIGH-LEVEL BLOCKING RUNNER
# ─────────────────────────────────────────────────────────────────────────────
def run_preview_measurement(
    url: str,
    api_key: str,
    poll_interval: int = POLL_INTERVAL,
    max_wait: int = MAX_WAIT,
    progress_callback=None,
) -> PreviewResult:
    """
    Start a preview measurement job for `url` and block until it finishes
    (or times out / errors).

    Args:
        url:               Target URL to measure.
        api_key:           PREVIEW_SERVICE_KEY.
        poll_interval:     Seconds between GET /preview/{id} calls.
        max_wait:          Hard timeout in seconds.
        progress_callback: Optional callable(str) for status messages —
                           useful for Streamlit spinners.

    Returns:
        PreviewResult (ok=True on success, ok=False on any failure).
    """
    def _log(msg: str):
        if progress_callback:
            progress_callback(msg)

    # ── 1. Start ──────────────────────────────────────────────────────────────
    _log("🚀 Provisioning fast.site edge preview…")
    job_id, preview_url, err = _start_job(url, api_key)
    if err:
        return PreviewResult(ok=False, url=url, status="api_error", error_message=err)

    _log(f"✅ Preview provisioned — polling for results (job {job_id[:8]}…)")

    # ── 2. Poll ───────────────────────────────────────────────────────────────
    deadline = time.time() + max_wait
    attempts = 0

    while time.time() < deadline:
        time.sleep(poll_interval)
        attempts += 1
        body, err = _poll_job(job_id, api_key)

        if err:
            _log(f"⚠️ Poll attempt {attempts} failed: {err}")
            continue

        status = body.get("status", "")
        _log(f"📡 Status: {status} (attempt {attempts})")

        if status == "pending":
            continue

        if status == "error":
            return PreviewResult(
                ok=False,
                job_id=job_id,
                url=url,
                preview_url=preview_url or "",
                status="error",
                error_message="Preview job failed on the server (stale or uncacheable origin).",
            )

        if status == "done":
            ps_raw   = body.get("pagespeed") or {}
            cmp_raw  = body.get("comparison") or {}
            origin   = PageSpeedData.from_dict(ps_raw.get("origin", {}))
            preview  = PageSpeedData.from_dict(ps_raw.get("preview", {}))
            cmp_data = ComparisonData.from_dict(cmp_raw)

            _log("✅ Measurement complete!")
            return PreviewResult(
                ok=True,
                job_id=job_id,
                url=url,
                preview_url=preview_url or body.get("preview_url", ""),
                status="done",
                origin=origin,
                preview=preview,
                score_improvement=ps_raw.get("score_improvement", 0),
                comparison=cmp_data,
            )

    # ── Timeout ───────────────────────────────────────────────────────────────
    return PreviewResult(
        ok=False,
        job_id=job_id,
        url=url,
        preview_url=preview_url or "",
        status="timeout",
        error_message=f"Measurement did not complete within {max_wait}s ({attempts} polls).",
    )


# ─────────────────────────────────────────────────────────────────────────────
# STREAMLIT DISPLAY HELPER
# ─────────────────────────────────────────────────────────────────────────────
def render_preview_results(result: PreviewResult):
    """
    Render a rich PreviewResult card inside Streamlit.
    Call this after run_preview_measurement() inside a st.expander or container.
    """
    import streamlit as st

    if not result.ok:
        st.error(f"❌ Preview measurement failed: {result.error_message}")
        if result.preview_url:
            st.markdown(f"Preview URL (may still be live): [{result.preview_url}]({result.preview_url})")
        return

    # ── Preview URL ───────────────────────────────────────────────────────────
    st.markdown(
        f"""
<div style="background:#EFF6FF;border:1px solid #BFDBFE;border-radius:8px;
            padding:12px 16px;margin-bottom:16px;">
  <div style="font-size:12px;font-weight:600;color:#1E40AF;text-transform:uppercase;
              letter-spacing:.05em;margin-bottom:4px;">🌐 Live Fast.site Edge Preview</div>
  <a href="{result.preview_url}" target="_blank"
     style="color:#2563EB;font-weight:600;font-size:0.95rem;word-break:break-all;">
    {result.preview_url}
  </a>
  <div style="font-size:11px;color:#6B7A99;margin-top:4px;">
    Shareable now — content served from the nearest fast.site POP
  </div>
</div>""",
        unsafe_allow_html=True,
    )

    # ── Inconclusive note (TTFB/TTLB comparison only — PageSpeed scores below
    #    are still real lab measurements and are shown regardless) ────────────
    if result.inconclusive:
        reason = result.comparison.inconclusive_reason or "Origin returned uncacheable / dynamic responses."
        st.info(
            f"ℹ️ **Network timing comparison inconclusive** — {reason}\n\n"
            "The preview URL is live and working. PageSpeed / Lighthouse scores below were "
            "still measured successfully; only the TTFB/TTLB speed-improvement comparison "
            "couldn't be reliably computed for this origin."
        )

    # ── Score cards ───────────────────────────────────────────────────────────
    st.markdown("**PageSpeed Scores — Origin vs Preview**")
    c1, c2, c3 = st.columns(3)

    def _score_colour(s: int) -> str:
        return "#2E7D32" if s >= 80 else ("#F57F17" if s >= 50 else "#C62828")

    def _delta_html(val: int, suffix: str = "") -> str:
        if val > 0:
            return f'<span style="color:#2E7D32;font-weight:600;">▲ +{val}{suffix}</span>'
        if val < 0:
            return f'<span style="color:#C62828;font-weight:600;">▼ {val}{suffix}</span>'
        return f'<span style="color:#888;">± 0{suffix}</span>'

    with c1:
        score_delta = result.score_improvement
        st.markdown(
            f"""<div style="background:#F9F9F9;border-radius:8px;padding:14px;text-align:center;">
  <div style="font-size:11px;color:#6B7A99;font-weight:600;text-transform:uppercase;
              letter-spacing:.05em;margin-bottom:6px;">Performance Score</div>
  <div style="font-size:13px;color:#888;">Origin</div>
  <div style="font-size:26px;font-weight:700;color:{_score_colour(result.perf_score_origin)};">
    {result.perf_score_origin}</div>
  <div style="font-size:13px;color:#888;margin-top:8px;">Preview</div>
  <div style="font-size:26px;font-weight:700;color:{_score_colour(result.perf_score_preview)};">
    {result.perf_score_preview}</div>
  <div style="margin-top:6px;">{_delta_html(score_delta, " pts")}</div>
</div>""",
            unsafe_allow_html=True,
        )

    if result.inconclusive:
        with c2:
            st.markdown(
                """<div style="background:#F9F9F9;border-radius:8px;padding:14px;text-align:center;height:100%;">
  <div style="font-size:11px;color:#6B7A99;font-weight:600;text-transform:uppercase;
              letter-spacing:.05em;margin-bottom:6px;">TTFB Improvement</div>
  <div style="font-size:24px;color:#94A3B8;margin-top:10px;">—</div>
  <div style="font-size:12px;color:#94A3B8;margin-top:4px;">not comparable for this origin</div>
</div>""",
                unsafe_allow_html=True,
            )
        with c3:
            st.markdown(
                """<div style="background:#F9F9F9;border-radius:8px;padding:14px;text-align:center;height:100%;">
  <div style="font-size:11px;color:#6B7A99;font-weight:600;text-transform:uppercase;
              letter-spacing:.05em;margin-bottom:6px;">TTLB & Payload</div>
  <div style="font-size:24px;color:#94A3B8;margin-top:10px;">—</div>
  <div style="font-size:12px;color:#94A3B8;margin-top:4px;">not comparable for this origin</div>
</div>""",
                unsafe_allow_html=True,
            )
    else:
        with c2:
            ttfb_pct = result.comparison.ttfb_improvement_pct
            st.markdown(
                f"""<div style="background:#F9F9F9;border-radius:8px;padding:14px;text-align:center;">
  <div style="font-size:11px;color:#6B7A99;font-weight:600;text-transform:uppercase;
              letter-spacing:.05em;margin-bottom:6px;">TTFB Improvement</div>
  <div style="font-size:38px;font-weight:700;color:{_score_colour(ttfb_pct)};">{ttfb_pct}%</div>
  <div style="font-size:12px;color:#888;margin-top:4px;">faster server response</div>
  <div style="margin-top:6px;">{_delta_html(ttfb_pct, "%")}</div>
</div>""",
                unsafe_allow_html=True,
            )

        with c3:
            ttlb_pct = result.comparison.ttlb_improvement_pct
            bytes_pct = result.comparison.response_bytes_savings_pct
            st.markdown(
                f"""<div style="background:#F9F9F9;border-radius:8px;padding:14px;text-align:center;">
  <div style="font-size:11px;color:#6B7A99;font-weight:600;text-transform:uppercase;
              letter-spacing:.05em;margin-bottom:6px;">TTLB & Payload</div>
  <div style="font-size:26px;font-weight:700;color:{_score_colour(ttlb_pct)};">{ttlb_pct}%</div>
  <div style="font-size:12px;color:#888;margin-top:2px;">faster full load</div>
  <div style="font-size:20px;font-weight:700;color:#2563EB;margin-top:8px;">{bytes_pct}%</div>
  <div style="font-size:12px;color:#888;">bytes saved</div>
</div>""",
                unsafe_allow_html=True,
            )

    # ── Lighthouse category scores (Accessibility / Best Practices / SEO) ────
    st.markdown("**Lighthouse Category Scores — Origin vs Preview**")
    _lh_cats = [
        ("Accessibility", result.origin.accessibility, result.preview.accessibility),
        ("Best Practices", result.origin.best_practices, result.preview.best_practices),
        ("SEO", result.origin.seo, result.preview.seo),
    ]
    _lh_cols = st.columns(3)
    for _lh_col, (_lh_label, _lh_orig, _lh_prev) in zip(_lh_cols, _lh_cats):
        with _lh_col:
            _lh_delta = _lh_prev - _lh_orig
            st.markdown(
                f"""<div style="background:#F9F9F9;border-radius:8px;padding:14px;text-align:center;">
  <div style="font-size:11px;color:#6B7A99;font-weight:600;text-transform:uppercase;
              letter-spacing:.05em;margin-bottom:6px;">{_lh_label}</div>
  <div style="font-size:13px;color:#888;">Origin</div>
  <div style="font-size:22px;font-weight:700;color:{_score_colour(_lh_orig)};">{_lh_orig}</div>
  <div style="font-size:13px;color:#888;margin-top:6px;">Preview</div>
  <div style="font-size:22px;font-weight:700;color:{_score_colour(_lh_prev)};">{_lh_prev}</div>
  <div style="margin-top:6px;">{_delta_html(_lh_delta, " pts")}</div>
</div>""",
                unsafe_allow_html=True,
            )

    # ── Core Web Vitals comparison table ─────────────────────────────────────
    cwv_rows = []
    metrics = [
        ("LCP", result.origin.lcp_ms, result.preview.lcp_ms, 2500, "ms"),
        ("FCP", result.origin.fcp_ms, result.preview.fcp_ms, 1800, "ms"),
        ("TBT", result.origin.tbt_ms, result.preview.tbt_ms, 200,  "ms"),
        ("CLS", result.origin.cls,    result.preview.cls,    0.1,   ""),
        ("Speed Index", result.origin.speed_index_ms, result.preview.speed_index_ms, 3400, "ms"),
    ]
    for label, orig_val, prev_val, threshold, unit in metrics:
        if orig_val is None and prev_val is None:
            continue
        o_str = f"{orig_val:.3f}" if isinstance(orig_val, float) else (f"{orig_val}{unit}" if orig_val is not None else "—")
        p_str = f"{prev_val:.3f}" if isinstance(prev_val, float) else (f"{prev_val}{unit}" if prev_val is not None else "—")
        if orig_val and prev_val:
            improvement = round((orig_val - prev_val) / orig_val * 100) if orig_val else 0
            delta = f"▲ {improvement}% faster" if improvement > 0 else ("▼ slower" if improvement < 0 else "—")
        else:
            delta = "—"
        cwv_rows.append({"Metric": label, "Origin": o_str, "Preview": p_str, "Improvement": delta})

    if cwv_rows:
        st.markdown("**Core Web Vitals Comparison**")
        import pandas as pd
        st.dataframe(
            pd.DataFrame(cwv_rows).set_index("Metric"),
            use_container_width=True,
        )

    st.caption(f"Job ID: `{result.job_id}` · Measurements are median of 3 runs, mobile strategy")


# ─────────────────────────────────────────────────────────────────────────────
# KEY RESOLUTION
# ─────────────────────────────────────────────────────────────────────────────
def get_preview_api_key() -> str | None:
    """
    Resolve the PREVIEW_SERVICE_KEY from (in priority order):
      1. Streamlit secrets  (st.secrets["PREVIEW_SERVICE_KEY"])
      2. Environment variable  (os.environ["PREVIEW_SERVICE_KEY"])
    Returns None if not found.
    """
    # Try Streamlit secrets first (works in deployed and local with secrets.toml)
    try:
        import streamlit as st
        key = st.secrets.get("PREVIEW_SERVICE_KEY")
        if key:
            return key
    except Exception:
        pass
    # Fall back to env var
    return os.environ.get("PREVIEW_SERVICE_KEY")