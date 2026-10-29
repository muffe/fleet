from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from fleet_report import render


class FleetReportTests(unittest.TestCase):
    def test_running_and_blocked_machines_remain_visible(self):
        state = {"sourceCommit": "a" * 40, "machines": {"server": {"status": "running"}, "macbook": {"status": "blocked", "error": "Offline"}}}
        document = render(state, {})
        self.assertIn("server", document)
        self.assertIn("running", document)
        self.assertIn("macbook", document)
        self.assertIn("Offline", document)

    def test_mismatched_revision_is_blocked_and_private_text_escaped(self):
        state = {"sourceCommit": "a" * 40, "machines": {"server": {"status": "running"}}}
        envelope = {"sourceCommit": "b" * 40, "status": "completed", "report": {"private": "not a comparable report"}}
        document = render(state, {"server": envelope})
        self.assertIn("different source revision", document)
        self.assertNotIn("not a comparable report", document)
        document = render(state, {"server": {"status": "blocked", "error": "<script>alert(1)</script>"}})
        self.assertNotIn("<script>", document)
        self.assertIn("&lt;script&gt;", document)


if __name__ == "__main__":
    unittest.main()
