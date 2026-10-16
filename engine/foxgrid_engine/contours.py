"""Probability-mass contours (marching squares) of a normalised posterior grid."""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
Ring = list[tuple[float, float]]  # (x, y) vertices, first == last
_Key = tuple[str, int, int]

# Segments per marching-squares case as pairs of cell edges.
# Corners: a=(j,i) b=(j,i+1) c=(j+1,i+1) d=(j+1,i); edges: B=a-b, R=b-c, T=d-c, L=a-d.
_CASES: dict[int, list[tuple[str, str]]] = {
    1: [("L", "B")],
    2: [("B", "R")],
    3: [("L", "R")],
    4: [("R", "T")],
    6: [("B", "T")],
    7: [("L", "T")],
    8: [("L", "T")],
    9: [("B", "T")],
    11: [("R", "T")],
    12: [("L", "R")],
    13: [("B", "R")],
    14: [("L", "B")],
}


def mass_threshold(post: FloatArray, mass: float) -> float:
    """Density level whose superlevel set holds ``mass`` of the total probability."""
    flat = np.sort(post.ravel())[::-1]
    cum = np.cumsum(flat)
    idx = int(np.searchsorted(cum, mass * cum[-1]))
    return float(flat[min(idx, flat.size - 1)])


def _edge_key(edge: str, j: int, i: int) -> _Key:
    return {
        "B": ("h", j, i),
        "T": ("h", j + 1, i),
        "L": ("v", j, i),
        "R": ("v", j, i + 1),
    }[edge]


def contour_rings(xs: FloatArray, ys: FloatArray, z: FloatArray, level: float) -> list[Ring]:
    """Closed iso-lines of ``z`` (shape ``(len(ys), len(xs))``) at ``level``.

    The grid is padded with a zero border so every contour is closed. Rings are not
    nested/oriented; a ring around a hole is returned as its own ring.
    """
    z = np.pad(z, 1, constant_values=0.0)
    dx, dy = float(xs[1] - xs[0]), float(ys[1] - ys[0])
    xs = np.concatenate([[xs[0] - dx], xs, [xs[-1] + dx]])
    ys = np.concatenate([[ys[0] - dy], ys, [ys[-1] + dy]])

    above = z > level
    code = above[:-1, :-1] * 1 + above[:-1, 1:] * 2 + above[1:, 1:] * 4 + above[1:, :-1] * 8
    mixed_j, mixed_i = np.nonzero((code > 0) & (code < 15))

    def point(key: _Key) -> tuple[float, float]:
        kind, j, i = key
        if kind == "h":  # between (j, i) and (j, i + 1)
            v0, v1 = z[j, i], z[j, i + 1]
            t = (level - v0) / (v1 - v0)
            return float(xs[i] + t * (xs[i + 1] - xs[i])), float(ys[j])
        v0, v1 = z[j, i], z[j + 1, i]  # between (j, i) and (j + 1, i)
        t = (level - v0) / (v1 - v0)
        return float(xs[i]), float(ys[j] + t * (ys[j + 1] - ys[j]))

    adjacency: dict[_Key, list[_Key]] = defaultdict(list)
    for j, i in zip(mixed_j.tolist(), mixed_i.tolist(), strict=True):
        case = int(code[j, i])
        if case in (5, 10):
            centre = (z[j, i] + z[j, i + 1] + z[j + 1, i + 1] + z[j + 1, i]) / 4.0 > level
            joined = (case == 5) == centre
            segs = [("B", "R"), ("L", "T")] if joined else [("L", "B"), ("R", "T")]
        else:
            segs = _CASES[case]
        for e0, e1 in segs:
            k0, k1 = _edge_key(e0, j, i), _edge_key(e1, j, i)
            adjacency[k0].append(k1)
            adjacency[k1].append(k0)

    rings: list[Ring] = []
    visited: set[_Key] = set()
    for start in list(adjacency):
        if start in visited:
            continue
        path = [start]
        visited.add(start)
        prev, cur = start, adjacency[start][0]
        while cur != start and cur not in visited:
            visited.add(cur)
            path.append(cur)
            nxt = [k for k in adjacency[cur] if k != prev]
            prev, cur = cur, (nxt[0] if nxt else adjacency[cur][0])
        ring = [point(k) for k in path]
        ring.append(ring[0])
        if len(ring) >= 4:
            rings.append(ring)
    return rings
