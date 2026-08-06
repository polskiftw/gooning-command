from __future__ import annotations

from .family_recertification_queue import PendingFamilyRecertification


def family_recertification_status_text(job: PendingFamilyRecertification) -> str:
    """Return literal, user-facing status for one unfinished family recertification."""
    attempt_word = "attempt" if job.attempt_count == 1 else "attempts"
    identity = (
        f"deleted {job.deleted_key}; protected partner {job.protected_key}; "
        f"{job.attempt_count} {attempt_word}"
    )

    if job.status == "running":
        return (
            f"Family recertification running — {identity}. The protected partner and its family "
            "remain hidden from review until recertification finishes."
        )
    if job.status == "retry":
        reason = job.last_error or "the previous recertification attempt did not finish"
        return (
            f"Family recertification saved for automatic retry — {identity}. Last failure: {reason}. "
            "The protected partner remains safe in R2 and hidden from review."
        )
    return (
        f"Family recertification pending — {identity}. The protected partner remains safe in R2 "
        "and hidden from review until recertification starts."
    )
