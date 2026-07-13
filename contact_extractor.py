"""
contact_extractor.py
────────────────────
Extracts contact info (email, phone, contact-page URL) from a business
website and detects whether a CDN / reverse-proxy cache is already in use.

Both functions are fast (<5 s), use only requests + BeautifulSoup, and
fail gracefully — they never raise, they return empty/unknown values.
"""
from __future__ import annotations
import re
import random
import requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

# ─── user-agent pool ──────────────────────────────────────────────────────────
_UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 "
    "Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

def _headers():
    return {
        "User-Agent": random.choice(_UA),
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }


# ─── CDN / Reverse-Proxy / Cache detection ───────────────────────────────────

_CDN_HEADER_MAP = {
    "varnish":          "Self-Hosted Reverse Proxy Cache",
    "squid":            "Squid Cache",
    "nginx":            "nginx Cache",
    "cloudflare":       "Cloudflare",
    "cf-ray":           "Cloudflare",
    "cf-cache-status":  "Cloudflare",
    "fastly":           "Fastly CDN",
    "x-served-by":      "Fastly CDN",
    "x-cache":          "Cache (generic)",
    "cloudfront":       "AWS CloudFront",
    "x-amz-cf":         "AWS CloudFront",
    "akamai":           "Akamai CDN",
    "x-check-cacheable":"Akamai CDN",
    "bunny":            "BunnyCDN",
    "b-cdn":            "BunnyCDN",
    "sucuri":           "Sucuri WAF/CDN",
    "keycdn":           "KeyCDN",
    "incapsula":        "Imperva/Incapsula",
    "x-iinfo":          "Imperva/Incapsula",
    "stackpath":        "StackPath CDN",
    "x-cache-hit":      "Cache (generic)",
    "x-proxy-cache":    "Cache (generic)",
}

_CDN_HEADER_NAMES = {
    "cf-ray", "cf-cache-status",
    "x-served-by",
    "x-amz-cf-id", "x-amz-cf-pop",
    "x-check-cacheable",
    "x-iinfo",
    "x-cache-hit", "x-proxy-cache",
    "bunny-cdn-cache-status",
}

def detect_cdn(url: str, timeout: int = 10) -> dict:
    result = {
        "has_cdn":     False,
        "cdn_name":    None,
        "is_hot_lead": True,
        "raw_signals": [],
    }
    try:
        resp = requests.head(
            url, headers=_headers(), timeout=timeout,
            allow_redirects=True, stream=False,
        )
        headers_lc = {k.lower(): v.lower() for k, v in resp.headers.items()}

        detected_names: list[str] = []

        for hname in _CDN_HEADER_NAMES:
            if hname in headers_lc:
                result["raw_signals"].append(f"header present: {hname}")
                for kw, name in _CDN_HEADER_MAP.items():
                    if kw in hname:
                        detected_names.append(name)
                        break
                else:
                    detected_names.append("Cache (generic)")

        for hname, hval in headers_lc.items():
            full = f"{hname}: {hval}"
            for kw, name in _CDN_HEADER_MAP.items():
                if kw in full and name not in detected_names:
                    detected_names.append(name)
                    result["raw_signals"].append(f"keyword '{kw}' in {hname}")

        if detected_names:
            specific = [n for n in detected_names if n != "Cache (generic)"]
            result["cdn_name"]    = specific[0] if specific else detected_names[0]
            result["has_cdn"]     = True
            result["is_hot_lead"] = False

    except Exception as e:
        result["raw_signals"].append(f"error: {e}")

    return result


# ─── Contact info extraction ──────────────────────────────────────────────────

_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", re.I
)

# ── Phone patterns ────────────────────────────────────────────────────────────
# We use a list of explicit, narrow patterns rather than one giant regex.
# Each pattern is anchored to avoid partial matches inside version strings,
# CSS class names, or other non-phone numeric text.
#
# Priority order (most specific → most general):
#   1. tel: href  (handled separately — most reliable)
#   2. International E.164  e.g.  +44 20 7946 0958 / +1-800-555-0199
#   3. UK national          e.g.  020 7946 0958 / 07700 900123 / 0800 123 456
#   4. Parenthesised area   e.g.  (020) 7946 0958 / (800) 555-0199
#   5. Generic separator    e.g.  212-555-1234 / 01632 960 960
#
# Intentionally NOT matched:
#   • Pure decimals / version strings  (3.1.17 · 2024.06.01)
#   • Year-only strings               (2024 · 1999)
#   • Short IDs / zip codes           (< 7 digits)

_PHONE_PATTERNS: list[re.Pattern] = [
    # 1. International: +<country> then groups — requires at least 2 groups after prefix
    re.compile(
        r"""
        (?<!\d)
        \+\d{1,3}               # country code  e.g. +44 / +1 / +353
        [\s\-.]?
        \(?\d{1,5}\)?           # area / city code
        [\s\-.]
        \d{3,5}                 # first local group
        (?:[\s\-.]?\d{3,5}){0,2}
        (?!\d)
        """,
        re.VERBOSE,
    ),
    # 2. UK national — starts with 0, 10–11 digits, common formats:
    #    020 XXXX XXXX  |  07XXX XXXXXX  |  01XXX XXXXXX  |  0800 XXX XXXX
    re.compile(
        r"""
        (?<!\d)
        0(?:
            [1-9]\d{1,4}        # area code after leading 0
        )
        [\s\-.]
        \d{3,5}                 # first group
        (?:[\s\-.]?\d{3,5})?    # optional second group
        (?!\d)
        """,
        re.VERBOSE,
    ),
    # 3. Parenthesised area code  e.g.  (020) 7946 0958  /  (800) 555-0199
    re.compile(
        r"""
        (?<!\d)
        \(\d{2,5}\)             # area code in parens
        [\s\-.]?
        \d{3,5}                 # first group
        [\s\-.]
        \d{3,5}                 # second group
        (?:[\s\-.]?\d{3,4})?    # optional third group
        (?!\d)
        """,
        re.VERBOSE,
    ),
    # 4. Generic: two digit-groups joined by hyphen or space (not dot — avoids decimals)
    #    e.g.  212-555-1234  /  01632 960960  — must have at least one hyphen or space separator
    #    Excludes leading groups of exactly 4 digits (year ranges like 2019-2024)
    re.compile(
        r"""
        (?<!\d)
        (?!(?:19|20)\d{2}[\s\-])  # reject if starts with a 4-digit year
        \d{2,5}                   # first group (2-5 digits, NOT a lone year)
        [\s\-]                    # separator (space or hyphen ONLY — no dot)
        \d{3,5}                   # second group (min 3 to avoid "24-7" false hits)
        (?:[\s\-]?\d{3,5}){0,2}
        (?!\d)
        """,
        re.VERBOSE,
    ),
]

_DIGIT_RE = re.compile(r"\d")


def _is_valid_phone(raw: str) -> bool:
    """
    Return True only if `raw` is likely a real phone number.

    Rejects:
      • Fewer than 7 or more than 15 digits  (E.164 bounds)
      • Pure dot-separated decimals / version strings  (e.g. "3.1.17")
      • Strings whose only separator is a dot  (catches "2024.06.01")
      • Strings that are purely numeric with no separators  (IDs, zips)
      • Year ranges  e.g. "2019-2024", "1999-2025"  (both parts 1900-2099)
      • Single 4-digit years  (1900-2099)
      • Copyright / date patterns  (© 2024, 2020–2024)
      • Strings where all digit-groups are 4 digits (year-like)
    """
    stripped_digits = _DIGIT_RE.sub("", raw)  # non-digits
    digits = _DIGIT_RE.findall(raw)
    n = len(digits)
    if not (7 <= n <= 15):
        return False

    raw_stripped = raw.strip()

    # Reject version strings / dotted decimals: only digits and dots
    if re.fullmatch(r"[\d.]+", raw_stripped):
        return False

    # Reject strings where every separator is a dot (catches "2024.06.01")
    separators = re.sub(r"[\d\s]", "", raw_stripped)
    if separators and all(c == "." for c in separators):
        return False

    # Reject year ranges like "2019-2024" or "1999–2025"
    # Pattern: 4-digit year, separator, 4-digit year — both in plausible year range
    if re.fullmatch(r"(19|20)\d{2}[\s\-–—](19|20)\d{2}", raw_stripped):
        return False

    # Reject single 4-digit years (1900–2099)
    if re.fullmatch(r"(19|20)\d{2}", raw_stripped):
        return False

    # Reject if ALL digit groups are exactly 4 digits (screams "years", not phone)
    digit_groups = re.findall(r"\d+", raw_stripped)
    if digit_groups and all(len(g) == 4 for g in digit_groups):
        return False

    # Reject patterns like "2019 - 2024" with spaces around separator
    if re.fullmatch(r"(19|20)\d{2}\s*[\-–—]\s*(19|20)\d{2}", raw_stripped):
        return False

    # Must have at least one non-digit character (separator) OR start with +
    if raw_stripped.isdigit() and n < 10:
        return False

    # Reject if number starts with a plausible year (19xx or 20xx) and is short
    if re.match(r"^(19|20)\d{2}", raw_stripped) and n < 10:
        return False

    return True


def _extract_phones_from_text(text: str) -> list[str]:
    """Run all phone patterns against `text` and return raw matches."""
    found: list[str] = []
    for pattern in _PHONE_PATTERNS:
        for m in pattern.finditer(text):
            candidate = m.group(0).strip()
            if _is_valid_phone(candidate):
                found.append(candidate)
    return found


_CONTACT_PAGE_HINTS = [
    "/contact", "/contact-us", "/contactus", "/get-in-touch",
    "/reach-us", "/support", "/about", "/about-us",
    "/impressum", "/kontakt",
]

_EMAIL_BLACKLIST = {
    "example.com", "domain.com", "yoursite.com", "sentry.io",
    "w3.org", "schema.org", "google.com", "facebook.com",
    "wixpress.com", "squarespace.com", "wordpress.com",
}

def _clean_emails(raw: list[str]) -> list[str]:
    out = []
    for e in raw:
        e = e.strip().lower()
        domain = e.split("@")[-1]
        if domain in _EMAIL_BLACKLIST:
            continue
        if any(e.endswith(ext) for ext in (".png", ".jpg", ".gif", ".css", ".js")):
            continue
        if e not in out:
            out.append(e)
    return out[:5]


def _clean_phones(raw: list[str]) -> list[str]:
    """Deduplicate and validate extracted phone strings."""
    seen: list[str] = []
    for p in raw:
        p = " ".join(p.split())  # normalise internal whitespace
        if p and p not in seen and _is_valid_phone(p):
            seen.append(p)
    return seen[:3]


def _scrape_page(url: str, timeout: int = 8) -> tuple[str, dict]:
    try:
        r = requests.get(
            url, headers=_headers(), timeout=timeout,
            allow_redirects=True,
        )
        return r.text, {k.lower(): v for k, v in r.headers.items()}
    except Exception:
        return "", {}


def _extract_from_html(html: str) -> tuple[list[str], list[str], str | None]:
    """Return (emails, phones, contact_page_url_hint) from raw HTML."""
    # ── Extract phones from visible text only, not raw HTML ──────────────────
    # Parsing the DOM first avoids matching version strings inside <script> tags,
    # CSS class names, and other non-visible noise.
    soup = BeautifulSoup(html, "lxml")

    # Remove script / style nodes before extracting text
    for tag in soup(["script", "style", "noscript", "meta", "link"]):
        tag.decompose()

    visible_text = soup.get_text(separator=" ")

    emails = _EMAIL_RE.findall(html)                       # emails fine from raw HTML
    phones = _extract_phones_from_text(visible_text)       # phones from visible text only

    # Also scan anchor href="tel:…" — most reliable phone source
    tel_phones: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.lower().startswith("tel:"):
            number = href[4:].strip()
            if number:
                tel_phones.append(number)

    phones = tel_phones + phones   # tel: links take priority

    # Look for a contact-page link
    contact_href = None
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        if any(hint in href for hint in _CONTACT_PAGE_HINTS):
            contact_href = a["href"]
            break

    return emails, phones, contact_href


def extract_contact_info(url: str) -> dict:
    """
    Scrape the homepage and (if found) the /contact page of `url`.

    Returns:
        {
            "emails":        [str],
            "phones":        [str],
            "contact_page":  str | None,
            "primary_email": str | None,
        }
    """
    result: dict = {
        "emails":        [],
        "phones":        [],
        "contact_page":  None,
        "primary_email": None,
    }

    html, _ = _scrape_page(url)
    if not html:
        return result

    emails, phones, contact_href = _extract_from_html(html)

    base = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
    contact_candidates = []
    if contact_href:
        full = urljoin(url, contact_href)
        contact_candidates.append(full)
    for hint in _CONTACT_PAGE_HINTS[:4]:
        contact_candidates.append(base + hint)

    for contact_url in contact_candidates:
        try:
            c_html, _ = _scrape_page(contact_url, timeout=6)
            if c_html:
                c_emails, c_phones, _ = _extract_from_html(c_html)
                emails  += c_emails
                phones  += c_phones
                if not result["contact_page"] and c_html.strip():
                    result["contact_page"] = contact_url
                break
        except Exception:
            continue

    result["emails"] = _clean_emails(emails)
    result["phones"] = _clean_phones(phones)  # uses new validated cleaner

    if result["emails"]:
        result["primary_email"] = result["emails"][0]

    return result