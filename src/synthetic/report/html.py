"""Render the report as a single self-contained HTML page.

PDF export (PRD F4, ``?format=pdf``) is a TODO for the next milestone; the
HTML page prints cleanly to PDF from any browser in the meantime.
"""

from __future__ import annotations

from html import escape
from typing import Any

_COLORS = {"pass": "#137333", "warn": "#b06000", "fail": "#c5221f", "not_applicable": "#5f6368"}


def _badge(status: str) -> str:
    color = _COLORS.get(status, "#5f6368")
    label = status.replace("_", " ")
    return f'<span class="badge" style="background:{color}">{escape(label)}</span>'


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(f"<th>{escape(str(h))}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in row) + "</tr>" for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def render_html(report: dict[str, Any], title: str = "Fidelity and Privacy Report") -> str:
    """Return the report as an HTML string."""
    integ, fid, priv = report["integrity"], report["fidelity"], report["privacy"]
    sections = []
    sections.append(
        f"<h2>Integrity {_badge(integ['status'])}</h2>"
        f"<p>Foreign keys resolved: <b>{integ['fk_resolved_pct']:.2f}%</b>. "
        f"Constraint violations: <b>{integ['constraint_violations']['total']}</b>.</p>"
        + (_table(["Child", "Parent", "Non-null", "Resolved", "%"],
                  [[f["child"], f["parent"], f["non_null"], f["resolved"], f["resolved_pct"]]
                   for f in integ["foreign_keys"]]) if integ["foreign_keys"] else "")
    )
    col_rows = [[c["column"], c["type"], c["metric"], f"{c['similarity']:.3f}"] for c in fid["columns"]]
    fid_html = (f"<h2>Fidelity {_badge(fid['status'])}</h2>"
                f"<p>Score: <b>{fid['score']:.1f} / 100</b> ({escape(fid['mode'])} mode)."
                + (f" {escape(fid['note'])}" if fid.get("note") else "") + "</p>"
                + _table(["Column", "Type", "Metric", "Similarity"], col_rows))
    corr = fid.get("correlation") or {}
    if corr.get("applicable"):
        fid_html += (f"<p>Correlation similarity: <b>{corr['similarity']:.3f}</b> "
                     f"(largest difference {corr['max_abs_difference']:.3f}).</p>")
    if fid.get("relationships"):
        fid_html += "<h3>Children per parent</h3>" + _table(
            ["Relationship", "Parents", "Mean", "Median", "P90", "Max", "% with none"],
            [[r["relationship"], r["parents"], r["children_mean"], r["children_p50"], r["children_p90"],
              r["children_max"], r["parents_without_children_pct"]] for r in fid["relationships"]])
    sections.append(fid_html)
    if priv.get("applicable"):
        rows = [[c["name"], c["value"], c["status"], c["explanation"]] for c in priv["checks"]]
        sections.append(f"<h2>Privacy {_badge(priv['status'])}</h2>"
                        + _table(["Check", "Value", "Status", "What it means"], rows)
                        + (f"<p>{escape(priv['note'])}</p>" if priv.get("note") else ""))
    else:
        sections.append(f"<h2>Privacy {_badge('not_applicable')}</h2><p>{escape(priv.get('note', ''))}</p>")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{escape(title)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body {{ font: 15px/1.5 system-ui, sans-serif; max-width: 960px; margin: 2rem auto; padding: 0 1rem; color: #202124; }}
h1 {{ font-size: 1.6rem; }} h2 {{ margin-top: 2rem; font-size: 1.2rem; }}
.badge {{ color: #fff; border-radius: 4px; padding: 2px 8px; font-size: .8rem; vertical-align: middle; }}
table {{ border-collapse: collapse; width: 100%; margin: .5rem 0; font-size: .9rem; }}
th, td {{ border-bottom: 1px solid #dadce0; padding: 6px 8px; text-align: left; vertical-align: top; }}
.summary {{ background: #f1f3f4; padding: 1rem; border-radius: 6px; }}
.meta {{ color: #5f6368; font-size: .85rem; }}
</style></head><body>
<h1>{escape(title)} {_badge(report['overall']['status'])}</h1>
<p class="meta">Engine {escape(str(report['engine_version']))} · seed {report['seed']} ·
report v{escape(report['report_version'])}</p>
<p class="summary">{escape(report['summary'])}</p>
{''.join(sections)}
<p class="meta">PDF export is not available yet; use your browser's Print → Save as PDF.</p>
</body></html>"""
