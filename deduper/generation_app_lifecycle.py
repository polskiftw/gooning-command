from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .generation_integration import GenerationStartupState
from .startup_validation import (
    StartupPhase,
    StartupSnapshot,
    StartupValidationCoordinator,
    startup_status_text,
)
from .survivor_policy import SurvivorPolicy, matcher_identity


class AppLike(Protocol):
    database: object
    store: object
    slider: object
    status: object
    pairs: list
    pair_index: int
    _inventory_verified_for_delete: bool

    def after(self, delay_ms: int, callback): ...
    def _refresh_pairs(self) -> None: ...
    def _set_action_state(self) -> None: ...
    def _set_review_state(self, enabled: bool) -> None: ...
    def _refresh_index_boundary(self, *, apply: bool) -> None: ...


@dataclass
class GenerationAppLifecycle:
    """Own startup projection, validation, and destructive-action gating.

    Certified generation rows remain immutable. The existing mutable `pairs`
    table is used only as a temporary UI projection until the review model is
    replaced natively in a later step.
    """

    app: AppLike
    startup: GenerationStartupState
    coordinator: StartupValidationCoordinator | None = None
    last_snapshot: StartupSnapshot | None = None

    def install(self) -> "GenerationAppLifecycle":
        active = self.startup.active_generation
        self.app._inventory_verified_for_delete = False
        config = getattr(self.app, "config", None)
        survivor_policy = getattr(config, "survivor_policy", SurvivorPolicy.BALANCED)
        configured_matcher = matcher_identity(survivor_policy)

        if active is not None and active.identity is not None:
            self._project_active_generation()
            self._set_slider(active.identity.slider_value)
            self.app.status.set(
                "Saved certified queue loaded — validating current R2 inventory — deletion locked"
            )
            self.coordinator = StartupValidationCoordinator(
                self.startup.store,
                self.app.store,
                active.identity.slider_value,
                matcher_version=configured_matcher,
            )
        else:
            self.app.status.set(
                "No trusted certified queue exists — rebuild required — deletion locked"
            )
            self.coordinator = StartupValidationCoordinator(
                self.startup.store,
                self.app.store,
                int(round(self.app.slider.get())),
                matcher_version=configured_matcher,
            )

        self._refresh_controls()
        self.app.after(0, self._begin_validation)
        return self

    def cancel(self) -> None:
        if self.coordinator is not None:
            self.coordinator.cancel()

    def _project_active_generation(self) -> None:
        active = self.startup.active_generation
        if active is None:
            return
        rows = self.startup.store.pairs(active.generation_id)
        projection = [
            (
                str(row["survivor_key"]),
                str(row["deletion_key"]),
                float(row["similarity"]),
                str(row["reason"]),
            )
            for row in rows
            if int(row["included"]) == 1 and int(row["excluded"]) == 0
        ]
        self.app.database.replace_pairs(projection, preserve_exclusions=False)
        self.app._refresh_pairs()
        if self.app.pairs:
            self.app.pair_index = min(active.saved_queue_position, len(self.app.pairs) - 1)

    def _set_slider(self, value: int) -> None:
        guard_exists = hasattr(self.app, "_slider_guard")
        if guard_exists:
            self.app._slider_guard = True
        try:
            self.app.slider.set(value)
        finally:
            if guard_exists:
                self.app._slider_guard = False

    def _begin_validation(self) -> None:
        if self.coordinator is None:
            return
        self.app.status.set("Validating current R2 inventory — deletion locked")
        self._refresh_controls()
        self.coordinator.start(
            lambda snapshot: self.app.after(
                0,
                lambda: self._apply_snapshot(snapshot),
            )
        )

    def _apply_snapshot(self, snapshot: StartupSnapshot) -> None:
        self.last_snapshot = snapshot
        self.app._inventory_verified_for_delete = snapshot.destructive_actions_enabled
        self.app.status.set(startup_status_text(snapshot))
        self._refresh_controls()

        # Preserve the single startup inventory snapshot for the staging builder.
        # A rebuild must consume this tuple rather than silently listing R2 again.
        self.app._startup_inventory_snapshot = snapshot.inventory
        self.app._startup_generation_phase = snapshot.phase

        if snapshot.rebuild_required:
            # Validation already materialized the one authoritative startup
            # inventory snapshot. Automatically build the replacement without
            # requiring a manual button or performing a second R2 listing.
            self.app.after(0, self.app.start_scan)

    def _refresh_controls(self) -> None:
        self.app._set_action_state()
        self.app._set_review_state(bool(self.app.pairs))
        self.app._refresh_index_boundary(apply=False)

