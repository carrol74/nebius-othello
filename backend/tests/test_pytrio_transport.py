import asyncio

import pytest
from pytrio.errors.actor import ActorEventGetError
from pytrio.transport.actor.event.get import EventGetActorMixin
from pytrio.transport.actor.event.submit import EventSubmitActorMixin

from nemothello import pytrio_transport


@pytest.fixture
def no_backoff(monkeypatch):
    async def sleep(_):
        pass

    monkeypatch.setattr(pytrio_transport.asyncio, "sleep", sleep)


def test_transient_reads_keep_event_identity_without_changing_submit(monkeypatch, no_backoff):
    calls = []
    result = object()

    async def get(self, event_id, *, wait_timeout_seconds=None):
        calls.append((self, event_id, wait_timeout_seconds))
        if len(calls) < 3:
            raise ActorEventGetError("read failed", retryable=True)
        return result

    monkeypatch.setattr(EventGetActorMixin, "get_event", get)
    original_submit = EventSubmitActorMixin.submit_event
    pytrio_transport.enable_event_get_retries()
    wrapped = EventGetActorMixin.get_event
    pytrio_transport.enable_event_get_retries()
    assert EventGetActorMixin.get_event is wrapped
    actor = object()
    assert asyncio.run(wrapped(actor, "same-event", wait_timeout_seconds=17)) is result
    assert calls == [(actor, "same-event", 17)] * 3
    assert EventSubmitActorMixin.submit_event is original_submit


def test_failed_reads_stop_after_three_attempts(monkeypatch, no_backoff):
    calls = []
    error = ActorEventGetError("read failed", retryable=True)

    async def get(self, event_id, *, wait_timeout_seconds=None):
        calls.append(event_id)
        raise error

    monkeypatch.setattr(EventGetActorMixin, "get_event", get)
    pytrio_transport.enable_event_get_retries()
    with pytest.raises(ActorEventGetError) as raised:
        asyncio.run(EventGetActorMixin.get_event(object(), "same-event"))
    assert raised.value is error
    assert calls == ["same-event"] * 3


@pytest.mark.parametrize("error", [
    ActorEventGetError("invalid request", code="invalid_request", status_code=400),
    ValueError("invalid response"), asyncio.CancelledError(),
])
def test_nontransient_errors_and_cancellation_are_not_retried(monkeypatch, no_backoff, error):
    calls = []

    async def get(self, event_id, *, wait_timeout_seconds=None):
        calls.append(event_id)
        raise error

    monkeypatch.setattr(EventGetActorMixin, "get_event", get)
    pytrio_transport.enable_event_get_retries()
    with pytest.raises(type(error)):
        asyncio.run(EventGetActorMixin.get_event(object(), "same-event"))
    assert calls == ["same-event"]


def test_sdk_upgrade_requires_review_before_modifying_transport(monkeypatch):
    original = EventGetActorMixin.get_event
    monkeypatch.setattr(pytrio_transport.importlib.metadata, "version", lambda _: "future-version")
    with pytest.raises(RuntimeError, match="兼容性"):
        pytrio_transport.enable_event_get_retries()
    assert EventGetActorMixin.get_event is original
