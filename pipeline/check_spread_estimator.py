"""
Check the method int_peer_year_spread uses to measure how much car models genuinely differ.

The funnel limits and the adjusted estimates both depend on tau, the spread in true
failure rates between models of the same age. If tau is underestimated, the funnel is too
narrow and ordinary models get called "more often" or "less often" than their peers.

This simulates model groups whose true spread is known, then estimates it the way the dbt
model does (Spiegelhalter 2005, additive random effects), with z-scores clipped at
different percentiles before estimating. Run it with:

    python pipeline/check_spread_estimator.py

What it showed (fixed seeds, so the output is the same every time): with no clipping a
few extreme models inflate tau; Spiegelhalter's 10% clipping roughly halves it when every
model genuinely differs; 1% stays within about 10% of the true spread in both cases, and
errs high (the cautious side) when extreme models are present. That is why
dbt_project.yml sets spread_clip_quantile to 0.01.

Needs numpy (pip install numpy); the website and dbt don't.
"""

import math

import numpy as np

MODELS = 700            # about the number of model groups for one year of first use
TRUE_SD = 0.045         # true spread of failure rates between models (4.5 points)
CENTRE = 0.25           # typical initial failure rate
CLIPS = [None, 0.10, 0.05, 0.025, 0.01]


def estimate_tau(tests, fails, clip):
    target = fails.sum() / tests.sum()
    s = np.sqrt(target * (1 - target) / tests)
    z = (fails / tests - target) / s
    if clip is not None:
        z = np.clip(z, np.quantile(z, clip), np.quantile(z, 1 - clip))
    w = 1 / s ** 2
    phi = np.mean(z ** 2)
    tau2 = (len(z) * phi - (len(z) - 1)) / (w.sum() - (w ** 2).sum() / w.sum())
    return math.sqrt(max(0.0, tau2))


def simulate(seed, extreme_share):
    rng = np.random.default_rng(seed)
    tests = np.exp(rng.uniform(math.log(30), math.log(60_000), MODELS)).astype(int)
    true = np.clip(rng.normal(CENTRE, TRUE_SD, MODELS), 0.02, 0.95)
    extreme = int(MODELS * extreme_share)
    true[:extreme] = 0.65                          # a few models that fail far more often
    fails = rng.binomial(tests, true)
    return tests, fails, true[extreme:].std()


def main():
    header = "extreme models  true sd  " + "  ".join(
        f"{'no clip' if c is None else f'clip {c:.1%}':>10}" for c in CLIPS)
    print("Estimated spread between models, in percentage points\n" + header)
    for extreme_share in (0.0, 0.02):
        for seed in (1, 2, 3):
            tests, fails, true_sd = simulate(seed, extreme_share)
            estimates = "  ".join(f"{100 * estimate_tau(tests, fails, c):>10.2f}" for c in CLIPS)
            print(f"{extreme_share:>14.0%}  {100 * true_sd:>7.2f}  {estimates}")


if __name__ == "__main__":
    main()
