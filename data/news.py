"""Free NFL news headlines from ESPN's public site API (no key).

Used by the fantasy "news" context factor as a fast, brief gate: it scans the
last day of team-tagged headlines for high-confidence scheme / role phrases the
historical coaching and injury factors can't see (a mid-week coordinator change,
a surprise benching announced in a presser, "the plan is to lean on the run").
Deterministic keyword match — no LLM in the projection loop.
"""
from __future__ import annotations

import time
from functools import lru_cache

import requests

_ESPN_NEWS = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news"
_TTL_SECONDS = 3600  # headlines don't move intraday enough to refetch faster


def _now_bucket() -> int:
    return int(time.time() // _TTL_SECONDS)


@lru_cache(maxsize=4)
def _all_articles(_bucket: int) -> list[dict]:
    try:
        resp = requests.get(_ESPN_NEWS, params={"limit": 50}, timeout=8)
        resp.raise_for_status()
        return list(resp.json().get("articles", []))
    except Exception:  # noqa: BLE001 - callers degrade to no news
        return []


def _article_teams(article: dict) -> set[str]:
    teams: set[str] = set()
    for cat in article.get("categories", []) or []:
        team = cat.get("team") or {}
        abbr = str(team.get("abbreviation", "")).upper()
        if abbr:
            teams.add(abbr)
    return teams


@lru_cache(maxsize=256)
def _team_headlines_bucketed(team: str, _bucket: int) -> tuple[str, ...]:
    out: list[str] = []
    for art in _all_articles(_bucket):
        if team in _article_teams(art):
            text = f"{art.get('headline', '')}. {art.get('description', '')}".strip().lower()
            if text and text != ".":
                out.append(text)
    return tuple(out)


def team_headlines(team: str) -> tuple[str, ...]:
    """Lower-cased 'headline. description' strings tagged to `team`, refreshed
    hourly. Empty when the feed is unreachable or has nothing for the team."""
    return _team_headlines_bucketed(team.upper(), _now_bucket()) if team else ()
