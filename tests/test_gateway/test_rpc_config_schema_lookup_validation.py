"""``config.schema.lookup`` rejects a non-string ``path`` as a client error.

The handler checked that ``path`` was present, then called ``path.split(".")``
on it. A non-string raised ``AttributeError``, and the dispatcher's catch-all
surfaced the Python error string as a raw ``INTERNAL_ERROR`` — the client saw
``'int' object has no attribute 'split'`` instead of a validation error. The
same shape as the ``sessions.send`` / ``sessions.delete`` gaps.
"""

from __future__ import annotations

from typing import Any

import pytest

# Importing the module registers its methods on the shared dispatcher.
import agentos.gateway.rpc_config  # noqa: F401
from agentos.gateway.config import GatewayConfig
from agentos.gateway.rpc import RpcContext, get_dispatcher

BAD_PATHS: list[Any] = [0, 12345, None, True, 1.5, ["heartbeat"], {"a": 1}]


@pytest.fixture
def dispatcher():
    return get_dispatcher()


@pytest.fixture
def ctx() -> RpcContext:
    return RpcContext(conn_id="test-conn", config=GatewayConfig())


@pytest.mark.asyncio
@pytest.mark.parametrize("value", BAD_PATHS)
async def test_non_string_path_is_invalid_request(dispatcher, ctx, value: Any) -> None:
    res = await dispatcher.dispatch("r1", "config.schema.lookup", {"path": value}, ctx)

    assert res.ok is False
    assert res.error.code == "INVALID_REQUEST"
    assert res.error.message == "params.path must be a string"


@pytest.mark.asyncio
async def test_missing_path_still_reports_the_presence_error(dispatcher, ctx) -> None:
    res = await dispatcher.dispatch("r1", "config.schema.lookup", {}, ctx)

    assert res.ok is False
    assert res.error.code == "INVALID_REQUEST"
    assert res.error.message == "params.path is required"


@pytest.mark.asyncio
async def test_a_real_path_still_resolves(dispatcher, ctx) -> None:
    res = await dispatcher.dispatch("r1", "config.schema.lookup", {"path": "heartbeat"}, ctx)

    assert res.ok is True
    assert res.payload["path"] == "heartbeat"


@pytest.mark.asyncio
async def test_an_unknown_path_still_reports_a_key_error(dispatcher, ctx) -> None:
    res = await dispatcher.dispatch("r1", "config.schema.lookup", {"path": "nope.nope"}, ctx)

    assert res.ok is False
    # KeyError's str() wraps the message in quotes; assert on the text itself.
    assert "Schema path not found: nope.nope" in res.error.message
