"""
HTML Intelligence Dashboard.

Generates a self-contained HTML report with:
  - Intelligence Index gauge (large number + letter grade)
  - Radar chart of all metric scores
  - Pass/fail metric table
  - Historical trend line (if history available)
  - Regression alerts
  - Full failure list
"""

from __future__ import annotations
import json
from pathlib import Path
from evals.runner import EvalRunResult
from evals.history import EvalHistory
from evals.config import REPORT_DIR, INDEX_WEIGHTS


def write_html_report(result: EvalRunResult, path: str | None = None) -> str:
    out_dir = Path(path or REPORT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = out_dir / f"eval_{result.run_id}.html"

    history = EvalHistory()
    trend = history.trend_data(last_n=20)

    html = _render_html(result, trend)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"  HTML report: {filename}")
    return str(filename)


def _render_html(result: EvalRunResult, trend: dict) -> str:
    idx = result.intelligence_index
    grade = result.index_breakdown.get("grade", "?")
    components = result.index_breakdown.get("components", {})

    # Metric data for radar chart
    metric_labels = list(components.keys())
    metric_scores = [components[k]["score"] for k in metric_labels]
    metric_passed = [components[k]["passed"] for k in metric_labels]

    # Colour the index number
    if idx >= 80:
        idx_color = "#34d399"  # emerald
    elif idx >= 65:
        idx_color = "#fbbf24"  # amber
    else:
        idx_color = "#f87171"  # red

    # Regression section HTML
    regression = result.regression_report
    regression_html = ""
    if regression.get("regressions"):
        rows = "".join(
            f'<tr class="reg-bad"><td>{r["metric"]}</td>'
            f'<td>{r["baseline"]:.1f}</td><td>{r["current"]:.1f}</td>'
            f'<td>{r["delta"]:+.1f}</td></tr>'
            for r in regression["regressions"]
        )
        regression_html = f"""
        <div class="alert alert-danger">
          <h3>⚠ Regressions vs {regression.get("baseline_commit", "?")}</h3>
          <table class="reg-table"><tr><th>Metric</th><th>Before</th><th>After</th><th>Δ</th></tr>
          {rows}</table>
        </div>"""
    elif regression.get("improvements"):
        rows = "".join(
            f'<tr class="reg-good"><td>{r["metric"]}</td>'
            f'<td>{r["baseline"]:.1f}</td><td>{r["current"]:.1f}</td>'
            f'<td>{r["delta"]:+.1f}</td></tr>'
            for r in regression["improvements"]
        )
        regression_html = f"""
        <div class="alert alert-success">
          <h3>↑ Improvements vs {regression.get("baseline_commit", "?")}</h3>
          <table class="reg-table"><tr><th>Metric</th><th>Before</th><th>After</th><th>Δ</th></tr>
          {rows}</table>
        </div>"""

    # Metric table rows
    metric_rows = ""
    for k, d in sorted(components.items(), key=lambda x: -x[1]["weight"]):
        status_cls = "pass" if d["passed"] else "fail"
        status_label = "✓" if d["passed"] else "✗"
        bar_pct = d["score"]
        metric_rows += f"""
        <tr class="metric-row {status_cls}">
          <td>{k.replace("_", " ").title()}</td>
          <td>
            <div class="score-bar-wrap">
              <div class="score-bar" style="width:{bar_pct}%"></div>
              <span class="score-label">{d['score']:.1f}</span>
            </div>
          </td>
          <td>{d['grade']}</td>
          <td class="status-cell {status_cls}">{status_label}</td>
        </tr>"""

    # Failures section
    failures_html = ""
    for metric, metric_result in result.metric_results.items():
        if metric_result.failures:
            items = "".join(f"<li>{f}</li>" for f in metric_result.failures[:10])
            failures_html += f'<div class="failure-group"><h4>{metric}</h4><ul>{items}</ul></div>'

    # Trend chart data
    trend_labels = json.dumps(trend.get("timestamps", []))
    trend_data = json.dumps(trend.get("indices", []))
    trend_commits = json.dumps(trend.get("commits", []))

    # Radar chart data
    radar_labels = json.dumps(metric_labels)
    radar_scores = json.dumps(metric_scores)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ShopSense Intelligence Report — {result.run_id}</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <style>
    :root {{
      --bg: #0d0d10; --surface: #18181b; --border: rgba(255,255,255,.08);
      --text: #fafafa; --muted: #71717a; --violet: #8b5cf6; --emerald: #34d399;
      --amber: #fbbf24; --red: #f87171;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: var(--bg); color: var(--text); font-family: system-ui, sans-serif;
            font-size: 14px; line-height: 1.6; padding: 2rem; }}
    h1 {{ font-size: 1.4rem; font-weight: 600; margin-bottom: 0.25rem; }}
    h2 {{ font-size: 1.1rem; font-weight: 600; color: var(--muted); margin: 1.5rem 0 0.75rem; }}
    h3 {{ font-size: 0.95rem; font-weight: 600; margin-bottom: 0.5rem; }}
    h4 {{ font-size: 0.85rem; color: var(--muted); margin-bottom: 0.25rem; }}
    .meta {{ color: var(--muted); font-size: 0.8rem; margin-bottom: 2rem; }}
    .grid {{ display: grid; gap: 1.5rem; }}
    .grid-2 {{ grid-template-columns: 1fr 1fr; }}
    .card {{ background: var(--surface); border: 1px solid var(--border);
             border-radius: 12px; padding: 1.25rem; }}

    /* Index hero */
    .index-hero {{ text-align: center; padding: 2rem; }}
    .index-number {{ font-size: 4.5rem; font-weight: 800; color: {idx_color}; line-height: 1; }}
    .index-label {{ font-size: 0.85rem; color: var(--muted); margin-top: 0.25rem; }}
    .grade-badge {{
      display: inline-block; font-size: 1.5rem; font-weight: 700;
      background: {idx_color}22; color: {idx_color}; border-radius: 8px;
      padding: 0.25rem 0.75rem; margin-top: 0.5rem;
    }}
    .meta-strip {{ font-size: 0.75rem; color: var(--muted); margin-top: 0.75rem; }}

    /* Metric table */
    table.metrics {{ width: 100%; border-collapse: collapse; }}
    table.metrics th {{ text-align: left; padding: 0.5rem 0.75rem; color: var(--muted);
                        font-size: 0.75rem; text-transform: uppercase; letter-spacing: .04em;
                        border-bottom: 1px solid var(--border); }}
    table.metrics td {{ padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border); }}
    .metric-row.pass {{ border-left: 3px solid var(--emerald); }}
    .metric-row.fail {{ border-left: 3px solid var(--red); }}
    .status-cell.pass {{ color: var(--emerald); font-weight: 700; }}
    .status-cell.fail {{ color: var(--red); font-weight: 700; }}
    .score-bar-wrap {{ position: relative; height: 20px; background: rgba(255,255,255,.06);
                       border-radius: 4px; overflow: hidden; }}
    .score-bar {{ height: 100%; background: var(--violet); opacity: .7; border-radius: 4px; }}
    .score-label {{ position: absolute; right: 6px; top: 2px; font-size: 0.75rem; font-mono: monospace; }}

    /* Alerts */
    .alert {{ border-radius: 10px; padding: 1rem 1.25rem; margin: 1rem 0; }}
    .alert-danger {{ background: rgba(248,113,113,.07); border: 1px solid rgba(248,113,113,.25); }}
    .alert-success {{ background: rgba(52,211,153,.07); border: 1px solid rgba(52,211,153,.25); }}
    .alert h3 {{ font-size: 0.9rem; margin-bottom: 0.5rem; }}
    table.reg-table {{ width: 100%; border-collapse: collapse; font-size: 0.8rem; }}
    table.reg-table th, table.reg-table td {{ padding: 0.3rem 0.5rem; text-align: left; }}
    .reg-bad {{ color: var(--red); }}
    .reg-good {{ color: var(--emerald); }}

    /* Failures */
    .failure-group {{ margin-bottom: 1rem; }}
    .failure-group ul {{ padding-left: 1.25rem; color: var(--muted); font-size: 0.8rem; }}
    .failure-group li {{ margin-bottom: 0.2rem; }}

    canvas {{ max-height: 300px; }}

    @media (max-width: 768px) {{ .grid-2 {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <h1>ShopSense Intelligence Report</h1>
  <p class="meta">Run {result.run_id} &nbsp;•&nbsp; {result.timestamp[:19].replace("T", " ")} UTC
     &nbsp;•&nbsp; commit <code>{result.commit}</code> ({result.branch})
     &nbsp;•&nbsp; mode: {result.mode} &nbsp;•&nbsp; {result.elapsed_s}s
  </p>

  {regression_html}

  <div class="grid grid-2">
    <div class="card index-hero">
      <div class="index-number">{idx:.1f}</div>
      <div class="index-label">Intelligence Index / 100</div>
      <div class="grade-badge">{grade}</div>
      <div class="meta-strip">
        {result.scenario_count} scenarios &nbsp;•&nbsp; {result.pass_rate}% pass rate
      </div>
    </div>

    <div class="card">
      <h2>Metric Radar</h2>
      <canvas id="radarChart"></canvas>
    </div>
  </div>

  <h2>Metric Breakdown</h2>
  <div class="card">
    <table class="metrics">
      <thead><tr><th>Metric</th><th>Score</th><th>Grade</th><th>Status</th></tr></thead>
      <tbody>{metric_rows}</tbody>
    </table>
  </div>

  <h2>Intelligence Trend</h2>
  <div class="card">
    <canvas id="trendChart"></canvas>
  </div>

  {f'<h2>Failures</h2><div class="card">{failures_html}</div>' if failures_html else ''}

  <script>
    // Radar chart
    new Chart(document.getElementById("radarChart"), {{
      type: "radar",
      data: {{
        labels: {radar_labels},
        datasets: [{{
          label: "Score",
          data: {radar_scores},
          backgroundColor: "rgba(139,92,246,.15)",
          borderColor: "#8b5cf6",
          pointBackgroundColor: "#8b5cf6",
          borderWidth: 2,
        }}]
      }},
      options: {{
        scales: {{ r: {{
          min: 0, max: 100,
          ticks: {{ color: "#71717a", stepSize: 25 }},
          grid: {{ color: "rgba(255,255,255,.08)" }},
          pointLabels: {{ color: "#a1a1aa", font: {{ size: 10 }} }}
        }} }},
        plugins: {{ legend: {{ display: false }} }},
      }}
    }});

    // Trend chart
    const trendLabels = {trend_labels};
    const trendData = {trend_data};
    const trendCommits = {trend_commits};

    if (trendData.length > 1) {{
      new Chart(document.getElementById("trendChart"), {{
        type: "line",
        data: {{
          labels: trendLabels,
          datasets: [{{
            label: "Intelligence Index",
            data: trendData,
            borderColor: "#8b5cf6",
            backgroundColor: "rgba(139,92,246,.1)",
            pointBackgroundColor: "#8b5cf6",
            tension: 0.3,
            fill: true,
          }}]
        }},
        options: {{
          scales: {{
            y: {{ min: 0, max: 100, grid: {{ color: "rgba(255,255,255,.06)" }},
                  ticks: {{ color: "#71717a" }} }},
            x: {{ grid: {{ color: "rgba(255,255,255,.04)" }},
                  ticks: {{ color: "#71717a", maxRotation: 0 }} }},
          }},
          plugins: {{
            legend: {{ display: false }},
            tooltip: {{
              callbacks: {{
                afterTitle: (items) => "commit: " + (trendCommits[items[0].dataIndex] || "?"),
              }}
            }}
          }},
        }}
      }});
    }} else {{
      document.getElementById("trendChart").insertAdjacentHTML(
        "afterend", '<p style="color:#52525b;font-size:.8rem;text-align:center">Run more evals to see trend.</p>'
      );
    }}
  </script>
</body>
</html>"""
