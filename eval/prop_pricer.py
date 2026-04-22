# Prop pricer - model distribution -> fair price -> edge vs book line
# Calibration: Platt/isotonic on 2025 closing lines
# See docs/plan.md Steps 3-4

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import joblib
import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from models.base import StatDistribution

# ---------------------------------------------------------------------------
# American odds <-> implied probability (single-sided, includes vig in line)
# ---------------------------------------------------------------------------


def implied_prob(american: int) -> float:
    """Convert American odds to implied win probability (not vig-removed)."""
    if american < 0:
        return float(-american) / float(-american + 100)
    return 100.0 / float(american + 100)


def fair_price_to_american(p: float) -> int:
    """Map calibrated probability p in (0,1) to whole-number American odds.

    Picks a nearby integer so ``implied_prob`` round-trips within rounding error
    of discrete sportsbook lines.
    """
    if p <= 0.0 or p >= 1.0:
        raise ValueError("p must be strictly between 0 and 1 for fair American odds")
    if p > 0.5:
        a0 = 100.0 * p / (1.0 - p)
        lo, hi = max(101, int(a0) - 3), int(a0) + 4
        best = min(range(lo, hi), key=lambda A: abs(implied_prob(-A) - p))
        return -best
    o0 = 100.0 * (1.0 - p) / p
    lo, hi = max(100, int(o0) - 3), int(o0) + 4
    return min(range(lo, hi), key=lambda O: abs(implied_prob(O) - p))


def edge(calibrated_prob: float, book_implied_prob: float) -> float:
    return calibrated_prob - book_implied_prob


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------


@dataclass
class PropCalibrator:
    """Post-hoc probability calibration: isotonic or Platt (logistic on logit)."""

    method: Literal["isotonic", "platt"] = "isotonic"
    _isotonic: IsotonicRegression | None = None
    _platt: LogisticRegression | None = None
    _fitted: bool = False

    def fit(
        self,
        raw_probs: np.ndarray,
        outcomes: np.ndarray,
    ) -> "PropCalibrator":
        """Fit on raw model probabilities and binary outcomes (1 = over hit, 0 = under)."""
        r = np.asarray(raw_probs, dtype=float).ravel()
        y = np.asarray(outcomes, dtype=float).ravel()
        if len(r) != len(y):
            raise ValueError("raw_probs and outcomes must be the same length")

        if self.method == "isotonic":
            self._isotonic = IsotonicRegression(
                y_min=0.0, y_max=1.0, out_of_bounds="clip"
            )
            self._isotonic.fit(r, y)
            self._platt = None
        else:
            eps = 1e-6
            rc = np.clip(r, eps, 1.0 - eps)
            x = np.log(rc / (1.0 - rc)).reshape(-1, 1)
            self._platt = LogisticRegression(max_iter=2000)
            self._platt.fit(x, y.astype(int))
            self._isotonic = None
        self._fitted = True
        return self

    def calibrate(
        self,
        raw: np.ndarray | float,
    ) -> np.ndarray | float:
        if not self._fitted:
            raise RuntimeError("Calibrator is not fitted")
        single = not isinstance(raw, np.ndarray)
        r = np.atleast_1d(np.asarray(raw, dtype=float))

        if self._isotonic is not None:
            out = self._isotonic.predict(r)
        else:
            assert self._platt is not None
            eps = 1e-6
            rc = np.clip(r, eps, 1.0 - eps)
            x = np.log(rc / (1.0 - rc)).reshape(-1, 1)
            out = self._platt.predict_proba(x)[:, 1]

        out = np.clip(out, 0.0, 1.0)
        if single:
            return float(out[0])
        return out

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "method": self.method,
            "isotonic": self._isotonic,
            "platt": self._platt,
            "fitted": self._fitted,
        }
        joblib.dump(payload, path)

    @classmethod
    def load(cls, path: Path) -> "PropCalibrator":
        data = joblib.load(Path(path))
        cal = cls(method=data.get("method", "isotonic"))
        cal._isotonic = data.get("isotonic")
        cal._platt = data.get("platt")
        cal._fitted = data.get("fitted", False)
        return cal


# ---------------------------------------------------------------------------
# Reliability (calibration) diagram stats (+ optional figure)
# ---------------------------------------------------------------------------


def reliability_diagram(
    raw: np.ndarray,
    outcomes: np.ndarray,
    n_bins: int = 10,
    save_path: Path | None = None,
) -> dict[str, Any]:
    """Binned reliability: mean predicted vs positive rate per bin. Returns ECE among stats."""
    r = np.asarray(raw, dtype=float).ravel()
    y = np.asarray(outcomes, dtype=float).ravel()
    n = len(r)
    if n == 0:
        return {"bin_means": [], "bin_fracs": [], "ece": 0.0}

    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_idx = np.digitize(r, edges[1:-1], right=False)
    # digitize: 0 for < edges[1], up to n_bins-1; clamp
    bin_idx = np.clip(bin_idx, 0, n_bins - 1)

    bin_means: list[float] = []
    bin_fracs: list[float] = []
    ece = 0.0
    for b in range(n_bins):
        m = bin_idx == b
        if not np.any(m):
            continue
        mean_p = float(r[m].mean())
        acc = float(y[m].mean())
        w = float(m.sum()) / n
        ece += w * abs(mean_p - acc)
        bin_means.append(mean_p)
        bin_fracs.append(acc)

    stats_out: dict[str, Any] = {
        "bin_means": bin_means,
        "bin_fracs": bin_fracs,
        "ece": ece,
    }
    if save_path is not None:
        _plot_reliability(r, y, n_bins, Path(save_path))
    return stats_out


def _plot_reliability(
    r: np.ndarray, y: np.ndarray, n_bins: int, save_path: Path
) -> None:
    import matplotlib.pyplot as plt

    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bin_idx = np.digitize(r, edges[1:-1], right=False)
    bin_idx = np.clip(bin_idx, 0, n_bins - 1)

    xs: list[float] = []
    ys: list[float] = []
    for b in range(n_bins):
        m = bin_idx == b
        if not np.any(m):
            continue
        xs.append(float(r[m].mean()))
        ys.append(float(y[m].mean()))

    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], "k--", alpha=0.4, label="perfect")
    ax.plot(xs, ys, "o-", label="model")
    ax.set_xlabel("Mean predicted prob (bin)")
    ax.set_ylabel("Fraction positives")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_aspect("equal", adjustable="box")
    ax.legend()
    fig.tight_layout()
    fig.savefig(save_path)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Price a single over/under vs book
# ---------------------------------------------------------------------------


def price_prop(
    dist: StatDistribution,
    line: float,
    book_odds: int,
    calibrator: PropCalibrator | None,
) -> dict[str, float]:
    """P(over) from model, optional calibration, edge vs book, fair US odds."""
    raw_prob = float(dist.prob_over(line))
    if calibrator is None:
        calibrated_prob = raw_prob
    else:
        cp = calibrator.calibrate(raw_prob)
        calibrated_prob = float(cp) if not isinstance(cp, float) else cp

    book_implied = implied_prob(book_odds)
    e = edge(calibrated_prob, book_implied)
    fair_am = fair_price_to_american(calibrated_prob)
    return {
        "raw_prob": raw_prob,
        "calibrated_prob": calibrated_prob,
        "book_implied_prob": book_implied,
        "edge": e,
        "fair_american": float(fair_am),
    }
