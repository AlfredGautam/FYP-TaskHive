"""
Simple in-memory rate limiter for login/registration endpoints.
Uses Django's cache framework so it works with any cache backend.
"""

import functools
import time

from django.core.cache import cache
from django.http import JsonResponse


def rate_limit(max_requests=5, window_seconds=60, key_func=None):
    """
    Decorator that limits requests per IP (or custom key).
    Returns 429 Too Many Requests if the limit is exceeded.

    Args:
        max_requests: Maximum number of requests allowed in the window.
        window_seconds: Time window in seconds.
        key_func: Optional callable(request) -> str for custom cache keys.
    """

    def decorator(view_func):
        @functools.wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if key_func:
                rl_key = key_func(request)
            else:
                ip = _get_client_ip(request)
                rl_key = f"rl:{view_func.__name__}:{ip}"

            now = time.time()
            history = cache.get(rl_key) or []

            # Remove entries outside the window
            history = [t for t in history if now - t < window_seconds]

            if len(history) >= max_requests:
                retry_after = int(window_seconds - (now - history[0]))
                return JsonResponse(
                    {"ok": False, "error": "Too many requests. Please try again later."},
                    status=429,
                    headers={"Retry-After": str(max(retry_after, 1))},
                )

            history.append(now)
            cache.set(rl_key, history, timeout=window_seconds)
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


def _get_client_ip(request):
    """Extract client IP from request, respecting X-Forwarded-For."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "unknown")
