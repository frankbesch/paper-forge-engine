"""Console figures: three svgcharts figures from the built payload.

1. Captures per ISO week (`added`), last 10 weeks.
2. Route funnel: captured -> Read complete -> Understand complete -> Analyze complete -> assessed -> disposition.
3. Stage outcomes per pipeline stage (complete / in progress / not started / skipped).

svgcharts is imported by path from a Quoin checkout named by $QUOIN_ROOT (see quoin.py); without
it the strip is left out, so the console never depends on it.
"""

from __future__ import annotations

import collections
import datetime as dt
import sys

from pf_lib.load import STAGES
from pf_lib.quoin import quoin_root

STATUS_ORDER = ("complete", "in_progress", "not_started")  # skipped = route decision, reported in the subtitle
WIDTH = 430  # one third of the 1420 px shell minus card padding
STATUS_LABEL = {"complete": "complete", "in_progress": "in progress", "not_started": "not started", "skipped": "skipped"}


def _svgcharts():
    if quoin_root() is None:
        raise ImportError("QUOIN_ROOT is not set; figures are left out")
    scripts = quoin_root() / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        import svgcharts  # type: ignore
        return svgcharts
    finally:
        sys.path.remove(str(scripts))


def _iso_week(day: str) -> str:
    y, w, _ = dt.date.fromisoformat(day).isocalendar()
    return f"{y}-W{w:02d}"


def _last_weeks(as_of: str, n: int) -> list[str]:
    d = dt.date.fromisoformat(as_of)
    monday = d - dt.timedelta(days=d.weekday())
    return [_iso_week((monday - dt.timedelta(weeks=i)).isoformat()) for i in range(n - 1, -1, -1)]


def captures_figure(sc, papers: list[dict], as_of: str, weeks: int = 10) -> str:
    counts = collections.Counter(_iso_week(p["added"]) for p in papers if p.get("added"))
    wk = _last_weeks(as_of, weeks)
    vals = [counts.get(w, 0) for w in wk]
    total = sum(vals)
    return sc.figure(
        sc.bar(["W" + w.split("-W")[1] for w in wk], vals, f"Captures per ISO week, last {weeks} weeks",
               "Count of items by the ISO week of their `added` date.", orient="v", labels="max", width=WIDTH,
               subtitle=f"{len(papers)} items in the library; weeks start Monday"),
        f"Reading: {total} of {len(papers)} items were captured in the last {weeks} weeks; "
        "intake arrives in bursts around source sweeps, not evenly.",
        [["ISO week", "captures"]] + [[w, str(counts.get(w, 0))] for w in wk], summary="week table")


def funnel_figure(sc, papers: list[dict]) -> str:
    def done(p, stage):
        return (p.get("statuses") or {}).get(stage) == "complete"
    steps = [
        ("captured", len(papers)),
        ("Read complete", sum(done(p, "read") for p in papers)),
        ("Understand complete", sum(done(p, "understand") for p in papers)),
        ("Analyze complete", sum(done(p, "analyze") for p in papers)),
        ("assessed", sum(p.get("assessmentStatus") == "assessed" for p in papers)),
        ("disposition set", sum(bool(p.get("disposition")) for p in papers)),
    ]
    names = [s for s, _ in steps]
    vals = [v for _, v in steps]
    route_complete = sum(p.get("lifecycle") == "route_complete" for p in papers)
    return sc.figure(
        sc.bar(names, vals, "Route funnel: from capture to disposition",
               "Items that reached each stage; Capture-route items complete at Read by design.",
               orient="h", labels="all", width=WIDTH, subtitle=f"{route_complete} items route_complete"),
        f"Reading: {vals[1]} of {vals[0]} items have a complete Read, {vals[3]} a complete Analyze, "
        f"and {vals[5]} carry a disposition; the Capture route closes at Read, so the drop after Read is the design, not debt.",
        [["step", "items"]] + [[s, str(v)] for s, v in steps], summary="funnel table")


def stages_figure(sc, papers: list[dict]) -> str:
    keys = [k for k, _, _ in STAGES]
    labels = [lbl for _, lbl, _ in STAGES]
    series = {STATUS_LABEL[s]: [sum((p.get("statuses") or {}).get(k) == s for p in papers) for k in keys]
              for s in STATUS_ORDER}
    open_work = sum(series["in progress"]) + sum(series["not started"])
    skipped = sum((p.get("statuses") or {}).get(k) == "skipped" for p in papers for k in keys)
    return sc.figure(
        sc.stacked_bar(labels, series, "Stage outcomes across the pipeline",
                       "Per stage: items complete, in progress, or not started; slots skipped by route are excluded.",
                       orient="v", width=WIDTH,
                       subtitle=f"{len(papers)} items × {len(keys)} stages; {skipped} slots skipped by route"),
        f"Reading: {open_work} stage slots are open (in progress or not started) against {sum(series['complete'])} complete; "
        "open work sits in Understand and Analyze.",
        [["stage"] + list(series)] + [[lbl] + [str(series[s][i]) for s in series] for i, lbl in enumerate(labels)],
        summary="stage table")


def figures_html(papers: list[dict], as_of: str) -> str:
    try:
        sc = _svgcharts()
    except Exception as error:  # noqa: BLE001
        if quoin_root() is not None:
            print(f"figures: svgcharts unavailable ({error}); figure strip omitted", file=sys.stderr)
        return ""
    figs = [captures_figure(sc, papers, as_of), funnel_figure(sc, papers), stages_figure(sc, papers)]
    return ('<section class="figure-strip" aria-label="Library analytics">'
            '<header class="queue-head"><h3>Library analytics</h3><span>Generated at build</span></header>'
            '<div class="figure-grid">' + "".join(figs) + "</div></section>")
