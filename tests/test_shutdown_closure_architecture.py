from pathlib import Path
import unittest


class ShutdownClosureArchitectureTests(unittest.TestCase):
    def test_shutdown_cancels_then_waits_then_closes_resources(self) -> None:
        app = Path("deduper/app.py").read_text()
        close = app[app.index("    def _close(self) -> None:"):]
        self.assertIn("if self._closing:", close)
        self.assertIn("scan_cancel.set()", close)
        self.assertIn("cancellation.set()", close)
        self.assertIn("shutdown(wait=True, cancel_futures=True)", close)
        self.assertNotIn("shutdown(wait=False", close)
        self.assertLess(close.index("scan_cancel.set()"), close.index("self.executor.shutdown"))
        self.assertLess(close.index("self.executor.shutdown"), close.index("evidence.close()"))
        self.assertLess(close.index("evidence.close()"), close.index("self.database.close()"))

    def test_event_pump_and_new_work_fail_closed_during_shutdown(self) -> None:
        app = Path("deduper/app.py").read_text()
        self.assertIn("if self._closing or self.busy:", app)
        self.assertIn("if not self._closing:\n            self.events.put", app)
        self.assertIn("if self._closing:\n            return", app)


if __name__ == "__main__":
    unittest.main()
