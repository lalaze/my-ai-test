from collections import OrderedDict


class LRUCache:
    """固定容量的 LRU（最近最少使用）缓存。"""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("capacity 必须大于等于 1")
        self.capacity = capacity
        self._data: OrderedDict = OrderedDict()

    def get(self, key):
        if key not in self._data:
            return None
        self._data.move_to_end(key)
        return self._data[key]

    def put(self, key, value) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        if len(self._data) > self.capacity:
            self._data.popitem(last=False)

    def __len__(self) -> int:
        return len(self._data)
