"""In-process rate limiting for protected endpoints.

Sliding-window counters (per minute and per day) and a concurrency cap per authenticated principal, plus a
per-client-IP counter for failed authentication. State lives in this process only, so production
configuration refuses more than one worker (app.core.config: RATE_LIMITER_REQUIRES_SINGLE_PROCESS); a shared
store is needed before scaling out. Keys are opaque user IDs or IP strings; nothing else is stored.
Limits are engineering defaults, not validated operational values (docs/configuration.md).
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after_seconds: int = 0
    reason: str = ''


class SlidingWindow:
    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit, self.window = limit, window_seconds
        self.events: dict[str, deque[float]] = {}

    def check_and_add(self, key: str, now: float) -> Decision:
        q = self.events.setdefault(key, deque())
        while q and q[0] <= now - self.window:
            q.popleft()
        if len(q) >= self.limit:
            return Decision(False, max(1, math.ceil(q[0] + self.window - now)))
        q.append(now)
        return Decision(True)

    def count(self, key: str, now: float) -> int:
        q = self.events.get(key, deque())
        return sum(1 for t in q if t > now - self.window)

    def prune(self, now: float) -> None:
        for key in [k for k, q in self.events.items() if not q or q[-1] <= now - self.window]:
            del self.events[key]


class Limiter:
    def __init__(self, per_minute: int, per_day: int, max_concurrent: int, auth_failures_per_minute: int,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._lock = threading.Lock()
        self._clock = clock
        self.minute = SlidingWindow(per_minute, 60.0)
        self.day = SlidingWindow(per_day, 86_400.0)
        self.failures = SlidingWindow(auth_failures_per_minute, 60.0)
        self.max_concurrent = max_concurrent
        self._active: dict[str, int] = {}
        self._calls = 0

    def _maybe_prune(self, now: float) -> None:
        self._calls += 1
        if self._calls % 1000 == 0:
            for w in (self.minute, self.day, self.failures):
                w.prune(now)

    def failures_exceeded(self, ip: str) -> Decision:
        with self._lock:
            now = self._clock()
            if self.failures.count(ip, now) >= self.failures.limit:
                q = self.failures.events[ip]
                return Decision(False, max(1, math.ceil(q[0] + 60.0 - now)), 'auth_failures')
            return Decision(True)

    def record_failure(self, ip: str) -> None:
        with self._lock:
            now = self._clock()
            self.failures.check_and_add(ip, now)
            self._maybe_prune(now)

    def acquire(self, principal: str) -> Decision:
        """Counts one request and takes a concurrency slot; call release() in a finally block if allowed."""
        with self._lock:
            now = self._clock()
            self._maybe_prune(now)
            if self._active.get(principal, 0) >= self.max_concurrent:
                return Decision(False, 1, 'concurrency')
            # Check both windows before recording, so a refused request does not consume the other window.
            if self.minute.count(principal, now) >= self.minute.limit:
                return Decision(False, self.minute.check_and_add(principal, now).retry_after_seconds, 'per_minute')
            if self.day.count(principal, now) >= self.day.limit:
                return Decision(False, self.day.check_and_add(principal, now).retry_after_seconds, 'per_day')
            self.minute.check_and_add(principal, now)
            self.day.check_and_add(principal, now)
            self._active[principal] = self._active.get(principal, 0) + 1
            return Decision(True)

    def release(self, principal: str) -> None:
        with self._lock:
            n = self._active.get(principal, 0) - 1
            if n > 0:
                self._active[principal] = n
            else:
                self._active.pop(principal, None)
