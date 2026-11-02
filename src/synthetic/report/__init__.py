"""The Fidelity and Privacy Report (FR7).

Imports are lazy so that ``synthetic.report.thresholds`` can be used by the
engine without creating an import cycle.
"""

from typing import Any

__all__ = ["build_report", "render_html", "summarize"]


def __getattr__(name: str) -> Any:
    if name in ("build_report", "summarize"):
        from synthetic.report import build

        return getattr(build, name)
    if name == "render_html":
        from synthetic.report.html import render_html

        return render_html
    raise AttributeError(name)
