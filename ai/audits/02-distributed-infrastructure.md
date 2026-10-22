# Audit 02: Distributed Infrastructure & Multi-Worker Concurrency

**Audit Date**: October 2026  
**Auditor**: Principal Systems Architect & Performance Engineer  
**Status**: Critical Multi-Process Concurrency Defects Discovered & Distributed Redis Architecture Specified  
**Affected Modules**: `api/auth.py`, `data/realtime_feed.py`, `api/training_router.py`, `api/router.py`

---

## 1. Executive Summary

The application is currently designed around single-process, in-memory concurrency primitives (`threading.Lock`, `asyncio.Lock`, `cachetools.TTLCache`, `threading.Thread`, and module-level globals). 

When deployed to production with multiple Uvicorn workers (`uvicorn api.main:app --workers 4`) or scaled across container replicas:
1. **Rate Limiting is Bypassed**: Rate limits are process-local; clients can multiply their request volume by the worker count without triggering HTTP 429.
2. **Training State is Fragmented**: Starting a training task on Worker A leaves Worker B reporting that training is idle, causing broken `/status` telemetry and unexecutable `/stop` requests.
3. **Data Sync Race Conditions**: Ingestion locks in `api/router.py` only protect within a single Python process, allowing concurrent workers to trigger simultaneous duplicate downloads and database conflicts for the same ticker.
4. **Redundant Upstream Quote Queries**: Real-time quote caches are isolated per worker, causing $N\times$ redundant network calls to Yahoo Finance and TradingView.

---

## 2. In-Depth Root Cause Analysis

### 2.1 Process-Local Rate Limiting (`api/auth.py`)
Lines 14–45 of `api/auth.py` implement rate limiting as follows:
```python
_RATE_LOCK = threading.Lock()
_RATE_LIMITS = TTLCache(maxsize=100000, ttl=60)
```
- **OS Boundary**: Each Uvicorn worker is an independent OS process created via `fork` or `subprocess`. Memory is strictly unshared.
- **Quota Leakage**: If a route allows 60 req/min, a 4-worker pool permits 240 req/min across round-robin requests.
- **Worker Recycling**: In cloud environments (Kubernetes, AWS ECS) or when Uvicorn workers restart due to memory limits, rate limit history is destroyed.

### 2.2 Fragmented Training State (`api/training_router.py`)
Lines 22–27 of `api/training_router.py`:
```python
_lock = threading.Lock()
training_thread = None
stop_event = threading.Event()
training_logs = collections.deque(maxlen=200)
is_training = False
```
- **The Split-Brain Failure**:
  1. User clicks "Start Training" in the web UI. Request reaches Worker 1. Worker 1 spawns a background thread and sets `is_training = True`.
  2. The UI polls `GET /api/v1/training/status` every 2 seconds. The next poll request hits Worker 2.
  3. Worker 2 reads its local `is_training`, which is `False`, and returns `status: "STOPPED"`, `is_running: false`, and an empty log array.
  4. The UI abruptly flickers back to "IDLE" and displays an offline state.
  5. If the user clicks "Stop Training", the request hitting Worker 2 fails with HTTP 400 (`"Training is not running"`).

### 2.3 Unsynchronized Ingestion Locks (`api/router.py`)
Lines 39–65 of `api/router.py` manage synchronization using:
```python
_SYNC_LOCKS: Dict[str, RefCountedLock] = {}
_SYNC_LOCKS_GUARD = asyncio.Lock()
```
- Because `asyncio.Lock` operates only within a single event loop in a single process, two concurrent incoming requests to `/sync` for ticker `RELIANCE.NS` handled by separate workers will both acquire their respective "locks" and run simultaneous database bulk upserts.
- While TimescaleDB `ON CONFLICT` prevents table corruption, simultaneous downloads cause redundant bandwidth consumption and database deadlocks.

### 2.4 Duplicate Upstream Data Scraping (`data/realtime_feed.py`)
`RealTimeDataFeed._cache = TTLCache(maxsize=10000, ttl=60.0)` stores live quotes in local memory.
- Under high concurrent user traffic on the Dashboard, 4 worker processes independently fetch quotes for the same 20 watchlist tickers every 3 seconds, increasing external network calls by 400% and triggering upstream rate limits or IP blacklisting from TradingView and Yahoo Finance.

---

## 3. Distributed Architecture Specification

```
                          ┌──────────────────────────┐
                          │   Reverse Proxy / LB     │
                          │   (Nginx / Traefik / ALB)│
                          └─────────────┬────────────┘
                                        │
                 ┌──────────────────────┼──────────────────────┐
                 ▼                      ▼                      ▼
        ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
        │ Uvicorn Worker 1│    │ Uvicorn Worker 2│    │ Uvicorn Worker 3│
        └────────┬────────┘    └────────┬────────┘    └────────┬────────┘
                 │                      │                      │
                 ├──────────────────────┼──────────────────────┤
                 │                      │                      │
                 ▼                      ▼                      ▼
        ┌──────────────────────────────────────────────────────────────┐
        │                         REDIS CLUSTER                        │
        │  • Shared Token-Bucket Rate Limiter                          │
        │  • Distributed Locks (Redlock / SET NX PX for Sync)          │
        │  • Real-Time Market Quote Cache (3s TTL)                     │
        │  • Training Job State & Pub/Sub Telemetry Streaming          │
        └──────────────────────────────┬───────────────────────────────┘
                                       │
                                       ▼
                        ┌──────────────────────────────┐
                        │  Dedicated Training Worker   │
                        │  (Separate Daemon / Celery)  │
                        └──────────────────────────────┘
```

### 3.1 Distributed Redis Rate Limiter
Replace process-local `TTLCache` with a Redis sliding-window counter using a high-performance Lua script:
```lua
-- Keys: [rate_limit_key]
-- Args: [now_timestamp, window_seconds, max_requests]
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local max_req = tonumber(ARGV[3])

redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)

if count >= max_req then
    return 0 -- Rate limited
else
    redis.call('ZADD', key, now, now)
    redis.call('EXPIRE', key, math.ceil(window))
    return 1 -- Allowed
end
```
**Advantage**: Atomically evaluates rate limits across an unlimited number of workers with sub-millisecond latency.

### 3.2 Distributed Ingestion Lock
Implement distributed mutual exclusion for ticker syncing:
```python
async def acquire_distributed_lock(redis_client, key: str, ttl_seconds: int = 120):
    lock_key = f"lock:sync:{key}"
    acquired = await redis_client.set(lock_key, "1", ex=ttl_seconds, nx=True)
    return acquired
```

### 3.3 Decoupled Asynchronous Training Worker
Decouple continuous training completely from the FastAPI HTTP processes:
1. `POST /api/v1/training/start`: Writes a task intent to Redis key `training:state = {"status": "START_REQUESTED", "config": ...}`.
2. A standalone supervisor daemon (`python -m ml.training_worker` or Celery task) reads the intent, manages the continuous training loop, and streams telemetry logs into a Redis capped list (`RPUSH training:logs` with `LTRIM -200`).
3. `GET /api/v1/training/status`: Reads `training:state` and `training:logs` directly from Redis. Every worker returns identical, real-time status.

---

## 4. Remediation Implementation Strategy

To preserve local developer experience while enabling enterprise production clustering:

1. **Dual-Mode Adapter Pattern**:
   Add `REDIS_URL: Optional[str] = Field(default=None)` to `api/config.py`.
   - If `REDIS_URL` is configured: initialize `redis.asyncio.from_url(...)` and use distributed rate limiting, locks, and quote caching.
   - If `REDIS_URL` is omitted (`None`): seamlessly fall back to existing in-memory `TTLCache` and `asyncio.Lock` primitives for local development.

2. **Docker Compose Integration**:
   Add a standard Redis service to `docker-compose.yml`:
   ```yaml
   redis:
     image: redis:7-alpine
     container_name: trading_redis
     restart: unless-stopped
     ports:
       - "127.0.0.1:6379:6379"
   ```
