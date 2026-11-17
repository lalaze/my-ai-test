def count_words(text: str) -> int:
    """统计文本中的单词数。"""
    if not text:
        return 0
    return len(text.split(" "))


def top_words(text: str, n: int = 3) -> list[tuple[str, int]]:
    """返回出现次数最多的 n 个单词及其次数。"""
    counts: dict[str, int] = {}
    for word in text.split(" "):
        counts[word] = counts.get(word, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])[:n]
