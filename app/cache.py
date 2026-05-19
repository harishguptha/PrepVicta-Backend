import time
from collections import OrderedDict
from collections.abc import Hashable
from copy import deepcopy
from typing import Generic, TypeVar

T = TypeVar("T")


class TTLCache(Generic[T]):
    """Small in-process TTL cache for repeated read-heavy API calls."""

    def __init__(self, max_size: int = 256, ttl_seconds: int = 300) -> None:
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._items: OrderedDict[Hashable, tuple[float, T]] = OrderedDict()

    def get(self, key: Hashable) -> T | None:
        item = self._items.get(key)
        if item is None:
            return None

        expires_at, value = item
        if expires_at <= time.monotonic():
            self._items.pop(key, None)
            return None

        self._items.move_to_end(key)
        return deepcopy(value)

    def set(self, key: Hashable, value: T) -> None:
        self._items[key] = (time.monotonic() + self.ttl_seconds, deepcopy(value))
        self._items.move_to_end(key)
        while len(self._items) > self.max_size:
            self._items.popitem(last=False)

    def delete(self, key: Hashable) -> None:
        self._items.pop(key, None)
