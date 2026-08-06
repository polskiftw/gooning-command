from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from .generation_identity import (
    MATCHER_VERSION,
    GenerationValidation,
    ValidationState,
    build_generation_identity,
    validate_generation,
)
from .generation_store import GenerationRecord, GenerationStore
from .models import Asset


class InventorySource(Protocol):
    def list_assets(self) -> list[Asset]: ...


class StartupPhase(str, Enum):
    SAVED_QUEUE_LOCKED = "saved_queue_locked"
    VALIDATING_R2 = "validating_r2"
    VALIDATED_ACTIONABLE = "validated_actionable"
    REBUILD_REQUIRED = "rebuild_required"
    VALIDATION_FAILED = "validation_failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class StartupSnapshot:
    phase: StartupPhase
    saved_generation: GenerationRecord | None
    validation: GenerationValidation | None
    inventory: tuple[Asset, ...]
    error: str | None = None

    @property
    def saved_queue_visible(self) -> bool:
        return self.saved_generation is not None

    @property
    def destructive_actions_enabled(self) -> bool:
        return self.phase == StartupPhase.VALIDATED_ACTIONABLE

    @property
    def rebuild_required(self) -> bool:
        return self.phase == StartupPhase.REBUILD_REQUIRED


class StartupValidationCoordinator:
    """Validate one immutable startup inventory snapshot against saved certification.

    The coordinator never polls R2. One successful listing is materialized and reused
    for identity validation and the subsequent staging build. Listing failures leave
    the saved generation visible but locked.
    """

    def __init__(
        self,
        generations: GenerationStore,
        inventory_source: InventorySource,
        slider_value: int,
        *,
        matcher_version: str = MATCHER_VERSION,
    ) -> None:
        self.generations = generations
        self.inventory_source = inventory_source
        self.slider_value = slider_value
        self.matcher_version = matcher_version
        self._lock = threading.RLock()
        self._cancelled = threading.Event()
        self._thread: threading.Thread | None = None
        self._snapshot = StartupSnapshot(
            phase=StartupPhase.SAVED_QUEUE_LOCKED,
            saved_generation=generations.active(),
            validation=None,
            inventory=(),
        )

    def snapshot(self) -> StartupSnapshot:
        with self._lock:
            return self._snapshot

    def validate_now(self) -> StartupSnapshot:
        with self._lock:
            if self._cancelled.is_set():
                return self._set_cancelled()
            self._snapshot = StartupSnapshot(
                phase=StartupPhase.VALIDATING_R2,
                saved_generation=self._snapshot.saved_generation,
                validation=None,
                inventory=(),
            )

        try:
            inventory = tuple(self.inventory_source.list_assets())
        except Exception as exc:
            with self._lock:
                self._snapshot = StartupSnapshot(
                    phase=StartupPhase.VALIDATION_FAILED,
                    saved_generation=self._snapshot.saved_generation,
                    validation=None,
                    inventory=(),
                    error=f"{type(exc).__name__}: {exc}",
                )
                return self._snapshot

        with self._lock:
            if self._cancelled.is_set():
                return self._set_cancelled()
            current_identity = build_generation_identity(
                inventory,
                self.slider_value,
                matcher_version=self.matcher_version,
            )
            validation = validate_generation(
                self._snapshot.saved_generation,
                current_identity,
            )
            phase = (
                StartupPhase.VALIDATED_ACTIONABLE
                if validation.actionable
                else StartupPhase.REBUILD_REQUIRED
            )
            self._snapshot = StartupSnapshot(
                phase=phase,
                saved_generation=self._snapshot.saved_generation,
                validation=validation,
                inventory=inventory,
            )
            return self._snapshot

    def start(
        self,
        on_complete: Callable[[StartupSnapshot], None] | None = None,
    ) -> threading.Thread:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("startup validation is already running")
            self._thread = threading.Thread(
                target=self._run,
                args=(on_complete,),
                name="gparty-startup-validation",
                daemon=False,
            )
            self._thread.start()
            return self._thread

    def cancel(self) -> None:
        self._cancelled.set()

    def join(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _run(
        self,
        on_complete: Callable[[StartupSnapshot], None] | None,
    ) -> None:
        result = self.validate_now()
        if on_complete is not None:
            on_complete(result)

    def _set_cancelled(self) -> StartupSnapshot:
        self._snapshot = StartupSnapshot(
            phase=StartupPhase.CANCELLED,
            saved_generation=self._snapshot.saved_generation,
            validation=self._snapshot.validation,
            inventory=(),
        )
        return self._snapshot


def startup_status_text(snapshot: StartupSnapshot) -> str:
    """Return literal UI language with no implied safety beyond current state."""
    if snapshot.phase == StartupPhase.SAVED_QUEUE_LOCKED:
        return "Saved certified queue loaded — validating current R2 inventory — deletion locked"
    if snapshot.phase == StartupPhase.VALIDATING_R2:
        return "Validating current R2 inventory — deletion locked"
    if snapshot.phase == StartupPhase.VALIDATED_ACTIONABLE:
        return "Certified queue validated for current R2 inventory — deletion enabled"
    if snapshot.phase == StartupPhase.REBUILD_REQUIRED:
        reason = snapshot.validation.reason if snapshot.validation else "Saved certification is not current."
        return f"Saved queue is view-only — {reason} Rebuild required — deletion locked"
    if snapshot.phase == StartupPhase.VALIDATION_FAILED:
        return "R2 validation failed — saved queue remains view-only — deletion locked"
    return "Startup validation cancelled — deletion locked"
