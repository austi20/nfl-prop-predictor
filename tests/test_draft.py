import pandas as pd

from data import draft


_PICKS = pd.DataFrame(
    {
        "season": [2026, 2026, 2025],
        "round": [1, 6, 2],
        "pick": [4, 190, 45],
        "gsis_id": ["00-000R1", "00-000R6", "00-000R2"],
    }
)


def test_draft_capital_returns_round_and_pick(monkeypatch):
    monkeypatch.setattr(draft, "_picks_frame", lambda seasons: _PICKS)
    draft.draft_capital.cache_clear()
    assert draft.draft_capital("00-000R1", (2025, 2026)) == (1, 4)


def test_draft_capital_none_for_undrafted(monkeypatch):
    monkeypatch.setattr(draft, "_picks_frame", lambda seasons: _PICKS)
    draft.draft_capital.cache_clear()
    assert draft.draft_capital("00-000UDFA", (2025, 2026)) is None


def test_capital_multiplier_is_monotonic_in_round():
    r1 = draft.capital_multiplier((1, 4))
    r6 = draft.capital_multiplier((6, 190))
    udfa = draft.capital_multiplier(None)
    assert r1 > r6 > udfa
    assert 0.5 <= udfa and r1 <= 1.5, "stays inside a sane band"
