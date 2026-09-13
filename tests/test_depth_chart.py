import pandas as pd

from data import nflverse_loader


def test_load_depth_charts_is_cached_per_year(tmp_path, monkeypatch):
    calls: list[list[int]] = []

    def fake_import(years):
        calls.append(list(years))
        return pd.DataFrame({"season": years, "gsis_id": ["00-0000001"] * len(years)})

    monkeypatch.setattr(nflverse_loader, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(nflverse_loader.nfl, "import_depth_charts", fake_import)

    first = nflverse_loader.load_depth_charts([2024])
    second = nflverse_loader.load_depth_charts([2024])

    assert len(first) == 1
    assert first.equals(second)
    assert calls == [[2024]], "second call must hit the parquet cache, not the network"


from data import depth_chart


_LEGACY = pd.DataFrame(
    {
        "season": [2024, 2024, 2024],
        "club_code": ["JAX", "JAX", "JAX"],
        "week": [1.0, 1.0, 1.0],
        "game_type": ["REG", "REG", "REG"],
        "formation": ["Offense", "Offense", "Defense"],
        "depth_team": ["1", "3", "1"],
        "position": ["RB", "RB", "CB"],
        "gsis_id": ["00-0000ETN", "00-0000TUT", "00-0000CB1"],
    }
)

_MODERN = pd.DataFrame(
    {
        "dt": ["2026-09-13T12:42:08Z", "2026-09-13T12:42:08Z", "2026-08-01T00:00:00Z"],
        "team": ["JAX", "JAX", "JAX"],
        "pos_grp": ["3WR 1TE", "3WR 1TE", "3WR 1TE"],
        "pos_abb": ["RB", "RB", "RB"],
        "pos_rank": [1, 2, 3],
        "gsis_id": ["00-0000TUT", "00-0000ROD", "00-0000TUT"],
    }
)


def test_normalize_legacy_keeps_offense_and_maps_depth_team():
    out = depth_chart._normalize_legacy(_LEGACY)
    assert set(out["gsis_id"]) == {"00-0000ETN", "00-0000TUT"}, "defense rows dropped"
    tuten = out[out["gsis_id"] == "00-0000TUT"].iloc[0]
    assert tuten["rank"] == 3
    assert tuten["position"] == "RB"
    assert tuten["team"] == "JAX"
    assert tuten["week"] == 1


def _patch_week_starts(monkeypatch):
    """Week 1 kicks off 2026-09-10, so the Aug snapshot is preseason (week 0)
    and the Sep 13 snapshot lands in week 1."""
    monkeypatch.setattr(
        depth_chart,
        "_week_starts",
        lambda season: ((1, pd.Timestamp("2026-09-10", tz="UTC")),),
    )


def test_normalize_modern_keeps_history_and_dates_each_snapshot(monkeypatch):
    _patch_week_starts(monkeypatch)
    out = depth_chart._normalize_modern(_MODERN, season=2026)
    tuten = out[out["gsis_id"] == "00-0000TUT"].sort_values("week")
    assert len(tuten) == 2, "in-season progression must survive, not just the newest chart"
    assert list(tuten["week"]) == [0, 1]
    assert list(tuten["rank"]) == [3, 1], "preseason RB3 -> in-season RB1"


def test_normalize_modern_collapses_same_week_snapshots_to_the_last(monkeypatch):
    _patch_week_starts(monkeypatch)
    same_week = pd.DataFrame(
        {
            "dt": ["2026-09-11T00:00:00Z", "2026-09-13T12:42:08Z"],
            "team": ["JAX", "JAX"],
            "pos_grp": ["3WR 1TE", "3WR 1TE"],
            "pos_abb": ["RB", "RB"],
            "pos_rank": [2, 1],
            "gsis_id": ["00-0000TUT", "00-0000TUT"],
        }
    )
    out = depth_chart._normalize_modern(same_week, season=2026)
    assert len(out) == 1
    assert out.iloc[0]["rank"] == 1, "the later snapshot in a week wins"


def test_normalize_modern_drops_non_offense_groups(monkeypatch):
    _patch_week_starts(monkeypatch)
    defense = _MODERN.assign(pos_grp="Base 4-3 D")
    assert depth_chart._normalize_modern(defense, season=2026).empty


_FRAME = pd.DataFrame(
    {
        "gsis_id": ["00-0000TUT"] * 5 + ["00-0000ETN"],
        "season": [2025, 2025, 2025, 2025, 2026, 2025],
        "week": [1, 2, 3, 4, 0, 1],
        "team": ["JAX"] * 6,
        "position": ["RB"] * 6,
        "rank": [3, 3, 3, 2, 1, 1],
        "asof": pd.to_datetime(
            [
                "2025-09-08", "2025-09-15", "2025-09-22", "2025-09-29",
                "2026-09-13", "2025-09-08",
            ],
            utc=True,
        ),
    }
)


def _patch_frame(monkeypatch):
    monkeypatch.setattr(depth_chart, "rank_frame", lambda seasons: _FRAME)
    depth_chart.current_rank.cache_clear()
    depth_chart.prior_rank.cache_clear()


def test_current_rank_prefers_the_live_snapshot(monkeypatch):
    _patch_frame(monkeypatch)
    assert depth_chart.current_rank("00-0000TUT", 2026, 1, (2025, 2026)) == 1


def test_prior_rank_is_the_modal_rank_of_the_trailing_window(monkeypatch):
    _patch_frame(monkeypatch)
    # 2025 weeks 1-4 are ranks 3,3,3,2 -> mode 3
    assert depth_chart.prior_rank("00-0000TUT", 2026, 1, (2025, 2026)) == 3


def test_prior_rank_ignores_the_zero_week_live_snapshot(monkeypatch):
    _patch_frame(monkeypatch)
    assert depth_chart.prior_rank("00-0000TUT", 2026, 1, (2025, 2026)) != 1


def test_unknown_player_returns_none(monkeypatch):
    _patch_frame(monkeypatch)
    assert depth_chart.current_rank("00-0000XXX", 2026, 1, (2025, 2026)) is None
    assert depth_chart.prior_rank("00-0000XXX", 2026, 1, (2025, 2026)) is None
