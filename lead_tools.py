"""
lead_tools.py
─────────────
Fast.site lead-generation utilities.

  • opportunity_score(audit)          → int 0-100
  • generate_cold_email(...)          → str
  • build_leads_csv(audits, contacts) → bytes  (UTF-8 CSV)
"""
from __future__ import annotations
import csv
import io
from datetime import datetime


# ─── Feature 6: Opportunity Score ────────────────────────────────────
def opportunity_score(audit: dict, cdn_info: dict | None = None) -> int:
    """
    A fast.site-specific composite score (0-100) focused entirely on Speed
    and Performance — the two metrics that edge caching fixes.

    Formula:
      • Speed score       × 0.55   (most direct Edge Cache impact — increased weight)
      • Performance score × 0.35   (PageSpeed / Core Web Vitals)
      • Page Ranking score × 0.10  (rank signal)

    Inverted: a HIGH opportunity score means the site is SLOW and needs help.
    Returns (100 - weighted_score), then applies a +15 bonus when no CDN is
    detected — because an uncached origin is the single clearest buying signal.
    Result is clamped to 0-100.
    """
    bd = audit.get("breakdown", {})
    speed   = (bd.get("speed") or {}).get("score", 50)
    perf    = (bd.get("performance") or {}).get("score", 50)
    ranking = (bd.get("page_ranking") or {}).get("score", 50)

    weighted = speed * 0.55 + perf * 0.35 + ranking * 0.10

    # Invert: low speed score → high opportunity
    opportunity = round(100 - weighted)

    # No CDN detected → strong lead; boost score by 15 points
    if cdn_info and not cdn_info.get("has_cdn"):
        opportunity += 15

    return max(0, min(100, opportunity))


def opportunity_label(score: int) -> tuple[str, str]:
    """Return (label, colour_hex) for a given opportunity score.

    Thresholds calibrated so that a site with Speed ~45 and no CDN
    lands comfortably in MEDIUM, and Speed <35 + no CDN hits HIGH.
    """
    if score >= 65:
        return "🔥 HIGH OPPORTUNITY", "#DC2626"
    if score >= 42:
        return "⚡ MEDIUM OPPORTUNITY", "#D97706"
    if score >= 22:
        return "📊 LOW OPPORTUNITY", "#2563EB"
    return "✅ ALREADY FAST", "#059669"


# ─── Feature 5: Cold Email Generator ─────────────────────────────────────────
def generate_cold_email(
    business_name: str,
    url: str,
    overall_score: int,
    speed_score: int,
    performance_score: int,
    opportunity_score: int,
    primary_email: str | None = None,
    ttfb_ms: int | None = None,
    lcp_ms: int | None = None,
    has_cdn: bool = False,
) -> str:
    """
    Generate a personalised cold-outreach email for a fast.site prospect.
    Uses real audit data to make the email specific, not generic.
    """
    # Extract domain for greeting
    import re
    m = re.search(r"https?://(?:www\.)?([^/]+)", url)
    domain = m.group(1) if m else url

    # Personalised opening based on worst metric. Every branch ties the speed
    # problem back to Google search ranking / visibility — that's the hook a
    # non-technical business owner actually cares about, not raw millisecond
    # metrics on their own.
    if speed_score < 40:
        pain_point = (
            f"your site's server response time is critically slow "
            f"({ttfb_ms}ms TTFB — ideal is under 200ms), and Google treats slow "
            f"sites like this as a negative ranking signal" if ttfb_ms
            else "your site has a critically slow server response time, which "
                 "Google treats as a negative ranking signal"
        )
        cta_benefit = "cut load times by up to 10× with Edge Cache — and climb back up the search rankings you're currently losing to faster competitors"
    elif performance_score < 40:
        pain_point = (
            f"your site is failing Google's Core Web Vitals "
            f"(LCP of {lcp_ms/1000:.1f}s — Google's threshold is 2.5s). Core Web "
            f"Vitals are a confirmed Google ranking factor, so this is quietly "
            f"costing you search visibility" if lcp_ms
            else "your site is failing Google's Core Web Vitals thresholds — a "
                 "confirmed Google ranking factor that's quietly costing you "
                 "search visibility"
        )
        cta_benefit = "push your PageSpeed score from {perf} to 85+ in 24 hours, so Google starts ranking you above slower competitors"
        cta_benefit = cta_benefit.format(perf=performance_score)
    elif overall_score < 60:
        pain_point = f"your overall site health score is {overall_score}/100 — below the threshold where Google rewards you with better search rankings"
        cta_benefit = "lift your search rankings and conversion rate without touching a line of code"
    else:
        pain_point = f"your site scored {overall_score}/100 on our independent audit — there's meaningful room to improve speed, search ranking and visibility"
        cta_benefit = "squeeze extra performance and search visibility out of your site with zero code changes"

    cdn_note = ""
    if not has_cdn:
        cdn_note = (
            "\n\nOne thing stood out: your site isn't behind any CDN or caching layer. "
            "That means every visitor — and every Google bot — hits your origin server directly, "
            "adding hundreds of milliseconds of unnecessary delay."
        )

    greeting_name = business_name if business_name and business_name.lower() != domain else "there"

    email = f"""Subject: {domain} speed audit — {overall_score}/100 

Hi {greeting_name},

I ran a quick independent performance audit on {domain} and noticed {pain_point}.{cdn_note}

This matters beyond just user experience: Google uses page speed and Core Web Vitals as direct ranking factors, so a slow site quietly pushes you down the search results — and below faster competitors — for the exact terms your customers are searching.

Fast.site can {cta_benefit} — using Edge Cache deployed in front of your existing server. No code changes, no plugins, no downtime. Just a DNS switch and you go live within 24 hours.

Here's what the numbers look like for {domain}:
• Overall site score: {overall_score}/100
• Speed score: {speed_score}/100
• Performance score: {performance_score}/100
• fast.site opportunity score: {opportunity_score}/100

We serve content from 6 global edge nodes, include DDoS protection and free SSL, and charge a flat €80/month — cancel anytime.

I can share your full audit PDF on request — it shows exactly where the gaps are and what the projected improvements look like after enabling Edge Cache.

Would you be open to a 15-minute call to walk through the results?

Best Regards,
[Your name]
fast.site
https://fast.site

--
You received this one-off email because we ran a public performance audit of {domain}. fast.site — Edge Cache Services. If you'd rather not hear from us, just reply "unsubscribe" and we'll remove you immediately and permanently."""

    return email


# ─── Feature 4: CSV Export ────────────────────────────────────────────────────
def build_leads_csv(
    audit_results: list[dict],
    contact_data: dict[str, dict],
    cdn_data: dict[str, dict],
) -> bytes:
    """
    Build a CSV file with one row per audited site.

    Columns:
      Business Name, URL, Primary Email, Phone, Contact Page,
      Overall Score, Speed Score, Performance Score,
      Opportunity Score, CDN Detected, CDN Name,
      TTFB (ms), LCP (ms), PageSpeed Score,
      Audit Date
    """
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL)

    writer.writerow([
        "Business Name",
        "URL",
        "Primary Email",
        "Phone",
        "Contact Page",
        "Overall Score",
        "Speed Score",
        "Performance Score",
        "SEO Score",
        "Opportunity Score",
        "CDN Detected",
        "CDN Name",
        "TTFB (ms)",
        "LCP (ms)",
        "PageSpeed Score",
        "Audit Date",
    ])

    today = datetime.now().strftime("%Y-%m-%d")

    for audit in audit_results:
        if audit.get("error"):
            continue  # skip failed audits

        url      = audit.get("url", "")
        bd       = audit.get("breakdown", {})
        proj     = audit.get("fastsite_projection") or {}
        cur      = proj.get("current", {})

        # Scores
        overall  = audit.get("overall_score", 0)
        speed    = (bd.get("speed") or {}).get("score", 0)
        perf     = (bd.get("performance") or {}).get("score", 0)
        seo      = (bd.get("seo") or {}).get("score", 0)
        opp      = opportunity_score(audit, cdn_info=cdn_data.get(url, {}))

        # Contact
        contact  = contact_data.get(url, {})
        email    = contact.get("primary_email", "")
        phones   = contact.get("phones", [])
        phone    = phones[0] if phones else ""
        c_page   = contact.get("contact_page", "")

        # CDN
        cdn      = cdn_data.get(url, {})
        has_cdn  = "Yes" if cdn.get("has_cdn") else "No"
        cdn_name = cdn.get("cdn_name", "")

        # Performance details
        ttfb     = cur.get("ttfb_ms", "")
        lcp      = cur.get("lcp_ms", "")
        ps       = cur.get("perf_score", "")

        # Business name: try to extract from URL if not stored
        import re
        biz = audit.get("business_name", "")
        if not biz:
            m = re.search(r"https?://(?:www\.)?([^/]+)", url)
            biz = m.group(1) if m else url

        writer.writerow([
            biz, url, email, phone, c_page,
            overall, speed, perf, seo, opp,
            has_cdn, cdn_name,
            ttfb, lcp, ps,
            today,
        ])

    return buf.getvalue().encode("utf-8")