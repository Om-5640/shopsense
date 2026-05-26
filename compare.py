"""
Head-to-head product comparison.

Takes 2-3 product names from a previous scored run and displays them side-by-side.
Useful when the user is choosing between specific top picks.

Pure logic - no LLM calls needed since we already have scored data.
"""


def _find_product(scored_products: list[dict], name: str) -> dict | None:
    """Case-insensitive partial match on product name."""
    name_lower = name.lower().strip()
    # Try exact match first
    for p in scored_products:
        if p.get("name", "").lower() == name_lower:
            return p
    # Try contains match
    for p in scored_products:
        if name_lower in p.get("name", "").lower():
            return p
    # Try reverse: product name contained in query
    for p in scored_products:
        if p.get("name", "").lower() in name_lower:
            return p
    return None


def compare_products(scored_products: list[dict], names: list[str]) -> None:
    """
    Display side-by-side comparison of 2-3 named products.
    Prints a clean comparison table to stdout.
    """
    if len(names) < 2:
        print("[compare] need at least 2 product names")
        return
    if len(names) > 3:
        print("[compare] showing first 3 products only")
        names = names[:3]

    # Find each product
    products = []
    for name in names:
        match = _find_product(scored_products, name)
        if match is None:
            print(f"[compare] couldn't find product matching: '{name}'")
            print(f"[compare] available: {[p.get('name') for p in scored_products[:10]]}")
            return
        products.append(match)

    # Display header
    print(f"\n{'='*88}")
    print(f"  HEAD-TO-HEAD COMPARISON")
    print(f"{'='*88}\n")

    # Names + overall score
    col_width = 24
    name_row = "Criterion".ljust(20)
    for p in products:
        name_row += p["name"][:col_width - 1].ljust(col_width)
    print(name_row)
    print("-" * (20 + col_width * len(products)))

    # Overall score row
    overall = "Overall Score".ljust(20)
    for p in products:
        score_str = f"{p['weighted_total']:.0f}/{p['max_possible']:.0f} ({p['percentage']:.0f}%)"
        overall += score_str.ljust(col_width)
    print(overall)

    # Signal strength row
    signal = "Signal".ljust(20)
    for p in products:
        signal += p.get("signal_strength", "?").upper().ljust(col_width)
    print(signal)

    print("-" * (20 + col_width * len(products)))

    # Per-criterion comparison
    # Build a unified criterion list (assume all products have same rubric)
    if products and products[0].get("scores"):
        for s_first in products[0]["scores"]:
            crit_name = s_first["criterion"]
            label = s_first["label"][:19]
            weight = s_first["weight"]
            row = f"{label} (×{weight})".ljust(20)
            for p in products:
                p_score = next((s for s in p["scores"] if s["criterion"] == crit_name), None)
                if p_score:
                    cell = f"{p_score['score']:.0f}/10  ({p_score['weighted_contribution']:.0f} pts)"
                else:
                    cell = "-"
                row += cell.ljust(col_width)
            print(row)

    print("-" * (20 + col_width * len(products)))

    # Strongest evidence per product (one quote each)
    print("\nKEY EVIDENCE PER PRODUCT:")
    for p in products:
        print(f"\n  {p['name']}:")
        # Top-scoring criterion's evidence
        if p.get("scores"):
            top_score = max(p["scores"], key=lambda s: s["weighted_contribution"])
            print(f"    Strongest: {top_score['label']} ({top_score['score']:.0f}/10)")
            print(f"    Evidence: {top_score['evidence']}")
            # Weakest criterion's evidence
            weak = min(p["scores"], key=lambda s: s["score"])
            if weak["score"] <= 5:
                print(f"    Weakest: {weak['label']} ({weak['score']:.0f}/10)")
                print(f"    Evidence: {weak['evidence']}")

    # Verdict
    print(f"\n{'='*88}")
    print("  VERDICT")
    print(f"{'='*88}")
    winner = max(products, key=lambda p: p["weighted_total"])
    print(f"\n  Best fit for your priorities: {winner['name']}")
    print(f"  Score: {winner['weighted_total']:.0f} / {winner['max_possible']:.0f} "
          f"({winner['percentage']:.0f}%)")

    # Why it wins over the others
    if len(products) > 1:
        print(f"\n  Where it wins:")
        for p in products:
            if p is winner:
                continue
            wins = []
            for w_score in winner.get("scores", []):
                other_score = next(
                    (s for s in p.get("scores", []) if s["criterion"] == w_score["criterion"]),
                    None,
                )
                if other_score and w_score["score"] > other_score["score"] + 1:
                    diff = w_score["score"] - other_score["score"]
                    wins.append((w_score["label"], diff, w_score["weight"]))
            # Sort by weight × diff to find most impactful wins
            wins.sort(key=lambda w: w[1] * w[2], reverse=True)
            if wins:
                print(f"    vs {p['name']}:")
                for label, diff, weight in wins[:3]:
                    print(f"      • {label}: +{diff:.0f} points (weighted ×{weight})")
    print()