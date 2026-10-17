"""Bounded Actor retries for the pinned PyTRIO SDK."""

import asyncio
import functools
import importlib.metadata
import logging

from pytrio.errors.actor import ActorEventGetError, ActorEventSubmitError
from pytrio.protocol.actor.events.event import EventType
from pytrio.transport.actor.event.get import EventGetActorMixin
from pytrio.transport.actor.event.submit import EventSubmitActorMixin

logger = logging.getLogger(__name__)
RETRIED_SUBMIT_TYPES = frozenset({EventType.TRAINER_FORWARD_BACKWARD,
                                EventType.TRAINER_OPTIMIZE_STEP})


def _check_sdk_version() -> None:
    if importlib.metadata.version("pytrio") != "0.2.9":
        raise RuntimeError("Event retry adapter is verified only with PyTRIO 0.2.9; check SDK compatibility first")


def _transient(error: ActorEventGetError | ActorEventSubmitError) -> bool:
    # The SDK's generic actor.request_failed code can mark even a permanent
    # HTTP error retryable. Require a transport failure or a transient status.
    return error.retryable and error.status_code in (0, 408, 429, 500, 502, 503, 504)


def enable_event_get_retries() -> None:
    """Retry only event GETs; leave submission methods and SDK files unchanged.

    PyTRIO 0.2.9 shares one retry timeout between event submission and polling.
    Training disables that timeout to avoid replaying uncertain submissions.
    This version-checked compatibility wrapper keeps transient GET failures
    inside the coordinator's existing future, querying the same event ID.
    """
    _check_sdk_version()
    original = EventGetActorMixin.get_event
    if getattr(original, "_nemothello_read_retry", False):
        return

    @functools.wraps(original)
    async def get_with_retries(self, event_id, *, wait_timeout_seconds=None):
        for attempt in range(1, 4):
            try:
                return await original(self, event_id, wait_timeout_seconds=wait_timeout_seconds)
            except ActorEventGetError as error:
                if not _transient(error) or attempt == 3:
                    raise
                logger.warning("Retry reading training event %s, next attempt %s/3", event_id, attempt + 1)
                await asyncio.sleep(attempt)

    get_with_retries._nemothello_read_retry = True
    EventGetActorMixin.get_event = get_with_retries


def enable_training_event_retries() -> None:
    """Retry gradient/optimizer submissions using the identical event envelope.

    Live duplicate probes verified these two event types return event_exists,
    which the pinned SDK converts to acceptance of the original event. Saves
    returned checkpoint-name conflict instead, so they remain single-attempt.
    Neither an event ID nor its payload/sequence is regenerated on retry.
    """
    _check_sdk_version()
    enable_event_get_retries()
    original = EventSubmitActorMixin.submit_event
    if getattr(original, "_nemothello_submit_retry", False):
        return

    @functools.wraps(original)
    async def submit_with_retries(self, envelope):
        if envelope.type not in RETRIED_SUBMIT_TYPES:
            return await original(self, envelope)
        for attempt in range(1, 4):
            try:
                return await original(self, envelope)
            except ActorEventSubmitError as error:
                if not _transient(error) or attempt == 3:
                    raise
                logger.warning("Retry submitting the same training event %s, next attempt %s/3",
                               envelope.event_id, attempt + 1)
                await asyncio.sleep(attempt)

    submit_with_retries._nemothello_submit_retry = True
    EventSubmitActorMixin.submit_event = submit_with_retries
