from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from api.trading.types import ExecutionIntent, PortfolioState, RiskDecision


@dataclass
class StaticRiskEngine:
    max_notional_per_order: float = 100.0
    max_open_notional_per_market: float = 500.0
    daily_loss_cap: float = 200.0
    min_edge: float = 0.03
    reject_cooldown_n: int = 3
    reject_cooldown_seconds: float = 60.0

    _tripped: bool = field(default=False, init=False, repr=False)
    _trip_reason: str = field(default="", init=False, repr=False)
    _reject_times: deque[float] = field(default_factory=deque, init=False, repr=False)

    def evaluate(self, intent: ExecutionIntent, portfolio: PortfolioState) -> RiskDecision:
        if self._tripped:
            return RiskDecision(
                intent_id=intent.client_order_id,
                approved=False,
                reason=f"kill_switch: {self._trip_reason}",
                caps_snapshot=self._caps_snapshot(portfolio),
            )

        notional = intent.limit_price * intent.size

        if notional > self.max_notional_per_order:
            return self._reject(intent, portfolio, f"notional {notional:.2f} > max {self.max_notional_per_order:.2f}")

        market_id = intent.market_ref.market_id
        pos = portfolio.positions.get(market_id)
        open_notional = (pos.size * pos.avg_price if pos else 0.0) + notional
        if open_notional >= self.max_open_notional_per_market:
            return self._reject(
                intent, portfolio,
                f"open_notional {open_notional:.2f} > max {self.max_open_notional_per_market:.2f}",
            )

        total_pnl = portfolio.realized_pnl + portfolio.unrealized_pnl
        if total_pnl < -self.daily_loss_cap:
            return self._reject(
                intent, portfolio,
                f"daily_loss {-total_pnl:.2f} > cap {self.daily_loss_cap:.2f}",
            )

        if intent.edge < self.min_edge:
            return self._reject(intent, portfolio, f"edge {intent.edge:.4f} < min {self.min_edge:.4f}")

        return RiskDecision(
            intent_id=intent.client_order_id,
            approved=True,
            reason="ok",
            caps_snapshot=self._caps_snapshot(portfolio),
        )

    def trip(self, reason: str) -> None:
        self._tripped = True
        self._trip_reason = reason

    def is_tripped(self) -> bool:
        return self._tripped

    def _reject(self, intent: ExecutionIntent, portfolio: PortfolioState, reason: str) -> RiskDecision:
        now = time.monotonic()
        self._reject_times.append(now)
        cutoff = now - self.reject_cooldown_seconds
        while self._reject_times and self._reject_times[0] < cutoff:
            self._reject_times.popleft()
        if len(self._reject_times) >= self.reject_cooldown_n:
            self.trip(f"reject_cooldown: {len(self._reject_times)} rejects in {self.reject_cooldown_seconds}s")
        return RiskDecision(
            intent_id=intent.client_order_id,
            approved=False,
            reason=reason,
            caps_snapshot=self._caps_snapshot(portfolio),
        )

    def _caps_snapshot(self, portfolio: PortfolioState) -> dict[str, float]:
        return {
            "max_notional_per_order": self.max_notional_per_order,
            "max_open_notional_per_market": self.max_open_notional_per_market,
            "daily_loss_cap": self.daily_loss_cap,
            "min_edge": self.min_edge,
            "current_realized_pnl": portfolio.realized_pnl,
            "current_unrealized_pnl": portfolio.unrealized_pnl,
        }
