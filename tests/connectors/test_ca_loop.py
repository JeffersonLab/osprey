"""The process's Channel Access loop: what it holds the CA environment to.

Each test makes a ``CaLoop`` of its own rather than the process's, so nothing
here talks Channel Access or touches the shared loop.
"""

import asyncio

import pytest

from osprey_connectors.control_system.ca_loop import CA_ENV_KEYS, CaLoop, current_ca_env

GATEWAY_A = {
    "EPICS_CA_ADDR_LIST": "gw-a",
    "EPICS_CA_SERVER_PORT": "5064",
    "EPICS_CA_NAME_SERVERS": None,
    "EPICS_CA_AUTO_ADDR_LIST": "NO",
}
GATEWAY_B = dict(GATEWAY_A, EPICS_CA_ADDR_LIST="gw-b")


async def _nothing() -> None:
    return None


@pytest.fixture
def ca_loop(monkeypatch):
    for key in CA_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    loop = CaLoop()
    yield loop
    loop.stop()


def test_a_claim_is_replaced_freely_until_ca_is_first_called(ca_loop):
    ca_loop.claim_env(GATEWAY_A)
    ca_loop.claim_env(GATEWAY_B)
    ca_loop.run_sync(_nothing(), timeout=5)

    with pytest.raises(RuntimeError, match="cannot be repointed"):
        ca_loop.claim_env(GATEWAY_A)
    ca_loop.claim_env(GATEWAY_B)


def test_a_first_call_with_nothing_claimed_pins_the_environment_it_ran_with(ca_loop, monkeypatch):
    """The dispatch source calls CA without claiming; a connector after it is still held."""
    for key, setting in GATEWAY_A.items():
        if setting is not None:
            monkeypatch.setenv(key, setting)
    ca_loop.run_sync(_nothing(), timeout=5)

    with pytest.raises(RuntimeError, match="cannot be repointed"):
        ca_loop.claim_env(GATEWAY_B)
    ca_loop.claim_env(current_ca_env())


def test_a_call_awaited_on_the_loop_thread_pins_the_environment_too(ca_loop):
    async def nested() -> None:
        await ca_loop.run(_nothing())

    ca_loop.claim_env(GATEWAY_A)
    asyncio.run_coroutine_threadsafe(nested(), ca_loop.loop).result(5)

    with pytest.raises(RuntimeError, match="cannot be repointed"):
        ca_loop.claim_env(GATEWAY_B)
