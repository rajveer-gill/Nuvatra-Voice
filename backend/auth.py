"""Clerk JWT verification and tenant resolution for multi-tenant API auth."""
import os
from typing import Optional, Tuple

from fastapi import HTTPException, Request, status

def get_bearer_token(request: Request) -> Optional[str]:
    """Extract Bearer token from Authorization header."""
    auth = request.headers.get("Authorization")
    if not auth or not auth.startswith("Bearer "):
        return None
    return auth[7:].strip()

def verify_clerk_token(token: str) -> Tuple[str, Optional[str]]:
    """
    Verify Clerk JWT and return (clerk_user_id, tenant_id from metadata).
    Raises HTTPException on invalid token.
    """
    jwks_url = os.getenv("CLERK_JWKS_URL", "").strip()
    if not jwks_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="CLERK_JWKS_URL not configured",
        )
    issuer = os.getenv("CLERK_ISSUER", "").strip()
    audience = os.getenv("CLERK_AUDIENCE", "").strip()
    if not issuer or not audience:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Clerk token validation not fully configured",
        )

    try:
        import jwt
        from jwt import PyJWKClient, PyJWKClientError
        from jwt.exceptions import (
            ExpiredSignatureError,
            ImmatureSignatureError,
            InvalidAudienceError,
            InvalidIssuerError,
            InvalidSignatureError,
            InvalidTokenError,
            MissingRequiredClaimError,
        )
    except Exception:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="JWT library unavailable")

    try:
        jwks_client = PyJWKClient(jwks_url)
        signing_key = jwks_client.get_signing_key_from_jwt(token)
    except PyJWKClientError:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Auth key service unavailable")

    try:
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=issuer,
            audience=audience,
            options={"verify_aud": True, "verify_iss": True},
        )
    except (
        ExpiredSignatureError,
        ImmatureSignatureError,
        InvalidAudienceError,
        InvalidIssuerError,
        InvalidSignatureError,
        MissingRequiredClaimError,
        InvalidTokenError,
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    metadata = payload.get("public_metadata") or {}
    tenant_id = metadata.get("tenant_id")
    return (user_id, tenant_id)
