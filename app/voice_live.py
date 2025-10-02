"""Compatibility shim for legacy imports.

The preview implementation exposed ``VoiceLiveSessionGA`` from this module.
The GA code path now lives in :mod:`app.speech_session`.  To avoid confusing
callers (or stale imports during refactors), this module simply re-exports the
``SpeechSession`` class so any remaining references continue to work while
keeping the GA-only implementation.
"""

from __future__ import annotations

from .speech_session import SpeechSession

__all__ = ["SpeechSession", "VoiceLiveSessionGA", "create_ga_session"]


# Legacy alias -------------------------------------------------------------

VoiceLiveSessionGA = SpeechSession


def create_ga_session(*_args, **_kwargs) -> SpeechSession:
    """Return a GA speech session.

    Parameters are ignored because :class:`SpeechSession` already consumes the
    global :mod:`app.config` settings.  The signature is preserved for
    backwards-compatibility with preview callers.
    """

    return SpeechSession()
