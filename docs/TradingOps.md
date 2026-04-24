# TradingOps — Paper & Venue Operations Guide

## Modes

| Mode | Status | Notes |
|------|--------|-------|
| **Paper** | Active | Immediate fills at limit price; no real money; no real venue connection |
| **Kalshi (Demo)** | Scaffold only | Activation pending v0.8a-live (preseason ~Aug 2026) |
| **Kalshi (Live)** | Out of scope | v0.9+ after season validates the scaffolding |
| **Polymarket** | Out of scope | v0.9+ |

---

## Paper Trading

Paper mode is always active. The `FakePaperAdapter` fills every valid order at the limit price
immediately — no order-book simulation, no jitter. Use it to:

- Verify the end-to-end pipeline (pick → signal → risk → fill → ledger).
- Test the kill switch behavior before any real venue is connected.
- Build intuition for edge thresholds and position sizing without risking real funds.

**How to use:**
1. Open the Execution page in the desktop app.
2. Submit picks from the queue. Each pick creates an order that fills immediately.
3. Portfolio panel updates in real time.
4. Audit event tail streams all lifecycle events.

---

## Kill Switch

The kill switch is a hard stop. Clicking **KILL SWITCH** on the Execution page:

1. Trips the `StaticRiskEngine` — all subsequent `evaluate()` calls return `approved=False`.
2. Trips the `FakePaperAdapter` (or real adapter once live).
3. Cancels all currently open intents via `cancel_all()`.
4. Appends a `kill_switch` event to the audit log.

**The kill switch is one-way per session.** Restart the sidecar to reset. This is intentional —
a live kill should require a conscious decision to re-enable, not an accidental click.

---

## Secret Vault

Credentials are stored in the OS system keyring via the `keyring` library. They never appear
in config files, logs, or environment variables.

**To provision Kalshi credentials (when scaffold activates):**

1. Start the sidecar. The startup log prints a one-time confirmation token:
   ```
   WARNING  api.routes.secrets: Kalshi secret-vault confirmation token: <token>
   ```

2. POST credentials to the sidecar (local only — the endpoint is not exposed externally):
   ```bash
   curl -X POST http://127.0.0.1:<port>/api/secrets/kalshi \
     -H "Content-Type: application/json" \
     -d '{
       "access_key": "YOUR_KALSHI_ACCESS_KEY",
       "private_key_pem": "-----BEGIN PRIVATE KEY-----\n...",
       "confirm_token": "<token from log>"
     }'
   ```

3. Credentials are stored under `nfl-prop-workstation / kalshi:access_key` and
   `nfl-prop-workstation / kalshi:private_key_pem` in the system keyring.

4. The sidecar reads them at startup via `api.trading.secrets.load("kalshi", ...)`.

---

## Kalshi Integration (Scaffold)

> **Scaffold only — activation pending v0.8a-live**

The Kalshi module is fully shaped but raises `NotImplementedError` on all network calls:

| File | Status |
|------|--------|
| `api/trading/kalshi/signing.py` | **Real** — RSA-PSS signing tested without a Kalshi account |
| `api/trading/kalshi/client.py` | Scaffold — method signatures match the Kalshi REST API |
| `api/trading/kalshi/adapter.py` | Scaffold — wires Protocols to the client |
| `api/trading/kalshi/ws.py` | Scaffold — auth-header construction real; `connect()` raises |

**In-season activation checklist (see plan.md "Season-Start Activation Checklist"):**
1. Provision a Kalshi demo account.
2. POST credentials via `POST /api/secrets/kalshi`.
3. Replace `NotImplementedError` in `kalshi/client.py` with real HTTP calls.
4. Replace `ws.py`'s stub with a real authenticated WebSocket listener.
5. Implement `KalshiMapper.map_signal` using Kalshi's `get_markets` discovery.
6. Enable the venue selector in the Execution page UI.

No file-structure changes required. No caller changes. That is the point of shipping the scaffold now.

---

## Audit Log

All order lifecycle events are appended to `docs/audit/events-<date>.jsonl`.
Portfolio snapshots are written to `docs/audit/portfolio-<session>.json`.

Both paths are append-only. Do not edit these files manually.

---

## Compliance Disclaimer

This software is for personal, research, and paper-trading use only. No financial advice is
implied. The authors are not registered broker-dealers or investment advisors. Use of the Kalshi
integration (when activated) is subject to Kalshi's terms of service and applicable law. Users
are responsible for compliance with all relevant regulations in their jurisdiction.
