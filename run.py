"""
Shopping research agent (v3) — CLI entry point.

Flow:
  1. Detect category
  2. Generate criteria
  3. Get or create user profile (interview if needed)
  4. Build weighted rubric (CHECKPOINT 1: review before research)
  5. Run v2 research pipeline (Reddit + reviews)
  6. Score each product against rubric with evidence
  7. Show ranking (CHECKPOINT 2: tweak weights + re-rank)

Usage:
    python run.py "best blanket for me"
    python run.py "best earbuds under 2500" --new-profile      # force re-interview
    python run.py "best blanket" --skip-interview              # use defaults, no Q&A
    python run.py "best blanket" --no-reviews                  # Reddit only
    python run.py "best blanket" --output results.json
"""

import argparse
import json
import sys
from datetime import datetime

from category import resolve_category_interactively
from criteria import generate_criteria
from interview import get_or_create_profile, run_interview, save_profile, load_profile
from rubric import generate_rubric, review_rubric, load_rubric, save_rubric, display_rubric
from reddit_fetch import fetch_all_threads, resolve_region_interactively, set_session_region
from review_fetch import fetch_all_reviews
from normalizer import normalize_all
from llm_client import analyze_sources
from scorer import score_all_products, recompute_with_new_weights, display_results
import google_search


def main():
    parser = argparse.ArgumentParser(description="Shopping research agent v3")
    parser.add_argument("query", help="What you're researching")
    parser.add_argument("--limit", type=int, default=15, help="Reddit threads (default 15)")
    parser.add_argument("--reviews", type=int, default=8, help="Review pages (default 8)")
    parser.add_argument("--no-reviews", action="store_true", help="Skip review sites")
    parser.add_argument("--no-cache", action="store_true", help="Bypass cache")
    parser.add_argument("--new-profile", action="store_true", help="Force re-interview")
    parser.add_argument("--skip-interview", action="store_true", help="Use default weights, no interview")
    parser.add_argument("--no-checkpoint", action="store_true", help="Skip both review checkpoints")
    parser.add_argument("--category", default=None, help="Force a specific category slug, skip disambiguation (e.g. 'watches/analog')")
    parser.add_argument("--output", default=None, help="Save full JSON to file")
    parser.add_argument("--save-raw", action="store_true", help="Also save raw source data")
    parser.add_argument("--export", action="store_true", help="Export Markdown + HTML report at end")
    parser.add_argument("--shopping-links", action="store_true", help="Generate buy links per product (uses Serper quota)")
    parser.add_argument("--detailed", action="store_true", help="Generate detailed 'why this not that' explanations (extra Groq calls)")
    parser.add_argument("--compare", nargs="+", default=None, help="Compare named products side-by-side (must have run query first)")
    args = parser.parse_args()

    if args.no_cache:
        import shutil
        from pathlib import Path
        cache_dir = Path(__file__).parent / "cache"
        if cache_dir.exists():
            shutil.rmtree(cache_dir)
            cache_dir.mkdir()
            print("[cache] cleared")

    print(f"\n{'='*72}")
    print(f"  SHOPPING RESEARCH AGENT v3")
    print(f"  Query: {args.query}")
    print(f"{'='*72}\n")

    # ---- Step 1: detect category (with disambiguation if ambiguous) ----
    print("[1/6] Detecting category...")
    cat_info = resolve_category_interactively(args.query, forced_category=args.category)
    category = cat_info["category"]
    print(f"[1/6] Category: {category} (confidence: {cat_info['confidence']})\n")

    # ---- Step 2: criteria ----
    print("[2/6] Generating criteria...")
    criteria = generate_criteria(category)
    print(f"[2/6] {len(criteria)} criteria identified")
    for c in criteria:
        print(f"      - {c['label']}")
    print()

    # ---- Step 2.5: resolve region (ambiguous prices → ask user, persist in profile) ----
    existing_profile = load_profile(category)
    region, _ = resolve_region_interactively(args.query, profile=existing_profile)
    set_session_region(region)

    # ---- Step 3: profile ----
    print("[3/6] Profile check...")
    if args.skip_interview:
        profile = {
            "interview": [],
            "preferences_summary": "(skipped - using default weights)",
            "region": region,
        }
        save_profile(category, profile)
    else:
        # get_or_create_profile handles region persistence internally now (single save)
        profile = get_or_create_profile(category, criteria, force_new=args.new_profile, region=region)
    print(f"[3/6] Profile ready\n")

    # ---- Step 4: rubric ----
    print("[4/6] Building personalized rubric...")
    rubric = generate_rubric(category, criteria, profile)
    rubric["category"] = category
    if not args.no_checkpoint:
        rubric = review_rubric(rubric)
    else:
        display_rubric(rubric)

    # ---- Step 5: research ----
    print("\n[5/6] Researching products...")
    reddit_threads = fetch_all_threads(args.query, limit=args.limit)
    print(f"      Reddit: {len(reddit_threads)} threads")

    review_pages = []
    if not args.no_reviews:
        review_pages = fetch_all_reviews(args.query, limit=args.reviews)
        print(f"      Reviews: {len(review_pages)} pages")

    if not reddit_threads and not review_pages:
        print("No sources fetched. Try a different query.")
        sys.exit(1)

    # ---- Step 5: parallel thread summarization + main aggregation ----
    print(f"\n[5/6] Summarizing threads in parallel...")
    from thread_summarizer import summarize_threads_parallel
    from llm_client import analyze_with_summaries
    thread_summaries = summarize_threads_parallel(reddit_threads, args.query)

    print(f"\n[5/6] Aggregating summaries + reviews via main analyzer...")
    analysis = analyze_with_summaries(args.query, thread_summaries, review_pages)
    products = analysis.get("products", [])
    materials = analysis.get("materials", [])
    summary = analysis.get("summary", "")
    print(f"[5/6] Found {len(products)} specific products + {len(materials)} categories\n")

    if not products:
        print("No specific products to score. Showing analysis only:")
        print(summary)
        sys.exit(0)

    # ---- Step 5.5: fill gaps in rubric using research signal ----
    from rubric import fill_criterion_gaps
    # Reconstruct sources for gap-filling using summaries
    sources = normalize_all(reddit_threads, review_pages)
    research_text = _build_research_text(analysis, sources)
    rubric = fill_criterion_gaps(rubric, category, profile, research_text)

    # Re-display the updated rubric if any changes were made
    if any("[inferred]" in c.get("rationale", "") for c in rubric["weighted_criteria"]):
        print("\n[rubric] updated with inferred weights:")
        display_rubric(rubric)

    # ---- Step 6: scoring ----
    print("[6/6] Scoring each product against your rubric...")
    scored = score_all_products(products, rubric, research_text)
    print(f"[6/6] Scoring complete\n")

    # ---- Step 6.5: targeted evidence enrichment (fill high-impact data gaps) ----
    try:
        from evidence_enricher import enrich_scores, ENABLE_TARGETED_FETCH
        if ENABLE_TARGETED_FETCH:
            print("[6/6] Filling high-impact data gaps via targeted search...")
            scored = enrich_scores(scored, rubric, region)
    except Exception as _e:
        print(f"[enrich] non-fatal: {_e}")

    # Show overall summary first — coerce dict→string defensively
    print(f"{'─'*72}")
    print("COMMUNITY CONSENSUS")
    print(f"{'─'*72}")
    from report import _coerce_to_string
    print(_coerce_to_string(summary))
    print()

    # Show materials briefly with example products so user knows what's in each category
    if materials:
        print(f"{'─'*72}")
        print("MATERIALS / CATEGORIES")
        print(f"{'─'*72}")
        # Defensive: filter out non-dict entries and entries without a name
        valid_materials = [
            m for m in materials
            if isinstance(m, dict) and m.get("name")
        ]
        for m in sorted(valid_materials, key=lambda x: x.get("mention_count", 0), reverse=True)[:5]:
            count = m.get("mention_count") or "?"
            print(f"  • {m['name']} — {count} mentions")
            examples = m.get("example_products") or []
            if examples:
                example_strs = [str(e) for e in examples[:4] if e]
                if example_strs:
                    print(f"    Examples: {', '.join(example_strs)}")
        print()

    # Show personalized ranking
    display_results(scored, top_n=5)

    # ---- v4 Feature: shopping links ----
    shopping_links_map = {}
    if args.shopping_links and scored:
        print(f"\n{'─'*72}")
        print("SHOPPING LINKS")
        print(f"{'─'*72}")
        from shopping_links import generate_links_for_product, is_affiliate_configured
        affiliate_note = " (with affiliate tags)" if is_affiliate_configured() else ""
        print(f"Generating buy links for top 5 products{affiliate_note}...\n")
        for p in scored[:5]:
            links = generate_links_for_product(p["name"], args.query, use_serper=False)
            shopping_links_map[p["name"]] = links
            print(f"{p['name']}:")
            for link in links:
                affiliate_tag = " (affiliate)" if link.get("is_affiliate") else ""
                print(f"  • {link['retailer']}{affiliate_tag}: {link['url']}")
            print()

    # ---- v4 Feature: detailed explanations ----
    explanations_map = {}
    if args.detailed and scored:
        print(f"\n{'─'*72}")
        print("DETAILED EXPLANATIONS")
        print(f"{'─'*72}")
        from agents import run_agent
        for p in scored[:3]:
            prompt = (
                f"In 2-3 sentences, explain why {p['name']} fits the user who has these priorities:\n"
                f"{profile.get('preferences_summary', '')}\n\n"
                f"Based on scores: {[(s['label'], s['score']) for s in p['scores'][:5]]}\n"
                f"Be specific. No marketing speak."
            )
            try:
                explanation = run_agent("explanation_writer", user_prompt=prompt).strip()
                explanations_map[p["name"]] = explanation
                print(f"\n{p['name']}:")
                print(f"  {explanation}")
            except Exception as e:
                print(f"[detailed] failed for {p['name']}: {e}")
        print()

    # ---- Checkpoint 2: re-weight + re-rank ----
    if not args.no_checkpoint:
        scored = _final_checkpoint(scored, rubric)

    # ---- v4 Feature: comparison mode ----
    if args.compare and scored:
        from compare import compare_products
        compare_products(scored, args.compare)

    # ---- v4 Feature: Markdown + HTML export ----
    if args.export:
        from report import export_reports
        md_path, html_path = export_reports(
            query=args.query,
            category=category,
            profile=profile,
            rubric=rubric,
            analysis=analysis,
            scored_products=scored,
            shopping_links=shopping_links_map,
            explanations=explanations_map,
        )
        print(f"\n{'─'*72}")
        print("REPORT EXPORTED")
        print(f"{'─'*72}")
        print(f"  Markdown: {md_path}")
        print(f"  HTML:     {html_path}")
        print(f"  Open the HTML in any browser to view nicely, or send the MD anywhere.")

    # ---- Save JSON ----
    if args.output:
        out = {
            "query": args.query,
            "run_at": datetime.utcnow().isoformat() + "Z",
            "category": category,
            "profile": profile,
            "rubric": rubric,
            "analysis": analysis,
            "scored_products": scored,
            "shopping_links": shopping_links_map,
            "explanations": explanations_map,
        }
        if args.save_raw:
            out["raw_reddit"] = reddit_threads
            out["raw_reviews"] = review_pages
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        print(f"\nSaved to {args.output}")


def _build_research_text(analysis: dict, sources: list[dict]) -> str:
    """Build a FULL research context for the scorer.

    Includes raw Reddit thread bodies + comments and review page content.
    This is what the scorer actually scans for product-specific evidence.
    """
    parts = []

    # Start with extracted insights (compact)
    parts.append(f"=== COMMUNITY CONSENSUS ===\n{analysis.get('summary', '')}\n")

    # Include compact product extracts (the analyzer's notes per product)
    parts.append("\n=== PRODUCT EXTRACTS ===")
    for p in analysis.get("products", []):
        parts.append(f"\n{p['name']}")
        if p.get("praise"):
            parts.append(f"  Praise: {', '.join(p['praise'][:3])}")
        if p.get("complaints"):
            comps = [f"{c.get('text', '')} [{c.get('confidence', '?')}]" for c in p["complaints"][:3]]
            parts.append(f"  Complaints: {'; '.join(comps)}")
        if p.get("representative_quote"):
            parts.append(f"  Quote: \"{p['representative_quote']}\"")

    # CRITICAL: include the actual raw source text so scorer has real evidence
    parts.append("\n\n=== RAW SOURCES (Reddit threads + review excerpts) ===")
    for s in sources:
        parts.append(f"\n--- {s['source_type'].upper()}: {s['source_name']} ---")
        parts.append(f"Title: {s.get('title', '')}")
        if s.get("body"):
            parts.append(f"Body: {s['body'][:2000]}")
        if s.get("discussions"):
            parts.append("Comments:")
            for d in s["discussions"][:20]:  # cap comments to keep prompt manageable
                parts.append(f"  - {d['text'][:600]}")

    return "\n".join(parts)


def _final_checkpoint(scored: list[dict], rubric: dict) -> list[dict]:
    """Let user adjust weights at end, re-rank with pure Python (no new LLM calls)."""
    while True:
        try:
            choice = input("\nAdjust rubric weights to re-rank? (yes/no) [no]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = "no"

        if choice not in {"yes", "y"}:
            break

        from rubric import edit_weights
        rubric = edit_weights(rubric)
        save_rubric(rubric.get("category", ""), rubric)
        scored = recompute_with_new_weights(scored, rubric)
        display_results(scored, top_n=5)

    return scored


if __name__ == "__main__":
    main()