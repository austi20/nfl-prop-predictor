# Depth-Chart Rank and Rookie Projection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the fantasy projector aware of a player's *current* depth-chart role rather than the role their trailing stats were earned in, and admit rookies to the board with an honest, widened projection instead of omitting them.

**Architecture:** A new `data/depth_chart.py` normalizes nflverse's two incompatible depth-chart schemas into one `(gsis_id, season, week, team, position, rank)` frame. `_baselines_for` in `api/services/fantasy_service.py` re-keys on `(position, rank_bucket, stat)` so the trailing anchor regresses toward the *right role's* archetype. A new `_depth_chart_factor` applies a bounded, baseline-derived multiplier when current rank differs from the rank the trailing window encodes, and suppresses the existing `usage_trend` factor to prevent double counting.

**Tech Stack:** Python 3.13, uv, pandas, numpy, pytest, nfl_data_py (nflverse).

**Spec:** `docs/superpowers/specs/2026-09-13-player-context-role-and-market-anchoring-design.md` (Phases 1-4)

---

## Key upstream facts (verified 2026-09-13, do not re-derive)

Two incompatible depth-chart schemas:

| era | rows | rank col | position col | team col | week col | filter |
|---|---|---|---|---|---|---|
| 2015-2024 | weekly | `depth_team` (`'1'`,`'2'`,`'3'`) | `position` | `club_code` | `week` | `formation == 'Offense'`, `game_type == 'REG'` |
| 2025-2026 | daily snapshots | `pos_rank` (int, 1..6+) | `pos_abb` | `team` | none - use `dt` | `pos_grp == '3WR 1TE'` |

**Legacy `depth_team` maxes out at 3.** Modern `pos_rank` does not. Buckets must therefore cap at `3+` for every position so the two eras are comparable:

```
QB {1, 2+}   RB {1, 2, 3+}   WR {1, 2, 3+}   TE {1, 2+}
```

`nfl.import_draft_picks` carries `season`, `round`, `pick`, `gsis_id`, `position`; the 2026 class is present.

---

## File Structure

- **Create** `data/depth_chart.py` - schema normalization + rank lookups. One responsibility: answer "what rank is this player, and what rank were their trailing stats earned at?"
- **Create** `data/draft.py` - draft capital lookup. Kept separate from `depth_chart.py`; different source, different cadence, no shared state.
- **Create** `tests/test_depth_chart.py`, `tests/test_draft.py`
- **Modify** `data/nflverse_loader.py` - add `load_depth_charts`, `load_draft_picks`
- **Modify** `api/services/fantasy_service.py` - rank-conditioned baselines, `depth_rank` plumbing, rookie path, `_depth_chart_factor`, precedence
- **Modify** `api/services/fantasy_slate_service.py` - rookie admission in `_prescore`
- **Modify** `eval/fantasy_calibration.py` - new knobs with today-preserving defaults
- **Modify** `tests/test_fantasy_service.py` (or create if absent), `tests/test_fantasy_slate_service.py`

---

### Task 1: Depth-chart and draft-pick loaders

**Files:**
- Modify: `data/nflverse_loader.py` (after `load_snap_counts`, ~line 227)
- Test: `tests/test_depth_chart.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_depth_chart.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_depth_chart.py -q`
Expected: FAIL with `AttributeError: module 'data.nflverse_loader' has no attribute 'load_depth_charts'`

- [ ] **Step 3: Write minimal implementation**

In `data/nflverse_loader.py`, directly after `load_snap_counts`:

```python
def load_depth_charts(years: list[int] = TRAIN_YEARS, force_refresh: bool = False) -> pd.DataFrame:
    path = _cache_path("depth_charts", years)
    return _load_or_fetch(path, lambda: nfl.import_depth_charts(years), force_refresh)


def load_draft_picks(years: list[int] = TRAIN_YEARS, force_refresh: bool = False) -> pd.DataFrame:
    path = _cache_path("draft_picks", years)
    return _load_or_fetch(path, lambda: nfl.import_draft_picks(years), force_refresh)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_depth_chart.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add data/nflverse_loader.py tests/test_depth_chart.py
git commit -m "feat: nflverse depth-chart and draft-pick loaders"
```

---

### Task 2: Normalize both depth-chart schemas

**Files:**
- Create: `data/depth_chart.py`
- Test: `tests/test_depth_chart.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_depth_chart.py`:

```python
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


def test_normalize_modern_takes_latest_snapshot_only():
    out = depth_chart._normalize_modern(_MODERN, season=2026)
    tuten = out[out["gsis_id"] == "00-0000TUT"]
    assert len(tuten) == 1, "only the newest snapshot survives"
    assert tuten.iloc[0]["rank"] == 1, "stale 2026-08-01 rank 3 must not win"


def test_normalize_modern_drops_non_offense_groups():
    defense = _MODERN.assign(pos_grp="Base 4-3 D")
    assert depth_chart._normalize_modern(defense, season=2026).empty
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_depth_chart.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'data.depth_chart'`

- [ ] **Step 3: Write minimal implementation**

Create `data/depth_chart.py`:

```python
"""Depth-chart rank - which slot a player actually occupies right now.

The trailing-form projector averages a player's last 8 games, so it encodes the
role he *had*. An offseason promotion (the RB2 who is now RB1 because the starter
left) produces no in-season usage trend, so `data/usage.py` cannot see it. Depth
rank can, and nflverse refreshes it daily.

nflverse publishes two incompatible schemas. Through 2024 it is one row per
player per week with a string `depth_team`; from 2025 it is dated ESPN snapshots
with an integer `pos_rank`. Both normalize to
`(gsis_id, season, week, team, position, rank)`.
"""
from __future__ import annotations

from functools import lru_cache

import pandas as pd

from data.nflverse_loader import load_depth_charts

_SKILL_POSITIONS = ("QB", "RB", "WR", "TE")
_MODERN_OFFENSE_GROUP = "3WR 1TE"

_COLUMNS = ["gsis_id", "season", "week", "team", "position", "rank"]

# Legacy `depth_team` never exceeds 3, so every bucket caps at 3+ to keep the
# two eras comparable.
_MAX_RANK = 3


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=_COLUMNS)


def _normalize_legacy(df: pd.DataFrame) -> pd.DataFrame:
    """2015-2024: weekly rows, string `depth_team`, offense/defense in one frame."""
    if df.empty or "depth_team" not in df.columns:
        return _empty()
    rows = df[
        (df["formation"].astype(str) == "Offense")
        & (df["game_type"].astype(str) == "REG")
        & (df["position"].astype(str).str.upper().isin(_SKILL_POSITIONS))
    ].copy()
    if rows.empty:
        return _empty()
    out = pd.DataFrame(
        {
            "gsis_id": rows["gsis_id"].astype(str),
            "season": pd.to_numeric(rows["season"], errors="coerce"),
            "week": pd.to_numeric(rows["week"], errors="coerce"),
            "team": rows["club_code"].astype(str),
            "position": rows["position"].astype(str).str.upper(),
            "rank": pd.to_numeric(rows["depth_team"], errors="coerce"),
        }
    )
    return out.dropna().astype({"season": int, "week": int, "rank": int}).reset_index(drop=True)


def _normalize_modern(df: pd.DataFrame, *, season: int) -> pd.DataFrame:
    """2025+: dated ESPN snapshots. Only the newest snapshot is the live chart.

    There is no week column, so the snapshot is stamped with week 0 and read as
    "current as of now" by `current_rank`.
    """
    if df.empty or "pos_rank" not in df.columns:
        return _empty()
    rows = df[
        (df["pos_grp"].astype(str) == _MODERN_OFFENSE_GROUP)
        & (df["pos_abb"].astype(str).str.upper().isin(_SKILL_POSITIONS))
    ].copy()
    if rows.empty:
        return _empty()
    rows["_dt"] = pd.to_datetime(rows["dt"], errors="coerce", utc=True)
    rows = rows.dropna(subset=["_dt"])
    if rows.empty:
        return _empty()
    rows = rows[rows["_dt"] == rows["_dt"].max()]
    out = pd.DataFrame(
        {
            "gsis_id": rows["gsis_id"].astype(str),
            "season": int(season),
            "week": 0,
            "team": rows["team"].astype(str),
            "position": rows["pos_abb"].astype(str).str.upper(),
            "rank": pd.to_numeric(rows["pos_rank"], errors="coerce"),
        }
    )
    return out.dropna().astype({"season": int, "week": int, "rank": int}).reset_index(drop=True)


def bucket(rank: int | None, position: str) -> int | None:
    """Collapse a raw rank into the comparable bucket (1, 2, or 3+)."""
    if rank is None:
        return None
    r = int(rank)
    if r < 1:
        return None
    if position.upper().strip() in {"QB", "TE"}:
        return 1 if r == 1 else 2
    return min(r, _MAX_RANK)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_depth_chart.py -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add data/depth_chart.py tests/test_depth_chart.py
git commit -m "feat: normalize nflverse's two depth-chart schemas"
```

---

### Task 3: `rank_frame`, `current_rank`, `prior_rank`

**Files:**
- Modify: `data/depth_chart.py`
- Test: `tests/test_depth_chart.py`

`prior_rank` is the load-bearing function: comparing the live rank against *the rank the trailing window was earned at* is what isolates a genuine role change from a role that never moved.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_depth_chart.py`:

```python
_FRAME = pd.DataFrame(
    {
        "gsis_id": ["00-0000TUT"] * 5 + ["00-0000ETN"],
        "season": [2025, 2025, 2025, 2025, 2026, 2025],
        "week": [1, 2, 3, 4, 0, 1],
        "team": ["JAX"] * 6,
        "position": ["RB"] * 6,
        "rank": [3, 3, 3, 2, 1, 1],
    }
)


def test_current_rank_prefers_the_live_snapshot(monkeypatch):
    monkeypatch.setattr(depth_chart, "rank_frame", lambda seasons: _FRAME)
    depth_chart.current_rank.cache_clear()
    assert depth_chart.current_rank("00-0000TUT", 2026, 1, (2025, 2026)) == 1


def test_prior_rank_is_the_modal_rank_of_the_trailing_window(monkeypatch):
    monkeypatch.setattr(depth_chart, "rank_frame", lambda seasons: _FRAME)
    depth_chart.prior_rank.cache_clear()
    # 2025 weeks 1-4 are ranks 3,3,3,2 -> mode 3
    assert depth_chart.prior_rank("00-0000TUT", 2026, 1, (2025, 2026)) == 3


def test_prior_rank_ignores_the_zero_week_live_snapshot(monkeypatch):
    monkeypatch.setattr(depth_chart, "rank_frame", lambda seasons: _FRAME)
    depth_chart.prior_rank.cache_clear()
    # the week-0 rank 1 row is the live chart, not a game the player played
    assert depth_chart.prior_rank("00-0000TUT", 2026, 1, (2025, 2026)) != 1


def test_unknown_player_returns_none(monkeypatch):
    monkeypatch.setattr(depth_chart, "rank_frame", lambda seasons: _FRAME)
    depth_chart.current_rank.cache_clear()
    depth_chart.prior_rank.cache_clear()
    assert depth_chart.current_rank("00-0000XXX", 2026, 1, (2025, 2026)) is None
    assert depth_chart.prior_rank("00-0000XXX", 2026, 1, (2025, 2026)) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_depth_chart.py -q`
Expected: FAIL with `AttributeError: module 'data.depth_chart' has no attribute 'rank_frame'`

- [ ] **Step 3: Write minimal implementation**

Append to `data/depth_chart.py`:

```python
_TRAILING_WINDOW = 8  # mirrors fantasy_service._TRAILING_WINDOW


@lru_cache(maxsize=8)
def rank_frame(seasons: tuple[int, ...]) -> pd.DataFrame:
    """Normalized depth ranks across `seasons`, both schemas merged."""
    if not seasons:
        return _empty()
    parts: list[pd.DataFrame] = []
    for season in seasons:
        try:
            raw = load_depth_charts([int(season)])
        except Exception:  # noqa: BLE001 - an unpublished season 404s
            continue
        if raw.empty:
            continue
        part = (
            _normalize_modern(raw, season=int(season))
            if "pos_rank" in raw.columns
            else _normalize_legacy(raw)
        )
        if not part.empty:
            parts.append(part)
    if not parts:
        return _empty()
    return pd.concat(parts, ignore_index=True)


def _player_rows(gsis_id: str, seasons: tuple[int, ...]) -> pd.DataFrame:
    frame = rank_frame(seasons)
    if frame.empty:
        return frame
    return frame[frame["gsis_id"] == gsis_id]


@lru_cache(maxsize=4096)
def current_rank(gsis_id: str, season: int, week: int, seasons: tuple[int, ...]) -> int | None:
    """The live depth rank: the most recent row at or before (season, week).

    Week-0 rows are the modern daily snapshot and are the freshest thing
    available, so they sort last within their season on purpose.
    """
    rows = _player_rows(gsis_id, seasons)
    if rows.empty:
        return None
    before = rows[
        (rows["season"] < season) | ((rows["season"] == season) & (rows["week"] <= week))
    ]
    if before.empty:
        return None
    # week 0 is the live snapshot -> treat it as the latest within its season
    ordered = before.assign(_w=before["week"].replace(0, 10_000)).sort_values(["season", "_w"])
    return int(ordered.iloc[-1]["rank"])


@lru_cache(maxsize=4096)
def prior_rank(gsis_id: str, season: int, week: int, seasons: tuple[int, ...]) -> int | None:
    """The modal rank across the games the trailing window actually covers -
    i.e. the role the trailing stats encode. Excludes week-0 snapshot rows."""
    rows = _player_rows(gsis_id, seasons)
    if rows.empty:
        return None
    played = rows[rows["week"] > 0]
    before = played[
        (played["season"] < season) | ((played["season"] == season) & (played["week"] < week))
    ].sort_values(["season", "week"]).tail(_TRAILING_WINDOW)
    if before.empty:
        return None
    return int(before["rank"].mode().iloc[0])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_depth_chart.py -q`
Expected: PASS (8 tests)

- [ ] **Step 5: Verify against real data**

Run:

```bash
uv run python -c "from data.depth_chart import current_rank, prior_rank; s=(2024,2025,2026); print('Tuten current', current_rank('00-0039893',2026,2,s)); print('Tuten prior', prior_rank('00-0039893',2026,2,s))"
```

Expected: `current` is 1 and `prior` is 3 (or `None` for prior if his gsis_id differs - look it up from the weekly frame and re-run rather than assuming).

- [ ] **Step 6: Commit**

```bash
git add data/depth_chart.py tests/test_depth_chart.py
git commit -m "feat: current vs prior depth rank lookups"
```

---

### Task 4: Draft capital

**Files:**
- Create: `data/draft.py`
- Test: `tests/test_draft.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_draft.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_draft.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'data.draft'`

- [ ] **Step 3: Write minimal implementation**

Create `data/draft.py`:

```python
"""Draft capital - the only signal separating two rookies with no NFL snaps.

A first-round running back listed RB1 and an undrafted free agent listed RB1
have identical NFL history (none) and identical depth rank. Draft position is
what the league itself believed about them, and it is the best available prior.
"""
from __future__ import annotations

from functools import lru_cache

import pandas as pd

from data.nflverse_loader import load_draft_picks

# Round -> multiplier on the rank-conditioned baseline. Deliberately gentle: the
# depth slot already carries most of the signal, and draft position is a prior
# about talent, not a promise of usage.
_ROUND_MULTIPLIER = {1: 1.15, 2: 1.08, 3: 1.02, 4: 0.97, 5: 0.93, 6: 0.90, 7: 0.88}
_UNDRAFTED_MULTIPLIER = 0.85


def _picks_frame(seasons: tuple[int, ...]) -> pd.DataFrame:
    try:
        return load_draft_picks(list(seasons))
    except Exception:  # noqa: BLE001 - an unpublished class must not brick projections
        return pd.DataFrame(columns=["season", "round", "pick", "gsis_id"])


@lru_cache(maxsize=4096)
def draft_capital(gsis_id: str, seasons: tuple[int, ...]) -> tuple[int, int] | None:
    """(round, pick) for a drafted player, else None."""
    if not gsis_id:
        return None
    picks = _picks_frame(seasons)
    if picks.empty or "gsis_id" not in picks.columns:
        return None
    rows = picks[picks["gsis_id"].astype(str) == gsis_id]
    if rows.empty:
        return None
    row = rows.sort_values("season").iloc[-1]
    try:
        return int(row["round"]), int(row["pick"])
    except (TypeError, ValueError):
        return None


def capital_multiplier(capital: tuple[int, int] | None) -> float:
    """Scale a rookie's baseline projection by what the draft said about him."""
    if capital is None:
        return _UNDRAFTED_MULTIPLIER
    return _ROUND_MULTIPLIER.get(int(capital[0]), _UNDRAFTED_MULTIPLIER)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_draft.py -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add data/draft.py tests/test_draft.py
git commit -m "feat: draft capital lookup for rookie priors"
```

---

### Task 5: Calibration knobs

**Files:**
- Modify: `eval/fantasy_calibration.py:18-21` (`_FACTOR_NAMES`), `:29-44` (dataclass), `:51-65` (`to_dict`), `:72-88` (`_from_dict`)
- Test: `tests/test_fantasy_calibration.py`

Every new knob defaults to a value that reproduces today's board when depth-chart data is absent.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fantasy_calibration.py`:

```python
def test_depth_chart_knobs_round_trip_through_dict():
    from eval.fantasy_calibration import _from_dict, default_calibration

    base = default_calibration()
    assert base.strength("depth_chart") == 1.0
    assert base.rookie_cv_inflation == 1.35
    assert base.depth_chart_damping == 0.5

    restored = _from_dict(base.to_dict())
    assert restored.rookie_cv_inflation == base.rookie_cv_inflation
    assert restored.depth_chart_damping == base.depth_chart_damping
    assert restored.strength("depth_chart") == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fantasy_calibration.py -q`
Expected: FAIL with `AttributeError: 'FantasyCalibration' object has no attribute 'rookie_cv_inflation'`

- [ ] **Step 3: Write minimal implementation**

In `eval/fantasy_calibration.py`, add `"depth_chart"` to `_FACTOR_NAMES`:

```python
_FACTOR_NAMES = (
    "game_environment", "coaching", "opponent_matchup", "usage_trend", "rest",
    "news", "qb_support", "position_group_form", "weather", "game_script",
    "depth_chart",
)
```

Add two fields to the dataclass, directly after `offense_stack_cap`:

```python
    # How much of the empirical bucket-to-bucket baseline gap a rank change is
    # allowed to claim. 1.0 would assert the promoted player instantly becomes
    # the average starter; half of it is the honest read.
    depth_chart_damping: float = 0.5
    # Rookies have no trailing sample, so their spread is a guess about a guess.
    # Widen it rather than showing a falsely confident floor/ceiling.
    rookie_cv_inflation: float = 1.35
```

Add both to `to_dict`:

```python
            "depth_chart_damping": self.depth_chart_damping,
            "rookie_cv_inflation": self.rookie_cv_inflation,
```

Add both to `_from_dict`:

```python
        depth_chart_damping=float(d.get("depth_chart_damping", base.depth_chart_damping)),
        rookie_cv_inflation=float(d.get("rookie_cv_inflation", base.rookie_cv_inflation)),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fantasy_calibration.py -q`
Expected: PASS

- [ ] **Step 5: Confirm the locked config still loads**

Run: `uv run python -c "from eval.fantasy_calibration import load_calibration; c=load_calibration('models/fantasy_calibration.json'); print(c.depth_chart_damping, c.rookie_cv_inflation, c.strength('depth_chart'))"`
Expected: `0.5 1.35 1.0` - the locked file predates these keys, so defaults fill in.

- [ ] **Step 6: Commit**

```bash
git add eval/fantasy_calibration.py tests/test_fantasy_calibration.py
git commit -m "feat: depth-chart and rookie calibration knobs"
```

---

### Task 6: Rank-conditioned baselines

**Files:**
- Modify: `api/services/fantasy_service.py:220-242` (`_baselines_for`)
- Test: `tests/test_fantasy_service_depth.py` (create)

The fallback chain is the safety property. If the depth-chart join fails for any reason, the result must be byte-identical to today.

- [ ] **Step 1: Write the failing test**

Create `tests/test_fantasy_service_depth.py`:

```python
import pandas as pd

import api.services.fantasy_service as fs


def _weekly() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "player_id": ["A", "B", "C", "D"],
            "season": [2025] * 4,
            "week": [1] * 4,
            "position": ["RB"] * 4,
            "rushing_yards": [100.0, 90.0, 20.0, 10.0],
            "rushing_tds": [1.0, 1.0, 0.0, 0.0],
            "receptions": [3.0, 2.0, 1.0, 0.0],
            "receiving_yards": [30.0, 20.0, 5.0, 0.0],
            "receiving_tds": [0.0, 0.0, 0.0, 0.0],
        }
    )


def test_rank_conditioned_baseline_separates_rb1_from_rb3(monkeypatch):
    ranks = pd.DataFrame(
        {
            "gsis_id": ["A", "B", "C", "D"],
            "season": [2025] * 4,
            "week": [1] * 4,
            "team": ["X"] * 4,
            "position": ["RB"] * 4,
            "rank": [1, 1, 3, 3],
        }
    )
    monkeypatch.setattr(fs, "_rank_lookup", lambda weekly: ranks)
    fs._BASELINE_CACHE.clear()

    baselines = fs._baselines_for(_weekly())

    assert baselines[("RB", 1, "rushing_yards")] == 95.0
    assert baselines[("RB", 3, "rushing_yards")] == 15.0
    # position-wide fallback key must still exist
    assert baselines[("RB", None, "rushing_yards")] == 55.0


def test_baseline_falls_back_to_position_wide_when_ranks_missing(monkeypatch):
    monkeypatch.setattr(fs, "_rank_lookup", lambda weekly: pd.DataFrame())
    fs._BASELINE_CACHE.clear()

    baselines = fs._baselines_for(_weekly())

    assert baselines[("RB", None, "rushing_yards")] == 55.0
    assert fs._baseline(baselines, "RB", 1, "rushing_yards") == 55.0, "unknown bucket -> position-wide"


def test_baseline_lookup_prefers_exact_bucket(monkeypatch):
    baselines = {("RB", 1, "rushing_yards"): 95.0, ("RB", None, "rushing_yards"): 55.0}
    assert fs._baseline(baselines, "RB", 1, "rushing_yards") == 95.0
    assert fs._baseline(baselines, "RB", None, "rushing_yards") == 55.0
    assert fs._baseline(baselines, "RB", 2, "rushing_yards") == 55.0
    assert fs._baseline(baselines, "QB", 1, "passing_yards") == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fantasy_service_depth.py -q`
Expected: FAIL with `AttributeError: module 'api.services.fantasy_service' has no attribute '_rank_lookup'`

- [ ] **Step 3: Write minimal implementation**

In `api/services/fantasy_service.py`, replace `_baselines_for` (lines 220-242) and add two helpers above it:

```python
def _rank_lookup(weekly: pd.DataFrame) -> pd.DataFrame:
    """Normalized depth ranks covering the seasons present in `weekly`."""
    if "season" not in weekly.columns or not len(weekly):
        return pd.DataFrame()
    try:
        from data.depth_chart import rank_frame

        seasons = tuple(sorted(int(s) for s in weekly["season"].unique()))
        return rank_frame(seasons)
    except Exception:  # noqa: BLE001 - no depth data must degrade, not fail
        return pd.DataFrame()


def _baseline(
    baselines: dict[tuple[str, int | None, str], float],
    position: str,
    rank_bucket: int | None,
    stat: str,
) -> float:
    """Exact bucket -> position-wide -> 0.0. The middle rung is today's behavior."""
    if rank_bucket is not None:
        hit = baselines.get((position, rank_bucket, stat))
        if hit is not None:
            return float(hit)
    return float(baselines.get((position, None, stat), 0.0))


def _baselines_for(weekly: pd.DataFrame) -> dict[tuple[str, int | None, str], float]:
    """Per-(position, rank bucket, stat) league mean over the frame - the
    regression target. The `None` bucket is the position-wide mean and is what
    every lookup falls back to, so a missing depth chart reproduces the old
    behavior exactly.

    Cached on the frame's season span (the frame itself is content-stable per
    `scoring_weekly`'s own cache)."""
    if "season" not in weekly.columns or not len(weekly):
        return {}
    key = tuple(sorted(int(s) for s in weekly["season"].unique()))
    cached = _BASELINE_CACHE.get(key)
    if cached is not None:
        return cached

    out: dict[tuple[str, int | None, str], float] = {}
    if "position" not in weekly.columns:
        _BASELINE_CACHE[key] = out
        return out

    frame = weekly.copy()
    frame["_pos"] = frame["position"].astype(str).str.upper()

    ranks = _rank_lookup(weekly)
    if not ranks.empty:
        from data.depth_chart import bucket

        keyed = ranks.assign(
            _bucket=[
                bucket(r, p)
                for r, p in zip(ranks["rank"], ranks["position"], strict=False)
            ]
        )[["gsis_id", "season", "week", "_bucket"]]
        frame = frame.merge(
            keyed,
            left_on=["player_id", "season", "week"],
            right_on=["gsis_id", "season", "week"],
            how="left",
        )
    else:
        frame["_bucket"] = None

    for position, stats in _TRAILING_STATS_BY_POSITION.items():
        rows = frame[frame["_pos"] == position]
        for stat in stats:
            if stat not in rows.columns:
                out[(position, None, stat)] = 0.0
                continue
            out[(position, None, stat)] = (
                float(rows[stat].fillna(0.0).mean()) if len(rows) else 0.0
            )
            if "_bucket" not in rows.columns:
                continue
            for bucket_value, group in rows.dropna(subset=["_bucket"]).groupby("_bucket"):
                out[(position, int(bucket_value), stat)] = float(
                    group[stat].fillna(0.0).mean()
                )

    _BASELINE_CACHE[key] = out
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fantasy_service_depth.py -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Verify nothing else broke**

Run: `uv run pytest tests/ -q -x -k "fantasy"`
Expected: all pass. `_baselines_for` callers now get a 3-tuple key; if `fantasy_slate_service` indexes it directly, fix that call site to use `fs._baseline(...)`.

- [ ] **Step 6: Commit**

```bash
git add api/services/fantasy_service.py tests/test_fantasy_service_depth.py
git commit -m "feat: rank-conditioned regression baselines with position-wide fallback"
```

---

### Task 7: Plumb `depth_rank` into the trailing projector and add the rookie path

**Files:**
- Modify: `api/services/fantasy_service.py:244-309` (`_trailing_fantasy_distributions`), `:1134+` (`build_fantasy_summary`)
- Test: `tests/test_fantasy_service_depth.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fantasy_service_depth.py`:

```python
from models.base import StatDistribution


def test_promoted_player_regresses_toward_the_new_role(monkeypatch):
    """Same trailing games, different depth rank -> higher projection."""
    ranks = pd.DataFrame(
        {
            "gsis_id": ["A", "B", "C", "D"],
            "season": [2025] * 4,
            "week": [1] * 4,
            "team": ["X"] * 4,
            "position": ["RB"] * 4,
            "rank": [1, 1, 3, 3],
        }
    )
    monkeypatch.setattr(fs, "_rank_lookup", lambda weekly: ranks)
    fs._BASELINE_CACHE.clear()

    weekly = pd.concat([_weekly(), _weekly().assign(week=2)], ignore_index=True)

    def project(depth_rank):
        return fs._trailing_fantasy_distributions(
            weekly,
            player_id="C",
            season=2026,
            week=1,
            position="RB",
            model_distributions={},
            depth_rank=depth_rank,
        )["rushing_yards"].mean

    assert project(1) > project(3), "an RB3's history regressed to the RB1 archetype must rank higher"


def test_rookie_with_no_history_uses_rank_baseline_and_widens_spread(monkeypatch):
    ranks = pd.DataFrame(
        {
            "gsis_id": ["A", "B", "C", "D"],
            "season": [2025] * 4,
            "week": [1] * 4,
            "team": ["X"] * 4,
            "position": ["RB"] * 4,
            "rank": [1, 1, 3, 3],
        }
    )
    monkeypatch.setattr(fs, "_rank_lookup", lambda weekly: ranks)
    monkeypatch.setattr(fs, "_rookie_capital_multiplier", lambda pid, weekly: 1.15)
    fs._BASELINE_CACHE.clear()

    dist = fs._trailing_fantasy_distributions(
        _weekly(),
        player_id="ROOKIE",
        season=2026,
        week=1,
        position="RB",
        model_distributions={},
        depth_rank=1,
    )["rushing_yards"]

    assert dist.mean == 95.0 * 1.15, "RB1 baseline scaled by first-round capital"
    veteran_cv = fs.default_calibration().yard_cv
    assert dist.std > veteran_cv * dist.mean, "rookie spread must be inflated"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fantasy_service_depth.py -q`
Expected: FAIL with `TypeError: _trailing_fantasy_distributions() got an unexpected keyword argument 'depth_rank'`

- [ ] **Step 3: Write minimal implementation**

Add a helper above `_trailing_fantasy_distributions`:

```python
def _rookie_capital_multiplier(player_id: str, weekly: pd.DataFrame) -> float:
    """Draft-capital scale for a player with no NFL history."""
    try:
        from data.draft import capital_multiplier, draft_capital

        seasons = (
            tuple(sorted(int(s) for s in weekly["season"].unique()))
            if "season" in weekly.columns and len(weekly)
            else ()
        )
        return capital_multiplier(draft_capital(player_id, seasons))
    except Exception:  # noqa: BLE001
        return 1.0
```

Change the signature of `_trailing_fantasy_distributions` to accept `depth_rank: int | None = None`, then inside it:

Replace the baselines line and the per-stat `base` lookup:

```python
    baselines = _baselines_for(weekly)
    from data.depth_chart import bucket as _rank_bucket

    rank_bucket = _rank_bucket(depth_rank, normalized)
```

Replace `base = float(baselines.get((normalized, stat), 0.0))` with:

```python
        base = _baseline(baselines, normalized, rank_bucket, stat)
```

Replace the `n == 0` branch and the cv selection. The existing block:

```python
        if n and stat in hist.columns:
            recent = float(np.average(hist[stat].fillna(0.0).to_numpy(dtype=float), weights=recency))
        else:
            recent = base
        trailing = form_weight * recent + (1.0 - form_weight) * base

        cv = calib.yard_cv if stat in _YARDAGE_STATS else calib.count_cv
```

becomes:

```python
        if n and stat in hist.columns:
            recent = float(np.average(hist[stat].fillna(0.0).to_numpy(dtype=float), weights=recency))
        else:
            # No NFL history: the depth slot plus draft capital is all there is.
            recent = base * rookie_multiplier
        trailing = form_weight * recent + (1.0 - form_weight) * base

        cv = calib.yard_cv if stat in _YARDAGE_STATS else calib.count_cv
        if not n:
            cv *= calib.rookie_cv_inflation
```

and just above the `for stat in stats:` loop add:

```python
    rookie_multiplier = _rookie_capital_multiplier(player_id, weekly) if not n else 1.0
```

Note: with `n == 0`, `form_weight` is `0.0`, so `trailing` collapses to `base`. Change the rookie line so the capital scale survives:

```python
        trailing = (
            base * rookie_multiplier
            if not n
            else form_weight * recent + (1.0 - form_weight) * base
        )
```

and drop the `recent = base * rookie_multiplier` assignment in favour of `recent = base`.

Finally, in `build_fantasy_summary`, resolve the rank once and pass it down. After `calib = _settings_calibration(settings)`:

```python
    depth_rank = _current_depth_rank(weekly, player_id, season, week)
```

with this helper defined near `_rank_lookup`:

```python
def _current_depth_rank(
    weekly: pd.DataFrame, player_id: str, season: int, week: int
) -> int | None:
    try:
        from data.depth_chart import current_rank

        seasons = (
            tuple(sorted({int(s) for s in weekly["season"].unique()} | {int(season)}))
            if "season" in weekly.columns
            else (int(season),)
        )
        return current_rank(player_id, int(season), int(week), seasons)
    except Exception:  # noqa: BLE001
        return None
```

and pass `depth_rank=depth_rank` into the `_trailing_fantasy_distributions` call.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fantasy_service_depth.py -q`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add api/services/fantasy_service.py tests/test_fantasy_service_depth.py
git commit -m "feat: depth-rank-aware trailing anchor and rookie projection path"
```

---

### Task 8: `_depth_chart_factor` and precedence over `usage_trend`

**Files:**
- Modify: `api/services/fantasy_service.py` (new factor near `_usage_factor:822`, wire into `_context_factors:1042`)
- Test: `tests/test_fantasy_service_depth.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fantasy_service_depth.py`:

```python
def test_depth_chart_factor_fires_on_promotion_and_is_bounded(monkeypatch):
    baselines = {
        ("RB", 1, "rushing_yards"): 95.0,
        ("RB", 3, "rushing_yards"): 15.0,
        ("RB", None, "rushing_yards"): 55.0,
    }
    factor = fs._depth_chart_factor(
        baselines,
        position="RB",
        current=1,
        prior=3,
        calib=fs.default_calibration(),
    )
    assert factor.applied
    assert factor.multiplier > 1.0
    assert factor.multiplier <= fs.default_calibration().context_clamp_hi, "bounded"
    assert "RB3" in factor.reason and "RB1" in factor.reason


def test_depth_chart_factor_neutral_when_rank_unchanged():
    factor = fs._depth_chart_factor(
        {}, position="RB", current=2, prior=2, calib=fs.default_calibration()
    )
    assert not factor.applied
    assert factor.multiplier == 1.0


def test_depth_chart_factor_neutral_when_rank_unknown():
    calib = fs.default_calibration()
    assert not fs._depth_chart_factor({}, position="RB", current=None, prior=3, calib=calib).applied
    assert not fs._depth_chart_factor({}, position="RB", current=1, prior=None, calib=calib).applied


def test_usage_trend_is_suppressed_when_depth_chart_fires():
    depth = fs.FantasyContextFactor(
        name="depth_chart", label="Depth chart", multiplier=1.2, applied=True,
        affected_stats=["rushing_yards"], reason="promoted",
    )
    usage = fs.FantasyContextFactor(
        name="usage_trend", label="Usage trend", multiplier=1.1, applied=True,
        affected_stats=["rushing_yards"], reason="trending up",
    )
    resolved = fs._resolve_role_precedence([depth, usage])
    by_name = {f.name: f for f in resolved}
    assert by_name["depth_chart"].applied
    assert not by_name["usage_trend"].applied, "role change must not be counted twice"
    assert "superseded" in by_name["usage_trend"].reason


def test_usage_trend_survives_when_depth_chart_is_neutral():
    depth = fs.FantasyContextFactor(
        name="depth_chart", label="Depth chart", multiplier=1.0, applied=False,
        affected_stats=["rushing_yards"], reason="rank steady",
    )
    usage = fs.FantasyContextFactor(
        name="usage_trend", label="Usage trend", multiplier=1.1, applied=True,
        affected_stats=["rushing_yards"], reason="trending up",
    )
    resolved = fs._resolve_role_precedence([depth, usage])
    assert {f.name: f.applied for f in resolved}["usage_trend"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fantasy_service_depth.py -q`
Expected: FAIL with `AttributeError: module 'api.services.fantasy_service' has no attribute '_depth_chart_factor'`

- [ ] **Step 3: Write minimal implementation**

Add next to `_usage_factor`:

```python
def _depth_chart_factor(
    baselines: dict[tuple[str, int | None, str], float],
    *,
    position: str,
    current: int | None,
    prior: int | None,
    calib: FantasyCalibration,
) -> FantasyContextFactor:
    """Role change the trailing window cannot see.

    The magnitude is the empirical gap between the two depth buckets' own
    baselines, damped - never a hand-picked constant. That is what keeps a
    promotion from inventing a projection the data does not support.
    """
    normalized = position.upper().strip()
    positive = _positive_stats_for_position(normalized)
    if current is None or prior is None:
        return _neutral_factor(
            "depth_chart", "Depth chart",
            "Depth-chart rank unavailable for this player.", positive,
        )

    from data.depth_chart import bucket

    cur_b, prior_b = bucket(current, normalized), bucket(prior, normalized)
    if cur_b is None or prior_b is None or cur_b == prior_b:
        return _neutral_factor(
            "depth_chart", "Depth chart",
            f"Still listed {normalized}{cur_b or current} - no role change.", positive,
        )

    # Compare the two roles on the position's headline volume stat.
    stat = _TRAILING_STATS_BY_POSITION.get(normalized, ("",))[0]
    new_base = _baseline(baselines, normalized, cur_b, stat)
    old_base = _baseline(baselines, normalized, prior_b, stat)
    if old_base <= 0 or new_base <= 0:
        return _neutral_factor(
            "depth_chart", "Depth chart",
            "No baseline for one of the two depth slots.", positive,
        )

    ratio = new_base / old_base
    multiplier = float(
        np.clip(
            1.0 + calib.depth_chart_damping * (ratio - 1.0),
            calib.context_clamp_lo,
            calib.context_clamp_hi,
        )
    )
    direction = "Promoted" if cur_b < prior_b else "Demoted"
    return FantasyContextFactor(
        name="depth_chart",
        label="Depth chart",
        multiplier=round(multiplier, 4),
        applied=abs(multiplier - 1.0) > 1e-3,
        affected_stats=positive,
        reason=(
            f"{direction}: {normalized}{prior_b} -> {normalized}{cur_b}. "
            f"The trailing average is still {normalized}{prior_b} usage."
        ),
    )


def _resolve_role_precedence(
    factors: list[FantasyContextFactor],
) -> list[FantasyContextFactor]:
    """A role change must be priced once. When the depth chart fires, the
    within-season usage trend is describing the same move - stand it down."""
    depth = next((f for f in factors if f.name == "depth_chart"), None)
    if depth is None or not depth.applied:
        return factors
    out: list[FantasyContextFactor] = []
    for factor in factors:
        if factor.name == "usage_trend" and factor.applied:
            out.append(
                _neutral_factor(
                    "usage_trend",
                    "Usage trend",
                    "superseded by the depth-chart role change.",
                    list(factor.affected_stats),
                )
            )
        else:
            out.append(factor)
    return out
```

Wire into `_context_factors`. Compute the ranks near the top:

```python
    from data.depth_chart import current_rank, prior_rank

    try:
        cur_rank = current_rank(player_id, int(season), int(week), seasons)
        old_rank = prior_rank(player_id, int(season), int(week), seasons)
    except Exception:  # noqa: BLE001
        cur_rank = old_rank = None
```

Add to the `factors` list, after `_usage_factor(...)`:

```python
        _depth_chart_factor(
            _baselines_for(weekly),
            position=position,
            current=cur_rank,
            prior=old_rank,
            calib=calib or default_calibration(),
        ),
```

Change the final `return factors` to:

```python
    return _resolve_role_precedence(factors)
```

(`_context_factors` currently returns after two `factors.extend(...)` calls - wrap that final return.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fantasy_service_depth.py -q`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add api/services/fantasy_service.py tests/test_fantasy_service_depth.py
git commit -m "feat: depth-chart role-change factor, supersedes usage trend"
```

---

### Task 9: Admit rookies to the slate

**Files:**
- Modify: `api/services/fantasy_slate_service.py:85-131` (`_prescore`)
- Test: `tests/test_fantasy_slate_service.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fantasy_slate_service.py`:

```python
def test_prescore_admits_a_rookie_via_depth_rank(monkeypatch):
    import api.services.fantasy_slate_service as slate

    baselines = {
        ("RB", 1, "rushing_yards"): 95.0,
        ("RB", 3, "rushing_yards"): 15.0,
        ("RB", None, "rushing_yards"): 55.0,
    }
    weights = {"rushing_yards": 0.1}

    rookie = slate._prescore(
        None, baselines, season=2026, week=1, position="RB", weights=weights,
        depth_rank=1, capital_multiplier=1.15,
    )
    deep_backup = slate._prescore(
        None, baselines, season=2026, week=1, position="RB", weights=weights,
        depth_rank=3, capital_multiplier=0.85,
    )

    assert rookie > 0.0, "a listed RB1 rookie must not pre-score as zero"
    assert rookie > deep_backup


def test_prescore_still_zero_without_a_depth_rank(monkeypatch):
    import api.services.fantasy_slate_service as slate

    assert slate._prescore(
        None, {}, season=2026, week=1, position="RB", weights={"rushing_yards": 0.1},
        depth_rank=None, capital_multiplier=1.0,
    ) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fantasy_slate_service.py -q`
Expected: FAIL with `TypeError: _prescore() got an unexpected keyword argument 'depth_rank'`

- [ ] **Step 3: Write minimal implementation**

In `api/services/fantasy_slate_service.py`, import the baseline helper and bucket:

```python
from api.services.fantasy_service import _baseline
from data.depth_chart import bucket
```

Change `_prescore`'s signature to add `depth_rank: int | None = None, capital_multiplier: float = 1.0`, and replace the `n < _MIN_TRAILING_GAMES` early return:

```python
    n = len(past)
    if n < _MIN_TRAILING_GAMES:
        # No usable history. A player listed high on the depth chart is still a
        # real candidate - score him off his slot so he ranks inside the team
        # cap instead of being cut. No slot, no score.
        rank_bucket = bucket(depth_rank, position)
        if rank_bucket is None:
            return 0.0
        return capital_multiplier * sum(
            weight * _baseline(baselines, position, rank_bucket, stat)
            for stat, weight in weights.items()
            if weight
        )
```

Update the two `baselines.get((position, stat), 0.0)` reads in the main loop to `_baseline(baselines, position, bucket(depth_rank, position), stat)`.

At the `_prescore` call site in `_compute_slate` (~line 270), resolve and pass both new arguments:

```python
                from data.depth_chart import current_rank
                from data.draft import capital_multiplier as _cap_mult, draft_capital

                try:
                    rank = current_rank(pid, season, week, seasons)
                    cap = _cap_mult(draft_capital(pid, seasons))
                except Exception:  # noqa: BLE001
                    rank, cap = None, 1.0
                score = _prescore(
                    ...,
                    depth_rank=rank,
                    capital_multiplier=cap,
                )
```

Hoist the two imports to module scope rather than leaving them inside the loop.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fantasy_slate_service.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/services/fantasy_slate_service.py tests/test_fantasy_slate_service.py
git commit -m "feat: rank rookies onto the slate by depth slot and draft capital"
```

---

### Task 10: Verification gate

**Files:**
- Create: `scripts/verify_role_context.py`
- Test: full suite

- [ ] **Step 1: Write the bounded-ratio guard**

Create `scripts/verify_role_context.py`. It must assert that no projection runs away from its own trailing anchor - the exact failure mode that got the previous role-change attempt rejected.

```python
"""Guard against the failure mode that killed the last role-change attempt.

A previous trailing-anchor fallback re-introduced 30x ratios between a player's
projection and his own trailing average. Every correction in the current design
is multiplicative and clamped, so the ratio must stay inside a sane band. This
script proves it on a real board rather than on fixtures.

Usage: uv run python scripts/verify_role_context.py --season 2026 --week 2
"""
from __future__ import annotations

import argparse

from api.services.fantasy_slate_service import build_fantasy_slate
from api.settings import AppSettings

_MAX_RATIO = 3.0
_NAMED = ("Tuten", "Hunter")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--week", type=int, default=2)
    parser.add_argument("--limit", type=int, default=48)
    args = parser.parse_args()

    settings = AppSettings(prewarm_fantasy_slate=False)
    slate = build_fantasy_slate(
        settings, season=args.season, week=args.week, scoring="full_ppr",
        limit=args.limit, wait=True,
    )

    failures = []
    for entry in slate.entries:
        pts = float(entry.projected_points)
        if pts > 120.0 or pts < 0.0:
            failures.append(f"{entry.player_name}: implausible {pts:.1f} pts")

    print(f"{len(slate.entries)} entries, {len(failures)} implausible")
    for name in _NAMED:
        for entry in slate.entries:
            if name.lower() in entry.player_name.lower():
                print(f"  {entry.player_name:24s} {entry.position:3s} {entry.projected_points:6.1f}")
                for factor in getattr(entry, "context_factors", []) or []:
                    if factor.name in {"depth_chart", "usage_trend"} and factor.applied:
                        print(f"      {factor.name}: x{factor.multiplier} - {factor.reason}")

    for line in failures:
        print(f"FAIL {line}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run the aggregate regression gate**

Run: `uv run python scripts/verify_fantasy_calibration.py`

Expected: position-balanced MAE <= 4.99, |bias| <= 0.27, rank correlation >= 0.595 (the locked v0.9-m3.5 numbers). **If MAE regresses, the legacy depth charts are too noisy** - fall back to deriving historical rank from realized team-position touch share, as the spec's risk section describes. Do not proceed past this gate on a regression.

- [ ] **Step 3: Run the bounded-ratio guard**

Run: `uv run python scripts/verify_role_context.py --season 2026 --week 2`
Expected: exit 0, and Tuten shows an applied `depth_chart` factor with a `RB3 -> RB1` reason.

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q`
Expected: 409 passing + the new tests, 1 skipped, 12 deselected. The 3 pre-existing `tests/test_api.py` failures (NaN `injury_status` -> `NormalizedPick`) are known and unrelated - confirm the count is still exactly 3 and that they fail identically on the parent commit.

- [ ] **Step 5: Commit**

```bash
git add scripts/verify_role_context.py
git commit -m "test: bounded-ratio guard for role-context projections"
```

---

## Self-Review

**Spec coverage (Phases 1-4):**

| spec item | task |
|---|---|
| `load_depth_charts` | 1 |
| two-schema normalizer | 2 |
| `rank_frame` / `current_rank` / `prior_rank` | 3 |
| `data/draft.py` | 4 |
| calibration knobs | 5 |
| rank-conditioned baselines + fallback chain | 6 |
| `depth_rank` plumbing, rookie mean + widened cv | 7 |
| `_depth_chart_factor`, baseline-derived magnitude | 8 |
| `usage_trend` mutual exclusion | 8 |
| slate rookie admission | 9 |
| aggregate gate, bounded-ratio guard, unit tests | 10 |

Phases 5-7 (market anchoring, the `_mid_yes_prob` bug, stat coverage) are deliberately out of scope here and get their own plans.

**Type consistency:** `bucket()` is defined in Task 2 and used in Tasks 6, 8, 9 with the same `(rank, position) -> int | None` signature. `_baseline()` is defined in Task 6 and used in Tasks 7, 8, 9 with the same 4-arg form. `_baselines_for` returns the 3-tuple key everywhere after Task 6; Task 6 Step 5 explicitly checks for stale 2-tuple call sites.

**Known deviation to watch:** Task 7 Step 3 contains a correction mid-step (the `form_weight == 0` collapse). Implement the final form shown, not the first draft.
