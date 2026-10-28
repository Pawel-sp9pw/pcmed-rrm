import hashlib
import logging
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, Header, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import database
from .models import Device, Gateway

bearer = HTTPBearer(auto_error=False)


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Principal:
    subject: str
    roles: set[str]
    tenants: set[str]

    def allow(self, tenant_id: str, write: bool = False, approval: bool = False):
        if "platform_admin" in self.roles:
            return
        needed = {"approver"} if approval else {"operator"} if write else {"viewer", "operator", "approver"}
        if tenant_id not in self.tenants or not (needed & self.roles):
            raise HTTPException(403, "No access to this client or action")


@lru_cache
def jwks():
    return jwt.PyJWKClient(settings().oidc_jwks_url, cache_keys=False, lifespan=300, timeout=5)


def principal(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Principal:
    if not credentials or len(credentials.credentials) > 16384:
        raise HTTPException(401, "Authentication required")
    try:
        token = credentials.credentials
        key = jwks().get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=settings().oidc_audience,
                            issuer=settings().oidc_issuer, options={"require": ["exp", "iat", "sub"]})
        roles = claims.get("realm_access", {}).get("roles", [])
        tenants = claims.get("tenant_ids", [])
        if not isinstance(tenants, list) or not isinstance(roles, list) or not isinstance(claims["sub"], str):
            raise ValueError("Invalid claims")
        return Principal(claims["sub"], set(roles), set(tenants))
    except (jwt.PyJWTError, ValueError, TypeError, AttributeError) as error:
        logging.getLogger(__name__).warning("OIDC validation rejected (%s)", type(error).__name__)
        raise HTTPException(401, "Invalid or expired access token") from None


def gateway(header: str | None, session: Session) -> Gateway | None:
    if header is None:
        return None
    found = session.scalar(select(Gateway).where(Gateway.token_hash == digest(header), Gateway.revoked.is_(False)))
    if not found:
        raise HTTPException(401, "Invalid gateway credential")
    return found


def agent(credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
          gateway_token: str | None = Header(default=None, alias="X-PCMED-Gateway"),
          session: Session = Depends(database)) -> Device:
    if not credentials:
        raise HTTPException(401, "Agent authentication required")
    device = session.scalar(select(Device).where(Device.token_hash == digest(credentials.credentials), Device.revoked.is_(False)))
    if not device:
        raise HTTPException(401, "Invalid agent credential")
    relay = gateway(gateway_token, session)
    if relay and relay.tenant_id != device.tenant_id:
        raise HTTPException(403, "Gateway belongs to another client")
    device.gateway_id = relay.id if relay else None
    return device
