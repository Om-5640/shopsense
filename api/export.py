"""
Export utilities — CSV and PDF report generation for search results.

Both generators take the raw search row dict (from db.get_search) and return
bytes that can be streamed directly as a file download.

PDF uses fpdf2 (pure Python, no browser dependency).
CSV uses the stdlib csv module.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime
from typing import Any

_logger = logging.getLogger(__name__)

# ── Currency symbol helper ────────────────────────────────────────────────────

_CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "GBP": "£", "EUR": "€", "AUD": "A$", "CAD": "C$"}

def _sym(currency: str) -> str:
    return _CURRENCY_SYMBOLS.get(currency, currency)


def _fmt_price(product: dict) -> str:
    price_data = product.get("price") or {}
    best = price_data.get("best_price") or {}
    currency = price_data.get("currency", "INR")
    sym = _sym(currency)
    val = best.get("price_inr") or best.get("price_usd")
    if val:
        return f"{sym}{val:,}"
    retailers = price_data.get("retailers") or []
    if retailers:
        r = retailers[0]
        p = r.get("price_inr") or r.get("price_usd")
        if p:
            return f"{sym}{p:,}"
    return "N/A"


def _top_criterion(product: dict) -> str:
    scores = product.get("scores") or []
    if not scores:
        return ""
    top = max(scores, key=lambda s: s.get("score", 0))
    return f"{top.get('label', top.get('criterion', ''))}: {top.get('score', 0):.1f}/10"


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def generate_csv(search_row: dict) -> bytes:
    """
    Return UTF-8 encoded CSV bytes for the scored products in this search.
    Columns: Rank, Product, Score%, Price, Store, Mentions, +ve, -ve, Signal, Top Criterion
    """
    scored_products = search_row.get("scoredProducts") or []
    if isinstance(scored_products, str):
        try:
            scored_products = json.loads(scored_products)
        except Exception:
            scored_products = []

    buf = io.StringIO()
    writer = csv.writer(buf)

    writer.writerow([
        "Rank", "Product", "Score (%)", "Price", "Store",
        "Mentions", "Positive", "Negative", "Signal Strength", "Top Criterion",
        "Summary / Explanation",
    ])

    for rank, p in enumerate(scored_products, 1):
        price_data = p.get("price") or {}
        retailers = price_data.get("retailers") or []
        store = retailers[0].get("name", "—") if retailers else "—"

        writer.writerow([
            rank,
            p.get("name", ""),
            f"{p.get('percentage', 0):.1f}",
            _fmt_price(p),
            store,
            p.get("mention_count") or 0,
            p.get("positive_mentions") or 0,
            p.get("negative_mentions") or 0,
            p.get("signal_strength", ""),
            _top_criterion(p),
            (p.get("explanation") or "")[:300],
        ])

    return buf.getvalue().encode("utf-8-sig")  # BOM for Excel compatibility


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------

def generate_pdf(search_row: dict) -> bytes:
    """
    Return PDF bytes for the search results using fpdf2.
    Falls back to a minimal plain text PDF if fpdf2 is not installed.
    """
    try:
        from fpdf import FPDF
        return _build_pdf_fpdf(search_row)
    except ImportError:
        _logger.warning("[export] fpdf2 not installed — returning plain text fallback PDF")
        return _build_pdf_fallback(search_row)


def _safe(text: str) -> str:
    """Strip any character outside the latin-1 range so fpdf2 built-in fonts don't crash."""
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _build_pdf_fpdf(search_row: dict) -> bytes:
    from fpdf import FPDF

    scored_products = search_row.get("scoredProducts") or []
    if isinstance(scored_products, str):
        try:
            scored_products = json.loads(scored_products)
        except Exception:
            scored_products = []

    rubric_raw = search_row.get("rubric") or {}
    if isinstance(rubric_raw, str):
        try:
            rubric_raw = json.loads(rubric_raw)
        except Exception:
            rubric_raw = {}
    criteria = rubric_raw.get("weighted_criteria") or []

    query    = _safe(search_row.get("query", ""))
    category = _safe(search_row.get("category", "").replace("/", " > "))
    region   = _safe(search_row.get("region", "global"))
    created  = search_row.get("createdAt", "")[:10]

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_margins(15, 15, 15)

    # ── Header ────────────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(140, 100, 255)   # violet
    pdf.cell(0, 12, "ShopSense", ln=True, align="C")

    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(160, 160, 170)
    pdf.cell(0, 6, "AI-powered shopping research", ln=True, align="C")
    pdf.ln(4)

    # ── Search meta ───────────────────────────────────────────────────────────
    pdf.set_draw_color(60, 60, 70)
    pdf.set_fill_color(20, 20, 28)
    pdf.rect(15, pdf.get_y(), 180, 22, "F")
    pdf.set_xy(18, pdf.get_y() + 4)

    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(250, 250, 250)
    pdf.cell(0, 6, query, ln=True)

    pdf.set_xy(18, pdf.get_y() + 1)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(113, 113, 122)
    pdf.cell(60, 5, f"Category: {category}")
    pdf.cell(50, 5, f"Region: {region}")
    pdf.cell(0, 5, f"Date: {created}", ln=True)
    pdf.ln(6)

    # ── Rubric criteria summary ────────────────────────────────────────────────
    if criteria:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(140, 100, 255)
        pdf.cell(0, 7, "Scoring Criteria", ln=True)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(161, 161, 170)
        for c in criteria[:6]:
            label = _safe(c.get('label', c.get('name', '')))
            pdf.cell(95, 5, f"- {label}: weight {c.get('weight', 5)}/10")
        pdf.ln(4)

    # ── Products ──────────────────────────────────────────────────────────────
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(140, 100, 255)
    pdf.cell(0, 7, f"Top Products  ({len(scored_products)} results)", ln=True)

    for rank, p in enumerate(scored_products, 1):
        if pdf.get_y() > 250:
            pdf.add_page()

        name = _safe(p.get("name", "Unknown"))
        pct  = p.get("percentage", 0)
        safe_price = _safe(_fmt_price(p))
        signal = _safe(p.get("signal_strength", "-"))
        mentions = p.get("mention_count") or 0

        # Product row background
        fill_color = (18, 18, 24) if rank % 2 == 0 else (15, 15, 20)
        pdf.set_fill_color(*fill_color)
        row_y = pdf.get_y()
        pdf.rect(15, row_y, 180, 18, "F")
        pdf.set_xy(18, row_y + 3)

        # Rank badge
        badge_color = (140, 100, 255) if rank <= 3 else (60, 60, 70)
        pdf.set_fill_color(*badge_color)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(250, 250, 250)
        pdf.cell(10, 7, f"#{rank}", border=0)

        # Product name
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(250, 250, 250)
        pdf.cell(90, 7, name[:45])

        score_color = (74, 222, 128) if pct >= 80 else (251, 191, 36) if pct >= 50 else (248, 113, 113)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*score_color)
        pdf.cell(35, 7, f"{pct:.1f}%")

        # Price
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(113, 113, 122)
        pdf.cell(0, 7, safe_price, ln=True)

        # Sub-row: community data
        pdf.set_xy(28, pdf.get_y())
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(82, 82, 91)
        pos = p.get("positive_mentions") or 0
        neg = p.get("negative_mentions") or 0
        sub = f"Signal: {signal}  |  {mentions} mentions  |  +{pos} / -{neg}"
        pdf.cell(0, 5, sub, ln=True)
        pdf.ln(2)

    # ── Footer ────────────────────────────────────────────────────────────────
    pdf.set_y(-15)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(82, 82, 91)
    pdf.cell(0, 10, f"Generated by ShopSense  ·  {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC", align="C")

    return bytes(pdf.output())


def _build_pdf_fallback(search_row: dict) -> bytes:
    """Minimal text-based 'PDF' when fpdf2 is unavailable — actually returns plain text."""
    scored_products = search_row.get("scoredProducts") or []
    if isinstance(scored_products, str):
        try:
            scored_products = json.loads(scored_products)
        except Exception:
            scored_products = []

    lines = [
        "ShopSense Results Export",
        "=" * 40,
        f"Query: {search_row.get('query', '')}",
        f"Category: {search_row.get('category', '')}",
        f"Region: {search_row.get('region', '')}",
        "",
    ]
    for rank, p in enumerate(scored_products, 1):
        lines.append(f"#{rank} {p.get('name', '')}  —  {p.get('percentage', 0):.1f}%  {_fmt_price(p)}")
    return "\n".join(lines).encode("utf-8")
