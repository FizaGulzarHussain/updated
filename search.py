import os
import time
import random
import requests
from typing import Optional
from urllib.parse import urlparse as _urlparse

import re as _re

# ---------------------------------------------------------------------------
# Layer 1: Exact / suffix domain blocklist
# ---------------------------------------------------------------------------
_AGGREGATOR_DOMAINS = [
    # Directories & review platforms
    "yelp.com", "yellowpages.com", "tripadvisor.com", "trustpilot.com",
    "glassdoor.com", "indeed.com", "zomato.com", "justdial.com",
    "foursquare.com", "angi.com", "thumbtack.com", "houzz.com",
    "bbb.org", "manta.com", "superpages.com", "citysearch.com",
    "yp.com", "dexknows.com", "whitepages.com", "411.com",
    "wheree.com", "kompass.com", "cylex.com", "hotfrog.com",
    "brownbook.net", "n49.com", "tupalo.com", "yalwa.com",
    "showmelocal.com", "merchantcircle.com", "ezlocal.com",
    "locanto.com", "finda.com", "localstore.com", "bizify.com",
    "traveloka.com", "booking.com", "expedia.com", "hotels.com",
    "airbnb.com", "vrbo.com",
    # Food guide / awards / recommendation sites
    "agfg.com.au", "bestrestaurants.com.au", "theworlds50best.com",
    "worlds50best.com", "50bestrestaurants.com", "goodfood.com.au",
    "smh.com.au", "theage.com.au", "timeout.com", "thrillist.com",
    "nymag.com", "grubstreet.com", "eatingwell.com", "delish.com",
    "foodandwine.com", "taste.com.au", "taste.com",
    "australianfoodguide.com", "australian-food-guide.com",
    "urbanspoon.com", "zenchef.com", "dimmi.com.au", "quandoo.com",
    "restaurantaustralia.com", "menulog.com.au",
    # Search engines & maps
    "google.com", "bing.com", "yahoo.com", "duckduckgo.com",
    "maps.google.com", "maps.apple.com",
    # Social media & forums
    "facebook.com", "instagram.com", "twitter.com", "x.com",
    "linkedin.com", "pinterest.com", "tiktok.com", "snapchat.com",
    "threads.net", "reddit.com", "quora.com",
    "community.ricksteves.com", "ricksteves.com",
    "tripadvisor.com", "fodors.com", "lonelyplanet.com",
    "frommers.com", "roughguides.com",
    # Video platforms
    "youtube.com", "vimeo.com", "dailymotion.com", "twitch.tv",
    # E-commerce marketplaces
    "amazon.com", "amazon.co.uk", "amazon.de", "amazon.fr",
    "ebay.com", "etsy.com", "walmart.com", "target.com",
    # News & media outlets
    "nytimes.com", "washingtonpost.com", "theguardian.com", "bbc.com",
    "bbc.co.uk", "cnn.com", "foxnews.com", "nbcnews.com", "abcnews.go.com",
    "cbsnews.com", "usatoday.com", "npr.org", "reuters.com", "apnews.com",
    "bloomberg.com", "businessinsider.com", "forbes.com", "fortune.com",
    "wsj.com", "ft.com", "economist.com", "time.com", "newsweek.com",
    "theatlantic.com", "newyorker.com", "slate.com", "salon.com",
    "huffpost.com", "buzzfeed.com", "vice.com", "vox.com",
    "dailymail.co.uk", "thesun.co.uk", "telegraph.co.uk", "mirror.co.uk",
    "independent.co.uk", "express.co.uk",
    # Food & lifestyle media
    "eater.com", "michelin.com", "michelinguide.com", "zagat.com",
    "seriouseats.com", "epicurious.com", "allrecipes.com", "foodnetwork.com",
    "bonappetit.com", "tastingtable.com", "infatuation.com",
    "resy.com", "opentable.com", "grubhub.com", "doordash.com",
    "ubereats.com", "seamless.com", "postmates.com",
    # Reference / encyclopedias
    "wikipedia.org", "britannica.com", "wikihow.com",
    # Healthcare booking platforms / "find a provider" portals
    "healthengine.com.au", "hotdoc.com.au", "zocdoc.com",
    # Professional / industry associations
    "ada.org.au", "teeth.org.au",
    # Blogs & content farms
    "medium.com", "substack.com", "blogspot.com", "wordpress.com",
    "wix.com", "squarespace.com", "weebly.com",
    # Personal pages / celebrities
    "imdb.com", "biography.com",
    # Lifestyle / parenting "best-of" blogs
    "sassymamahk.com",
    # Travel listicle blogs
    "enjoytravelsite.com", "enjoy-travel.de", "traveltriangle.com",
    "travelandleisure.com", "cntraveler.com", "afar.com",
    "matadornetwork.com", "nomadicmatt.com", "theculturetrip.com",
    "wanderlust.co.uk", "worldnomads.com",
    "travelingoutsidethebox.com", "outsidethebox.travel",
    "theblondeabroad.com", "bemytravelmuse.com", "theplanetd.com",
    "adventurouskate.com", "thebrokebackpacker.com", "expertvagabond.com",
    "onestep4ward.com", "goatsontheroad.com", "ytravelblog.com",
    "handluggageonly.co.uk", "travelblog.org", "journeyera.com",
    "iheartberlin.de", "berlinartlink.com", "introducingberlin.com",
    "secretcitytrails.com", "bumppy.com", "likealocalguide.com",
    # Medical tourism aggregators (list hundreds of clinics across countries)
    "bookimed.com", "medigo.com", "whatclinic.com", "doctolib.fr",
    "medawaytourism.com", "placidway.com", "medicaltourism.com",
    "treatmentabroad.com", "mediglobus.com", "cmtsp.com",
    "global-healthaccreditation.com", "healthtravel.com",
    "medicana.com.tr", "anadoluhastanesi.com.tr",
    "medicaltourismco.com", "hospitalby.com", "tripsmedic.com",
    "drclinic.com", "medicover.com", "heliocare.com",
    # Dental-specific aggregators / price-comparison portals
    "dentaldeals.com", "dentaly.org", "dentacoin.com",
    "dentistfind.com", "1800dentist.com", "cleardent.com",
    "topdentists.com", "bestdentists.com", "cosmetic-dentistry-guide.com",
    # Stock photo / image libraries & photo-sharing sites
    "alamy.com", "shutterstock.com", "gettyimages.com", "gettyimages.co.uk",
    "gettyimages.de", "gettyimages.in", "istockphoto.com", "dreamstime.com",
    "123rf.com", "depositphotos.com", "stock.adobe.com", "canstockphoto.com",
    "bigstockphoto.com", "pexels.com", "unsplash.com", "pixabay.com",
    "freepik.com", "vectorstock.com", "stocksy.com", "agefotostock.com",
    "colourbox.com", "fotolia.com", "flickr.com", "500px.com",
    "picfair.com", "eyeem.com", "photobucket.com", "imageshack.com",
    "wikimedia.org", "pond5.com",
]

# ---------------------------------------------------------------------------
# Layer 1a: Brand-root blocklist — matches the registrable name of a known
# aggregator regardless of country TLD (e.g. catches tripadvisor.de,
# tripadvisor.co.uk, yelp.fr, cylex-uk.co.uk — not just the .com listed
# above). We compare the second-level label of the domain against this set,
# so any ccTLD/gTLD variant of the same brand is blocked automatically.
# ---------------------------------------------------------------------------
_AGGREGATOR_BRAND_ROOTS = {
    # Global review / directory brands (catches all country TLDs at once)
    "yelp", "tripadvisor", "trustpilot", "glassdoor", "indeed", "zomato",
    "justdial", "foursquare", "angi", "thumbtack", "houzz", "manta",
    "superpages", "citysearch", "yellowpages", "dexknows", "whitepages",
    "kompass", "cylex", "hotfrog", "brownbook", "n49", "tupalo", "yalwa",
    "showmelocal", "merchantcircle", "ezlocal", "locanto", "europages",
    "booking", "expedia", "hotels", "airbnb", "vrbo", "traveloka",
    "opentable", "resy", "grubhub", "doordash", "ubereats", "menulog",
    "quandoo", "zenchef", "dimmi", "wongnai", "gogovan", "grab",
    "alibaba", "indiamart", "tradeindia", "sulekha", "truelocal",
    "yellow", "goldenpages", "infobel", "cybo", "wlw",
    # Region/language-specific "yellow pages" & directories (real brands,
    # not just .com — this is what lets non-English-market listings through
    # today even though English ones get blocked)
    "gelbeseiten", "dasoertliche", "11880", "pagesjaunes", "paginegialle",
    "paginasamarillas", "goudengids", "detelefoongids", "panoramafirm",
    "firmy", "zoominfo",
    # Restaurant / hospitality review sites outside the anglosphere
    "tabelog", "gurunavi", "dianping", "meituan", "chope", "eatigo",
    "burpple", "hungryhouse",
    # Local business directories in Russian/CIS, Middle East, LatAm
    "2gis", "yandex", "zoon", "yalla", "mercadolibre", "guiaLocal",
}


def _brand_root_match(netloc: str) -> bool:
    """True if any dot- or hyphen-separated token in the hostname is a
    known aggregator brand root, regardless of country TLD or a
    hyphenated country suffix (e.g. tripadvisor.de, cylex-uk.co.uk,
    hotfrog-usa.com all resolve to their bare brand root)."""
    tokens = _re.split(r"[.\-]", netloc)
    return any(tok in _AGGREGATOR_BRAND_ROOTS for tok in tokens)


# ---------------------------------------------------------------------------
# Layer 1b: Government / regulatory-authority domains, any country.
# ---------------------------------------------------------------------------
_GOV_DOMAIN_RE = _re.compile(r"(^|\.)gov(\.[a-z]{2,3})?$", _re.I)

# ---------------------------------------------------------------------------
# Layer 2: Domain keyword patterns — catch lookalike aggregators by name
# ---------------------------------------------------------------------------
_AGGREGATOR_DOMAIN_KEYWORDS = _re.compile(
    r"""
    best[-.]?restaurants? |
    top[-.]?\d*[-.]?restaurants? |
    worlds?\d*best |
    \d+best |
    best[-.]?cafes? |
    best[-.]?bars? |
    best[-.]?eateries |
    restaurant[-.]?guide |
    dining[-.]?guide |
    food[-.]?guide |
    restaurant[-.]?awards? |
    restaurant[-.]?discovery |
    restaurant[-.]?finder |
    restaurant[-.]?directory |
    restaurant[-.]?recommendations? |
    places[-.]?to[-.]?eat |
    where[-.]?to[-.]?eat |
    eat[-.]?out |
    local[-.]?eats |
    australian[-.]?food[-.]?guide |
    good[-.]?food[-.]?guide |
    travel[-.]?forum |
    travel[-.]?guide |
    travel[-.]?blog |
    travel[-.]?tips |
    enjoy[-.]?travel |
    ^traveling |
    travell?ing[-.]?outside |
    outside[-.]?the[-.]?box |
    travel[-.]?outside |
    trip[-.]?advisor |
    holiday[-.]?guide |
    iheart[-.]?\w+ |
    introducing[-.]?\w+city |
    cityguide |
    city[-.]?guide |
    local[-.]?guide |
    like[-.]?a[-.]?local |
    medical[-.]?tour |
    med[-.]?tour |
    health[-.]?tour |
    treatment[-.]?abroad |
    clinic[-.]?finder |
    clinic[-.]?compare |
    hospital[-.]?find |
    book[-.]?clinic |
    book[-.]?hospital |
    book[-.]?doctor |
    book[-.]?med |
    placid[-.]?way |
    dental[-.]?abroad |
    dental[-.]?tour |
    dentist[-.]?find |
    best[-.]?clinic |
    top[-.]?clinic |
    best[-.]?hospital |
    top[-.]?hospital |
    stock[-.]?photo |
    stock[-.]?image |
    stock[-.]?footage |
    royalty[-.]?free |
    photo[-.]?library |
    image[-.]?library |

    # --- English: reviews / surveys / favourites (not just "best/top") ---
    reviews? |
    surveys? |
    ratings? |
    favou?rites? |
    recommend(ed|ations?)? |

    # --- French ---
    meilleur[es]{0,2} |
    classement |
    comparatif |
    avis[-.]?clients? |
    sondage |
    annuaire |

    # --- German ---
    beste[nr]? |
    bestenliste |
    vergleich |
    bewertung(en)? |
    umfrage |
    branchenbuch |

    # --- Spanish ---
    mejor(es)? |
    comparaci[oó]n |
    opiniones |
    encuesta |
    directorio |

    # --- Italian ---
    migliori |
    classifica |
    recensioni |
    sondaggio |

    # --- Portuguese ---
    melhores |
    avalia[cç][oõ]es |
    pesquisa |

    # --- Dutch ---
    beoordelingen |
    vergelijking |
    enquete |

    # --- Polish ---
    najlepsze |
    ranking |
    opinie |
    ankieta |

    # --- Turkish ---
    en[-.]?iyi |
    yorumlar |
    anket |

    # --- Indonesian / Malay ---
    terbaik |
    ulasan |

    # --- Vietnamese ---
    tot[-.]?nhat |
    danh[-.]?gia
    """,
    _re.I | _re.VERBOSE,
)

# ---------------------------------------------------------------------------
# Shared business-category nouns
# ---------------------------------------------------------------------------
_BUSINESS_NOUNS = [
    "dentist", "doctor", "physician", "lawyer", "attorney", "nurse",
    "practitioner", "professional", "specialist", "expert", "consultant",
    "restaurant", "cafe", "bar", "salon", "spa", "hospital", "clinic",
    "hotel", "shop", "store", "service", "provider", "agency", "firm",
]
_BUSINESS_NOUN_ALT = "|".join(_BUSINESS_NOUNS)

# ---------------------------------------------------------------------------
# Layer 2b: "ranking word + category" domain pattern
# ---------------------------------------------------------------------------
_LISTICLE_DOMAIN_RE = _re.compile(
    rf"(?:top\d*|best|\d+\s*best)[-_.]?(?:{_BUSINESS_NOUN_ALT})s?",
    _re.I,
)

# ---------------------------------------------------------------------------
# Layer 3: URL path patterns that indicate list/media/forum content
# ---------------------------------------------------------------------------
_AGGREGATOR_PATH_PATTERNS = _re.compile(
    r"""
    /best[-_] |
    /top[-_]\d+ |
    /top[-_][a-z] |
    /\d+[-_]best |
    /recommendations? |
    /restaurant[-_]guide |
    /dining[-_]guide |
    /food[-_]guide |
    /where[-_]to[-_]eat |
    /places[-_]to[-_]eat |
    /discovery/ |
    /sitemap |
    /travel[-_]forum |
    /forum/ |
    /community/ |
    /blog/ |
    /news/ |
    /article/ |
    /magazine/ |
    /guide/ |
    /ranking |
    /awards? |
    /review |
    /list/ |
    /listing/ |
    /directory/ |
    /register/ |
    /registry/ |
    /members?[-_]directory |
    /find[-_]an?[-_]\w+ |
    /search/ |
    /stock[-_]photo |
    /stock[-_]image |
    /stock[-_]footage |
    /editorial/ |
    # Medical tourism aggregator path patterns
    country= |               # /clinics/country=germany — multi-country listing
    direction= |             # /direction=dentistry — category filter
    /clinics/country |       # bookimed-style: /clinics/country=X
    /hospitals/country |
    /doctors/country |
    /find[-_]clinic |
    /compare[-_]clinic |
    /clinic[-_]list |
    /hospital[-_]list |
    /doctor[-_]list |
    /treatment[-_]abroad |
    /medical[-_]tour |
    # Reviews / surveys / favourites / "find a business" pages
    /reviews?/ |
    /survey/ |
    /poll/ |
    /ratings?/ |
    /favou?rites?/ |
    /find[-_]a[-_] |
    /find[-_]business |
    # Non-English review/directory path segments
    /avis[-/] |            # French: reviews
    /bewertung(en)?[-/] |  # German: reviews
    /opinie[-/] |          # Polish: opinions/reviews
    /opiniones[-/] |       # Spanish: opinions/reviews
    /recensioni[-/] |      # Italian: reviews
    /avaliacoes[-/]        # Portuguese: reviews
    """,
    _re.I | _re.VERBOSE,
)

# ---------------------------------------------------------------------------
# Layer 4: Generic directory-listing URL patterns
# ---------------------------------------------------------------------------
_DIRECTORY_PATH_RE = _re.compile(r"-c\d+-g\d+", _re.I)

# ---------------------------------------------------------------------------
# Layer 5: Multi-category signal
# ---------------------------------------------------------------------------
_MULTI_CATEGORY_WORDS = [
    "clinics", "dentists", "doctors", "lawyers", "attorneys",
    "restaurants", "cafes", "bars", "salons", "spas", "hospitals",
    "schools", "hotels", "shops", "stores", "services", "providers",
    "specialists", "professionals", "practitioners", "experts",
    "consultants", "agencies", "firms", "centers", "centres",
]
_MULTI_CATEGORY_RE = _re.compile(
    r"\b(" + "|".join(_MULTI_CATEGORY_WORDS) + r")\b", _re.I
)


def _has_multiple_categories(text: str) -> bool:
    """True if 2+ distinct plural business-category words appear together."""
    if not text:
        return False
    matches = {m.lower() for m in _MULTI_CATEGORY_RE.findall(text)}
    return len(matches) >= 2


# ---------------------------------------------------------------------------
# Layer 6: Title/snippet text signals — FIXED to catch "The 25 Best...",
# "N Best X in Y", and all common listicle title patterns.
# ---------------------------------------------------------------------------
_LISTICLE_TEXT_RE = _re.compile(
    r"""
    # --- Numbered ranking titles ---
    \b\d+\s*(best|top|great|amazing)\b |          # "25 Best Clinics", "16 Best Pizzas"
    \b(best|top)\s*\d+\b |                        # "Top 10 ...", "Best 5 ..."
    \bthe\s+\d+\s+(best|top|great|worst)\b |      # "The 25 Best ..."

    # --- "Best/Top ... in [Place]" — any length phrase between best and in ---
    # Uses a non-greedy lookahead to country/city names; works for long titles
    # like "Best Clinics and Costs for Dental Treatment in Germany 2026"
    \bbest\b[^|\n]{1,80}\bin\s+[A-Z] |            # "Best Clinics ... in Germany"
    \btop\b[^|\n]{1,80}\bin\s+[A-Z] |             # "Top Dentists ... in Berlin"
    \bbest\b[^|\n]{1,60}\bin\s+\d{4}\b |          # "Best ... in 2026" (year instead of place)
    \btop\b[^|\n]{1,60}\bin\s+\d{4}\b |           # "Top ... in 2026"

    # --- "Best/Top X [City]" WITHOUT "in" — e.g. "Best coffee shops Berlin" ---
    \b(the\s+)?(best|top)\s+\w[\w\s]{2,50}[A-Z][a-z]{2,} |  # "Best coffee shops Berlin"

    # --- Cost/price comparison articles (not a real business) ---
    \bcosts?\s+(for|of)\b |                        # "Costs for Dental Treatment"
    \bpric(e|ing)\s+(guide|comparison|list)\b |    # "Pricing Guide", "Price List"
    \bhow\s+much\s+(does|do|is|are)\b |            # "How much does a dentist cost"
    \bcompar(e|ing|ison)\b |                       # "Comparison", "Comparing clinics"

    # --- Year-suffixed aggregator/review articles ---
    \b20\d{2}\b[^|\n]{0,30}\b(comparison|review|ranking|guide|cost|pric)\b |  # "2026 Comparison"
    \b(comparison|review|ranking|guide)\b[^|\n]{0,30}\b20\d{2}\b |            # "Guide 2026"
    \b(cost|pric|review)[^|\n]{0,50}\b20\d{2}\b |                             # "Costs and Reviews 2026"
    \b(best|top)\b[^|\n]{1,60}\b20\d{2}\b |       # "Best Clinics Germany 2026"

    # --- Guide / how-to articles about a category (not one business) ---
    \bguide\s+to\b[^|\n]{0,60}\b(clinic|dentist|doctor|lawyer|restaurant|hotel|treatment|surgery|implant)s?\b |
    \b(clinic|dentist|doctor|treatment|implant|surgery)s?\b[^|\n]{0,40}\bguide\b |

    # --- Classic listicle patterns ---
    \blist\s+of\b |                                # "List of Registered Dentists"
    \b(our|editor.?s?)\s*(pick|picks|round.?up)\b |
    \bcompiled\s+(a\s+)?list\b |
    \bmust[-\s]?visit\b |                          # "Must-Visit Restaurants in..."
    \bhidden\s+gems?\b |                           # "Hidden Gems in Berlin"
    \bwhere\s+to\s+(eat|drink|stay|go|find)\b |    # "Where to Eat in Munich"
    \bbest\s+place[s]?\s+to\b |                    # "Best Places to Eat..."

    # --- Stock photo / image library listings (not a business at all) ---
    \bstock\s+photo(graphy|s)?\b |                 # "stock photography and images"
    \bstock\s+(image|footage|video)s?\b |
    \b(hi[-\s]?res|high[-\s]?resolution)\s+stock\b |
    \broyalty[-\s]?free\s+(photo|image|footage)s?\b |
    \beditorial\s+(photo|image)s?\b |
    \bphoto\s+library\b |
    \bimage\s+library\b |
    \bdownload\s+(this\s+)?(photo|image|stock)\b |
    \bsimilar\s+images?\b |

    # --- Favourites / surveys / ratings (English) ---
    \b(our|readers.?|customer)\s*favou?rites?\b |
    \btop[-\s]?rated\b |
    \b(reader|customer|user)\s+(survey|poll|ratings?)\b |
    \bvote\s+for\s+(your|the)\s+favou?rite\b |

    # --- Multilingual "best/top N in [place]" phrasing ---
    \bles?\s+meilleur[es]{0,2}\b[^|\n]{1,60}\b[àa]\b |         # French: "les meilleurs ... à"
    \bdie\s+besten\b[^|\n]{1,60}\bin\b |                        # German: "die besten ... in"
    \blos?\s+mejores?\b[^|\n]{1,60}\ben\b |                     # Spanish: "los mejores ... en"
    \bi\s+migliori\b[^|\n]{1,60}\ba\b |                         # Italian: "i migliori ... a"
    \bos?\s+melhores\b[^|\n]{1,60}\bem\b |                      # Portuguese: "os melhores ... em"
    \bde\s+beste\b[^|\n]{1,60}\bin\b                            # Dutch: "de beste ... in"
    """,
    _re.I | _re.VERBOSE,
)

_REGULATORY_BODY_TEXT_RE = _re.compile(
    rf"""
    \bcouncil\b |
    \bstatutory\s+board\b |
    \bregulatory\s+(body|authority)\b |
    \bprofessional\s+body\b |
    \blicensing\s+(board|authority)\b |
    \bregist(ered|ry|ration)\b[^.]{{0,30}}\b(dentist|doctor|lawyer|nurse|practitioner|professional)s? |
    \b(dentist|doctor|lawyer|nurse|practitioner|professional)s?\b[^.]{{0,30}}\bregist(ered|ry|ration)\b |
    \b({_BUSINESS_NOUN_ALT})s?\s+association\b |
    \bassociation\s+of\s+({_BUSINESS_NOUN_ALT})s?\b |
    \bfind\s+an?\s+({_BUSINESS_NOUN_ALT})\b
    """,
    _re.I | _re.VERBOSE,
)


def is_aggregator(url: str, title: str = "", snippet: str = "") -> bool:
    """
    Return True if the URL is an aggregator, media, directory, forum,
    listicle, official registry/council, or any non-business page.
    """
    if not url:
        return True
    try:
        parsed = _urlparse(url)
        netloc = parsed.netloc.lower().replace("www.", "")
        path = parsed.path.lower()
        full_url_lc = url.lower()

        # Layer 1: exact domain blocklist
        if any(netloc == agg or netloc.endswith("." + agg) for agg in _AGGREGATOR_DOMAINS):
            return True

        # Layer 1a: brand-root match — same brand, any country TLD
        if _brand_root_match(netloc):
            return True

        # Layer 1b: government / regulatory-authority domain
        if _GOV_DOMAIN_RE.search(netloc):
            return True

        # Layer 2: domain name contains aggregator keywords
        if _AGGREGATOR_DOMAIN_KEYWORDS.search(netloc):
            return True

        # Layer 2b: domain name is a "ranking word + category" listicle
        if _LISTICLE_DOMAIN_RE.search(netloc):
            return True

        # Layer 3: URL path signals a list/media/forum page
        if _AGGREGATOR_PATH_PATTERNS.search(path):
            return True

        # Layer 4: generic directory geo/category code in path
        if _DIRECTORY_PATH_RE.search(full_url_lc):
            return True

        # Layer 5: URL slug names 2+ different business categories
        if _has_multiple_categories(path.replace("-", " ").replace("_", " ")):
            return True

        # Layer 6: title/snippet text signals (listicles + regulatory bodies)
        combined_text = f"{title} {snippet}".strip()
        if combined_text:
            if _LISTICLE_TEXT_RE.search(combined_text):
                return True
            if _REGULATORY_BODY_TEXT_RE.search(combined_text):
                return True
            if _has_multiple_categories(combined_text):
                return True

        return False
    except Exception:
        return False


# ===========================================================================
# Layer 7: Content-based verification — fetch the page and analyse its HTML
# to confirm it belongs to a single real business, not an aggregator.
# ===========================================================================

# Signals found in real business pages
_REAL_BUSINESS_SIGNALS = _re.compile(
    r"""
    # Contact / location signals
    \b(contact\s+us|get\s+in\s+touch|reach\s+us|visit\s+us)\b |
    \b(our\s+location|find\s+us|directions)\b |
    \b(opening\s+hours?|business\s+hours?|hours\s+of\s+operation|we\s+are\s+open)\b |
    \b(call\s+us|phone\s+us|telephone)\b |
    \b(book\s+(a\s+)?table|make\s+a\s+reservation|reserve\s+a\s+table)\b |
    \b(order\s+online|order\s+now|place\s+an?\s+order)\b |
    # About / team signals
    \b(about\s+us|our\s+story|our\s+team|meet\s+the\s+(team|chef|owner))\b |
    \b(our\s+(mission|vision|values|history))\b |
    # Specific service/product pages (single business)
    \b(our\s+menu|view\s+menu|download\s+menu|today.?s\s+specials?)\b |
    \b(our\s+services?|what\s+we\s+offer|our\s+products?)\b
    """,
    _re.I | _re.VERBOSE,
)

# Signals found in aggregator / listicle pages
_AGGREGATOR_CONTENT_SIGNALS = _re.compile(
    r"""
    # Numbered list / ranking content
    (?:^|\n)\s*\d{1,2}[\.\)]\s+[A-Z] |          # "1. Restaurant Name" or "1) Name"
    \b(number|no\.?)\s*\d+\s*[:\-–] |            # "Number 1:" or "No. 3 –"
    # Typical aggregator UI patterns
    \bsee\s+all\s+\d+\b |                         # "See all 25 restaurants"
    \bshowing\s+\d+\s+of\s+\d+\b |               # "Showing 10 of 48"
    \bfilter\s+(by|results)\b |                    # filter controls
    \bsort\s+by\b |                               # sort controls
    \badd\s+your\s+(business|listing|restaurant)\b |  # aggregator CTA
    \bclaim\s+(your|this)\s+(business|listing|profile)\b |
    \bwrite\s+a\s+review\b |
    \bsubmit\s+(a\s+)?review\b |
    # Multi-business listing patterns
    \bview\s+details?\b |                          # card CTA repeated per item
    \bget\s+directions?\b.{0,200}\bget\s+directions?\b |  # repeated = list
    \bmore\s+info\b.{0,200}\bmore\s+info\b |      # repeated = list
    # Typical listicle headings
    \b(best|top)\s+\d+\s+\w+\s+in\b |            # "Best 25 Pizzas in Germany"
    \bhere\s+(are|is)\s+(the|our)\b               # "Here are the best..."
    """,
    _re.I | _re.VERBOSE | _re.MULTILINE,
)

# Structured-data / schema signals for a single business
_SCHEMA_SINGLE_BUSINESS_RE = _re.compile(
    r'"@type"\s*:\s*"(Restaurant|LocalBusiness|FoodEstablishment|MedicalBusiness'
    r'|LegalService|Hotel|Store|HealthAndBeautyBusiness|AutoDealer'
    r'|FinancialService|HomeAndConstructionBusiness)"',
    _re.I,
)

# Structured-data signals for a list / article
_SCHEMA_AGGREGATOR_RE = _re.compile(
    r'"@type"\s*:\s*"(ItemList|Article|NewsArticle|BlogPosting|WebPage|CollectionPage)"',
    _re.I,
)

# Phone number pattern (international-friendly)
_PHONE_RE = _re.compile(
    r"""
    (?:\+?\d{1,3}[\s\-.]?)? # country code
    (?:\(?\d{2,4}\)?)        # area code
    [\s\-.]?
    \d{3,5}
    [\s\-.]?
    \d{3,5}
    """,
    _re.VERBOSE,
)

# Physical address signals
_ADDRESS_RE = _re.compile(
    r"\b\d{1,5}\s+\w[\w\s]{2,40}(?:street|st|avenue|ave|road|rd|blvd|boulevard"
    r"|lane|ln|drive|dr|way|court|ct|place|pl|square|sq)\b",
    _re.I,
)


def _score_page_content(html: str) -> dict:
    """
    Analyse raw HTML of a page and return a verdict dict:
      {
        'is_real_business': bool,
        'confidence': float,          # 0.0 – 1.0
        'reason': str,
        'signals': dict               # breakdown of what was found
      }
    """
    # Strip tags for text-level checks
    text = _re.sub(r"<[^>]+>", " ", html)
    text = _re.sub(r"\s+", " ", text)

    signals = {}

    # --- Schema.org structured data (strongest signal) ---
    single_schema = bool(_SCHEMA_SINGLE_BUSINESS_RE.search(html))
    agg_schema = bool(_SCHEMA_AGGREGATOR_RE.search(html))
    signals["single_business_schema"] = single_schema
    signals["aggregator_schema"] = agg_schema

    # --- Contact / business-presence signals ---
    real_signal_count = len(_REAL_BUSINESS_SIGNALS.findall(text))
    signals["real_business_signals"] = real_signal_count

    # --- Phone numbers ---
    phones = _PHONE_RE.findall(text)
    signals["phone_numbers_found"] = len(phones)

    # --- Physical address ---
    has_address = bool(_ADDRESS_RE.search(text))
    signals["has_address"] = has_address

    # --- Aggregator content patterns ---
    agg_content_count = len(_AGGREGATOR_CONTENT_SIGNALS.findall(text))
    signals["aggregator_content_signals"] = agg_content_count

    # --- Listicle text in page body (same regex as Layer 6) ---
    listicle_text = bool(_LISTICLE_TEXT_RE.search(text[:5000]))  # focus on early content
    signals["listicle_text_in_body"] = listicle_text

    # --- Multiple h2/h3 headings that look like business names (list page) ---
    headings = _re.findall(r"<h[23][^>]*>(.*?)</h[23]>", html, _re.I | _re.S)
    heading_texts = [_re.sub(r"<[^>]+>", "", h).strip() for h in headings]
    heading_texts = [h for h in heading_texts if 3 < len(h) < 80]
    signals["heading_count"] = len(heading_texts)

    # Many short similar-length headings = list of businesses
    if len(heading_texts) >= 5:
        avg_len = sum(len(h) for h in heading_texts) / len(heading_texts)
        length_variance = sum((len(h) - avg_len) ** 2 for h in heading_texts) / len(heading_texts)
        signals["heading_variance"] = round(length_variance, 1)
        # Low variance + many headings → likely a list of items
        if length_variance < 200 and len(heading_texts) >= 8:
            signals["uniform_headings_list"] = True
        else:
            signals["uniform_headings_list"] = False
    else:
        signals["heading_variance"] = None
        signals["uniform_headings_list"] = False

    # --- Scoring ---
    score = 0  # positive = real business, negative = aggregator

    if single_schema:
        score += 4
    if agg_schema:
        score -= 3

    score += min(real_signal_count, 4)        # cap at 4
    score += min(len(phones), 2)              # cap at 2
    if has_address:
        score += 2

    score -= min(agg_content_count * 2, 6)   # cap at -6
    if listicle_text:
        score -= 3
    if signals["uniform_headings_list"]:
        score -= 3

    # Normalise to 0–1 confidence (score range roughly -12 to +12)
    raw_conf = (score + 12) / 24
    confidence = max(0.0, min(1.0, raw_conf))

    is_real = confidence >= 0.45  # threshold

    if is_real:
        reason = f"Real business (score={score}, schema={'✓' if single_schema else '✗'}, " \
                 f"contacts={real_signal_count}, phones={len(phones)}, address={'✓' if has_address else '✗'})"
    else:
        reason = f"Aggregator/listicle (score={score}, agg_signals={agg_content_count}, " \
                 f"listicle_text={listicle_text}, uniform_headings={signals['uniform_headings_list']})"

    return {
        "is_real_business": is_real,
        "confidence": round(confidence, 3),
        "reason": reason,
        "signals": signals,
    }


def verify_real_business(
    url: str,
    timeout: int = 10,
    progress_callback=None,
) -> dict:
    """
    Fetch `url` and run content-based verification.

    Returns a dict:
      {
        'url': str,
        'is_real_business': bool,
        'confidence': float,
        'reason': str,
        'signals': dict,
        'fetch_error': str | None,
      }
    """
    base = {"url": url, "is_real_business": False, "confidence": 0.0,
            "reason": "not fetched", "signals": {}, "fetch_error": None}

    if not url:
        base["fetch_error"] = "empty URL"
        return base

    try:
        if progress_callback:
            progress_callback(f"🌐 Verifying content: {url[:60]}…")

        resp = requests.get(
            url,
            headers={
                "User-Agent": random.choice(USER_AGENTS),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
            },
            timeout=timeout,
            allow_redirects=True,
        )
        resp.raise_for_status()

        # Only analyse HTML responses
        content_type = resp.headers.get("Content-Type", "")
        if "html" not in content_type.lower():
            base["reason"] = f"Non-HTML content-type: {content_type}"
            base["fetch_error"] = "non-html"
            return base

        result = _score_page_content(resp.text)
        result["url"] = url
        result["fetch_error"] = None
        return result

    except requests.exceptions.Timeout:
        base["fetch_error"] = "timeout"
        base["reason"] = "Page timed out — excluded for safety"
        return base
    except requests.exceptions.TooManyRedirects:
        base["fetch_error"] = "too_many_redirects"
        base["reason"] = "Too many redirects — excluded"
        return base
    except requests.exceptions.RequestException as exc:
        base["fetch_error"] = str(exc)
        base["reason"] = f"Fetch error: {exc}"
        return base


def _filter_business_only_with_content(
    results: list[dict],
    max_results: int,
    content_verify: bool = True,
    verify_timeout: int = 10,
    progress_callback=None,
) -> list[dict]:
    """
    Two-stage filter:
      Stage 1 — fast URL/title/snippet heuristics (is_aggregator)
      Stage 2 — optional content fetch + analysis (verify_real_business)

    A result passes only if it clears both stages.
    """
    # Stage 1: fast heuristic filter
    stage1 = [
        r for r in results
        if r.get("source_url")
        and not is_aggregator(
            r["source_url"], r.get("business_name", ""), r.get("snippet", "")
        )
    ]

    if not content_verify:
        return stage1[:max_results]

    # Stage 2: content verification (fetch + analyse)
    verified = []
    for r in stage1:
        if len(verified) >= max_results:
            break
        verdict = verify_real_business(
            r["source_url"],
            timeout=verify_timeout,
            progress_callback=progress_callback,
        )
        if verdict["is_real_business"]:
            # Attach verification metadata for transparency
            r["content_verified"] = True
            r["content_confidence"] = verdict["confidence"]
            r["content_reason"] = verdict["reason"]
            verified.append(r)
        else:
            if progress_callback:
                progress_callback(
                    f"❌ Removed by content check: {r.get('business_name', r['source_url'][:40])} "
                    f"({verdict['reason']})"
                )

    return verified


# ---------------------------------------------------------------------------
# Backwards-compatible simple filter (used internally when content_verify=False)
# ---------------------------------------------------------------------------
def _filter_business_only(results: list[dict], max_results: int) -> list[dict]:
    """Remove aggregator / non-business URLs and trim to max_results."""
    return _filter_business_only_with_content(
        results, max_results, content_verify=False
    )


# ---------------------------------------------------------------------------
# User-agent pool
# ---------------------------------------------------------------------------
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 OPR/108.0.0.0",
]

SERPER_API_KEY = "ed92cd653e12f00849abbdedd5dd835efa952391"
SERPER_URL = "https://google.serper.dev/search"


def _random_delay():
    """Sleep for a random 2–5 second delay."""
    time.sleep(random.uniform(2, 5))


def _get_proxies() -> Optional[dict]:
    """Return proxy config from env var PROXY_URL, or None."""
    proxy_url = os.environ.get("PROXY_URL")
    if proxy_url:
        return {"http": proxy_url, "https": proxy_url}
    return None


def _rotate_headers() -> dict:
    """Return headers with a randomly chosen user-agent."""
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }


# ---------------------------------------------------------------------------
# Primary: Serper
# ---------------------------------------------------------------------------
def _build_query(industry: str, area: str, query: str = "") -> str:
    """
    Build a Google-style search string from the three input fields, the
    same way a person would type it straight into google.com:
        <categories> <free-text query> in <location>

    Any of the three pieces can be blank — empty pieces are simply
    dropped rather than leaving stray "in" or double spaces behind.
    """
    parts = [p.strip() for p in (industry, query) if p and p.strip()]
    base = " ".join(parts)
    area = (area or "").strip()
    if base and area:
        return f"{base} in {area}"
    if area:
        return area
    return base


def search_serper(industry: str, area: str, max_results: int = 20, query: str = "",
                   page: int = 1) -> list[dict]:
    """Query Serper (Google) and return list of business dicts.

    `industry` = categories field, `area` = location field, `query` =
    optional free-text keywords — combined into one Google-style search
    string, e.g. "dentists open now in Berlin, Germany".

    `page` selects which page of Google's results to fetch (Serper's
    native pagination, same as Google's own page 1 / 2 / 3…). Previously
    this was never sent, so every search silently only ever looked at
    page 1 — if that page didn't have enough usable organic results
    (very common for local/niche queries dominated by Maps/Local-Pack
    listings), there was no way to pull more.
    """
    search_query = _build_query(industry, area, query)
    payload = {"q": search_query, "num": min(max_results, 100)}
    if page and page > 1:
        payload["page"] = page
    headers = {
        "X-API-KEY": SERPER_API_KEY,
        "Content-Type": "application/json",
    }
    proxies = _get_proxies()

    response = requests.post(
        SERPER_URL,
        json=payload,
        headers=headers,
        proxies=proxies,
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()

    results = []

    # Organic results
    for item in data.get("organic", [])[:max_results]:
        results.append(
            {
                "business_name": item.get("title", "").strip(),
                "source_url": item.get("link", "").strip(),
                "snippet": item.get("snippet", "").strip(),
                "source": "Google (Serper)",
            }
        )

    # Knowledge graph if present (page 1 only — it doesn't repeat on later pages)
    kg = data.get("knowledgeGraph", {})
    if kg and page == 1 and len(results) < max_results:
        results.insert(
            0,
            {
                "business_name": kg.get("title", "").strip(),
                "source_url": kg.get("website", "").strip(),
                "snippet": kg.get("description", "").strip(),
                "source": "Google Knowledge Graph",
            },
        )

    return results[:max_results]


# ---------------------------------------------------------------------------
# Fallback 1: Bing
# ---------------------------------------------------------------------------
def search_bing(industry: str, area: str, max_results: int = 20, query: str = "") -> list[dict]:
    """Scrape Bing search results as a fallback."""
    search_query = _build_query(industry, area, query)
    url = "https://www.bing.com/search"
    params = {"q": search_query, "count": max_results}
    proxies = _get_proxies()

    _random_delay()
    response = requests.get(
        url,
        params=params,
        headers=_rotate_headers(),
        proxies=proxies,
        timeout=15,
    )
    response.raise_for_status()

    from html.parser import HTMLParser

    class BingParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.results = []
            self._in_title = False
            self._in_snippet = False
            self._current = {}
            self._depth = 0

        def handle_starttag(self, tag, attrs):
            attrs_dict = dict(attrs)
            cls = attrs_dict.get("class", "")
            if tag == "li" and "b_algo" in cls:
                self._current = {}
            if tag == "a" and self._current is not None and "href" in attrs_dict:
                href = attrs_dict["href"]
                if href.startswith("http") and "business_name" not in self._current:
                    self._current["source_url"] = href
                    self._in_title = True
            if tag in ("p", "div") and "b_caption" in cls:
                self._in_snippet = True

        def handle_endtag(self, tag):
            if tag == "a":
                self._in_title = False
            if tag in ("p", "div"):
                self._in_snippet = False
            if tag == "li" and self._current.get("source_url"):
                self.results.append(self._current)
                self._current = {}

        def handle_data(self, data):
            data = data.strip()
            if not data:
                return
            if self._in_title and "business_name" not in self._current:
                self._current["business_name"] = data
            if self._in_snippet and "snippet" not in self._current:
                self._current["snippet"] = data

    parser = BingParser()
    parser.feed(response.text)

    results = []
    for item in parser.results[:max_results]:
        results.append(
            {
                "business_name": item.get("business_name", "Unknown"),
                "source_url": item.get("source_url", ""),
                "snippet": item.get("snippet", ""),
                "source": "Bing",
            }
        )
    return results


# ---------------------------------------------------------------------------
# Fallback 2: DuckDuckGo
# ---------------------------------------------------------------------------
def search_duckduckgo(industry: str, area: str, max_results: int = 20, query: str = "") -> list[dict]:
    """Use DuckDuckGo instant-answer API as second fallback."""
    search_query = _build_query(industry, area, query)
    url = "https://api.duckduckgo.com/"
    params = {
        "q": search_query,
        "format": "json",
        "no_html": "1",
        "skip_disambig": "1",
    }
    proxies = _get_proxies()

    _random_delay()
    response = requests.get(
        url,
        params=params,
        headers=_rotate_headers(),
        proxies=proxies,
        timeout=15,
    )
    response.raise_for_status()
    data = response.json()

    results = []

    # RelatedTopics
    for topic in data.get("RelatedTopics", [])[:max_results]:
        if isinstance(topic, dict) and "Text" in topic:
            first_url = topic.get("FirstURL", "")
            text = topic.get("Text", "")
            name = text.split(" - ")[0] if " - " in text else text[:60]
            results.append(
                {
                    "business_name": name.strip(),
                    "source_url": first_url,
                    "snippet": text.strip(),
                    "source": "DuckDuckGo",
                }
            )

    # Abstract as top result
    if data.get("AbstractURL") and len(results) < max_results:
        results.insert(
            0,
            {
                "business_name": data.get("Heading", search_query),
                "source_url": data.get("AbstractURL", ""),
                "snippet": data.get("AbstractText", ""),
                "source": "DuckDuckGo Abstract",
            },
        )

    return results[:max_results]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def search(
    industry: str,
    area: str,
    max_results: int = 20,
    content_verify: bool = True,
    verify_timeout: int = 10,
    progress_callback=None,
    query: str = "",
) -> tuple[list[dict], str]:
    """
    Search for businesses matching `industry` in `area`, optionally
    refined by free-text `query` keywords — the three fields are combined
    into a single Google-style search string, exactly like typing
    "<industry> <query> in <area>" into google.com.

    Parameters
    ----------
    industry : str
        Business type / category to search for (e.g. "pizza restaurant").
    area : str
        Geographic area (e.g. "Berlin, Germany").
    query : str
        Optional free-text keywords to refine the search further
        (e.g. "open on weekends", "family owned", "site:instagram.com").
    max_results : int
        Maximum number of verified business results to return.
    content_verify : bool
        If True (default), fetch each candidate page and run Layer 7
        content-based verification before including it in results.
        Set to False to skip fetching and rely only on URL/title heuristics
        (faster but less accurate).
    verify_timeout : int
        Seconds to wait when fetching each page for content verification.
    progress_callback : callable | None
        Optional function(message: str) called with status updates.

    Returns
    -------
    tuple[list[dict], str]
        (results, engine_used)
        Each result dict contains:
            business_name, source_url, snippet, source,
            content_verified (bool), content_confidence (float),
            content_reason (str)
    """
    # Fetch a larger buffer so enough results survive after filtering.
    BUFFER_MULTIPLIER = 5
    fetch_count = min(max_results * BUFFER_MULTIPLIER, 100)

    if progress_callback:
        progress_callback("🔍 Querying Serper (Google)…")

    # Keep asking for subsequent pages of Google results until we've
    # collected enough verified results or we run out of pages to try.
    MAX_SERPER_PAGES = 5
    seen_urls: set[str] = set()
    accumulated: list[dict] = []

    try:
        for page_num in range(1, MAX_SERPER_PAGES + 1):
            if len(accumulated) >= max_results:
                break

            if progress_callback and page_num > 1:
                progress_callback(f"🔍 Querying Serper (Google) — page {page_num}…")

            raw = search_serper(industry, area, fetch_count, query=query, page=page_num)

            # Drop anything already seen on an earlier page before filtering.
            new_raw = [r for r in raw if r.get("source_url") not in seen_urls]
            if not new_raw:
                # Nothing new on this page — later pages won't help either.
                if progress_callback:
                    progress_callback(
                        f"ℹ️ Page {page_num}: 0 new candidates (raw={len(raw)}) — stopping pagination."
                    )
                break
            seen_urls.update(r.get("source_url") for r in new_raw)

            filtered = _filter_business_only_with_content(
                new_raw, max_results - len(accumulated),
                content_verify=content_verify,
                verify_timeout=verify_timeout,
                progress_callback=progress_callback,
            )
            accumulated.extend(filtered)

            if progress_callback:
                progress_callback(
                    f"ℹ️ Page {page_num}: {len(raw)} raw → {len(new_raw)} new → "
                    f"{len(filtered)} survived filtering (running total: {len(accumulated)}/{max_results})"
                )

            # NOTE: previously we broke out of the loop here whenever
            # `len(raw) < fetch_count`, on the assumption that a short
            # page meant Google had no more results. That heuristic was
            # cutting pagination short for broad queries (e.g. a whole
            # country) where a single page can legitimately return fewer
            # organic results than requested while later pages still
            # contain new businesses. We now only stop early when a page
            # yields zero *new* URLs (handled above) or when we hit
            # MAX_SERPER_PAGES.

        if accumulated:
            return accumulated[:max_results], "Google via Serper"
    except Exception:
        if progress_callback:
            progress_callback("⚠️ Serper failed. Trying Bing…")

    try:
        results = search_bing(industry, area, fetch_count, query=query)
        results = _filter_business_only_with_content(
            results, max_results,
            content_verify=content_verify,
            verify_timeout=verify_timeout,
            progress_callback=progress_callback,
        )
        if results:
            return results, "Bing (fallback)"
    except Exception:
        if progress_callback:
            progress_callback("⚠️ Bing also failed. No results found.")

    return [], "None"