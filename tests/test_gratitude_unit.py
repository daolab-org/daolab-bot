"""Minimal unit tests for GratitudeService core logic.

These tests avoid DB/network by monkeypatching the service's `db`.
"""

import types
import pytest

from app.services.gratitude_service import gratitude_service


class _FakeUser:
    def __init__(self, username: str, nickname: str | None = None):
        self.username = username
        self.nickname = nickname or username


class _FakeDB:
    def __init__(self, sent_today: int = 0):
        self._base_sent = sent_today
        self._sent_incremented = False

    def ensure_connected(self) -> None:  # pragma: no cover - trivial
        return None

    async def get_or_create_user(
        self,
        discord_id: str,
        username: str,
        generation: int,
        nickname: str | None = None,
    ):
        return _FakeUser(username=username, nickname=nickname)

    async def count_gratitude_sent_today(self, from_user_id: str) -> int:
        # Reflect the post-insert count after send_gratitude is called
        return self._base_sent + (1 if self._sent_incremented else 0)

    async def send_gratitude(
        self, from_user_id: str, to_user_id: str, message: str | None = None
    ):
        self._sent_incremented = True
        # Return an object mimicking a stored record
        return types.SimpleNamespace(id="fake", message=message)

    async def get_user_points(self, discord_id: str) -> int:
        # Not essential for these unit assertions
        return 0


@pytest.mark.asyncio
async def test_gratitude_self_send_unit(monkeypatch):
    """Self-send is blocked before any DB writes."""
    monkeypatch.setattr(gratitude_service, "db", _FakeDB(sent_today=0))

    res = await gratitude_service.send_gratitude("u1", "User1", "u1", "User1")

    assert res["success"] is False
    assert "자기 자신에게는" in res["message"]


@pytest.mark.asyncio
async def test_gratitude_daily_limit_unit(monkeypatch):
    """Daily limit blocks after 2 sends with explanatory message."""
    monkeypatch.setattr(gratitude_service, "db", _FakeDB(sent_today=2))

    res = await gratitude_service.send_gratitude("from", "FromUser", "to", "ToUser")

    assert res["success"] is False
    assert res.get("already_sent") is True
    assert "한도를 모두 사용" in res["message"]


@pytest.mark.asyncio
async def test_gratitude_success_remaining_and_trim_unit(monkeypatch):
    """Success response includes remaining-quota text and trims message to 200 chars."""
    # Simulate one prior send, so after this success remaining becomes 0
    fake_db = _FakeDB(sent_today=1)
    monkeypatch.setattr(gratitude_service, "db", fake_db)

    long_msg = "x" * 250
    res = await gratitude_service.send_gratitude(
        "from", "FromUser", "to", "ToUser", message=long_msg
    )

    assert res["success"] is True
    # Trimmed message is echoed in quotes in the response message
    assert '"' + ("x" * 200) + '"' in res["message"]
    # Remaining quota guidance
    assert "오늘 남은 가능 횟수: 0회" in res["message"]
