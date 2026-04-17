"""Per-call session that owns speech, state, and timeouts.

A CallSession is created when a call starts and destroyed when it ends.
It encapsulates the SpeechService, tracks call state in AppState, and
runs a timeout watcher that auto-hangs-up on expiry.
"""
from __future__ import annotations

import asyncio
import logging
import time

from ..config import settings
from ..models.state import AppState
from .speech import SpeechService
from ..services.event_bus import event_bus, EventType

logger = logging.getLogger("app.call")


class CallSession:
    """Encapsulates a single call's lifecycle.

    Created by CallManager on call start, destroyed on call end.
    Owns the SpeechService and timeout watcher for this call.
    """

    def __init__(self, call_id: str, app_state: AppState, session_id: str) -> None:
        self.call_id = call_id
        self.session_id = session_id
        self._app_state = app_state
        self.speech: SpeechService = SpeechService(auth_session_id=session_id)
        self._timeout_task: asyncio.Task | None = None
        self._hangup_callback: asyncio.Future | None = None

    @property
    def active(self) -> bool:
        return self.speech.active

    async def start(self, system_prompt: str | None = None) -> None:
        """Connect to Voice Live and start the timeout watcher."""
        await self.speech.connect(system_prompt)
        # Record Voice Live session in app state
        await self._app_state.begin_voicelive(
            self.session_id,
            self.speech.session_id,
            self.speech.voice or "unknown",
            self.speech.model,
        )
        event_bus.emit(EventType.VL_SESSION_STARTED, session_id=self.session_id, call_id=self.call_id, vl_session_id=self.speech.session_id)
        # Start timeout watcher
        self._timeout_task = asyncio.create_task(self._watch_timeouts())
        logger.info(
            "CallSession started call_id=%s speech_id=%s session_id=%s",
            self.call_id,
            self.speech.session_id,
            self.session_id,
        )

    async def stop(self, reason: str | None = None) -> None:
        """Tear down speech session and cancel timeout watcher."""
        if self._timeout_task:
            self._timeout_task.cancel()
            try:
                await self._timeout_task
            except (asyncio.CancelledError, Exception):
                pass
            self._timeout_task = None

        if self.speech.active:
            await self.speech.close()

        event_bus.emit(EventType.VL_SESSION_ENDED, session_id=self.session_id, call_id=self.call_id, reason=reason)
        await self._app_state.end_voicelive(self.session_id, reason)
        await self._app_state.end_call(self.session_id, self.call_id, reason)
        logger.info(
            "CallSession stopped call_id=%s reason=%s", self.call_id, reason
        )

    def set_hangup_callback(self, callback: asyncio.Future) -> None:
        """Register a future that the timeout watcher can signal for auto-hangup.

        The CallManager provides this so the session can request a hangup
        without knowing about ACS directly.
        """
        self._hangup_callback = callback

    async def _watch_timeouts(self) -> None:
        """Background task: check call duration and idle time every 5 seconds."""
        try:
            while True:
                await asyncio.sleep(5)

                call = self._app_state.get_call(self.session_id)
                if not call:
                    break

                elapsed = time.time() - call.started_at

                # Hard timeout
                if elapsed > settings.call_timeout_sec:
                    logger.info(
                        "Call timeout after %.0fs call_id=%s",
                        elapsed,
                        self.call_id,
                    )
                    if self._hangup_callback and not self._hangup_callback.done():
                        self._hangup_callback.set_result("Timeout")
                    break

                # Idle timeout
                last_event = self._app_state.get_last_event(self.session_id)
                if last_event and (time.time() - last_event) > settings.call_idle_timeout_sec:
                    logger.info("Call idle timeout call_id=%s", self.call_id)
                    if self._hangup_callback and not self._hangup_callback.done():
                        self._hangup_callback.set_result("Idle")
                    break

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("timeout watcher error: %s", exc)
