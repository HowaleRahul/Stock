import time
import os
from typing import Dict, List
from collections import defaultdict
from fastapi import Request, HTTPException, status, Depends
from fastapi.security import APIKeyHeader
from api.config import settings
from cachetools import TTLCache

# Sliding window rate limiting: IP -> list of request timestamps
# Use TTLCache with a TTL of 60 seconds so IPs that only ping once are automatically garbage collected.
_RATE_LIMITS = TTLCache(maxsize=100000, ttl=60)

def rate_limiter(requests_per_minute: int = 60):
    async def dependency(request: Request):
        client_ip = request.client.host if request.client else "127.0.0.1"
        now = time.time()
        
        # In a real production system, this would use Redis.
        # Clean up old timestamps (older than 60s)
        timestamps = _RATE_LIMITS.get(client_ip, [])
        valid_timestamps = [ts for ts in timestamps if now - ts < 60.0]
        
        if len(valid_timestamps) >= requests_per_minute:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Maximum {requests_per_minute} requests per minute."
            )
        
        valid_timestamps.append(now)
        _RATE_LIMITS[client_ip] = valid_timestamps
        return True
    return dependency

# Optional API Key Authentication
API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

async def get_api_key(api_key: str = Depends(api_key_header)):
    """
    Validates API key if it's set in the environment.
    If 'API_KEY' is not set in env, allows open access (for backwards compatibility).
    """
    expected_api_key = os.getenv("API_KEY")
    if not expected_api_key:
        return None
    if api_key != expected_api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing API Key"
        )
    return api_key
