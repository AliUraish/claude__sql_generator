"""Clerk JWT authentication for FastAPI."""

import os
import json
from typing import Optional, Any, Dict
from functools import lru_cache
from dataclasses import dataclass

import httpx
from jose import jwt, JWTError
from fastapi import HTTPException, Header, Depends


class ClerkAuth:
    """Clerk JWT verification."""
    
    @staticmethod
    @lru_cache(maxsize=1)
    def get_jwks_url() -> str:
        """Get JWKS URL from env (with fallback to clerk issuer)."""
        jwks_url = os.getenv("CLERK_JWKS_URL")
        if jwks_url:
            return jwks_url
        
        issuer = os.getenv("CLERK_ISSUER")
        if not issuer:
            raise RuntimeError("CLERK_JWKS_URL or CLERK_ISSUER must be set")
        
        # Derive JWKS URL from issuer
        return f"{issuer.rstrip('/')}/.well-known/jwks.json"
    
    @staticmethod
    async def fetch_jwks() -> dict:
        """Fetch JWKS from Clerk."""
        jwks_url = ClerkAuth.get_jwks_url()
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(jwks_url)
            response.raise_for_status()
            return response.json()
    
    @staticmethod
    async def verify_token(token: str) -> dict:
        """Verify Clerk JWT and return payload."""
        try:
            # Fetch JWKS
            jwks = await ClerkAuth.fetch_jwks()
            
            # Decode header to get kid
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")
            
            # Find matching key
            key = None
            for jwk in jwks.get("keys", []):
                if jwk.get("kid") == kid:
                    key = jwk
                    break
            
            if not key:
                raise HTTPException(status_code=401, detail="Unable to find appropriate key")
            
            # Verify signature and decode
            audience = os.getenv("CLERK_AUDIENCE")
            issuer = os.getenv("CLERK_ISSUER")
            
            payload = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=audience if audience else None,
                issuer=issuer if issuer else None,
                options={"verify_aud": bool(audience), "verify_iss": bool(issuer)}
            )
            
            return payload
        
        except JWTError as e:
            raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
        except Exception as e:
            raise HTTPException(status_code=401, detail=f"Token verification failed: {str(e)}")


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    session_id: Optional[str] = None


def _extract_session_id(payload: Dict[str, Any]) -> Optional[str]:
    """
    Best-effort session id extraction from a Clerk JWT payload.

    Clerk's exact claim names can vary by configuration; commonly "sid" exists.
    """
    for key in ("sid", "session_id", "sessionId"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return None


async def require_user_id(authorization: Optional[str] = Header(None)) -> str:
    """FastAPI dependency to extract and verify Clerk user ID from JWT."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header format")
    
    token = authorization.split(" ", 1)[1]
    
    try:
        payload = await ClerkAuth.verify_token(token)
        user_id = payload.get("sub")
        
        if not user_id:
            raise HTTPException(status_code=401, detail="Token missing 'sub' claim")
        
        return user_id
    
    except HTTPException as e:
        # Re-raise HTTP exceptions (already properly formatted)
        raise
    except Exception as e:
        # Log the actual error for debugging
        import traceback
        print(f"⚠️  Auth error: {str(e)}")
        print(f"⚠️  Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")


async def require_auth_context(authorization: Optional[str] = Header(None)) -> AuthContext:
    """
    FastAPI dependency to extract Clerk user id + session id (if present) from JWT.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header format")

    token = authorization.split(" ", 1)[1]

    try:
        payload = await ClerkAuth.verify_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token missing 'sub' claim")

        session_id = _extract_session_id(payload)
        return AuthContext(user_id=user_id, session_id=session_id)

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"⚠️  Auth error: {str(e)}")
        print(f"⚠️  Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")
