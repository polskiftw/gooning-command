from __future__ import annotations

from tkinter import ttk

from .certified_group_admission import admit_closed_frontier_group, preview_projection
from .evidence_inventory import reconcile_asset_inventory
from .frontier_worker import scan_closed_group
from .matcher import partition_exact_duplicates


class ByeBitchMixin:
    """Immediate certified-family deletion controls for the smart deduper.

    The visible pair is actionable only when startup inventory validation succeeded,
    deletion is enabled, and both objects still belong to one admitted closed family.
    A successful deletion removes every row from that family and immediately gives
    the surviving members priority frontier recertification.
    """

    def _build(self) -> None:
        super()._build()

        # Replace the old one-sided center action with one unmistakable action under
        # each preview. Both buttons deliberately use Claire's requested label.
        self.reverse_delete_button.pack_forget()
        self.left_bye_bitch_button = ttk.Button(
            self.left_preview.master,
            text="BYE BITCH",
            style="Danger.TButton",
            command=lambda: self._bye_bitch("left"),
        )
        self.left_bye_bitch_button.pack(fill="x", padx=8, pady=(0, 8))
        self.right_bye_bitch_button = ttk.Button(
            self.right_preview.master,
            text="BYE BITCH",
            style="Danger.TButton",
            command=lambda: self._bye_bitch("right"),
        )
        self.right_bye_bitch_button.pack(fill="x", padx=8, pady=(0, 8))

    def _set_review_state(self, enabled: bool) -> None:
        super()._set_review_state(enabled)
        if not hasattr(self, "left_bye_bitch_button"):
            return
        queue = getattr(self, "_active_certified_queue", None)
        pair = self.pairs[self.pair_index] if enabled and self.pairs else None
        family_is_actionable = False
        if queue is not None and pair is not None:
            try:
                family_is_actionable = queue.family_for_pair(
                    pair.left_key,
                    pair.right_key,
                ) is not None
            except ValueError:
                family_is_actionable = False
        actionable = (
            enabled
            and not self.review_locked
            and not self.reverse_delete_busy
            and self.config.allow_delete
            and bool(getattr(self, "_inventory_verified_for_delete", False))
            and family_is_actionable
        )
        state = "normal" if actionable else "disabled"
        self.left_bye_bitch_button.configure(state=state)
        self.right_bye_bitch_button.configure(state=state)

    def _bye_bitch(self, side: str) -> None:
        if side not in {"left", "right"}:
            raise ValueError("BYE BITCH side must be left or right")
        if (
            not self.config.allow_delete
            or not getattr(self, "_inventory_verified_for_delete", False)
            or self.review_locked
            or self.reverse_delete_busy
            or not self.pairs
        ):
            return

        queue = getattr(self, "_active_certified_queue", None)
        if queue is None:
            return
        pair = self.pairs[self.pair_index]
        family = queue.family_for_pair(pair.left_key, pair.right_key)
        if family is None:
            self._refresh_pairs()
            return

        deleted_key = pair.left_key if side == "left" else pair.right_key
        protected_key = pair.right_key if side == "left" else pair.left_key
        deleted_asset = self.database.asset(deleted_key)
        if deleted_asset is None or deleted_asset.deleted:
            self._refresh_pairs()
            return

        self.reverse_delete_busy = True
        self._set_action_state()
        self._set_review_state(True)
        self.status.set(f"BYE BITCH — deleting {deleted_key}")

        def worker() -> None:
            try:
                results, deleted, index_error = self.store.delete_queued(
                    [(deleted_key, pair.id, deleted_asset.size)]
                )
                result_text = (
                    results[0][3]
                    if results
                    else "R2 did not return a deletion result"
                )
                self.database.record_reverse_deletion(
                    deleted_key,
                    protected_key,
                    deleted_asset.size,
                    result_text,
                )
                if index_error:
                    self.database.queue_index_cleanup(deleted)
                if not deleted:
                    self._ui(
                        self._bye_bitch_finished,
                        None,
                        f"BYE BITCH FAILED — {result_text}",
                    )
                    return

                invalidation = queue.invalidate_for_deletion(
                    deleted_key,
                    protected_key,
                )
                self.database.replace_pairs(
                    preview_projection(queue),
                    preserve_exclusions=True,
                )
                message = (
                    f"BYE BITCH — deleted {deleted_key}; protected {protected_key}; "
                    f"removed {len(invalidation.family.pairs)} family rows; "
                    f"prioritizing {len(invalidation.recertify_keys)} survivors for recertification."
                )
                if index_error:
                    message += " Gallery index cleanup was saved for automatic retry."
                self._ui(self._bye_bitch_finished, invalidation.recertify_keys, message)
            except Exception as exc:
                self._ui(
                    self._bye_bitch_finished,
                    None,
                    f"BYE BITCH FAILED — {type(exc).__name__}: {exc}",
                )

        self.executor.submit(worker)

    def _bye_bitch_finished(
        self,
        recertify_keys: tuple[str, ...] | None,
        message: str,
    ) -> None:
        self.reverse_delete_busy = False
        self.status.set(message)
        self._refresh_counts()
        self._refresh_pairs()
        self._set_action_state()
        self._set_review_state(bool(self.pairs))
        if recertify_keys:
            self.executor.submit(self._recertify_bye_bitch_family, recertify_keys)

    def _recertify_bye_bitch_family(self, priority_keys: tuple[str, ...]) -> None:
        """Recertify the damaged family first without hiding unrelated families."""
        try:
            inventory = self.store.list_assets()
            evidence_sync = reconcile_asset_inventory(self.evidence, inventory)
            live_keys = {asset.key for asset in inventory}
            self.database.upsert_inventory(inventory)
            self.database.mark_missing_deleted(live_keys)
            assets = self.database.all_hashed_assets()
            visual_assets, _ = partition_exact_duplicates(
                assets,
                self.config.survivor_policy,
            )
            slider = int(round(self.slider.get()))
            queue = getattr(self, "_active_certified_queue", None)
            if queue is None:
                return

            completed = 0
            for seed in priority_keys:
                if seed not in live_keys or self.scan_cancel.is_set():
                    continue
                result = scan_closed_group(
                    self.evidence,
                    visual_assets,
                    seed,
                    slider,
                    cancelled=self.scan_cancel.is_set,
                )
                admission = admit_closed_frontier_group(
                    queue,
                    self.evidence,
                    visual_assets,
                    result,
                    policy=self.config.survivor_policy,
                )
                if admission.admitted:
                    completed += 1
                    self.database.replace_pairs(
                        preview_projection(queue),
                        preserve_exclusions=True,
                    )
                    self._ui(self._refresh_pairs)

            self._ui(
                self.status.set,
                (
                    f"Family apology complete — {completed} repaired certified families admitted "
                    f"first; inventory delta: {len(evidence_sync.delta.added)} added, "
                    f"{len(evidence_sync.delta.changed)} changed, "
                    f"{len(evidence_sync.delta.removed)} removed."
                ),
            )
        except Exception as exc:
            self._ui(
                self.status.set,
                (
                    "Deletion succeeded, but priority family recertification needs the next scan — "
                    f"{type(exc).__name__}: {exc}"
                ),
            )
