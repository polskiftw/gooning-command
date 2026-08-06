from __future__ import annotations

from dataclasses import dataclass

from .database import Database
from .generation_store import GenerationRecord, GenerationStore


@dataclass(frozen=True)
class GenerationStartupState:
    """Generation persistence discovered during normal database startup."""

    store: GenerationStore
    active_generation: GenerationRecord | None
    legacy_view_only_generation_id: str | None


def initialize_generation_storage(database: Database) -> GenerationStartupState:
    """Install generation persistence on the primary deduper connection.

    The migration is additive and idempotent. Existing assets, hashes, mutable
    review rows, deletion logs, and index-cleanup work remain in place. An old
    mutable queue is recorded only as legacy view-only material; it is never
    promoted or treated as certified merely because legacy matching metadata
    says that matching completed.
    """

    store = GenerationStore(database.connection)
    legacy_generation_id = store.register_legacy_view_only()
    return GenerationStartupState(
        store=store,
        active_generation=store.active(),
        legacy_view_only_generation_id=legacy_generation_id,
    )
