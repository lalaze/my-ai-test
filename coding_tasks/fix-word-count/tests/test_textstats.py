from textstats import count_words, top_words


def test_count_simple():
    assert count_words("hello world") == 2


def test_count_multiple_spaces():
    assert count_words("hello   world") == 2


def test_count_tabs_and_newlines():
    assert count_words("a\tb\nc  d\n") == 4


def test_count_blank():
    assert count_words("") == 0
    assert count_words("   \n\t") == 0


def test_top_case_insensitive():
    assert top_words("Cat cat dog", 1) == [("cat", 2)]


def test_top_tie_sorted_alphabetically():
    assert top_words("b a c b a c", 3) == [("a", 2), ("b", 2), ("c", 2)]


def test_top_ignores_extra_whitespace():
    assert top_words("x  x\n y", 5) == [("x", 2), ("y", 1)]
