from __future__ import annotations

import secrets as _secrets
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from api.trading import secrets as vault

router = APIRouter(tags=["secrets"])

_logger = logging.getLogger(__name__)
_CONFIRM_TOKEN: str = _secrets.token_hex(8)

# Print token at module import so the sidecar log exposes it.
_logger.warning("Kalshi secret-vault confirmation token: %s", _CONFIRM_TOKEN)


class KalshiSecretsRequest(BaseModel):
    access_key: str
    private_key_pem: str
    confirm_token: str


@router.post("/secrets/kalshi")
async def store_kalshi_secrets(payload: KalshiSecretsRequest, request: Request) -> dict:
    if not _secrets.compare_digest(payload.confirm_token, _CONFIRM_TOKEN):
        raise HTTPException(status_code=403, detail="Invalid confirmation token. Check sidecar log.")
    vault.store("kalshi", "access_key", payload.access_key)
    vault.store("kalshi", "private_key_pem", payload.private_key_pem)
    _logger.info("Kalshi credentials stored in system keyring.")
    return {"success": True, "data": {"stored": ["access_key", "private_key_pem"]}}
