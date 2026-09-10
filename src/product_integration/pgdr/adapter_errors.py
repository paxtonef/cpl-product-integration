"""PI-03 adapter error taxonomy.

Distinct types for each failure category §25 of the PI-03 instruction
requires kept separate — never one generic status.
"""
from __future__ import annotations


class PGDRAdapterError(Exception):
    """Base for all PI-03-raised errors."""


class PGDRSessionAlreadyTerminalError(PGDRAdapterError):
    """continue_pgdr_session was called against an execution whose CPL
    RunnerExecution is already COMPLETED — refused before PGDR is ever
    called again, since PGDR's own contract does not define behavior for
    submitting an answer to an already-finished session, and calling it
    anyway would risk double-finalization."""

    def __init__(self, execution_id):
        super().__init__(f"RunnerExecution {execution_id} is already terminal; refusing to continue the PGDR session")
        self.execution_id = execution_id


class UnexpectedPGDRSessionStateError(PGDRAdapterError):
    """The completeness guard (§34): raised if a PGDR session is observed
    in a state this adapter's status-derivation logic does not recognize
    as either 'needs an answer' or 'terminal' — i.e. SessionController's
    real, empirically-confirmed synchronous behavior (every start()/
    submit_answer() call returns either with pending_questions or in a
    terminal SessionState) has changed. Fails loudly rather than guessing."""

    def __init__(self, state, has_pending_questions: bool):
        super().__init__(
            f"PGDR session.state={state!r} with pending_questions={has_pending_questions} does not match any "
            f"recognized adapter signal (terminal: COMPLETED/ESCALATED; awaiting answer: pending_questions "
            f"non-empty) — refusing to guess a CPL execution status."
        )
        self.state = state
        self.has_pending_questions = has_pending_questions
