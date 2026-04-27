from __future__ import annotations

from typing import Literal


NoVigMethod = Literal["multiplicative", "additive", "shin"]


def _implied_prob(american: int) -> float:
    if american < 0:
        return float(-american) / float(-american + 100)
    return 100.0 / float(american + 100)


def remove_vig_two_sided(
    over_odds: int,
    under_odds: int,
    *,
    method: NoVigMethod = "multiplicative",
) -> tuple[float, float]:
    """Convert two-sided American odds into no-vig over/under probabilities."""
    p_over = _implied_prob(int(over_odds))
    p_under = _implied_prob(int(under_odds))
    total = p_over + p_under
    if total <= 0:
        raise ValueError("Two-sided odds imply zero total probability")

    if method == "multiplicative":
        return p_over / total, p_under / total

    if method == "additive":
        vig = total - 1.0
        no_vig_over = p_over - vig / 2.0
        no_vig_under = p_under - vig / 2.0
        adjusted_total = no_vig_over + no_vig_under
        if adjusted_total <= 0:
            raise ValueError("Additive no-vig adjustment produced invalid probabilities")
        return no_vig_over / adjusted_total, no_vig_under / adjusted_total

    if method == "shin":
        raise NotImplementedError("shin no-vig method is not implemented yet")

    raise ValueError(f"Unsupported no-vig method: {method}")
