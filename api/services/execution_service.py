from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from api.schemas import NormalizedPick
from api.trading.audit import log_event
from api.trading.ledger import InMemoryPortfolioLedger
from api.trading.mapper import PickToIntentMapper
from api.trading.paper_adapter import FakePaperAdapter
from api.trading.risk import StaticRiskEngine
from api.trading.types import PortfolioState, Signal


def _pick_to_signal(pick: NormalizedPick) -> Signal:
    pick_id = f"{pick.player_id}-{pick.stat}-{pick.week or 0}"
    side = pick.selected_side if pick.selected_side in ("over", "under") else "over"
    return Signal(
        pick_id=pick_id,
        player_id=pick.player_id,
        stat=pick.stat,
        line=pick.line,
        selected_side=side,  # type: ignore[arg-type]
        modeled_prob=pick.selected_prob,
        edge=pick.selected_edge,
        created_at=datetime.now(timezone.utc),
    )


class ExecutionService:
    def __init__(
        self,
        adapter: FakePaperAdapter,
        ledger: InMemoryPortfolioLedger,
        mapper: PickToIntentMapper,
        risk: StaticRiskEngine,
        audit_dir: Path,
    ) -> None:
        self._adapter = adapter
        self._ledger = ledger
        self._mapper = mapper
        self._risk = risk
        self._audit_dir = audit_dir
        self._open_intents: dict[str, Any] = {}
        self._events: list[dict[str, Any]] = []

    def _append_event(self, kind: str, payload: dict[str, Any]) -> None:
        entry = {"kind": kind, "ts": datetime.now(timezone.utc).isoformat(), **payload}
        self._events.append(entry)
        log_event(kind, payload, self._audit_dir)

    async def submit_picks(self, picks: list[NormalizedPick]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for pick in picks:
            signal = _pick_to_signal(pick)
            markets = await self._adapter.list_markets(signal.stat, signal.player_id)
            intent = self._mapper.map_signal(signal, markets)
            if intent is None:
                entry: dict[str, Any] = {"status": "no_market", "pick_id": signal.pick_id}
                self._append_event("no_market", entry)
                results.append(entry)
                continue

            portfolio = self._ledger.snapshot()
            decision = self._risk.evaluate(intent, portfolio)
            if not decision.approved:
                entry = {
                    "status": "risk_rejected",
                    "intent_id": intent.client_order_id,
                    "pick_id": signal.pick_id,
                    "reason": decision.reason,
                }
                self._append_event("risk_rejected", entry)
                results.append(entry)
                continue

            self._ledger.register_intent(intent)
            self._open_intents[intent.client_order_id] = intent

            order_event = await self._adapter.submit(intent)
            self._ledger.apply(order_event)

            event_entry: dict[str, Any] = {
                "intent_id": order_event.intent_id,
                "event_type": order_event.event_type,
                "venue_order_id": order_event.venue_order_id,
                "price": order_event.price,
                "size": order_event.size,
                "market_id": intent.market_ref.market_id,
                "side": intent.side,
                "edge": intent.edge,
                "pick_id": signal.pick_id,
            }
            self._append_event("order_event", event_entry)

            if order_event.event_type in ("filled", "rejected"):
                self._open_intents.pop(intent.client_order_id, None)

            results.append({
                "status": order_event.event_type,
                "intent_id": intent.client_order_id,
                "pick_id": signal.pick_id,
                "market_id": intent.market_ref.market_id,
                "side": intent.side,
                "limit_price": intent.limit_price,
                "size": intent.size,
                "edge": intent.edge,
            })

        self._ledger.persist()
        return results

    async def cancel(self, intent_id: str) -> dict[str, Any]:
        intent = self._open_intents.pop(intent_id, None)
        if intent is None:
            return {"status": "not_found", "intent_id": intent_id}

        order_event = await self._adapter.cancel(intent.market_ref.market_id)
        entry: dict[str, Any] = {
            "intent_id": intent_id,
            "event_type": "canceled",
            "venue_order_id": order_event.venue_order_id,
        }
        self._append_event("order_event", entry)
        return {"status": "canceled", "intent_id": intent_id}

    def get_portfolio(self) -> PortfolioState:
        return self._ledger.snapshot()

    def get_events(self, since: int = 0) -> list[dict[str, Any]]:
        return self._events[since:]

    async def trip_kill_switch(self, reason: str) -> int:
        self._risk.trip(reason)
        self._adapter.trip(reason)
        canceled = 0
        for intent_id in list(self._open_intents.keys()):
            await self.cancel(intent_id)
            canceled += 1
        self._append_event("kill_switch", {"reason": reason, "canceled": canceled})
        return canceled
