from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .models import Pair


def pair_identity(left_key: str, right_key: str) -> tuple[str, str]:
    """Return an orientation-independent identity for one review pair."""
    return tuple(sorted((left_key, right_key)))


def preserved_pair_index(
    pairs: Iterable[Pair],
    left_key: str | None,
    right_key: str | None,
    fallback_index: int,
) -> int:
    """Keep the visible pair stable across disposable pair-table rebuilds.

    Exact orientation wins so the survivor/delete sides do not unexpectedly swap.
    If only a reoriented row exists, keep that logical pair rather than jumping to
    unrelated work. Otherwise clamp the old numeric position into the new list.
    """
    materialized = list(pairs)
    if not materialized:
        return 0
    if left_key is not None and right_key is not None:
        for index, pair in enumerate(materialized):
            if pair.left_key == left_key and pair.right_key == right_key:
                return index
        wanted = pair_identity(left_key, right_key)
        for index, pair in enumerate(materialized):
            if pair_identity(pair.left_key, pair.right_key) == wanted:
                return index
    return min(max(0, int(fallback_index)), len(materialized) - 1)


def install_review_ui_hardening(app_class: type[Any]) -> None:
    """Install idempotent UI guards for streaming READY queue rebuilds."""
    if getattr(app_class, "_review_ui_hardening_installed", False):
        return

    original_refresh_pairs = app_class._refresh_pairs
    original_load_preview = app_class._load_preview
    original_finish_preview = app_class._finish_preview
    original_show_current_pair = app_class._show_current_pair

    def refresh_pairs(self: Any) -> None:
        old_left = self.left_asset_key
        old_right = self.right_asset_key
        old_index = self.pair_index
        refreshed = self.database.scan_pairs()
        self.pairs = refreshed
        self.pair_index = preserved_pair_index(
            refreshed,
            old_left,
            old_right,
            old_index,
        )
        self._show_current_pair()

    def load_preview(self: Any, key: str, widget: Any) -> None:
        loaded = getattr(self, "_review_loaded_preview_keys", None)
        if loaded is None:
            loaded = {}
            self._review_loaded_preview_keys = loaded
        pending = getattr(self, "_review_pending_preview_keys", None)
        if pending is None:
            pending = {}
            self._review_pending_preview_keys = pending
        if loaded.get(widget) == key or pending.get(widget) == key:
            return
        pending[widget] = key
        original_load_preview(self, key, widget)

    def finish_preview(
        self: Any,
        widget: Any,
        request: int,
        preview: Any,
        error: str | None,
    ) -> None:
        original_finish_preview(self, widget, request, preview, error)
        pending = getattr(self, "_review_pending_preview_keys", {})
        key = pending.pop(widget, None)
        if error is None and preview is not None and key is not None:
            loaded = getattr(self, "_review_loaded_preview_keys", None)
            if loaded is None:
                loaded = {}
                self._review_loaded_preview_keys = loaded
            loaded[widget] = key

    def show_current_pair(self: Any) -> None:
        if not self.pairs:
            getattr(self, "_review_loaded_preview_keys", {}).clear()
            getattr(self, "_review_pending_preview_keys", {}).clear()
        original_show_current_pair(self)

    app_class._refresh_pairs = refresh_pairs
    app_class._load_preview = load_preview
    app_class._finish_preview = finish_preview
    app_class._show_current_pair = show_current_pair
    app_class._review_ui_hardening_installed = True
