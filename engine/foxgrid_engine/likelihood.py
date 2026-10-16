"""Von Mises bearing likelihood with a uniform outlier mixture."""

from __future__ import annotations

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]

_HALF_PI = np.pi / 2.0
_TWO_PI = 2.0 * np.pi


def wrap_pi(angle: FloatArray) -> FloatArray:
    """Wrap angles in radians to [-pi, pi)."""
    return np.asarray((angle + np.pi) % _TWO_PI - np.pi, dtype=np.float64)


def sigma_to_kappa(sigma_deg: FloatArray) -> FloatArray:
    """Concentration from angular sigma (normal approximation: kappa = 1 / sigma^2)."""
    sigma = np.radians(np.asarray(sigma_deg, dtype=np.float64))
    return np.asarray(1.0 / np.square(sigma), dtype=np.float64)


def log_bessel_i0(kappa: FloatArray) -> FloatArray:
    """log I0(kappa), stable for large kappa."""
    k = np.asarray(kappa, dtype=np.float64)
    small = np.log(np.i0(np.minimum(k, 50.0)))
    big_k = np.maximum(k, 50.0)
    big = (
        big_k
        - 0.5 * np.log(_TWO_PI * big_k)
        + np.log1p(1.0 / (8.0 * big_k) + 9.0 / (128.0 * big_k**2))
    )
    return np.asarray(np.where(k <= 50.0, small, big), dtype=np.float64)


def bearing_log_likelihood(
    delta: FloatArray,
    kappa: FloatArray,
    outlier_fraction: float,
) -> FloatArray:
    """Log-likelihood of angular deviations ``delta`` (radians, wrapped to [-pi, pi)).

    ``delta`` has the bearing axis last and ``kappa`` has shape ``(B,)``. Deviations beyond
    90 degrees (cell behind the station) only get the outlier component.
    """
    eps = outlier_fraction
    log_uniform = np.log(eps / _TWO_PI)
    log_norm = np.log(_TWO_PI) + log_bessel_i0(kappa)
    log_vm = kappa * np.cos(delta) - log_norm
    in_front = np.logaddexp(np.log1p(-eps) + log_vm, log_uniform)
    return np.asarray(np.where(np.abs(delta) > _HALF_PI, log_uniform, in_front), dtype=np.float64)
