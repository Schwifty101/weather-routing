"""Route ranking.

Order of preference (from the brief): fewest Severe miles, fewest High miles, lowest average
risk, shortest travel time. We add one criterion *above* those: miles of No Travel weather.
A route you may not drive is worse than one that is merely Severe, so it must rank last
however short it is.

Strict lexicographic comparison on raw floats would let 0.4 miles of Severe beat a route that is
two hours faster. Miles are only known to within the checkpoint spacing, so each criterion is
bucketed (5 mi, 0.05 risk, 5 min); routes in the same bucket count as tied and the next
criterion decides. That is how "balancing weather risk and travel time" is realised.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

TIE_MILES = 5.0
TIE_RISK = 0.05
TIE_SECONDS = 300.0


@dataclass(frozen=True)
class RouteMetrics:
    route_id: str
    name: str
    no_travel_miles: float
    severe_miles: float
    high_miles: float
    avg_risk: float  # distance-weighted mean of the 0-4 level
    duration_s: float


@dataclass(frozen=True)
class Recommendation:
    best_id: str
    ranking: list[str]  # best -> worst
    summary: str
    reasons: list[str]
    blocked: bool  # even the best route crosses No Travel weather


def _bucket(x: float, size: float) -> int:
    return math.floor(x / size + 0.5)


def sort_key(m: RouteMetrics) -> tuple:
    return (
        (1 if m.no_travel_miles > 0 else 0, _bucket(m.no_travel_miles, TIE_MILES)),
        _bucket(m.severe_miles, TIE_MILES),
        _bucket(m.high_miles, TIE_MILES),
        _bucket(m.avg_risk, TIE_RISK),
        _bucket(m.duration_s, TIE_SECONDS),
    )


def _fmt_miles(x: float) -> str:
    return f"{x:.0f} mi" if x >= 10 else f"{x:.1f} mi"


def _fmt_duration(seconds: float) -> str:
    minutes = round(seconds / 60)
    h, m = divmod(minutes, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


# (label, value getter, formatter) in the same order as sort_key
_CRITERIA = (
    ("No Travel miles", lambda m: m.no_travel_miles, _fmt_miles),
    ("Severe miles", lambda m: m.severe_miles, _fmt_miles),
    ("High miles", lambda m: m.high_miles, _fmt_miles),
    ("average risk", lambda m: m.avg_risk, lambda v: f"{v:.2f}"),
    ("travel time", lambda m: m.duration_s, _fmt_duration),
)


def rank(metrics: list[RouteMetrics]) -> list[RouteMetrics]:
    return sorted(metrics, key=lambda m: (sort_key(m), m.route_id))


def recommend(metrics: list[RouteMetrics]) -> Recommendation:
    ranked = rank(metrics)
    best = ranked[0]
    fastest = min(metrics, key=lambda m: m.duration_s)

    reasons: list[str] = []
    for other in ranked[1:]:
        kb, ko = sort_key(best), sort_key(other)
        idx = next((i for i in range(len(kb)) if kb[i] != ko[i]), None)
        if idx is None:
            reasons.append(f"{best.name} and {other.name} are equivalent on risk and travel time.")
        else:
            label, getter, fmt = _CRITERIA[idx]
            reasons.append(f"Beats {other.name} on {label}: {fmt(getter(best))} vs {fmt(getter(other))}.")

    if best.route_id != fastest.route_id:
        extra = round((best.duration_s - fastest.duration_s) / 60)
        reasons.append(f"Takes {extra} min longer than {fastest.name}, the fastest route.")

    blocked = best.no_travel_miles > 0
    if blocked:
        summary = (
            f"Every route crosses No Travel weather at this departure time. {best.name} has the "
            f"least ({_fmt_miles(best.no_travel_miles)}); consider departing at a different time."
        )
    elif best.severe_miles > 0:
        summary = f"{best.name} is the best option but still has {_fmt_miles(best.severe_miles)} of Severe weather."
    elif best.high_miles > 0:
        summary = f"{best.name} avoids Severe weather; {_fmt_miles(best.high_miles)} of High risk remain."
    else:
        summary = f"{best.name} stays clear of High and Severe weather."
    summary += f" Drive time {_fmt_duration(best.duration_s)}."

    return Recommendation(best.route_id, [m.route_id for m in ranked], summary, reasons, blocked)
