import streamlit as st


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _badge(label: str, colour: str) -> str:
    """Return an HTML badge span."""
    colours = {
        "critical": ("#7A1A1A", "#FCEBEB"),
        "high":     ("#7C3B0A", "#FFF3E0"),
        "medium":   ("#6B5000", "#FFFDE7"),
        "low":      ("#1B4D2E", "#E8F5E9"),
        "good":     ("#0D4A2F", "#E8F5E9"),
        "info":     ("#0C3A6B", "#E3F2FD"),
    }
    fg, bg = colours.get(colour, ("#333", "#EEE"))
    return (
        f'<span style="background:{bg};color:{fg};padding:2px 8px;'
        f'border-radius:4px;font-size:11px;font-weight:600;'
        f'letter-spacing:.5px;text-transform:uppercase;">{label}</span>'
    )


def _score_colour(score: int) -> str:
    if score >= 80:
        return "#2E7D32"
    if score >= 60:
        return "#F57F17"
    return "#C62828"


def _gauge_html(score: int, label: str) -> str:
    colour = _score_colour(score)
    return f"""
<div style="text-align:center;padding:12px 8px;">
  <div style="font-size:32px;font-weight:700;color:{colour};">{score}</div>
  <div style="font-size:12px;color:#666;margin-top:2px;">{label}</div>
  <div style="height:4px;background:#eee;border-radius:2px;margin-top:8px;">
    <div style="height:4px;width:{score}%;background:{colour};border-radius:2px;"></div>
  </div>
</div>"""


def _issue_block(severity: str, title: str, description: str, recommendation: str,
                 affected_urls: list | None = None, estimated_time: str | None = None):
    colour_map = {
        "critical": "#FCEBEB",
        "high":     "#FFF3E0",
        "medium":   "#FFFDE7",
        "low":      "#F1F8E9",
    }
    bg = colour_map.get(severity, "#F9F9F9")
    with st.container():
        st.markdown(
            f'<div style="background:{bg};border-radius:8px;padding:16px 20px;margin-bottom:12px;">'
            f'{_badge(severity, severity)} &nbsp; <strong>{title}</strong>'
            f'</div>',
            unsafe_allow_html=True,
        )
        inner_col1, inner_col2 = st.columns([1, 1])
        with inner_col1:
            st.markdown("**What's wrong**")
            st.write(description)
        with inner_col2:
            st.markdown("**Recommended action**")
            st.write(recommendation)
            if estimated_time:
                st.caption(f"Estimated time: {estimated_time}")
        if affected_urls:
            with st.expander(f"Affected URLs ({len(affected_urls)})"):
                for i, u in enumerate(affected_urls[:20], 1):
                    st.markdown(f"`{i}.` {u}")
                if len(affected_urls) > 20:
                    st.caption(f"… and {len(affected_urls) - 20} more")


def _cwv_metric(label: str, value: str, target: str, good: bool):
    colour = "#2E7D32" if good else "#C62828"
    st.markdown(
        f"""
<div style="background:#F9F9F9;border-radius:8px;padding:14px;text-align:center;">
  <div style="font-size:22px;font-weight:700;color:{colour};">{value}</div>
  <div style="font-size:12px;color:#444;margin-top:2px;">{label}</div>
  <div style="font-size:11px;color:#888;margin-top:4px;">Target: {target}</div>
</div>""",
        unsafe_allow_html=True,
    )


def _detail_badge(label: str, ok: bool | None):
    if ok is None:
        return
    icon = "✅" if ok else "❌"
    st.markdown(f"{icon} {label}")


# ─────────────────────────────────────────────────────────────────────────────
# CATEGORY LABEL MAP
# ─────────────────────────────────────────────────────────────────────────────
_CAT_LABELS = {
    "seo":           "SEO",
    "speed":         "Speed",
    "performance":   "Performance",
    "page_ranking":  "Page Ranking",
    "mobile":        "Mobile",
    "ddos_security": "DDoS & Security",
    "client_reach":  "Client Reach",
    "trust":         "Trust",
    "content":       "Content",
    "design":        "Design",
}

def _cat_label(key: str) -> str:
    return _CAT_LABELS.get(key, key.replace("_", " ").title())


# ─────────────────────────────────────────────────────────────────────────────
# SEVERITY HELPERS
# ─────────────────────────────────────────────────────────────────────────────
def _sev(issue_text: str) -> str:
    t = issue_text.lower()
    if any(w in t for w in ["critical", "blocked", "missing", "no https", "noindex",
                             "no ddos", "no waf", "volumetric", "unencrypted",
                             "no clear calls", "no social proof"]):
        return "critical"
    if any(w in t for w in ["poor", "slow", "fail", "error", "rate-limit", "hsts",
                             "flood", "credential", "no contact form"]):
        return "high"
    if any(w in t for w in ["too long", "too short", "small", "multiple",
                             "security header", "limited social", "weak local", "only 1"]):
        return "medium"
    return "low"


def _auto_time(severity: str) -> str:
    return {
        "critical": "Immediate — fix today",
        "high":     "1–2 days",
        "medium":   "2–5 minutes per page",
        "low":      "5–10 minutes per page",
    }.get(severity, "Varies")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN RENDERER
# ─────────────────────────────────────────────────────────────────────────────
def render_audit_report(audit: dict):
    """Render a single audit dict in Streamlit."""
    from audit_pdf import _auto_recommendation as _rec

    url       = audit.get("url", "—")
    overall   = audit.get("overall_score", 0)
    breakdown = audit.get("breakdown", {})
    lh        = audit.get("lighthouse_details", {})

    # Build an enriched breakdown that includes fastsite_projection so that
    # _auto_recommendation can resolve ps_b (PageSpeed baseline) correctly.
    # Without this, proj defaults to {} and ps_b silently falls back to 50,
    # causing a mismatch between the badge score and the recommendation text.
    _audit_for_rec = {**audit, **breakdown, "fastsite_projection": audit.get("fastsite_projection", {})}

    st.markdown("## Site Audit Report")
    st.markdown(f"**{url}**")
    st.caption(f"Overall score · {overall}/100")

    # Executive Summary
    st.markdown("### Executive Summary")
    cols = st.columns(len(breakdown) or 1)
    for i, (key, data) in enumerate(breakdown.items()):
        with cols[i]:
            st.markdown(_gauge_html(data.get("score", 0), _cat_label(key)), unsafe_allow_html=True)

    # Performance Scores
    if lh:
        st.markdown("### Performance Scores")
        m1, m2, m3, m4 = st.columns(4)
        with m1: st.metric("Performance",    f"{lh.get('performance', '—')}")
        with m2: st.metric("Accessibility",  f"{lh.get('accessibility', '—')}")
        with m3: st.metric("SEO",            f"{lh.get('seo', '—')}")
        with m4: st.metric("Best Practices", f"{lh.get('best_practices', '—')}")

    # Core Web Vitals
    perf_det = breakdown.get("performance", {}).get("details", {})
    lcp = perf_det.get("lcp_ms")
    fcp = perf_det.get("fcp_ms")
    cls = perf_det.get("cls")
    tbt = perf_det.get("tbt_ms")
    if any(x is not None for x in [lcp, fcp, cls, tbt]):
        st.markdown("### Core Web Vitals")
        cwv_cols = st.columns(4)
        if lcp is not None:
            with cwv_cols[0]: _cwv_metric("LCP", f"{lcp/1000:.1f}s", "< 2.5s", lcp < 2500)
        if fcp is not None:
            with cwv_cols[1]: _cwv_metric("FCP", f"{fcp/1000:.1f}s", "< 1.8s", fcp < 1800)
        if tbt is not None:
            with cwv_cols[2]: _cwv_metric("TBT", f"{tbt}ms", "< 200ms", tbt < 200)
        if cls is not None:
            with cwv_cols[3]: _cwv_metric("CLS", f"{cls:.3f}", "< 0.1", cls < 0.1)

    # Priority Matrix
    from collections import Counter
    st.markdown("### Priority Matrix")
    all_issues = [i for d in breakdown.values() for i in d.get("issues", [])]
    sev_counts = Counter(_sev(i) for i in all_issues)
    pm_cols = st.columns(4)
    for col, (sev, colour) in zip(pm_cols, [
        ("critical", "#C62828"), ("high", "#E65100"),
        ("medium", "#F9A825"), ("low", "#388E3C")
    ]):
        with col:
            st.markdown(
                f'<div style="text-align:center;padding:12px;border-radius:8px;'
                f'background:#F9F9F9;border:1px solid #EEE;">'
                f'<div style="font-size:28px;font-weight:700;color:{colour};">'
                f'{sev_counts.get(sev, 0)}</div>'
                f'<div style="font-size:11px;color:#666;text-transform:uppercase;'
                f'letter-spacing:.5px;margin-top:4px;">{sev}</div></div>',
                unsafe_allow_html=True,
            )

    # Issues by Category
    st.markdown("### Issues by Category")
    cat_issue_map = {k: v["issues"] for k, v in breakdown.items() if v.get("issues")}
    for cat, issues in cat_issue_map.items():
        st.markdown(f"#### {_cat_label(cat)}")
        for issue in issues:
            severity  = _sev(issue)
            rec_text  = _rec(issue, _audit_for_rec)
            rec_parts = rec_text.split("\n\n")
            issue_desc = rec_parts[0] if rec_parts else issue
            issue_rec  = "\n\n".join(rec_parts[1:]) if len(rec_parts) > 1 else rec_text
            _issue_block(
                severity=severity,
                title=issue,
                description=issue_desc,
                recommendation=issue_rec,
                estimated_time=_auto_time(severity),
            )

    # SEO Details
    seo_det = breakdown.get("seo", {}).get("details", {})
    if seo_det:
        st.markdown("### SEO Details")
        c1, c2 = st.columns(2)
        with c1:
            _detail_badge("Title tag",        seo_det.get("has_title"))
            _detail_badge("Meta description", seo_det.get("has_meta_desc"))
            _detail_badge("Canonical URL",    seo_det.get("has_canonical"))
        with c2:
            _detail_badge("Open Graph tags",  seo_det.get("has_og"))
            _detail_badge("Schema / JSON-LD", seo_det.get("has_schema"))
            h1 = seo_det.get("h1_count")
            if h1 is not None:
                _detail_badge("Single H1 tag", h1 == 1)

    # Strengths
    all_strengths = [s for d in breakdown.values() for s in d.get("strengths", [])]
    if all_strengths:
        st.markdown("### Strengths")
        for s in all_strengths:
            st.markdown(f"✅ {s}")

    # Implementation Checklist
    st.markdown("### Implementation Checklist")
    for cat, issues in cat_issue_map.items():
        st.markdown(f"**{_cat_label(cat)}**")
        for issue in issues:
            severity = _sev(issue)
            badge_html = _badge(severity, severity)
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:8px;margin:4px 0;">'
                f'<input type="checkbox" style="margin:0;"> '
                f'{badge_html} <span style="font-size:13px;">{issue}</span></div>',
                unsafe_allow_html=True,
            )

    st.divider()
    st.caption(f"Audit generated for **{url}**")


# ─────────────────────────────────────────────────────────────────────────────
# DOWNLOAD BUTTON  — imported by app.py
# ─────────────────────────────────────────────────────────────────────────────
def render_download_button(audit: dict):
    """Render a PDF download button for a single audit result."""
    try:
        from audit_pdf import generate_audit_pdf
    except ImportError:
        st.warning("audit_pdf.py not found — PDF download unavailable.")
        return

    url       = audit.get("url", "site")
    safe_name = url.replace("https://", "").replace("http://", "").replace("/", "_").strip("_")
    filename  = f"audit_{safe_name}.pdf"

    # Generate PDF only when button is clicked, not on every render
    @st.cache_data(show_spinner=False)
    def _get_pdf(audit_url: str, score: int) -> bytes:
        return generate_audit_pdf(audit)

    try:
        pdf_bytes = _get_pdf(url, audit.get("overall_score", 0))
    except Exception as e:
        st.warning(f"PDF generation failed: {e}")
        return

    st.download_button(
        label="⬇ Download Audit Report (PDF)",
        data=pdf_bytes,
        file_name=filename,
        mime="application/pdf",
        use_container_width=True,
        key=f"dl_display_{safe_name}",
    )