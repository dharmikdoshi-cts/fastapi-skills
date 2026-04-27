"""Redis-backed sliding-window rate limiter. Drop into app/security/rate_limit.py."""
from __future__ import annotations

import time
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis

from app.config.dependencies import get_redis  # your Redis dep


class RateLimiter:
    """Sliding-window rate limit using a Redis sorted set per key."""

    def __init__(self, *, max_requests: int, window_seconds: int, prefix: str = "rl"):
        self.max = max_requests
        self.window = window_seconds
        self.prefix = prefix

    async def __call__(
        self,
        request: Request,
        redis: Annotated[Redis, Depends(get_redis)],
    ) -> None:
        ident = self._identify(request)
        key = f"{self.prefix}:{ident}"
        now_ms = int(time.time() * 1000)
        cutoff = now_ms - (self.window * 1000)

        pipe = redis.pipeline()
        pipe.zremrangebyscore(key, 0, cutoff)
        pipe.zadd(key, {str(now_ms): now_ms})
        pipe.zcard(key)
        pipe.expire(key, self.window)
        _, _, count, _ = await pipe.execute()

        if count > self.max:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded: {self.max}/{self.window}s",
                headers={"Retry-After": str(self.window)},
            )

    @staticmethod
    def _identify(request: Request) -> str:
        # Prefer authenticated user id, fall back to IP
        user = getattr(request.state, "user", None)
        if user and getattr(user, "id", None):
            return f"u:{user.id}"
        # Honor X-Forwarded-For only behind a trusted proxy
        ip = request.client.host if request.client else "unknown"
        return f"ip:{ip}"


login_limit = RateLimiter(max_requests=5, window_seconds=60, prefix="rl:login")
api_limit = RateLimiter(max_requests=100, window_seconds=60, prefix="rl:api")
