import asyncio
from types import SimpleNamespace

import pytest
from pytrio.errors.actor import ActorEventGetError, ActorEventSubmitError
from pytrio.protocol.actor.events.event import (
    EventEnvelope,
    EventMetadata,
    EventStatus,
    EventType,
)
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
    ActorEventGetError("bad request", status_code=400),
    ActorEventGetError("forbidden", status_code=403, retryable=True),
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
    with pytest.raises(RuntimeError, match="compatibility"):
        pytrio_transport.enable_event_get_retries()
    assert EventGetActorMixin.get_event is original


@pytest.mark.parametrize("kind", [EventType.TRAINER_FORWARD_BACKWARD, EventType.TRAINER_OPTIMIZE_STEP])
def test_lost_ack_reuses_sdk_event_bytes_and_accepts_deduplication(monkeypatch, no_backoff, kind):
    requests = []
    applied = set()

    async def request(method, path, **kwargs):
        requests.append((method, path, kwargs["content"], kwargs["event_cuid"]))
        event_id = kwargs["event_cuid"]
        if event_id not in applied:
            applied.add(event_id)
            # The operation reached the server, but its acknowledgement was lost.
            raise ActorEventSubmitError("Response read failed", retryable=True)
        raise ActorEventSubmitError("Already accepted", status_code=409, code="event_exists")

    actor = SimpleNamespace(actor=SimpleNamespace(actor_cuid="test-actor"),
        configuration=SimpleNamespace(actor_event_submit_timeout_seconds=90,
                                      training_retry_timeout_seconds=0),
        _request_with_actor_jwt=request)
    envelope = EventEnvelope(event_id="event_000000000001", type=kind,
        metadata=EventMetadata(index=3, step=2, timestamp=1, sdk="pytrio",
                               sdk_version="0.2.9", run_id="test-run"),
        payload={"data": [1, 2, 3]})
    # Restore the real SDK method after this test, including the wrapper installed
    # below, so enabling retry support cannot leak into unrelated tests.
    monkeypatch.setattr(EventSubmitActorMixin, "submit_event", EventSubmitActorMixin.submit_event)
    monkeypatch.setattr(pytrio_transport.EventGetActorMixin, "get_event",
                        EventGetActorMixin.get_event)
    pytrio_transport.enable_training_event_retries()
    wrapped = EventSubmitActorMixin.submit_event
    pytrio_transport.enable_training_event_retries()
    assert EventSubmitActorMixin.submit_event is wrapped
    response = asyncio.run(wrapped(actor, envelope))
    assert response.status == EventStatus.ACCEPTED
    assert response.event_id == envelope.event_id
    assert applied == {envelope.event_id}
    assert len(requests) == 2 and requests[0] == requests[1]


@pytest.mark.parametrize("kind", [kind for kind in EventType
                                 if kind not in pytrio_transport.RETRIED_SUBMIT_TYPES])
def test_unverified_event_types_are_never_resubmitted(monkeypatch, no_backoff, kind):
    calls = []
    error = ActorEventSubmitError("Response read failed", retryable=True)

    async def submit(self, envelope):
        calls.append(envelope)
        raise error

    monkeypatch.setattr(EventSubmitActorMixin, "submit_event", submit)
    monkeypatch.setattr(EventGetActorMixin, "get_event", EventGetActorMixin.get_event)
    pytrio_transport.enable_training_event_retries()
    envelope = SimpleNamespace(type=kind, event_id="same-event")
    with pytest.raises(ActorEventSubmitError) as raised:
        asyncio.run(EventSubmitActorMixin.submit_event(object(), envelope))
    assert raised.value is error
    assert calls == [envelope]


def test_repeated_transient_submissions_stop_after_three_attempts(monkeypatch, no_backoff):
    calls = []
    error = ActorEventSubmitError("Response read failed", retryable=True)

    async def submit(self, envelope):
        calls.append(envelope)
        raise error

    monkeypatch.setattr(EventSubmitActorMixin, "submit_event", submit)
    monkeypatch.setattr(EventGetActorMixin, "get_event", EventGetActorMixin.get_event)
    pytrio_transport.enable_training_event_retries()
    envelope = SimpleNamespace(type=EventType.TRAINER_OPTIMIZE_STEP, event_id="same-event")
    with pytest.raises(ActorEventSubmitError) as raised:
        asyncio.run(EventSubmitActorMixin.submit_event(object(), envelope))
    assert raised.value is error
    assert len(calls) == 3 and all(item is envelope for item in calls)


@pytest.mark.parametrize("error", [
    ActorEventSubmitError("bad payload", status_code=400),
    ActorEventSubmitError("forbidden", status_code=403, retryable=True),
    ActorEventSubmitError("conflict", status_code=409, code="conflict"),
    ValueError("invalid response"), asyncio.CancelledError(),
])
def test_submission_nontransient_errors_are_not_retried(monkeypatch, no_backoff, error):
    calls = []

    async def submit(self, envelope):
        calls.append(envelope)
        raise error

    monkeypatch.setattr(EventSubmitActorMixin, "submit_event", submit)
    monkeypatch.setattr(EventGetActorMixin, "get_event", EventGetActorMixin.get_event)
    pytrio_transport.enable_training_event_retries()
    envelope = SimpleNamespace(type=EventType.TRAINER_FORWARD_BACKWARD, event_id="same-event")
    with pytest.raises(type(error)):
        asyncio.run(EventSubmitActorMixin.submit_event(object(), envelope))
    assert calls == [envelope]


def test_sdk_upgrade_refuses_both_training_wrappers(monkeypatch):
    original_get = EventGetActorMixin.get_event
    original_submit = EventSubmitActorMixin.submit_event
    monkeypatch.setattr(pytrio_transport.importlib.metadata, "version", lambda _: "future-version")
    with pytest.raises(RuntimeError, match="compatibility"):
        pytrio_transport.enable_training_event_retries()
    assert EventGetActorMixin.get_event is original_get
    assert EventSubmitActorMixin.submit_event is original_submit
