"""``sessions.send`` rejects a non-string ``message`` before it does any work.

``message`` is a required parameter, but required is not the same as typed:
``message_text: str = params["message"]`` is an annotation, not a runtime
check. A falsy non-string (``0``, ``false``, ``null``, ``[]``) reached
``normalize_incoming_text``, whose ``text = message_text or ""`` turned it into
an empty string — so the send reported success with a message the caller never
composed. A truthy non-string (an ``int``, a non-empty list or dict) survived
normalisation and later hit a ``.lower()`` call, leaking the Python error
string as a raw ``INTERNAL_ERROR`` instead of a clean validation error.

``sessions.create`` already guards its optional seed message this way; the
required one on ``sessions.send`` did not. See issue #1885.
"""

from __future__ import annotations

from typing import Any

import pytest

# Importing the module registers its methods on the shared dispatcher.
import agentos.gateway.rpc_sessions  # noqa: F401
from agentos.gateway.config import GatewayConfig
from agentos.gateway.rpc import RpcContext, get_dispatcher

SESSION_KEY = "agent:main:webchat:send-validation"

BAD_MESSAGES: list[Any] = [0, 12345, None, False, True, 1.5, [], ["a"], {"a": 1}, b"bytes"]


class _FakeSession:
    def __init__(self, session_key: str) -> None:
        self.session_key = session_key
        self.session_id = session_key.rsplit(":", 1)[-1]


class _FakeStorage:
    """Records session lookups so a test can prove none happened."""

    def __init__(self, session: _FakeSession) -> None:
        self._session = session
        self.get_session_calls: list[str] = []
        self.memory_durable_receipts: list[Any] = []

    async def get_session(self, key: str) -> _FakeSession | None:
        self.get_session_calls.append(key)
        return self._session if key == self._session.session_key else None


class _FakeSessionManager:
    """Just enough manager to observe how far the handler got."""

    def __init__(self, session: _FakeSession) -> None:
        self._storage = _FakeStorage(session)

    @property
    def storage(self) -> _FakeStorage:
        return self._storage


@pytest.fixture
def dispatcher():
    return get_dispatcher()


@pytest.fixture
def manager() -> _FakeSessionManager:
    return _FakeSessionManager(_FakeSession(SESSION_KEY))


@pytest.fixture
def ctx(manager: _FakeSessionManager) -> RpcContext:
    context = RpcContext(conn_id="test-conn", config=GatewayConfig())
    context.session_manager = manager
    return context


# ---------------------------------------------------------------------------
# Handler: a non-string message is a client error, and nothing is looked up.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("value", BAD_MESSAGES)
async def test_non_string_message_is_invalid_request_and_touches_no_session(
    dispatcher, ctx, manager, value: Any
) -> None:
    res = await dispatcher.dispatch(
        "r1",
        "sessions.send",
        {"key": SESSION_KEY, "message": value},
        ctx,
    )

    assert res.ok is False
    assert res.error.code == "INVALID_REQUEST"
    assert res.error.message == "params.message must be a string"
    # The guard runs before any session is loaded, so a rejected send cannot
    # have appended anything anywhere.
    assert manager.storage.get_session_calls == []


@pytest.mark.asyncio
async def test_missing_message_still_reports_the_presence_error(dispatcher, ctx, manager) -> None:
    res = await dispatcher.dispatch("r1", "sessions.send", {"key": SESSION_KEY}, ctx)

    assert res.ok is False
    assert res.error.code == "INVALID_REQUEST"
    assert res.error.message == "params.message is required"
    assert manager.storage.get_session_calls == []


# ---------------------------------------------------------------------------
# Handler: a real string is still let through.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["", "hello", "你好 🎉", "   "])
async def test_string_message_passes_the_guard(dispatcher, ctx, manager, value: str) -> None:
    res = await dispatcher.dispatch(
        "r1",
        "sessions.send",
        {"key": SESSION_KEY, "message": value},
        ctx,
    )

    # The guard let it through: the handler went on to load the session. It may
    # still fail later on this deliberately thin fake manager, but never with
    # the message-type error.
    assert manager.storage.get_session_calls == [SESSION_KEY]
    assert not (res.ok is False and res.error.message == "params.message must be a string")
