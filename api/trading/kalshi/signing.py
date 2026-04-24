from __future__ import annotations

import base64

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


def sign_request(private_key_pem: str | bytes, timestamp_ms: int, method: str, path: str) -> str:
    """Return a base64-encoded RSA-PSS signature over `{timestamp_ms}{method}{path}`.

    Compatible with Kalshi's HMAC-alternative signing scheme (RSA-PSS, SHA-256, MGF1).
    """
    if isinstance(private_key_pem, str):
        private_key_pem = private_key_pem.encode()

    private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    message = f"{timestamp_ms}{method}{path}".encode()
    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode()
