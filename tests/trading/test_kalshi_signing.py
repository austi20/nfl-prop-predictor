from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from api.trading.kalshi.signing import sign_request


@pytest.fixture(scope="module")
def rsa_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return private_key, private_pem


def test_sign_returns_base64_string(rsa_keypair) -> None:
    _, private_pem = rsa_keypair
    sig = sign_request(private_pem, 1_700_000_000_000, "GET", "/trade-api/rest/v1/portfolio/balance")
    decoded = base64.b64decode(sig)
    assert len(decoded) == 256  # RSA-2048 signature is 256 bytes


def test_signature_verifies_with_public_key(rsa_keypair) -> None:
    private_key, private_pem = rsa_keypair
    ts = 1_700_000_000_001
    method = "POST"
    path = "/trade-api/rest/v1/portfolio/orders"

    sig_b64 = sign_request(private_pem, ts, method, path)
    signature = base64.b64decode(sig_b64)
    message = f"{ts}{method}{path}".encode()

    private_key.public_key().verify(
        signature,
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH,
        ),
        hashes.SHA256(),
    )


def test_different_payloads_produce_different_signatures(rsa_keypair) -> None:
    _, private_pem = rsa_keypair
    sig1 = sign_request(private_pem, 1000, "GET", "/path-a")
    sig2 = sign_request(private_pem, 1000, "GET", "/path-b")
    assert sig1 != sig2


def test_accepts_bytes_pem(rsa_keypair) -> None:
    private_key, private_pem = rsa_keypair
    sig = sign_request(private_pem.encode(), 9999, "DELETE", "/foo")
    assert len(base64.b64decode(sig)) == 256
