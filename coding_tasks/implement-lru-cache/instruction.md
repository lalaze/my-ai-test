请在 /workspace/lru.py 中实现 `LRUCache` 类（最近最少使用缓存），要求：

- `LRUCache(capacity)`：`capacity` 是最多能存的键数量；`capacity` 小于 1 时抛出 `ValueError`。
- `get(key)`：键存在时返回对应的值，并把它标记为「最近使用」；不存在时返回 `None`。
- `put(key, value)`：写入或更新键值，并把它标记为「最近使用」；写入后如果超出容量，淘汰最久没有被使用的键。
- `len(cache)`：返回当前存了多少个键。
- `get` 和 `put` 的平均时间复杂度都要是 O(1)。

目录里有一个基础测试 `test_lru_basic.py`，可以用 `python -m pytest` 运行。注意它只覆盖了最基本的情况。
