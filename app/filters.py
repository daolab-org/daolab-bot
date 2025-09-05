from __future__ import annotations

from typing import Any


def is_test_like_name(name: str | None) -> bool:
    """Return True if a username/nickname looks like test data.

    Heuristics: case-insensitive match for "test" or common placeholders.
    Keeps logic centralized so UI and publishers can consistently exclude tests.
    """
    if not name:
        return False
    n = name.strip().lower()
    if not n:
        return False
    # Core patterns; conservative but effective for typical test names
    patterns = [
        "testuser",
        "test",
        "테스트",
        "dummy",
        "sample",
    ]
    return any(p in n for p in patterns)


def is_test_user_doc(user_doc: dict[str, Any] | None) -> bool:
    if not user_doc:
        return False
    username = user_doc.get("username")
    nickname = user_doc.get("nickname")
    return is_test_like_name(username) or is_test_like_name(nickname)
