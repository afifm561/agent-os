"""``sessions.delete`` validates the shape of ``key``/``keys`` before it iterates.

The handler accepted two shapes — ``{key}`` for one session and ``{keys}`` for
bulk — but only checked that one of them was present. ``keys`` was then trusted:

- A bare string sent as ``keys`` was iterated **character by character**, so a
  one-key delete answered ``ok: true`` with every character of the key listed as
  a deleted session while removing nothing. A client that meant one key got a
  success report and a session still on disk.
- An ``int`` raised a raw ``INTERNAL_ERROR`` out of ``for k in keys``
  (``'int' object is not iterable``), leaking the Python error string.
- A ``dict`` iterated its keys, and ``[1, 2]`` coerced the entries, so both
  "deleted" sessions that were never named.

A string entry is also rejected here rather than passed to
``canonicalize_session_key``, so ``[""]`` cannot report a blank session as
deleted.
"""

from __future__ import annotations

from typing import Any

import pytest

# Importing the module registers its methods on the shared dispatcher.
import agentos.gateway.rpc_sessions  # noqa: F401
from agentos.gateway.config import GatewayConfig
from agentos.gateway.rpc import RpcContext, get_dispatcher
from agentos.gateway.rpc_sessions import canonicalize_session_key

SESSION_KEY = "agent:main:webchat:delete-shape"
OTHER_KEY = "agent:main:webchat:delete-shape-two"

BAD_KEYS: list[Any] = [
    SESSION_KEY,  # a bare string: the char-iteration bug
    5,
    True,
    None,
    {"a": 1},
    [1, 2],
    [None],
    [""],
    ["   "],
    [SESSION_KEY, 7],
]


class _FakeStorage:
    """Records every delete so a test can prove nothing was removed."""

    def __init__(self) -> None:
        self.deleted: list[str] = []
        self.memory_durable_receipts: list[Any] = []

    async def delete_session(self, key: str) -> None:
        self.deleted.append(key)


class _FakeSessionManager:
    def __init__(self) -> None:
        self._storage = _FakeStorage()

    @property
    def storage(self) -> _FakeStorage:
        return self._storage


@pytest.fixture
def dispatcher():
    return get_dispatcher()


@pytest.fixture
def manager() -> _FakeSessionManager:
    return _FakeSessionManager()


@pytest.fixture
def ctx(manager: _FakeSessionManager) -> RpcContext:
    context = RpcContext(conn_id="test-conn", config=GatewayConfig())
    context.session_manager = manager
    return context


# ---------------------------------------------------------------------------
# Handler: a malformed ``keys`` is a client error, and nothing is deleted.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("value", BAD_KEYS)
async def test_malformed_keys_is_invalid_request_and_deletes_nothing(
    dispatcher, ctx, manager, value: Any
) -> None:
    res = await dispatcher.dispatch("r1", "sessions.delete", {"keys": value}, ctx)

    assert res.ok is False
    assert res.error.code == "INVALID_REQUEST"
    assert res.error.message in {
        "params.keys must be an array of strings",
        "params.keys must contain non-empty strings",
    }
    assert manager.storage.deleted == []


@pytest.mark.asyncio
async def test_non_string_single_key_is_rejected(dispatcher, ctx, manager) -> None:
    res = await dispatcher.dispatch("r1", "sessions.delete", {"key": 5}, ctx)

    assert res.ok is False
    assert res.error.code == "INVALID_REQUEST"
    assert res.error.message == "params.keys must contain non-empty strings"
    assert manager.storage.deleted == []


@pytest.mark.asyncio
async def test_empty_list_still_reports_the_presence_error(dispatcher, ctx, manager) -> None:
    res = await dispatcher.dispatch("r1", "sessions.delete", {"keys": []}, ctx)

    assert res.ok is False
    assert res.error.code == "INVALID_REQUEST"
    assert res.error.message == "params.key or params.keys is required"
    assert manager.storage.deleted == []


# ---------------------------------------------------------------------------
# Handler: the two documented shapes still work.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_key_still_deletes(dispatcher, ctx, manager) -> None:
    res = await dispatcher.dispatch("r1", "sessions.delete", {"key": SESSION_KEY}, ctx)

    assert res.ok is True
    assert res.payload["deleted"] == [SESSION_KEY]
    assert manager.storage.deleted == [canonicalize_session_key(SESSION_KEY)]


@pytest.mark.asyncio
async def test_bulk_keys_still_delete(dispatcher, ctx, manager) -> None:
    res = await dispatcher.dispatch(
        "r1", "sessions.delete", {"keys": [SESSION_KEY, OTHER_KEY]}, ctx
    )

    assert res.ok is True
    assert res.payload["deleted"] == [SESSION_KEY, OTHER_KEY]
    assert manager.storage.deleted == [
        canonicalize_session_key(SESSION_KEY),
        canonicalize_session_key(OTHER_KEY),
    ]
