"""Bounded retries for read-only Actor polling in the pinned PyTRIO SDK."""

import asyncio
import functools
import importlib.metadata
import logging

from pytrio.errors.actor import ActorEventGetError
from pytrio.transport.actor.event.get import EventGetActorMixin

logger = logging.getLogger(__name__)


def enable_event_get_retries() -> None:
    """Retry only event GETs; leave submission methods and SDK files unchanged.

    PyTRIO 0.2.9 shares one retry timeout between event submission and polling.
    Training disables that timeout to avoid replaying uncertain submissions.
    This version-checked compatibility wrapper keeps transient GET failures
    inside the coordinator's existing future, querying the same event ID.
    """
    if importlib.metadata.version("pytrio") != "0.2.9":
        raise RuntimeError("事件查询重试适配器只验证了 PyTRIO 0.2.9，请先检查 SDK 兼容性")
    original = EventGetActorMixin.get_event
    if getattr(original, "_nemothello_read_retry", False):
        return

    @functools.wraps(original)
    async def get_with_retries(self, event_id, *, wait_timeout_seconds=None):
        for attempt in range(1, 4):
            try:
                return await original(self, event_id, wait_timeout_seconds=wait_timeout_seconds)
            except ActorEventGetError as error:
                if not error.retryable or attempt == 3:
                    raise
                logger.warning("重试读取训练事件 %s，下一次查询 %s/3", event_id, attempt + 1)
                await asyncio.sleep(attempt)

    get_with_retries._nemothello_read_retry = True
    EventGetActorMixin.get_event = get_with_retries
