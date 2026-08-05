from __future__ import annotations

from types import MethodType
from tkinter import ttk


def install_certified_slider_lock(app_class) -> None:
    """Make the similarity slider reflect only genuinely certified positions.

    Before any complete band exists, the slider is disabled and pinned to Strict.
    During a scan it remains disabled. Afterward, its usable range is restricted
    to the completely certified interval reported by the evidence cache.
    """
    if getattr(app_class, "_certified_slider_lock_installed", False):
        return

    original_init = app_class.__init__
    original_refresh_boundary = app_class._refresh_index_boundary
    original_set_action_state = app_class._set_action_state
    original_slider_changed = app_class._slider_changed
    original_start_scan = app_class.start_scan

    def slider_widget(self):
        widget = getattr(self, "_certified_slider_widget", None)
        if widget is not None:
            return widget
        parent = self.scan_button.master
        for child in parent.winfo_children():
            if isinstance(child, ttk.Scale):
                self._certified_slider_widget = child
                return child
        return None

    def apply_slider_lock(self) -> None:
        widget = slider_widget(self)
        if widget is None:
            return

        boundary = self.evidence.loosest_complete_slider()
        busy = bool(getattr(self, "busy", False) or getattr(self, "reverse_delete_busy", False))

        self._slider_guard = True
        try:
            if boundary is None:
                widget.configure(from_=99, to=99, state="disabled")
                self.slider.set(99)
                return

            boundary = max(0, min(99, int(boundary)))
            requested = int(round(self.slider.get()))
            requested = max(boundary, min(99, requested))
            widget.configure(
                from_=boundary,
                to=99,
                state="disabled" if busy else "normal",
            )
            self.slider.set(requested)
        finally:
            self._slider_guard = False

    def __init__(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        apply_slider_lock(self)

    def _refresh_index_boundary(self, *, apply: bool) -> None:
        original_refresh_boundary(self, apply=apply)
        apply_slider_lock(self)

    def _set_action_state(self) -> None:
        original_set_action_state(self)
        if hasattr(self, "scan_button"):
            self.after_idle(lambda: apply_slider_lock(self))

    def _slider_changed(self, *_args) -> None:
        if self._slider_guard:
            return
        boundary = self.evidence.loosest_complete_slider()
        if boundary is None or self.busy or self.reverse_delete_busy:
            apply_slider_lock(self)
            return
        requested = int(round(self.slider.get()))
        if requested < int(boundary) or requested > 99:
            apply_slider_lock(self)
            return
        original_slider_changed(self, *_args)

    def start_scan(self) -> None:
        widget = slider_widget(self)
        if widget is not None:
            widget.configure(state="disabled")
        original_start_scan(self)

    app_class.__init__ = __init__
    app_class._refresh_index_boundary = _refresh_index_boundary
    app_class._set_action_state = _set_action_state
    app_class._slider_changed = _slider_changed
    app_class.start_scan = start_scan
    app_class._certified_slider_lock_installed = True
