"""Generic disk-cache helper for metrics functions.

Usage:
    from ._cache import disk_cache

    @disk_cache("my_namespace")
    def expensive_fn(queries, kg_name, endpoint="dblp"):
        ...
        return result_dict   # must be JSON-serialisable

The cache key is built from **all** arguments (positional + keyword) so
different inputs always produce separate cache entries.  Cached values
are stored as JSON files under  `.cache/<namespace>/`.

Set the environment variable ``METRICS_NO_CACHE=1`` to bypass the cache
globally (useful for debugging).
"""

import functools
import hashlib
import json
import os

_CACHE_ROOT = os.path.join(os.path.dirname(__file__), "..", ".cache")


def _make_key(*args, **kwargs) -> str:
    """Deterministic hash of arbitrary JSON-serialisable arguments."""
    payload = json.dumps({"a": args, "k": kwargs}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def disk_cache(namespace: str):
    """Decorator: cache the return value of *func* on disk under *namespace*."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if os.environ.get("METRICS_NO_CACHE") == "1":
                return func(*args, **kwargs)

            rewrite_cache = kwargs.get("rewrite_cache", False)
            cache_kwargs = {k: v for k, v in kwargs.items() if k != "rewrite_cache"}
            cache_dir = os.path.join(_CACHE_ROOT, namespace)
            os.makedirs(cache_dir, exist_ok=True)
            key = _make_key(*args, **cache_kwargs)
            path = os.path.join(cache_dir, f"{key}.json")

            if not rewrite_cache and os.path.exists(path):
                try:
                    with open(path) as f:
                        return json.load(f)
                except Exception:
                    pass  # corrupted file → recompute

            result = func(*args, **kwargs)

            try:
                with open(path, "w") as f:
                    json.dump(result, f)
            except Exception:
                pass  # non-serialisable edge case → skip silently

            return result

        return wrapper

    return decorator
