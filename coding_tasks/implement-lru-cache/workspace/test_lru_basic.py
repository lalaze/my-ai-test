from lru import LRUCache


def test_put_then_get():
    cache = LRUCache(2)
    cache.put("a", 1)
    assert cache.get("a") == 1


def test_missing_key():
    assert LRUCache(1).get("x") is None
