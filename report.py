"""
Report generation.

Produces shareable Markdown and HTML reports from a completed research run.
Output is self-contained, no external dependencies in the HTML.

The user can:
- Send the .md to anyone (renders on GitHub, Notion, etc.)
- Open the .html in any browser
- Print the .html to PDF if they need that format
"""

import html
from datetime import datetime
from pathlib import Path


def _format_progress_bar(percentage: float, width: int = 20) -> str:
    filled = int(percentage / 100 * width)
    return "█" * filled + "░" * (width - filled)


def _coerce_to_string(value) -> str:
    """
    Defensive: LLMs sometimes return a dict where we expected a string.
    Coerce gracefully to a readable string instead of crashing.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        # Format dict as readable bullet list
        parts = []
        for k, v in value.items():
            label = k.replace("_", " ").title()
            v_str = _coerce_to_string(v)
            if v_str:
                parts.append(f"**{label}:** {v_str}")
        return "\n\n".join(parts)
    if isinstance(value, list):
        return "\n".join(f"- {_coerce_to_string(item)}" for item in value)
    return str(value)


def _markdown_complaints(complaints: list[dict]) -> str:
    if not complaints:
        return ""
    lines = []
    for c in complaints[:5]:
        conf = c.get("confidence", "single")
        badge = {"confirmed": "⚠️", "reported": "•", "single": "?"}.get(conf, "•")
        lines.append(f"  - {badge} {c.get('text', '')} *[{conf}]*")
    return "\n".join(lines)


def _markdown_links(links: list[dict]) -> str:
    if not links:
        return ""
    lines = []
    for link in links:
        affiliate = " *(affiliate)*" if link.get("is_affiliate") else ""
        direct = " 🎯" if link.get("is_direct") else ""
        lines.append(f"  - [{link['retailer']}]({link['url']}){direct}{affiliate}")
    return "\n".join(lines)


def generate_markdown(
    query: str,
    category: str,
    profile: dict,
    rubric: dict,
    analysis: dict,
    scored_products: list[dict],
    shopping_links: dict | None = None,
    explanations: dict | None = None,
) -> str:
    """Generate the full Markdown report."""
    shopping_links = shopping_links or {}
    explanations = explanations or {}

    md = []
    md.append(f"# Shopping Research Report")
    md.append(f"")
    md.append(f"**Query:** {query}")
    md.append(f"**Category:** `{category}`")
    md.append(f"**Generated:** {datetime.utcnow().strftime('%B %d, %Y')}")
    md.append(f"")

    # Summary — coerce non-string to string (the analyzer sometimes returns a dict)
    summary = analysis.get("summary", "")
    summary_text = _coerce_to_string(summary)
    if summary_text:
        md.append(f"## TL;DR")
        md.append(f"")
        md.append(summary_text)
        md.append(f"")

    # Your Profile
    md.append(f"## Your Profile")
    md.append(f"")
    if profile.get("preferences_summary"):
        md.append(profile["preferences_summary"])
        md.append(f"")

    # Your Rubric
    md.append(f"## How We Ranked (Your Priorities)")
    md.append(f"")
    md.append(f"| Criterion | Weight | Why |")
    md.append(f"|---|---|---|")
    sorted_crits = sorted(rubric["weighted_criteria"], key=lambda c: c["weight"], reverse=True)
    for c in sorted_crits:
        rationale = c.get("rationale", "").replace("|", "\\|")
        md.append(f"| {c['label']} | {c['weight']}/10 | {rationale} |")
    md.append(f"")

    # Top picks
    md.append(f"## Top Picks")
    md.append(f"")

    for i, p in enumerate(scored_products[:5], 1):
        md.append(f"### {i}. {p['name']}")
        md.append(f"")
        pct = p.get("percentage", 0)
        bar = _format_progress_bar(pct)
        signal = p.get("signal_strength", "?").upper()
        md.append(f"**Score:** {p['weighted_total']:.0f}/{p['max_possible']:.0f} "
                  f"({pct:.0f}%)  `{bar}`")
        md.append(f"**Evidence strength:** {signal}")
        md.append(f"")

        # Why this product
        explanation = explanations.get(p["name"], "")
        if explanation:
            md.append(f"**Why this fits you:**")
            md.append(f"")
            md.append(f"> {explanation}")
            md.append(f"")

        # Score breakdown
        md.append(f"**Score breakdown:**")
        md.append(f"")
        md.append(f"| Criterion | Score | Weight | Evidence |")
        md.append(f"|---|---|---|---|")
        sorted_scores = sorted(p["scores"], key=lambda s: s["weighted_contribution"], reverse=True)
        for s in sorted_scores:
            evidence = s["evidence"].replace("|", "\\|").replace("\n", " ")
            md.append(f"| {s['label']} | {s['score']:.0f}/10 | ×{s['weight']} | {evidence} |")
        md.append(f"")

        # Buy links
        links = shopping_links.get(p["name"], [])
        if links:
            md.append(f"**Where to buy:**")
            md.append(f"")
            md.append(_markdown_links(links))
            md.append(f"")

        md.append(f"---")
        md.append(f"")

    # Categories
    materials = analysis.get("materials", [])
    if materials:
        md.append(f"## Material / Category Insights")
        md.append(f"")
        for m in sorted(materials, key=lambda x: x.get("mention_count", 0), reverse=True)[:7]:
            md.append(f"**{m['name']}** — {m.get('mention_count', '?')} mentions, "
                      f"{m.get('distinct_recommenders', '?')} distinct recommenders")
            md.append(f"")
            if m.get("praise"):
                md.append(f"  - Praised for: {', '.join(m['praise'][:4])}")
            comps_md = _markdown_complaints(m.get("complaints", []))
            if comps_md:
                md.append(f"  - Complaints:")
                md.append(comps_md)
            md.append(f"")

    md.append(f"")
    md.append(f"---")
    md.append(f"")
    md.append(f"*Generated by Shopping Research Agent. Reddit + trusted reviews → personalized scoring.*")

    return "\n".join(md)


def generate_html(markdown_text: str, query: str) -> str:
    """
    Convert markdown to a self-contained HTML page.
    No external CSS - embedded styles. No JS - pure HTML.
    Works in any browser, prints to PDF cleanly.
    """
    # Simple markdown → HTML conversion (handles what we generate)
    html_body = _markdown_to_html(markdown_text)

    title = html.escape(f"Shopping Report: {query}")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
    max-width: 860px;
    margin: 0 auto;
    padding: 2em 1.5em;
    line-height: 1.6;
    color: #1a1a1a;
    background: #fafafa;
  }}
  h1 {{ font-size: 2em; border-bottom: 3px solid #2c5aa0; padding-bottom: 0.3em; }}
  h2 {{ font-size: 1.5em; color: #2c5aa0; margin-top: 1.8em; border-bottom: 1px solid #e0e0e0; padding-bottom: 0.2em; }}
  h3 {{ font-size: 1.2em; color: #333; margin-top: 1.5em; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; background: white; }}
  th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; vertical-align: top; }}
  th {{ background: #f4f6f8; font-weight: 600; }}
  tr:nth-child(even) td {{ background: #fafbfc; }}
  code {{ background: #f0f0f0; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }}
  blockquote {{
    border-left: 4px solid #2c5aa0;
    margin: 1em 0;
    padding: 0.5em 1em;
    background: #f0f4fa;
    color: #333;
  }}
  hr {{ border: none; border-top: 2px solid #e0e0e0; margin: 2em 0; }}
  a {{ color: #2c5aa0; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  ul {{ padding-left: 1.5em; }}
  strong {{ color: #1a1a1a; }}
  em {{ color: #555; }}
  @media print {{
    body {{ background: white; padding: 1em; }}
    a {{ color: #1a1a1a; }}
  }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""


def _markdown_to_html(md: str) -> str:
    """Simple markdown → HTML for the structures we generate. Not a general converter."""
    lines = md.split("\n")
    html_lines = []
    in_table = False
    in_list = False
    table_header_done = False

    for line in lines:
        stripped = line.strip()

        # Tables
        if stripped.startswith("|"):
            if not in_table:
                html_lines.append("<table>")
                in_table = True
                table_header_done = False
            # Skip separator rows like |---|---|
            if re.match(r"^\|[\s\-:|]+\|$", stripped):
                table_header_done = True
                continue
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            tag = "th" if not table_header_done else "td"
            row = "<tr>" + "".join(f"<{tag}>{_inline_md(c)}</{tag}>" for c in cells) + "</tr>"
            html_lines.append(row)
            continue
        else:
            if in_table:
                html_lines.append("</table>")
                in_table = False

        # Headers
        if stripped.startswith("# "):
            html_lines.append(f"<h1>{_inline_md(stripped[2:])}</h1>")
            continue
        if stripped.startswith("## "):
            html_lines.append(f"<h2>{_inline_md(stripped[3:])}</h2>")
            continue
        if stripped.startswith("### "):
            html_lines.append(f"<h3>{_inline_md(stripped[4:])}</h3>")
            continue

        # Horizontal rule
        if stripped == "---":
            html_lines.append("<hr>")
            continue

        # Blockquote
        if stripped.startswith("> "):
            html_lines.append(f"<blockquote>{_inline_md(stripped[2:])}</blockquote>")
            continue

        # List items
        if stripped.startswith("- ") or re.match(r"^\s+- ", line):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            content = stripped[2:] if stripped.startswith("- ") else line.lstrip()[2:]
            html_lines.append(f"<li>{_inline_md(content)}</li>")
            continue
        else:
            if in_list and stripped:
                html_lines.append("</ul>")
                in_list = False

        # Empty line
        if not stripped:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            continue

        # Paragraph
        html_lines.append(f"<p>{_inline_md(stripped)}</p>")

    # Close any open structures
    if in_table:
        html_lines.append("</table>")
    if in_list:
        html_lines.append("</ul>")

    return "\n".join(html_lines)


# Need re for markdown converter
import re


def _inline_md(text: str) -> str:
    """Handle inline markdown: bold, italic, links, code."""
    # Escape HTML first
    text = html.escape(text)
    # Code (do first so it doesn't get mangled)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    # Links [text](url)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2" target="_blank" rel="noopener">\1</a>', text)
    # Bold **text**
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    # Italic *text*
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", text)
    return text


def export_reports(
    query: str,
    category: str,
    profile: dict,
    rubric: dict,
    analysis: dict,
    scored_products: list[dict],
    output_dir: str = ".",
    shopping_links: dict | None = None,
    explanations: dict | None = None,
) -> tuple[str, str]:
    """
    Generate both .md and .html files. Returns (md_path, html_path).
    """
    safe_query = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:50]
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    base = f"report-{safe_query}-{timestamp}"

    md_text = generate_markdown(
        query, category, profile, rubric, analysis, scored_products,
        shopping_links=shopping_links, explanations=explanations,
    )
    html_text = generate_html(md_text, query)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    md_path = out_dir / f"{base}.md"
    html_path = out_dir / f"{base}.html"

    md_path.write_text(md_text, encoding="utf-8")
    html_path.write_text(html_text, encoding="utf-8")

    return str(md_path), str(html_path)