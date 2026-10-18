"""Bounded, process-local auth limits. Single backend; no proxy-header trust."""
from dataclasses import dataclass
import hashlib
import threading
import time

from .auth_service import AuthenticationBusy


class AuthRateLimited(AuthenticationBusy):
    def __init__(self, retry_after):
        super().__init__("Too many authentication requests")
        self.retry_after = retry_after


@dataclass(frozen=True)
class RateLimits:
    window: int = 60
    request_source: int = 120
    login_source: int = 20
    login_account: int = 10
    activation_source: int = 10
    activation_token: int = 5
    registration_source: int = 5
    session_token: int = 60
    max_keys: int = 8192

    def __post_init__(self):
        if any(type(value) is not int or value < 1 for value in vars(self).values()):
            raise ValueError("Rate limits must be positive integers")


class AuthRateLimiter:
    def __init__(self, limits=None, *, clock=time.monotonic):
        self.limits = limits or RateLimits()
        self._clock, self._lock, self._buckets = clock, threading.Lock(), {}

    def _consume(self, keys):
        with self._lock:
            now = self._clock()
            self._buckets = {key: value for key, value in self._buckets.items() if value[0] > now}
            for key, maximum in keys:
                if self._buckets.get(key, (0, 0))[1] >= maximum:
                    raise AuthRateLimited(self.limits.window)
            new_keys = {key for key, _ in keys if key not in self._buckets}
            if len(self._buckets) + len(new_keys) > self.limits.max_keys:
                # Never evict a live limit, which would permit bypass by key churn.
                raise AuthRateLimited(self.limits.window)
            for key, _ in keys:
                expiry, count = self._buckets.get(key, (now + self.limits.window, 0))
                self._buckets[key] = expiry, count + 1

    def request(self, source, audience=None, token=None):
        keys = [(("source", source), self.limits.request_source)]
        if token:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            keys.append((("session", audience, digest), self.limits.session_token))
        self._consume(keys)

    def registration(self, source):
        self._consume([(("registration-source", source), self.limits.registration_source)])

    def activation(self, source, token):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        self._consume([(("activation-source", source), self.limits.activation_source),
                       (("activation-token", digest), self.limits.activation_token)])

    def check(self, attempt):
        self._consume([(("login-source", attempt.audience, attempt.source_key), self.limits.login_source),
                       (("login-account", attempt.audience, attempt.username_key), self.limits.login_account)])

    def record(self, attempt, *, succeeded):
        # Every attempt was charged by check(), including successes. Do not reset
        # a limit on login or keep unbounded credential/result telemetry.
        pass
