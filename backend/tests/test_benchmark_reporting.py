"""Regression tests for benchmark reporting around the implemented Engine B."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from app.benchmark import runner


class BenchmarkReportingTest(unittest.TestCase):
    def test_unavailable_sections_do_not_claim_engine_b_is_missing(self):
        sections = runner._build_unavailable_sections()

        auto_clip = sections["auto_clip_results"]
        self.assertEqual(auto_clip["status"], "NOT_RUN")
        reason = auto_clip["reason"].lower()
        self.assertIn("implemented", reason)
        self.assertTrue("separate" in reason or "engine_b_e2e.py" in reason)

    def test_engine_a_baseline_report_does_not_claim_engine_b_is_missing(self):
        fake_case_result = {
            "id": "FAKE-1",
            "engine": "AI_VIDEO_CREATOR",
            "status": "PASS",
            "config": {"duration_min": 1},
            "job_status": "succeeded",
            "export_validation": {"ok": True},
        }
        with (
            patch.object(runner, "ensure_schema", return_value=None),
            patch.object(runner, "capture_environment", return_value={}),
            patch.object(runner, "save_run"),
            patch.object(runner, "generate_reports", return_value={"json": "fake.json", "html": "fake.html"}),
            patch.object(runner, "_run_single_video_creator_case", return_value=fake_case_result),
        ):
            report = runner.run_engine_a_baseline(cases=[{"id": "FAKE-1"}], title="reporting regression")

        serialized = json.dumps(report).lower()
        self.assertNotIn("not implemented", serialized)
        self.assertNotIn("not present in this codebase", serialized)
        self.assertNotIn("not_recommended_on_this_hardware", serialized)
        self.assertNotIn("no ai highlight extraction engine", serialized)
        self.assertEqual(report["sections"]["export_quality"]["engine_b"]["status"], "NOT_RUN")

        classifications = {
            row["engine"]: row for row in report["sections"]["hardware_capability_classification"]
        }
        self.assertEqual(
            classifications["AI_AUTO_CLIP_STUDIO"]["status"],
            "NOT_MEASURED_IN_THIS_SUITE",
        )


if __name__ == "__main__":
    unittest.main()
