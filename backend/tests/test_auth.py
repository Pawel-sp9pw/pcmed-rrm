import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.auth import principal
from app.config import settings


@pytest.fixture
def signer(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr("app.auth.jwks", lambda: SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=key.public_key())))
    claims = {"sub": "person", "iat": int(time.time()), "exp": int(time.time()) + 60,
              "iss": settings().oidc_issuer, "aud": settings().oidc_audience,
              "realm_access": {"roles": ["operator"]}, "tenant_ids": ["alpha"]}
    return key, claims


def test_valid_signed_identity(signer):
    key, claims = signer
    user = principal(HTTPAuthorizationCredentials(scheme="Bearer", credentials=jwt.encode(claims, key, algorithm="RS256")))
    assert user.subject == "person"
    assert user.tenants == {"alpha"}


@pytest.mark.parametrize("change", [{"aud": "wrong"}, {"iss": "https://evil.test"}, {"exp": 1}, {"tenant_ids": "alpha"}])
def test_invalid_tokens_rejected(signer, change):
    key, claims = signer
    token = jwt.encode(claims | change, key, algorithm="RS256")
    with pytest.raises(HTTPException) as caught:
        principal(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token))
    assert caught.value.status_code == 401


def test_unsigned_and_missing_tokens_rejected(signer):
    _, claims = signer
    with pytest.raises(HTTPException):
        principal(HTTPAuthorizationCredentials(scheme="Bearer", credentials=jwt.encode(claims, "", algorithm="none")))
    with pytest.raises(HTTPException):
        principal(None)
