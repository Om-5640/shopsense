"""
Canonical Product Resolver + Attribute Extractor (Phases 1 & 4)
Deterministic, regex-only, no LLM, < 5ms per call.

Usage:
    from product_canonicalizer import canonicalize_product, extract_product_attributes
    c = canonicalize_product("Samsung Galaxy S25 Ultra 512GB Titanium Black")
    # → CanonicalProduct(brand="Samsung", model="Galaxy S25 Ultra",
    #                     storage="512GB", color="Titanium Black", ...)
"""

import re
from dataclasses import dataclass, field
from functools import lru_cache

__all__ = ["CanonicalProduct", "canonicalize_product", "extract_product_attributes"]


@dataclass
class CanonicalProduct:
    brand: str | None
    model: str | None
    storage: str | None        # normalized: "512GB", "1TB"
    ram: str | None            # normalized: "8GB"
    color: str | None
    generation: str | None     # "Gen 2", "2nd Gen"
    screen_size: str | None    # "6.8\""
    variant: str | None        # e.g. "Pro", "Plus", "Ultra", "Max"
    canonical_name: str
    parse_confidence: float    # 0.0–1.0 — how complete the parse was


# ── Brand dictionary ──────────────────────────────────────────────────────────
# Maps lowercase aliases → canonical display name.
# Longer aliases must sort before shorter to prevent prefix conflicts.
_BRAND_MAP: dict[str, str] = {
    "samsung": "Samsung",
    "apple": "Apple",
    "iphone": "Apple",
    "macbook": "Apple",
    "ipad": "Apple",
    "airpods": "Apple",
    "sony": "Sony",
    "lg": "LG",
    "oneplus": "OnePlus",
    "one plus": "OnePlus",
    "google pixel": "Google",
    "google": "Google",
    "pixel": "Google",
    "motorola": "Motorola",
    "moto": "Motorola",
    "realme": "Realme",
    "oppo": "Oppo",
    "vivo": "Vivo",
    "xiaomi": "Xiaomi",
    "poco": "Poco",
    "redmi": "Redmi",
    "nokia": "Nokia",
    "asus": "ASUS",
    "zenfone": "ASUS",
    "rog phone": "ASUS",
    "lenovo": "Lenovo",
    "thinkpad": "Lenovo",
    "ideapad": "Lenovo",
    "hp": "HP",
    "dell": "Dell",
    "xps": "Dell",
    "inspiron": "Dell",
    "alienware": "Dell",
    "acer": "Acer",
    "msi": "MSI",
    "intel": "Intel",
    "amd": "AMD",
    "nvidia": "NVIDIA",
    "bose": "Bose",
    "jbl": "JBL",
    "sennheiser": "Sennheiser",
    "anker": "Anker",
    "boat": "boAt",
    "noise": "Noise",
    "nothing": "Nothing",
    "logitech": "Logitech",
    "razer": "Razer",
    "corsair": "Corsair",
    "hyperx": "HyperX",
    "nikon": "Nikon",
    "canon": "Canon",
    "fujifilm": "Fujifilm",
    "gopro": "GoPro",
    "dyson": "Dyson",
    "philips": "Philips",
    "bosch": "Bosch",
    "mi ": "Xiaomi",      # trailing space prevents matching "mixed" etc.
}

# Sorted by length desc so longer phrases match before shorter prefixes
_SORTED_BRANDS = sorted(_BRAND_MAP.keys(), key=len, reverse=True)


# ── Compiled regexes ──────────────────────────────────────────────────────────

# Storage: "512GB", "1TB", "256 GB", "2 TB"
_RE_STORAGE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(TB|GB|MB)\b",
    re.IGNORECASE,
)

# Explicit RAM labels
_RE_RAM_EXPLICIT = re.compile(
    r"\b(\d+)\s*GB\s*(?:RAM|LPDDR\w*|Memory)\b",
    re.IGNORECASE,
)

# RAM+Storage config: "8GB+256GB" or "12GB/512GB"
_RE_RAM_CONFIG = re.compile(
    r"\b(\d+)\s*GB\s*[+/]\s*(\d+)\s*(?:GB|TB)\b",
    re.IGNORECASE,
)

# Screen size: "6.7 inch", "13\"", "15.6-inch"
_RE_SCREEN = re.compile(
    r'\b(\d+(?:\.\d+)?)\s*[-–]?\s*(?:inch(?:es)?|")\b',
    re.IGNORECASE,
)

# Generation patterns: "5G", "Gen 2", "2nd Gen", "Generation 3", "Series 6"
_RE_GEN = re.compile(
    r'\b(?:(\d+)(?:st|nd|rd|th)?\s+Gen(?:eration)?|Gen(?:eration)?\s*(\d+)|Series\s*(\d+))\b',
    re.IGNORECASE,
)

# Color keywords — sorted longest first to prefer "Titanium Black" over "Black"
_COLOR_LIST = [
    # iPhone-specific (Apple names them with material prefix)
    "natural titanium", "black titanium", "white titanium", "desert titanium",
    "blue titanium",
    # Samsung titanium series
    "titanium black", "titanium gray", "titanium grey", "titanium silver",
    "titanium violet", "titanium blue", "titanium white", "titanium yellow",
    # Apple legacy
    "space gray", "space grey", "space black",
    "midnight green", "midnight black", "midnight",
    "starlight", "sierra blue", "alpine green", "product red",
    # Samsung phantom / mystic / prism
    "phantom black", "phantom white", "phantom silver", "phantom gray",
    "mystic bronze", "mystic black", "mystic white",
    "prism black", "prism white", "prism blue",
    "aura glow",
    # Common descriptors
    "rose gold", "dark blue", "light blue", "sky blue",
    "graphite", "obsidian",
    "black", "white", "silver", "gold", "blue", "red", "green",
    "purple", "violet", "pink", "yellow", "orange", "grey", "gray",
    "titanium", "graphite", "lavender", "coral", "copper", "bronze",
    "champagne", "cream", "sage", "teal", "indigo", "aqua", "mint",
    "navy", "emerald", "chalk", "clay", "natural", "crystal",
]

# Compile color patterns (word-boundary anchored, longest first)
_COLOR_PATTERNS = [
    (c, re.compile(r'\b' + re.escape(c) + r'\b', re.IGNORECASE))
    for c in sorted(_COLOR_LIST, key=len, reverse=True)
]

# Variant suffixes
_VARIANT_KEYWORDS = [
    "ultra", "pro max", "pro plus", "pro+", "pro", "plus", "max",
    "edge", "fold", "flip", "note", "lite", "fe", "neo",
    "s24+", "s25+",  # Samsung shorthand
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_gb(s: str) -> float | None:
    """Convert storage string to float GB for comparison."""
    s = s.upper().strip()
    m = re.search(r"[\d.]+", s)
    if not m:
        return None
    val = float(m.group())
    if "TB" in s:
        return val * 1024.0
    if "GB" in s:
        return val
    if "MB" in s:
        return val / 1024.0
    return None


def _normalize_storage(text: str) -> str | None:
    """
    Extract the storage value (not RAM) from a product name.
    Heuristic: largest GB/TB value is storage; < 32GB without explicit label → probably RAM.
    """
    # Check for explicit RAM config first to exclude those values
    ram_config_match = _RE_RAM_CONFIG.search(text)
    excluded_vals: set[int] = set()
    if ram_config_match:
        v1, v2 = int(ram_config_match.group(1)), int(ram_config_match.group(2))
        # Smaller value is RAM — exclude it
        excluded_vals.add(min(v1, v2))

    # Exclude explicit RAM-labelled values
    for m in _RE_RAM_EXPLICIT.finditer(text):
        excluded_vals.add(int(m.group(1)))

    candidates: list[tuple[float, str]] = []
    for m in _RE_STORAGE.finditer(text):
        val_str, unit = m.group(1), m.group(2).upper()
        val = float(val_str)
        int_val = int(val)

        if int_val in excluded_vals:
            continue
        # Very small GB values without label are likely RAM, skip
        if unit == "GB" and val <= 16 and int_val not in excluded_vals:
            continue

        if unit == "TB":
            gb_equiv = val * 1024.0
            label = f"{val_str}TB" if "." in val_str else f"{int_val}TB"
        elif unit == "GB":
            gb_equiv = val
            label = f"{int_val}GB"
        else:  # MB
            gb_equiv = val / 1024.0
            label = f"{int_val}MB"

        candidates.append((gb_equiv, label))

    if not candidates:
        return None
    # Return the largest value (primary storage)
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _normalize_ram(text: str) -> str | None:
    """Extract RAM value from product name."""
    m = _RE_RAM_EXPLICIT.search(text)
    if m:
        return f"{m.group(1)}GB"

    m = _RE_RAM_CONFIG.search(text)
    if m:
        v1, v2 = int(m.group(1)), int(m.group(2))
        ram = min(v1, v2)
        if ram <= 64:  # sanity: RAM ≤ 64 GB for consumer devices
            return f"{ram}GB"
    return None



# Brands that are also common English words — require them to appear at the
# START of the product name (not buried mid-title like "Noise Cancelling").
_PREFIX_ONLY_BRANDS = {"noise", "nothing", "pixel", "mi "}

def _extract_brand(text: str) -> str | None:
    """Match brand from known brand list. Returns canonical display name."""
    text_lower = text.lower().strip()
    for brand_key in _SORTED_BRANDS:
        key = brand_key.strip()
        if brand_key in _PREFIX_ONLY_BRANDS:
            # Only match if the product name starts with this brand
            if text_lower.startswith(key) or re.match(r'^' + re.escape(key) + r'\b', text_lower):
                return _BRAND_MAP[brand_key]
        else:
            pattern = r"(?:^|\s)" + re.escape(key) + r"(?:\s|$)"
            if re.search(pattern, text_lower):
                return _BRAND_MAP[brand_key]
    return None


def _extract_color(text: str) -> str | None:
    """Find the longest matching color keyword."""
    for color_name, pattern in _COLOR_PATTERNS:
        if pattern.search(text):
            return color_name.title()
    return None


def _extract_generation(text: str) -> str | None:
    m = _RE_GEN.search(text)
    if not m:
        return None
    gen_num = m.group(1) or m.group(2) or m.group(3)
    return f"Gen {gen_num}" if gen_num else None


def _extract_screen(text: str) -> str | None:
    m = _RE_SCREEN.search(text)
    return f'{m.group(1)}"' if m else None


def _extract_variant(text: str) -> str | None:
    """Extract variant suffix like Ultra, Pro Max, etc."""
    text_lower = text.lower()
    for kw in _VARIANT_KEYWORDS:
        if re.search(r'\b' + re.escape(kw) + r'\b', text_lower):
            return kw.title()
    return None


def _extract_model(
    text: str,
    brand: str | None,
    storage: str | None,
    ram: str | None,
    color: str | None,
    generation: str | None,
    screen_size: str | None,
) -> str | None:
    """
    Derive core model name by stripping known attributes from the product name.
    """
    cleaned = text

    # Remove brand prefix (case-insensitive)
    if brand:
        cleaned = re.sub(r'(?i)(?:^|\s)' + re.escape(brand) + r'(?:\s|$)', ' ', cleaned)

    # Remove RAM patterns FIRST (before storage) so "16GB RAM" is removed atomically
    cleaned = _RE_RAM_EXPLICIT.sub(' ', cleaned)
    cleaned = _RE_RAM_CONFIG.sub(' ', cleaned)

    # Remove storage (all remaining GB/TB patterns)
    cleaned = _RE_STORAGE.sub(' ', cleaned)

    # Remove screen size
    cleaned = _RE_SCREEN.sub(' ', cleaned)

    # Remove color
    if color:
        cleaned = re.sub(r'(?i)\b' + re.escape(color) + r'\b', ' ', cleaned)

    # Remove generation
    cleaned = _RE_GEN.sub(' ', cleaned)

    # Remove common noise words (including storage-tech orphans)
    noise = (
        r'\b(?:buy|online|india|price|review|specifications?|spec|official|'
        r'new|latest|brand new|ram|ssd|hdd|nvme|emmc|storage|memory|'
        r'5g|4g|lte|wi-?fi|bluetooth|wireless|earbuds?|earphones?|'
        r'headphones?|headsets?|noise cancel(?:ling|lation)?|true wireless|tws|anc)\b'
    )
    cleaned = re.sub(noise, ' ', cleaned, flags=re.IGNORECASE)

    # Clean brackets/parens/punctuation
    cleaned = re.sub(r'[(\[\{].*?[)\]\}]', ' ', cleaned)
    cleaned = re.sub(r'[^\w\s\-+]', ' ', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip().strip('-_,. ')

    return cleaned or None


@lru_cache(maxsize=4096)
def _canonicalize_cached(text: str) -> tuple[
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    str,
    float,
]:
    """Cache deterministic parses so repeated matching stays cheap."""
    brand      = _extract_brand(text)
    storage    = _normalize_storage(text)
    ram        = _normalize_ram(text)
    color      = _extract_color(text)
    generation = _extract_generation(text)
    screen     = _extract_screen(text)
    variant    = _extract_variant(text)
    model      = _extract_model(text, brand, storage, ram, color, generation, screen)

    parts: list[str] = []
    if brand:
        parts.append(brand)
    if model:
        parts.append(model)
    if ram:
        parts.append(f"{ram} RAM")
    if storage:
        parts.append(storage)
    if color:
        parts.append(color)
    canonical_name = " ".join(parts) if parts else text

    fields_found = sum(1 for f in [brand, model, storage] if f)
    confidence = fields_found / 3.0
    if storage:
        confidence = min(1.0, confidence + 0.1)
    if brand and model:
        confidence = min(1.0, confidence + 0.1)

    return (
        brand,
        model,
        storage,
        ram,
        color,
        generation,
        screen,
        variant,
        canonical_name,
        round(confidence, 3),
    )


# ── Public API ────────────────────────────────────────────────────────────────

def canonicalize_product(name: str) -> CanonicalProduct:
    """
    Phase 1: Canonical Product Resolver.
    Input:  "Samsung Galaxy S25 Ultra 512GB Titanium Black"
    Output: CanonicalProduct(brand="Samsung", model="Galaxy S25 Ultra",
                              storage="512GB", color="Titanium Black", ...)
    Pure regex, deterministic, < 5ms.
    """
    if not name or not name.strip():
        return CanonicalProduct(
            brand=None, model=None, storage=None, ram=None,
            color=None, generation=None, screen_size=None, variant=None,
            canonical_name=name or "", parse_confidence=0.0,
        )

    text = re.sub(r"[\u2010-\u2015]+", "-", name).strip()
    (
        brand,
        model,
        storage,
        ram,
        color,
        generation,
        screen,
        variant,
        canonical_name,
        confidence,
    ) = _canonicalize_cached(text)

    return CanonicalProduct(
        brand=brand,
        model=model,
        storage=storage,
        ram=ram,
        color=color,
        generation=generation,
        screen_size=screen,
        variant=variant,
        canonical_name=canonical_name,
        parse_confidence=confidence,
    )


def extract_product_attributes(title: str) -> dict:
    """
    Phase 4: Fast attribute extraction from any product title string.
    Returns a plain dict — safe to use without importing CanonicalProduct.
    """
    c = canonicalize_product(title)
    return {
        "brand":       c.brand,
        "model":       c.model,
        "storage":     c.storage,
        "ram":         c.ram,
        "color":       c.color,
        "generation":  c.generation,
        "screen_size": c.screen_size,
        "variant":     c.variant,
    }
