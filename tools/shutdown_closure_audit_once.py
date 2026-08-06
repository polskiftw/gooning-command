from pathlib import Path

path = Path('deduper/app.py')
text = path.read_text()

old = '''        self.busy = False
        self.review_locked = False
        self.reverse_delete_busy = False
'''
new = '''        self.busy = False
        self.review_locked = False
        self.reverse_delete_busy = False
        self._closing = False
'''
if old not in text:
    raise SystemExit('closing state anchor missing')
text = text.replace(old, new, 1)

old = '''    def _drain_events(self) -> None:
        try:
            while True:
                callback, args = self.events.get_nowait()
                callback(*args)
        except queue.Empty:
            pass
        self.after(60, self._drain_events)

    def _ui(self, callback: Callable, *args) -> None:
        self.events.put((callback, args))
'''
new = '''    def _drain_events(self) -> None:
        if self._closing:
            return
        try:
            while True:
                callback, args = self.events.get_nowait()
                if self._closing:
                    return
                callback(*args)
        except queue.Empty:
            pass
        if not self._closing:
            self.after(60, self._drain_events)

    def _ui(self, callback: Callable, *args) -> None:
        if not self._closing:
            self.events.put((callback, args))
'''
if old not in text:
    raise SystemExit('event pump anchor missing')
text = text.replace(old, new, 1)

old = '''    def _run(
        self,
        label: str,
        operation: Callable[[], str],
        finished: Callable[[], None] | None = None,
        *,
        lock_review: bool = True,
    ) -> None:
        if self.busy:
            return
'''
new = '''    def _run(
        self,
        label: str,
        operation: Callable[[], str],
        finished: Callable[[], None] | None = None,
        *,
        lock_review: bool = True,
    ) -> None:
        if self._closing or self.busy:
            return
'''
if old not in text:
    raise SystemExit('run guard anchor missing')
text = text.replace(old, new, 1)

old = '''    def _close(self) -> None:
        self.left_preview.stop()
        self.right_preview.stop()
        for cancellation in self.preview_cancellations.values():
            cancellation.set()
        self.preview_executor.shutdown(wait=False, cancel_futures=True)
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.database.close()
        self.destroy()
'''
new = '''    def _close(self) -> None:
        if self._closing:
            return
        self._closing = True

        # Stop every source of new work before waiting for existing work. Scan
        # cancellation is owned by FastDeduperApp, so keep the base app generic.
        scan_cancel = getattr(self, "scan_cancel", None)
        if scan_cancel is not None:
            scan_cancel.set()
        for cancellation in self.preview_cancellations.values():
            cancellation.set()
        slider_after_id = getattr(self, "_slider_after_id", None)
        if slider_after_id is not None:
            try:
                self.after_cancel(slider_after_id)
            except tk.TclError:
                pass
            self._slider_after_id = None

        self.left_preview.stop()
        self.right_preview.stop()

        try:
            # Waiting is mandatory: database handles must remain open until no
            # scan, deletion, slider-load, or preview callback can use them.
            self.preview_executor.shutdown(wait=True, cancel_futures=True)
            self.executor.shutdown(wait=True, cancel_futures=True)
        finally:
            evidence = getattr(self, "evidence", None)
            if evidence is not None:
                evidence.close()
            self.database.close()
            self.destroy()
'''
if old not in text:
    raise SystemExit('close method anchor missing')
text = text.replace(old, new, 1)
path.write_text(text)

Path('tests/test_shutdown_closure_architecture.py').write_text('''from pathlib import Path\nimport unittest\n\n\nclass ShutdownClosureArchitectureTests(unittest.TestCase):\n    def test_shutdown_cancels_then_waits_then_closes_resources(self) -> None:\n        app = Path("deduper/app.py").read_text()\n        close = app[app.index("    def _close(self) -> None:"):]\n        self.assertIn("if self._closing:", close)\n        self.assertIn("scan_cancel.set()", close)\n        self.assertIn("cancellation.set()", close)\n        self.assertIn("shutdown(wait=True, cancel_futures=True)", close)\n        self.assertNotIn("shutdown(wait=False", close)\n        self.assertLess(close.index("scan_cancel.set()"), close.index("self.executor.shutdown"))\n        self.assertLess(close.index("self.executor.shutdown"), close.index("evidence.close()"))\n        self.assertLess(close.index("evidence.close()"), close.index("self.database.close()"))\n\n    def test_event_pump_and_new_work_fail_closed_during_shutdown(self) -> None:\n        app = Path("deduper/app.py").read_text()\n        self.assertIn("if self._closing or self.busy:", app)\n        self.assertIn("if not self._closing:\\n            self.events.put", app)\n        self.assertIn("if self._closing:\\n            return", app)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''')
