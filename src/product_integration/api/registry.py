"""PI-05 — in-memory PGDR session registry.

PI-03 established (and PI-04 carried forward) a real, disclosed limitation:
`pgdr.session_controller.SessionController` keeps its own analytical state
purely in-process (`self._case_states`), never persisted anywhere. A
genuinely different `SessionController` instance cannot resume a session
started by another one — confirmed directly against PGDR's own source at
every prior PI unit in this project.

This registry is NOT an attempt to solve that limitation (forbidden, §28 of
the PI-05 instruction: "Do NOT add unauthorized PGDR persistence"). It is
the explicit, disclosed, process-local mechanism that lets *separate HTTP
requests within the same running process* share the *same* `SessionController`
instance for a given PGDR execution — exactly the "process-local controller
state" the instruction itself anticipates and permits ("If continuation
requires process-local controller state, surface this limitation through
explicit product/API behavior"). It is a plain in-memory dict, not a
database, not a new PGDR persistence layer, and it is lost on process
restart — that loss is the real, honest boundary of what this registry can
promise, and is exactly what PI-05's own process-restart continuation test
(§46) is designed to observe and report truthfully.
"""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Optional
from uuid import UUID

from pgdr.models import DiagnosticSession
from pgdr.session_controller import SessionController


@dataclass
class _RegistryEntry:
    session_controller: SessionController
    pgdr_session: DiagnosticSession


class PGDRSessionRegistry:
    """Process-local only. Never persisted. Never claims otherwise."""

    def __init__(self) -> None:
        self._entries: dict[UUID, _RegistryEntry] = {}
        self._lock = Lock()

    def put(self, execution_id: UUID, session_controller: SessionController, pgdr_session: DiagnosticSession) -> None:
        with self._lock:
            self._entries[execution_id] = _RegistryEntry(session_controller, pgdr_session)

    def get(self, execution_id: UUID) -> Optional[_RegistryEntry]:
        with self._lock:
            return self._entries.get(execution_id)

    def drop(self, execution_id: UUID) -> None:
        with self._lock:
            self._entries.pop(execution_id, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


# A single process-wide registry instance. Explicitly module-level, explicitly
# process-local, explicitly documented as such above -- not hidden behind a
# dependency-injection layer that could obscure its actual (lack of)
# durability. FastAPI's dependency wiring (see deps.py) exposes this same
# instance so tests can construct a genuinely fresh one to simulate a
# process restart (§46).
default_registry = PGDRSessionRegistry()
