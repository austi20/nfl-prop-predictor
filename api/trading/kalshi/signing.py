from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

_PSS_SALT_LENGTH = 32  # SHA-256 digest size — Kalshi's PSS spec (NOT PSS.MAX_LENGTH)


@lru_cache(maxsize=4)
def _load_private_key(path_or_pem: str):
    """Accepts a filesystem path to a PEM, or the PEM text itself."""
    if "-----BEGIN" in path_or_pem:
        pem = path_or_pem.encode()
    else:
        pem = Path(path_or_pem).expanduser().read_bytes()
    return serialization.load_pem_private_key(pem, password=None)


def sign_request(private_key: str | bytes, timestamp_ms: int | str, method: str, path: str) -> str:
    """Base64 RSA-PSS(SHA-256, salt=32) signature over ``{ts}{METHOD}{path}``.

    ``private_key`` may be a PEM string/bytes or a path to a .pem file. ``path``
    must include the ``/trade-api/v2`` prefix and exclude the query string.
    """
    key = _load_private_key(private_key.decode() if isinstance(private_key, bytes) else private_key)
    message = f"{timestamp_ms}{method.upper()}{path}".encode()
    signature = key.sign(
        message,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=_PSS_SALT_LENGTH),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("ascii")
