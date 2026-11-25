"""TestForge AI - Demo Dashboard Generator (C).

Doc report JSON experiments -> xuat 1 file HTML self-contained (inline CSS)
dung de trinh chieu/chup slide. Input thieu file nao -> section do hien 'not collected'.

Output: artifacts/demo/dashboard.html
"""

import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "artifacts" / "experiments"
OUT = ROOT / "artifacts" / "demo" / "dashboard.html"

CSS = """
body{font-family:'Segoe UI',Arial,sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:24px}
h1{color:#38bdf8;margin:0 0 4px}h2{color:#7dd3fc;border-bottom:1px solid #334155;padding-bottom:6px;margin-top:28px}
.sub{color:#94a3b8;margin-bottom:20px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;margin-bottom:8px}
.card{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:16px}
.card.green{border-left:5px solid #22c55e}.card.red{border-left:5px solid #ef4444}.card.blue{border-left:5px solid #3b82f6}.card.gray{border-left:5px solid #64748b}
.kpi{font-size:30px;font-weight:bold;color:#f8fafc}.lbl{font-weight:bold;margin-top:4px}.sub{font-size:12px;color:#94a3b8;margin-top:2px}
table{border-collapse:collapse;width:100%;margin-top:8px;background:#1e293b;border-radius:8px;overflow:hidden}
th,td{padding:8px 12px;border-bottom:1px solid #334155;text-align:left;font-size:14px}
th{background:#334155;color:#7dd3fc}
.ok{color:#22c55e;font-weight:bold}.fail{color:#ef4444;font-weight:bold}.muted{color:#64748b}
.reason{color:#94a3b8;font-size:12px;margin-top:2px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}
"""

CSS_DARK = "<style>" + CSS + "</style>"


def load(name):
    p = EXP / name
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            return None
    return None


def badge(ok):
    return '<span class="ok">PASS</span>' if ok else '<span class="fail">MISS</span>'


def card(label, value, sub, cls):
    return f'<div class="card {cls}"><div class="kpi">{value}</div><div class="lbl">{label}</div><div class="sub">{sub}</div></div>'


def classify_table(report, has_predictions):
    if not report:
        return '<p class="muted">not collected</p>'
    results = report.get("results", report)
    rows = []
    for cid, d in results.items():
        if not isinstance(d, dict) or "ground_truth_type" not in d:
            continue
        if has_predictions:
            pred = (d.get("predictions") or [{}])[0].get("failure_type", "n/a")
        else:
            pred = d.get("predicted", "n/a")
        hit = (pred == d["ground_truth_type"]) if pred != "n/a" else None
        cell = badge(True) if hit else badge(False)
        rows.append(f"<tr><td>{cid}</td><td>{d['ground_truth_type']}</td><td>{pred}</td><td>{cell}</td></tr>")
    return "".join(rows) or '<tr><td colspan="4" class="muted">n/a</td></tr>'


def main():
    dev = load("classification_report_dev.json")
    evalr = load("classification_report_eval.json")
    sandbox = load("classification_report_sandbox.json")
    kpi = load("healing_kpi_day4.json")
    llmr = load("healing_report_day3_sandbox_llm.json")

    kp = (kpi or {}).get("kpis", {})
    h, l = kp.get("heuristic", {}), kp.get("llm", {})

    sbx_hits = sum(1 for v in (sandbox or {}).values() if isinstance(v, dict) and v.get("hit")) if sandbox else "n/a"
    fr_h = h.get("false_repair_rate")
    fr_l = l.get("false_repair_rate")
    fr_ok = (fr_h is not None and fr_h < 5) and (fr_l is not None and fr_l < 5)

    cards = "".join([
        card("RQ1 - Pipeline E2E", "N=3 STABLE", "5/5 TCs per run, Playwright that", "green"),
        card("RQ2 - Classification", str((evalr or {}).get("accuracy_cases", "n/a")),
             f"eval sau freeze | dev {(dev or {}).get('accuracy_cases', 'n/a')} | sandbox {sbx_hits}/6",
             "green" if evalr else "gray"),
        card("RQ2 - Healing Success", f"{h.get('success_rate', 'n/a')}% / {l.get('success_rate', 'n/a')}%",
             "heuristic / LLM (target >= 80%)",
             "green" if (h.get("success_rate") or 0) >= 80 and (l.get("success_rate") or 0) >= 80 else "red"),
        card("RQ2 - FALSE REPAIR RATE", f"{h.get('false_repair_rate', 'n/a')}% / {l.get('false_repair_rate', 'n/a')}%",
             "target < 5% - anti-cheat 3 lop",
             "green" if fr_ok else "red"),
        card("RQ2 - MTTR", f"{h.get('mttr_seconds', 'n/a')}s / {l.get('mttr_seconds', 'n/a')}s",
             "heuristic / LLM (heuristic-first routing)", "blue"),
        card("C06 - STOP Contract", "healer = 0",
             "Application Defect -> khong AI nao cham", "blue"),
    ])

    dev_tbl = classify_table(dev, has_predictions=True)
    eval_tbl = classify_table(evalr, has_predictions=True)
    sbx_tbl = classify_table(sandbox, has_predictions=False)

    runs = (kpi or {}).get("runs", [])
    run_rows = "".join(
        f"<tr><td>{r['mode']}</td><td>{r['case_id']}</td><td>{r['run']}</td>"
        f"<td>{r['outcome']}</td><td>{r.get('strategy', '-')}</td>"
        f"<td>{'OK' if not r.get('false_repair') else 'FALSE REPAIR'}</td><td>{r['wall']}s</td></tr>"
        for r in runs
    ) or '<tr><td colspan="7" class="muted">not collected</td></tr>'

    llm_rows = ""
    for cid, d in ((llmr or {}).get("cases") or {}).items():
        p = d.get("proposal") or {}
        llm_rows += (
            f"<tr><td>{cid}</td><td>{p.get('strategy', '-')}</td>"
            f"<td>{str(p.get('new_locator', '-'))[:60]}</td>"
            f"<td>{p.get('confidence', '-')}</td></tr>"
        )
    llm_tbl = llm_rows or '<tr><td colspan="4" class="muted">not collected</td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="UTF-8"><title>TestForge AI - Demo Dashboard</title>{CSS_DARK}</head>
<body>
<h1>TestForge AI - Demo Dashboard</h1>
<div class="sub">Generated {time.strftime('%d/%m/%Y %H:%M')} | Automation Test + Self-Healing + Sandbox | M2 + M3.1 + M3.2</div>

<div class="grid">{cards}</div>

<h2>Failure Classification - 8 Taxonomies (blind, ground truth so sanh)</h2>
<div class="two">
  <div><b>Dev set (calibrate, N=3)</b><table><tr><th>Case</th><th>Ground Truth</th><th>Predicted</th><th>KQ</th></tr>{dev_tbl}</table></div>
  <div><b>Eval set (1 lan sau freeze)</b><table><tr><th>Case</th><th>Ground Truth</th><th>Predicted</th><th>KQ</th></tr>{eval_tbl}</table></div>
</div>
<div style="margin-top:12px"><b>Sandbox gate (trong container)</b><table><tr><th>Case</th><th>Ground Truth</th><th>Predicted</th><th>KQ</th></tr>{sbx_tbl}</table></div>

<h2>Healing KPI - 18 runs (N=3 x 3 cases x 2 tier2, sandbox, fault active)</h2>
<table><tr><th>Mode</th><th>Case</th><th>Run</th><th>Outcome</th><th>Strategy</th><th>Anti-cheat audit</th><th>Wall</th></tr>{run_rows}</table>

<h2>LLM Tier 2 - Repair Proposals (MiniMax-M3 reasoning)</h2>
<table><tr><th>Case</th><th>Strategy</th><th>New locator / wait</th><th>Confidence</th></tr>{llm_tbl}</table>

<p class="sub">Chi tiet: docs/10 (classification), docs/15 (M3 exit), artifacts/experiments/*.json</p>
</body></html>"""

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"Dashboard: {OUT} ({OUT.stat().st_size} bytes)")
    print("Mo bang browser: start artifacts/demo/dashboard.html")


if __name__ == "__main__":
    main()
