from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .store import REPORTS_DIR, ensure_dirs


def _status_badge(status: str) -> str:
    colors = {
        "PASS": "#16a34a",
        "WARNING": "#d97706",
        "FAIL": "#dc2626",
        "NOT_IMPLEMENTED": "#6b7280",
        "NOT_RUN": "#6b7280",
        "SKIPPED": "#6b7280",
        "EXPERIMENTAL": "#7c3aed",
        "SUPPORTED_WITH_OPTIMIZATION": "#0891b2",
        "FULLY_SUPPORTED": "#16a34a",
        "NOT_RECOMMENDED_ON_THIS_HARDWARE": "#dc2626",
    }
    c = colors.get(status, "#475569")
    return f'<span style="display:inline-block;padding:2px 8px;border-radius:999px;background:{c};color:#fff;font-size:12px;font-weight:600">{html.escape(status)}</span>'


def _pre(obj: Any) -> str:
    return "<pre style='white-space:pre-wrap;background:#0f172a;color:#e2e8f0;padding:12px;border-radius:8px;overflow:auto'>" + html.escape(json.dumps(obj, indent=2, default=str)) + "</pre>"


def generate_reports(run: dict[str, Any]) -> dict[str, str]:
    ensure_dirs()
    run_id = run.get("id", "unknown")
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"benchmark_{run_id}_{ts}"
    json_path = REPORTS_DIR / f"{base}.json"
    html_path = REPORTS_DIR / f"{base}.html"
    json_path.write_text(json.dumps(run, indent=2, default=str), encoding="utf-8")

    env = run.get("environment") or {}
    summary = run.get("summary") or {}
    tests = run.get("tests") or []
    methodology = run.get("methodology") or {}
    sections = run.get("sections") or {}

    def table(rows: list[list[str]], headers: list[str] | None = None) -> str:
        h = "".join(f"<th style='text-align:left;padding:8px;border-bottom:1px solid #334155'>{html.escape(x)}</th>" for x in (headers or []))
        head = f"<thead><tr>{h}</tr></thead>" if h else ""
        body = "".join("<tr>" + "".join(f"<td style='padding:8px;border-bottom:1px solid #1e293b;vertical-align:top'>{c}</td>" for c in r) + "</tr>" for r in rows)
        return f"<table style='width:100%;border-collapse:collapse;font-size:13px'>{head}<tbody>{body}</tbody></table>"

    test_rows = []
    for t in tests:
        test_rows.append([
            html.escape(str(t.get("id", ""))),
            html.escape(str(t.get("engine", ""))),
            html.escape(str(t.get("name", ""))),
            _status_badge(str(t.get("status", ""))),
            html.escape(str(t.get("duration_sec", t.get("total_time_sec", "")))),
            html.escape(str(t.get("peak_app_rss_mb", ""))),
            html.escape(str(t.get("notes", ""))[:300]),
        ])

    classification = sections.get("hardware_capability_classification") or run.get("classification") or []
    class_rows = [[html.escape(str(c.get("engine",""))), html.escape(str(c.get("workload",""))), _status_badge(str(c.get("status",""))), html.escape(str(c.get("notes","")))] for c in classification]

    html_doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Benchmark Report {html.escape(run_id)}</title>
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#020617;color:#e2e8f0;margin:0;padding:24px;line-height:1.5}}
.card{{background:#0b1220;border:1px solid #1e293b;border-radius:12px;padding:16px;margin:14px 0}}
h1,h2,h3{{margin:0 0 10px 0}} h1{{font-size:24px}} h2{{font-size:18px;color:#93c5fd}} h3{{font-size:15px;color:#cbd5e1}}
.muted{{color:#94a3b8}} .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}}
.kv{{background:#0f172a;border:1px solid #1e293b;border-radius:8px;padding:10px}} .k{{font-size:11px;color:#94a3b8;text-transform:uppercase}} .v{{font-size:14px;margin-top:2px}}
</style></head><body>
<h1>M2 Hardware Benchmark Report</h1>
<div class="muted">Run ID: {html.escape(str(run_id))} · Generated: {html.escape(ts)} · Suite: {html.escape(str(run.get('suite','')))} · Status: {_status_badge(str(run.get('status','')))}</div>

<div class="card"><h2>1. Hardware Configuration</h2>{_pre(env.get('hardware'))}</div>
<div class="card"><h2>2. Software and Model Versions</h2>{_pre(env.get('software'))}<h3>Config / Models / FFmpeg / Acceleration</h3>{_pre({'config': env.get('config'), 'disk_at_capture': env.get('disk')})}</div>
<div class="card"><h2>3. Test Methodology</h2>{_pre(methodology)}</div>
<div class="card"><h2>Summary</h2>{_pre(summary)}</div>
<div class="card"><h2>4-8. Results (AI Auto-Clip, Transcription, Highlight, Export, AI Video Creator)</h2>
{table(test_rows, ['Test ID','Engine','Name','Status','Time (s)','Peak App RSS (MB)','Notes']) if test_rows else '<p class="muted">No test rows recorded.</p>'}
<h3>AI Auto-Clip Results</h3>{_pre(sections.get('auto_clip_results'))}
<h3>Transcription Accuracy</h3>{_pre(sections.get('transcription_accuracy'))}
<h3>Highlight Quality</h3>{_pre(sections.get('highlight_quality'))}
<h3>Export Quality</h3>{_pre(sections.get('export_quality'))}
<h3>AI Video Creator Results</h3>{_pre(sections.get('video_creator_results'))}
</div>
<div class="card"><h2>9. Memory Performance</h2>{_pre(sections.get('memory_performance') or summary.get('memory'))}</div>
<div class="card"><h2>10. Stability Results</h2>{_pre(sections.get('stability_results'))}</div>
<div class="card"><h2>11. Bottleneck Analysis</h2>{_pre(sections.get('bottleneck_analysis'))}</div>
<div class="card"><h2>12. Optimization Recommendations</h2>{_pre(sections.get('optimization_recommendations'))}</div>
<div class="card"><h2>13. Failed Tests</h2>{_pre(sections.get('failed_tests') or [t for t in tests if t.get('status') == 'FAIL'])}</div>
<div class="card"><h2>14. Known Limitations</h2>{_pre(sections.get('known_limitations') or run.get('limitations'))}</div>
<div class="card"><h2>15. Final Hardware Capability Assessment</h2>
{table(class_rows, ['Engine','Workload','Classification','Notes']) if class_rows else '<p class="muted">No classifications recorded.</p>'}
{_pre(sections.get('final_assessment'))}
</div>
<div class="card"><h2>Measurement Sources & Raw Samples (excerpt)</h2><p class="muted">Full run JSON contains all samples, logs references and test identifiers.</p>{_pre({'measurement_sources': summary.get('measurement_sources'), 'sample_count': len(run.get('samples') or [])})}</div>
</body></html>"""
    html_path.write_text(html_doc, encoding="utf-8")
    return {"json": str(json_path), "html": str(html_path)}
