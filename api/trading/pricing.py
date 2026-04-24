from __future__ import annotations


def american_to_prob(american: int) -> float:
    """Convert American odds to implied probability [0, 1], ignoring vig."""
    if american > 0:
        return 100.0 / (american + 100.0)
    return abs(american) / (abs(american) + 100.0)


def prob_to_clob_price(prob: float) -> float:
    """Clamp a probability to the valid CLOB tick range [0.01, 0.99]."""
    return max(0.01, min(0.99, round(prob, 4)))
