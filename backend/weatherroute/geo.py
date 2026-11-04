"""Geometry helpers: distances along polylines, resampling, slicing, simplification.

Everything is pure Python on (lat, lon) tuples. Polylines from the routing API can hold tens
of thousands of points, so lookups along a route use bisect on a precomputed cumulative-distance
list rather than scanning.
"""
from __future__ import annotations

import bisect
import math
from collections.abc import Sequence

from .domain import LatLon

EARTH_RADIUS_MI = 3958.7613
MILES_PER_DEG_LAT = 69.0935


def haversine_mi(a: LatLon, b: LatLon) -> float:
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_MI * math.asin(min(1.0, math.sqrt(h)))


def cumulative_miles(points: Sequence[LatLon]) -> list[float]:
    cum = [0.0]
    for i in range(1, len(points)):
        cum.append(cum[-1] + haversine_mi(points[i - 1], points[i]))
    return cum


def point_at(points: Sequence[LatLon], cum: Sequence[float], d: float) -> LatLon:
    """The point `d` miles along the polyline (clamped to its ends)."""
    if d <= 0:
        return points[0]
    if d >= cum[-1]:
        return points[-1]
    i = bisect.bisect_right(cum, d)  # cum[i-1] <= d < cum[i]
    seg = cum[i] - cum[i - 1]
    t = (d - cum[i - 1]) / seg if seg > 0 else 0.0
    a, b = points[i - 1], points[i]
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def sample_distances(total: float, step: float) -> list[float]:
    """Checkpoint positions: 0, step, 2*step, ... and always the exact end of the route."""
    if total <= 0:
        return [0.0]
    ds = [0.0]
    k = 1
    while k * step < total - 1e-9:
        ds.append(k * step)
        k += 1
    # Drop a final interior checkpoint that would sit almost on top of the destination.
    if len(ds) > 1 and total - ds[-1] < 0.1 * step:
        ds.pop()
    ds.append(total)
    return ds


def slice_polyline(points: Sequence[LatLon], cum: Sequence[float], d0: float, d1: float) -> list[LatLon]:
    """The part of the polyline between `d0` and `d1` miles (inclusive of interpolated ends)."""
    start = point_at(points, cum, d0)
    if d1 <= d0:
        return [start]
    i0 = bisect.bisect_right(cum, d0)
    i1 = bisect.bisect_left(cum, d1)
    return [start, *points[i0:i1], point_at(points, cum, d1)]


def simplify(points: Sequence[LatLon], tolerance_mi: float) -> list[LatLon]:
    """Ramer-Douglas-Peucker (iterative) in a local flat projection. Keeps both end points."""
    n = len(points)
    if n <= 2:
        return list(points)
    lat0 = sum(p[0] for p in points) / n
    kx = math.cos(math.radians(lat0)) * MILES_PER_DEG_LAT
    xy = [(p[1] * kx, p[0] * MILES_PER_DEG_LAT) for p in points]
    keep = [False] * n
    keep[0] = keep[-1] = True
    tol2 = tolerance_mi * tolerance_mi
    stack = [(0, n - 1)]
    while stack:
        s, e = stack.pop()
        if e <= s + 1:
            continue
        ax, ay = xy[s]
        bx, by = xy[e]
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        worst, idx = -1.0, -1
        for i in range(s + 1, e):
            px, py = xy[i]
            if seg2 == 0:
                d2 = (px - ax) ** 2 + (py - ay) ** 2
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
                d2 = (px - (ax + t * dx)) ** 2 + (py - (ay + t * dy)) ** 2
            if d2 > worst:
                worst, idx = d2, i
        if worst > tol2:
            keep[idx] = True
            stack.append((s, idx))
            stack.append((idx, e))
    return [p for p, k in zip(points, keep) if k]


def bearing_deg(a: LatLon, b: LatLon) -> float:
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlon = math.radians(b[1] - a[1])
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def destination_point(p: LatLon, bearing: float, dist_mi: float) -> LatLon:
    lat1, lon1 = math.radians(p[0]), math.radians(p[1])
    brg = math.radians(bearing)
    ang = dist_mi / EARTH_RADIUS_MI
    lat2 = math.asin(math.sin(lat1) * math.cos(ang) + math.cos(lat1) * math.sin(ang) * math.cos(brg))
    lon2 = lon1 + math.atan2(
        math.sin(brg) * math.sin(ang) * math.cos(lat1), math.cos(ang) - math.sin(lat1) * math.sin(lat2)
    )
    return (math.degrees(lat2), (math.degrees(lon2) + 540) % 360 - 180)


def shared_fraction(a: Sequence[LatLon], b: Sequence[LatLon], tol_mi: float = 1.0, step_mi: float = 1.0) -> float:
    """Fraction of polyline `b` that runs within `tol_mi` of polyline `a`."""
    cum_a, cum_b = cumulative_miles(a), cumulative_miles(b)
    if cum_b[-1] <= 0:
        return 1.0
    a_pts = [point_at(a, cum_a, d) for d in sample_distances(cum_a[-1], step_mi)]
    b_pts = [point_at(b, cum_b, d) for d in sample_distances(cum_b[-1], step_mi)]

    lat_cell = tol_mi / MILES_PER_DEG_LAT
    mid_lat = a_pts[len(a_pts) // 2][0]
    lon_cell = lat_cell / max(0.2, math.cos(math.radians(mid_lat)))
    grid: dict[tuple[int, int], list[LatLon]] = {}
    for p in a_pts:
        grid.setdefault((int(p[0] // lat_cell), int(p[1] // lon_cell)), []).append(p)

    near = 0
    for p in b_pts:
        ci, cj = int(p[0] // lat_cell), int(p[1] // lon_cell)
        if any(
            haversine_mi(p, q) <= tol_mi
            for di in (-1, 0, 1)
            for dj in (-1, 0, 1)
            for q in grid.get((ci + di, cj + dj), ())
        ):
            near += 1
    return near / len(b_pts)


def corridor_points(
    polylines: Sequence[Sequence[LatLon]],
    max_points: int = 180,
    min_spacing_mi: float = 15.0,
    lateral_ratio: float = 0.75,
    max_lateral_mi: float = 30.0,
) -> tuple[list[LatLon], float]:
    """Sample a grid of points covering the corridor spanned by the routes.

    Points are taken along every route and, to give the corridor some width, at a lateral
    offset to either side. Spacing grows until the point budget is respected. Returns
    (points, spacing_mi); spacing is also the natural blob radius for rendering.
    """
    cums = [cumulative_miles(p) for p in polylines]
    longest = max(c[-1] for c in cums)
    spacing = max(min_spacing_mi, longest / 40.0)

    while True:
        seen: dict[tuple[int, int], LatLon] = {}
        lateral = min(max_lateral_mi, spacing * lateral_ratio)
        for pts, cum in zip(polylines, cums):
            for d in sample_distances(cum[-1], spacing):
                p = point_at(pts, cum, d)
                ahead = point_at(pts, cum, min(cum[-1], d + spacing / 2))
                behind = point_at(pts, cum, max(0.0, d - spacing / 2))
                brg = bearing_deg(behind, ahead) if behind != ahead else 0.0
                for q in (p, destination_point(p, brg + 90, lateral), destination_point(p, brg - 90, lateral)):
                    key = (round(q[0] / 0.05), round(q[1] / 0.05))
                    seen.setdefault(key, (round(q[0], 3), round(q[1], 3)))
        if len(seen) <= max_points or spacing > 800:
            return list(seen.values()), spacing
        spacing *= 1.25
