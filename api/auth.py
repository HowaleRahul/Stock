import time
import os
import secrets
import threading
from typing import Dict, List, Optional
from collections import defaultdict
from fastapi import Request, HTTPException, status, Depends
from fastapi.security import APIKeyHeader
from api.config import settings
from cachetools import TTLCache

# Sliding window rate limiting: (IP + Path + Quota) -> list of request timestamps
# Use TTLCache with a TTL of 60 seconds so IPs that only ping once are automatically garbage collected.
_RATE_LOCK = threading.Lock()
_RATE_LIMITS = TTLCache(maxsize=100000, ttl=60)

def rate_limiter(requests_per_minute: int = 60):
    async def dependency(request: Request):
        client_host = request.client.host if request.client else "127.0.0.1"
        # Only trust X-Forwarded-For if client_host is loopback or private network proxy
        if client_host in ("127.0.0.1", "::1", "localhost") or client_host.startswith(("10.", "172.", "192.168.")):
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                client_ip = forwarded.split(",")[0].strip()[:45]
            else:
                client_ip = client_host
        else:
            client_ip = client_host

        endpoint_key = f"{client_ip}:{request.scope.get('path', '')}:{requests_per_minute}"
        now = time.time()
        
        with _RATE_LOCK:
            timestamps = _RATE_LIMITS.get(endpoint_key, [])
            valid_timestamps = [ts for ts in timestamps if now - ts < 60.0]
            
            if len(valid_timestamps) >= requests_per_minute:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Rate limit exceeded. Maximum {requests_per_minute} requests per minute."
                )
            
            valid_timestamps.append(now)
            _RATE_LIMITS[endpoint_key] = valid_timestamps
        return True
    return dependency

# Optional API Key Authentication
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

async def get_api_key(request: Request, api_key: Optional[str] = Depends(api_key_header)):
    """
    Validates API key if it's set in the environment.
    Development can run without a key for local use. Production must always
    provide one; silently disabling authentication there exposes every
    state-changing endpoint.
    Supports both X-API-Key header and Authorization: Bearer <key>.
    """
    configured_key = settings.api_key.get_secret_value() if settings.api_key else None
    expected_api_key = configured_key or os.getenv("API_KEY")
    if not expected_api_key:
        if settings.environment.lower() != "development":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API authentication is not configured."
            )
        return None

    candidate = api_key
    if not candidate:
        auth_hdr = request.headers.get("Authorization", "")
        if auth_hdr.startswith("Bearer "):
            candidate = auth_hdr[7:].strip()

    if not candidate or not secrets.compare_digest(candidate, expected_api_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API Key"
        )
    return candidate
