import pytest

from lru import LRUCache


def test_basic_get_put():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1
    assert cache.get("b") == 2
    assert cache.get("c") is None


def test_evicts_least_recently_used():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    assert cache.get("a") is None
    assert cache.get("b") == 2
    assert cache.get("c") == 3


def test_get_refreshes_recency():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("a")
    cache.put("c", 3)
    assert cache.get("b") is None
    assert cache.get("a") == 1


def test_put_existing_updates_and_refreshes():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("a", 10)
    cache.put("c", 3)
    assert cache.get("a") == 10
    assert cache.get("b") is None
    assert len(cache) == 2


def test_len():
    cache = LRUCache(3)
    assert len(cache) == 0
    cache.put("a", 1)
    cache.put("a", 2)
    assert len(cache) == 1


def test_capacity_one():
    cache = LRUCache(1)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") is None
    assert cache.get("b") == 2


@pytest.mark.parametrize("capacity", [0, -1])
def test_invalid_capacity(capacity):
    with pytest.raises(ValueError):
        LRUCache(capacity)


def test_falsy_values_are_stored():
    cache = LRUCache(2)
    cache.put("zero", 0)
    cache.put("empty", "")
    assert cache.get("zero") == 0
    assert cache.get("empty") == ""
