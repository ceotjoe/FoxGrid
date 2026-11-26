"""Per-bearing weight, outlier fraction and grouping of correlated series (ADR 0010)."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from foxgrid_engine import Bearing, EngineError, EngineParams, estimate
from foxgrid_engine.estimate import _cluster_weights, _transformers, utm_epsg_for
from foxgrid_engine.likelihood import bearing_log_likelihood
from tests.conftest import ORIGIN, distance_m, make_bearings, offset, true_bearing


def at(east_m: float, north_m: float, az: float = 0.0, **kw: object) -> Bearing:
    lat, lon = offset(*ORIGIN, east_m, north_m)
    return Bearing(lat=lat, lon=lon, azimuth_deg=az, sigma_deg=5.0, **kw)  # type: ignore[arg-type]


def weights(bearings: list[Bearing], radius: float = 75.0) -> list[float]:
    """Cluster weights with positions projected like the engine does."""
    fwd, _ = _transformers(utm_epsg_for(*ORIGIN))
    east, north = fwd.transform([b.lon for b in bearings], [b.lat for b in bearings])
    return list(_cluster_weights(bearings, np.asarray(east), np.asarray(north), radius))


def test_a_stop_shares_one_weight() -> None:
    parked = [at(i * 2.0, 0.0, group="kraken") for i in range(20)]  # GPS jitter of a parked car
    w = weights(parked)
    assert w == pytest.approx([1 / 20] * 20)
    assert sum(w) == pytest.approx(1.0)


def test_a_drive_does_not_chain_into_one_cluster() -> None:
    drive = [at(i * 100.0, 0.0, group="kraken") for i in range(10)]
    assert weights(drive) == pytest.approx([1.0] * 10)
    # neighbours within the radius share, but only with their own neighbourhood
    dense = [at(i * 50.0, 0.0, group="kraken") for i in range(5)]
    assert weights(dense) == pytest.approx([1 / 2, 1 / 3, 1 / 3, 1 / 3, 1 / 2])


def test_groups_and_ungrouped_bearings_are_independent() -> None:
    mixed = [
        at(0, 0, group="a"),
        at(1, 0, group="a"),
        at(2, 0, group="b"),
        at(3, 0),
        at(4, 0),
    ]
    assert weights(mixed) == pytest.approx([0.5, 0.5, 1.0, 1.0, 1.0])
    assert weights(mixed, radius=0.0) == pytest.approx([1.0] * 5)


def test_a_long_stop_no_longer_outvotes_hand_bearings(
    target: tuple[float, float], triangle_stations: list[tuple[float, float]]
) -> None:
    hand = make_bearings(target, triangle_stations, sigma=5.0)
    # A parked station 30 times on the same spot with a consistent 25 degree error (multipath).
    spot = offset(*ORIGIN, -2000.0, 6000.0)
    biased = (true_bearing(spot, target) + 25.0) % 360.0
    parked = [
        Bearing(lat=spot[0], lon=spot[1] + i * 1e-6, azimuth_deg=biased, sigma_deg=6.0, group="k")
        for i in range(30)
    ]
    ungrouped = [replace(b, group=None) for b in parked]

    worse = estimate(hand + ungrouped)
    better = estimate(hand + parked)
    once = estimate([*hand, replace(parked[0], group=None)])
    # the whole stop counts like a single bearing ...
    assert distance_m((better.lat, better.lon), (once.lat, once.lon)) < 60.0
    # ... while 30 independent copies drag the estimate along the biased ray
    assert distance_m((worse.lat, worse.lon), target) > 1.5 * distance_m(
        (better.lat, better.lon), target
    )


def test_weight_zero_removes_a_bearing(
    target: tuple[float, float], triangle_stations: list[tuple[float, float]]
) -> None:
    hand = make_bearings(target, triangle_stations)
    wrong = replace(hand[0], azimuth_deg=(hand[0].azimuth_deg + 40.0) % 360.0, weight=0.0)
    base = estimate(hand[1:] + [make_bearings(target, [offset(*ORIGIN, 0.0, -8000.0)])[0]])
    with_zero = estimate(
        hand[1:] + [make_bearings(target, [offset(*ORIGIN, 0.0, -8000.0)])[0], wrong]
    )
    assert distance_m((base.lat, base.lon), (with_zero.lat, with_zero.lon)) < 30.0


def test_weight_scales_the_pull_of_a_bearing(
    target: tuple[float, float], triangle_stations: list[tuple[float, float]]
) -> None:
    hand = make_bearings(target, triangle_stations)
    spot = offset(*ORIGIN, -2000.0, 6000.0)
    off = Bearing(spot[0], spot[1], (true_bearing(spot, target) + 15.0) % 360.0, 5.0)
    full = estimate([*hand, off])
    half = estimate([*hand, replace(off, weight=0.3)])
    assert distance_m((half.lat, half.lon), target) < distance_m((full.lat, full.lon), target)


def test_outlier_fraction_per_bearing() -> None:
    delta = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]])
    kappa = np.array([50.0, 50.0])
    mixed = bearing_log_likelihood(delta, kappa, np.array([0.1, 0.3]))
    assert mixed[:, 0] == pytest.approx(bearing_log_likelihood(delta[:, :1], kappa[:1], 0.1)[:, 0])
    assert mixed[:, 1] == pytest.approx(bearing_log_likelihood(delta[:, 1:], kappa[1:], 0.3)[:, 0])


def test_higher_outlier_fraction_softens_a_wrong_bearing(
    target: tuple[float, float], triangle_stations: list[tuple[float, float]]
) -> None:
    hand = make_bearings(target, triangle_stations)
    spot = offset(*ORIGIN, -2000.0, 6000.0)
    wrong = Bearing(spot[0], spot[1], (true_bearing(spot, target) + 60.0) % 360.0, 5.0)
    strict = estimate([*hand, replace(wrong, outlier_fraction=0.01)])
    tolerant = estimate([*hand, replace(wrong, outlier_fraction=0.5)])
    assert distance_m((tolerant.lat, tolerant.lon), target) <= distance_m(
        (strict.lat, strict.lon), target
    )


@pytest.mark.parametrize(
    ("bearing_kw", "params_kw", "message"),
    [
        ({"weight": -1.0}, {}, "weight"),
        ({"weight": float("nan")}, {}, "weight"),
        ({"outlier_fraction": 0.0}, {}, "outlier_fraction"),
        ({"outlier_fraction": 1.0}, {}, "outlier_fraction"),
        ({}, {"cluster_radius_m": -1.0}, "cluster_radius_m"),
        ({}, {"cluster_radius_m": float("inf")}, "cluster_radius_m"),
    ],
)
def test_invalid_weights_are_rejected(
    target: tuple[float, float],
    triangle_stations: list[tuple[float, float]],
    bearing_kw: dict[str, float],
    params_kw: dict[str, float],
    message: str,
) -> None:
    bearings = make_bearings(target, triangle_stations)
    bearings[0] = replace(bearings[0], **bearing_kw)  # type: ignore[arg-type]
    with pytest.raises(EngineError, match=message):
        estimate(bearings, EngineParams(**params_kw))  # type: ignore[arg-type]


def test_all_weights_zero_is_an_error(
    target: tuple[float, float], triangle_stations: list[tuple[float, float]]
) -> None:
    bearings = [replace(b, weight=0.0) for b in make_bearings(target, triangle_stations)]
    with pytest.raises(EngineError, match="weight 0"):
        estimate(bearings)
