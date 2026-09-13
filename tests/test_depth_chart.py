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
