"""Limitador de ventana fija sobre la caché de Django (Redis en producción)."""

from __future__ import annotations

import time

from django.core.cache import cache


def hit(key: str, limits: list[tuple[int, int]], now: float | None = None) -> bool:
    """Registra un uso de `key`. Devuelve False si se superó alguno de los límites
    `(cantidad, segundos)`."""
    now = time.time() if now is None else now
    allowed = True
    for count, seconds in limits:
        bucket = f"rl:{key}:{seconds}:{int(now // seconds)}"
        cache.add(bucket, 0, timeout=seconds)
        try:
            used = cache.incr(bucket)
        except ValueError:  # expiró entre add e incr
            cache.set(bucket, 1, timeout=seconds)
            used = 1
        if used > count:
            allowed = False
    return allowed
