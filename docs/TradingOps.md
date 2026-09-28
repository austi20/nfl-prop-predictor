# TradingOps: Paper & Venue Operations Guide

## Modes

| Mode | Status | Notes |
|------|--------|-------|
| **Paper** | Active | `RealisticPaperAdapter`: spread, slippage, partial fills, non-fills. No real money |
| **Kalshi market data** | Live | Public reads anchor projections to coin-flip lines and feed the prop board |
| **Kalshi orders** | Not built | `KalshiClient` order methods raise `NotImplementedError`; not scheduled |

---

## Paper Trading

The Trading (Paper) tab runs the full pipeline (pick, signal, risk, fill, ledger) against
`RealisticPaperAdapter` with `ExposureRiskEngine`. Set `NFL_APP_USE_REALISTIC_PAPER=0` for
`FakePaperAdapter` (instant fills at limit) and `NFL_APP_USE_EXPOSURE_RISK=0` for
`StaticRiskEngine`.

---

## Kill Switch

Clicking **KILL SWITCH** on the Trading (Paper) tab:

1. Trips the risk engine, so every later `evaluate()` returns `approved=False`.
2. Trips the paper adapter.
3. Cancels all open intents via `cancel_all()`.
4. Appends a `kill_switch` event to the audit log.

**One way per session.** Restart the sidecar to reset.

---

## Secret Vault

Credentials are stored in the OS system keyring via the `keyring` library. They never appear
in config files, logs, or environment variables.

**To provision Kalshi credentials (for future order routing):**

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

Nothing reads these yet. Market data reads are unauthenticated.

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
