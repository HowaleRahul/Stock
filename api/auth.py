import time
import os
import secrets
import threading
import ipaddress
from typing import Dict, List, Optional
from fastapi import Request, HTTPException, status, Depends
from fastapi.security import APIKeyHeader
from api.config import settings
from cachetools import TTLCache

# Sliding window rate limiting: (IP + Path + Quota) -> list of request timestamps
# Use TTLCache with a TTL of 60 seconds so IPs that only ping once are automatically garbage collected.
_RATE_LOCK = threading.Lock()
_RATE_LIMITS = TTLCache(maxsize=100000, ttl=60)

def _is_trusted_proxy(host: str) -> bool:
    normalized = host.strip().lower()
    if normalized.startswith("[") and normalized.endswith("]"):
        normalized = normalized[1:-1]
    if normalized in ("localhost", "127.0.0.1", "::1", "testclient"):
        return True
    if normalized.startswith("::ffff:"):
        normalized = normalized[7:]
    try:
        ip = ipaddress.ip_address(normalized)
        if hasattr(ip, "ipv4_mapped") and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        return ip.is_loopback or ip.is_private
    except ValueError:
        return False


def rate_limiter(requests_per_minute: int = 60):
    async def dependency(request: Request):
        client_host = request.client.host if request.client else "127.0.0.1"
        # Only trust X-Forwarded-For if client_host is verified loopback or RFC1918 private proxy
        if _is_trusted_proxy(client_host):
            forwarded = request.headers.get("X-Forwarded-For")
            if forwarded:
                raw_ip = forwarded.split(",")[0].strip().replace("\x00", "")[:45]
                try:
                    ipaddress.ip_address(raw_ip)
                    client_ip = raw_ip
                except ValueError:
                    client_ip = client_host
            else:
                client_ip = client_host
        else:
            client_ip = client_host

        # Group by route template if available to prevent path parameter permutations from bypassing rate limits
        route = request.scope.get("route")
        route_path = getattr(route, "path", None) or request.scope.get("path", "")
        endpoint_key = f"{client_ip}:{route_path}:{requests_per_minute}"
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

# API key authentication with a loopback-only local development exception.
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

def _is_loopback_host(host: str) -> bool:
    normalized = host.strip().lower()
    if normalized.startswith("[") and normalized.endswith("]"):
        normalized = normalized[1:-1]
    if normalized in ("localhost", "testclient"):
        return True
    if normalized.startswith("::ffff:"):
        normalized = normalized[7:]
    try:
        ip = ipaddress.ip_address(normalized)
        if hasattr(ip, "ipv4_mapped") and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        return ip.is_loopback
    except ValueError:
        return False


def _configured_api_key() -> Optional[str]:
    configured_key = settings.api_key.get_secret_value() if settings.api_key else None
    return configured_key or os.getenv("API_KEY")


def _allows_keyless_development(request: Optional[Request] = None) -> bool:
    if settings.environment.lower() != "development":
        return False
    if not _is_loopback_host(settings.api_host):
        return False
    if request is not None:
        client_host = request.client.host if request.client else ""
        return _is_loopback_host(client_host)
    return True


def validate_auth_configuration() -> None:
    if not _configured_api_key() and not _allows_keyless_development():
        raise RuntimeError(
            "API authentication is not configured. Set API_KEY, or explicitly use "
            "development mode on a loopback bind for local-only access."
        )


async def get_api_key(request: Request, api_key: Optional[str] = Depends(api_key_header)):
    """
    Validates the configured API key. Keyless access is limited to explicit
    development mode on a loopback bind and loopback client.
    Supports both X-API-Key header and Authorization: Bearer <key>.
    """
    expected_api_key = _configured_api_key()
    if not expected_api_key:
        if not _allows_keyless_development(request):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API authentication is not configured."
            )
        return None

    candidate = api_key
    if not candidate:
        auth_hdr = request.headers.get("Authorization", "")
        if auth_hdr.lower().startswith("bearer "):
            candidate = auth_hdr[7:].strip()

    if not candidate or not secrets.compare_digest(candidate, expected_api_key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API Key"
        )
    return candidate
