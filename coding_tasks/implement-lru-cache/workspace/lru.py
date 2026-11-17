class LRUCache:
    """固定容量的 LRU（最近最少使用）缓存。"""

    def __init__(self, capacity: int) -> None:
        raise NotImplementedError

    def get(self, key):
        raise NotImplementedError

    def put(self, key, value) -> None:
        raise NotImplementedError

    def __len__(self) -> int:
        raise NotImplementedError
