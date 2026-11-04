"""Weather risk classification.

This module is the single source of truth for the thresholds and load rules in the brief.
It is pure (no I/O) so it can be tested exhaustively.

Boundary convention
-------------------
The brief's ranges touch (e.g. rain "0.10-0.25" Moderate and "0.25-0.50" High). We resolve that
as: a value on a shared boundary belongs to the *higher* band, i.e. lower bounds are inclusive.
The two No Travel cutoffs follow the brief literally: wind is ">= 55" (inclusive) while rain
and snow are "> 1.00" / "> 3.0" (exclusive), so rain of exactly 1.00 in/hr is Severe.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class Risk(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    SEVERE = 3
    NO_TRAVEL = 4

    @property
    def label(self) -> str:
        return _LABELS[self]

    @property
    def key(self) -> str:
        return _KEYS[self]


_LABELS = {
    Risk.LOW: "Low",
    Risk.MODERATE: "Moderate",
    Risk.HIGH: "High",
    Risk.SEVERE: "Severe",
    Risk.NO_TRAVEL: "No Travel",
}
_KEYS = {
    Risk.LOW: "low",
    Risk.MODERATE: "moderate",
    Risk.HIGH: "high",
    Risk.SEVERE: "severe",
    Risk.NO_TRAVEL: "no_travel",
}
LEVEL_KEYS = tuple(_KEYS[r] for r in Risk)


@dataclass(frozen=True)
class Scale:
    unit: str
    moderate: float  # lower bound (inclusive) of each band
    high: float
    severe: float
    no_travel: float
    no_travel_inclusive: bool


WIND = Scale("mph", moderate=25, high=35, severe=45, no_travel=55, no_travel_inclusive=True)
RAIN = Scale("in/hr", moderate=0.10, high=0.25, severe=0.50, no_travel=1.00, no_travel_inclusive=False)
SNOW = Scale("in/hr", moderate=0.5, high=1.0, severe=2.0, no_travel=3.0, no_travel_inclusive=False)

# Load rules (weights in lb). Ranges are the wind bands from the brief: 35-44 and 45-54 mph.
WIND_NO_TRAVEL_ANY_LOAD = 55
WIND_NO_TRAVEL_BAND = (45, 55)
WIND_NO_TRAVEL_MIN_LOAD = 30_000  # strictly greater than
WIND_SEVERE_BAND = (35, 45)
WIND_SEVERE_MIN_LOAD = 40_000  # strictly greater than

_ROUND = 3  # absorbs float noise from interpolation (0.2499999 -> 0.25)


def classify(value: float, scale: Scale) -> Risk:
    v = round(value, _ROUND)
    if (v >= scale.no_travel) if scale.no_travel_inclusive else (v > scale.no_travel):
        return Risk.NO_TRAVEL
    if v >= scale.severe:
        return Risk.SEVERE
    if v >= scale.high:
        return Risk.HIGH
    if v >= scale.moderate:
        return Risk.MODERATE
    return Risk.LOW


@dataclass(frozen=True)
class Assessment:
    level: Risk
    wind: Risk  # wind level *after* load rules
    rain: Risk
    snow: Risk
    load_rule: str | None  # set when a load rule raised the wind level
    drivers: tuple[str, ...]  # conditions sitting at the overall level (empty when Low)


def assess(wind_mph: float, rain_in_hr: float, snow_in_hr: float, load_weight_lb: float) -> Assessment:
    """Classify conditions at one checkpoint for a given load."""
    wind_level = classify(wind_mph, WIND)
    wind_after_load = wind_level
    load_rule: str | None = None

    w = round(wind_mph, _ROUND)
    if WIND_NO_TRAVEL_BAND[0] <= w < WIND_NO_TRAVEL_BAND[1] and load_weight_lb > WIND_NO_TRAVEL_MIN_LOAD:
        wind_after_load = max(wind_after_load, Risk.NO_TRAVEL)
    elif WIND_SEVERE_BAND[0] <= w < WIND_SEVERE_BAND[1] and load_weight_lb > WIND_SEVERE_MIN_LOAD:
        wind_after_load = max(wind_after_load, Risk.SEVERE)

    if wind_after_load > wind_level:
        load_rule = (
            f"wind {wind_mph:.0f} mph with a {load_weight_lb:,.0f} lb load "
            f"is {wind_after_load.label} (load rule)"
        )

    rain_level = classify(rain_in_hr, RAIN)
    snow_level = classify(snow_in_hr, SNOW)
    level = max(wind_after_load, rain_level, snow_level)
    drivers: tuple[str, ...] = ()
    if level > Risk.LOW:
        drivers = tuple(
            name
            for name, lvl in (("wind", wind_after_load), ("rain", rain_level), ("snow", snow_level))
            if lvl == level
        )
    return Assessment(level, wind_after_load, rain_level, snow_level, load_rule, drivers)


def describe(a: Assessment, wind_mph: float, rain_in_hr: float, snow_in_hr: float) -> str:
    """Short human-readable reason for a checkpoint's level."""
    if a.level == Risk.LOW:
        return "No significant weather."
    parts = []
    for name in a.drivers:
        if name == "wind":
            parts.append(f"wind {wind_mph:.0f} mph")
        elif name == "rain":
            parts.append(f"rain {rain_in_hr:.2f} in/hr")
        elif name == "snow":
            parts.append(f"snow {snow_in_hr:.1f} in/hr")
    text = f"{a.level.label}: " + ", ".join(parts)
    if a.load_rule and "wind" in a.drivers:
        text += " (load rule applied)"
    return text


def rules_payload() -> dict:
    """The rules as data, served to the UI so it never hard-codes thresholds."""

    def rows(scale: Scale) -> dict:
        return {
            "unit": scale.unit,
            "moderate_from": scale.moderate,
            "high_from": scale.high,
            "severe_from": scale.severe,
            "no_travel_over": scale.no_travel,
            "no_travel_inclusive": scale.no_travel_inclusive,
        }

    return {
        "levels": [{"level": int(r), "key": r.key, "label": r.label} for r in Risk],
        "thresholds": {"wind": rows(WIND), "rain": rows(RAIN), "snow": rows(SNOW)},
        "load_rules": [
            f"Wind >= {WIND_NO_TRAVEL_ANY_LOAD} mph: No Travel for any load.",
            f"Wind {WIND_NO_TRAVEL_BAND[0]}-{WIND_NO_TRAVEL_BAND[1] - 1} mph with a load over "
            f"{WIND_NO_TRAVEL_MIN_LOAD:,} lb: No Travel.",
            f"Wind {WIND_SEVERE_BAND[0]}-{WIND_SEVERE_BAND[1] - 1} mph with a load over "
            f"{WIND_SEVERE_MIN_LOAD:,} lb: Severe.",
        ],
        "recommendation_order": [
            "Fewest Severe miles",
            "Fewest High miles",
            "Lowest average risk",
            "Shortest travel time",
        ],
    }
