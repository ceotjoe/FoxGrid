# 0002 – Probabilistic grid fusion

**Status:** accepted

**Context.** Bearings from amateurs are noisy, sometimes grossly wrong, and cover few stations. Plain ray intersection gives no
uncertainty and breaks with outliers.

**Decision.** Evaluate the likelihood on a metric grid: a von Mises density per bearing with κ = 1/σ² from the mandatory
`sigma_deg`, mixed with a uniform outlier term (ε = 0.1), cells behind the station getting only ε. Sum log-likelihoods, optional age
decay and per-transmission scoping. RSSI is added later as a path-loss likelihood; fixed stations with unknown per-station offsets
use a GLS fit. Position suggestions use Fisher information instead of the grid posterior.

**Consequences.** A single outlier barely moves the result, uncertainty is explicit (ellipses, 50/80/95 % contours), and the cost is
bounded by a cell cap (250 per axis). Fixed-station accuracy is only coarse. See [Engine](../concepts/engine.md).
