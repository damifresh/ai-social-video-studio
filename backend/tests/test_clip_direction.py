"""Tests for the deterministic director/producer plan and one-clip assembly."""

from __future__ import annotations

import unittest

from app.clip import direction, highlights


class DirectorPlanTest(unittest.TestCase):
    def setUp(self):
        self.transcript = {
            "timing": "words",
            "sentences": [
                {"start": 0.0, "end": 5.0, "text": "Most people quit habits because the system is too complicated."},
                {"start": 6.0, "end": 11.0, "text": "The fix is one tiny habit you can repeat every morning."},
                {"start": 12.0, "end": 17.0, "text": "The meeting starts at nine in the conference room."},
            ],
        }
        self.structural = {"silence": {"gaps": []}, "envelope": {}}

    def test_presets_are_built_in_and_deterministic(self):
        data = direction.presets()
        self.assertEqual(data["default"], "tiktok")
        ids = [p["id"] for p in data["presets"]]
        self.assertIn("linkedin", ids)
        self.assertEqual(len(ids), 5)
        for item in data["presets"]:
            self.assertTrue(item["label"])
            self.assertTrue(item["instruction"])
            self.assertTrue(item["default_prompt"])

    def test_plan_uses_brief_and_explicit_ui_durations(self):
        prompt_text = "Funny 15s TikTok clips about habits; avoid jargon"
        plan = direction.deterministic_plan(prompt_text, "tiktok", [30])
        self.assertEqual(plan["durations"], [30.0])
        self.assertEqual(plan["brief"]["length_hint"]["seconds"], 15)
        self.assertEqual(plan["brief"]["tone"], "funny")
        self.assertEqual(plan["preset"], "tiktok")
        self.assertIn("deterministic", plan["engine"])
        self.assertNotIn("used_llm", plan)
        self.assertEqual(plan["focus_windows"], [])
        self.assertEqual(plan["segments"], [])

    def test_plan_falls_back_to_prompt_length_and_preset_default(self):
        prompt_text = "Funny 15s TikTok clips about habits; avoid jargon"
        plan = direction.deterministic_plan(prompt_text, "tiktok")
        self.assertEqual(plan["durations"], [15.0])
        defaulted = direction.deterministic_plan("", "unknown-preset")
        self.assertEqual(defaulted["preset"], "tiktok")
        self.assertEqual(defaulted["prompt"], direction.effective_prompt("", "tiktok"))
        self.assertEqual(defaulted["durations"], [15.0])

    def test_single_clip_plan_records_assembly_metadata(self):
        structural = {
            "silence": {"gaps": [{"start": 5.0, "end": 6.0}]},
            "scene_cuts": {"cuts": [12.0]},
            "envelope": {},
        }
        plan = direction.deterministic_plan(
            "Educational clips about habits", "educational", [30],
            single_clip=True, structural=structural,
        )
        self.assertTrue(plan["single_clip"])
        assembly = plan["assembly"]
        self.assertEqual(assembly["mode"], "single-final-video")
        self.assertEqual(assembly["target_seconds"], 30.0)
        self.assertEqual(assembly["pause_gaps_considered"], 1)
        self.assertEqual(assembly["scene_cuts_considered"], 1)
        self.assertIn("deterministic", assembly["engine"])
        self.assertTrue(plan["brief"]["single_clip"])
        self.assertEqual(plan["brief"]["assembly"], assembly)

    def test_single_clip_fallback_assembles_multiple_local_scenes(self):
        result = highlights.generate(
            self.transcript, self.structural, [15], count=5, single_clip=True
        )
        candidate = result["candidates"][0]
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["params"]["count"], 1)
        self.assertGreaterEqual(len(candidate["segments"]), 2)
        self.assertEqual(result["stats"]["fallback_segments"], len(candidate["segments"]))
        self.assertEqual(result["stats"]["directed_segments"], 0)
        self.assertEqual(candidate["duration"],
                         round(sum(s["duration"] for s in candidate["segments"]), 3))
        self.assertTrue(candidate["copy"]["grounding"]["all_grounded"])

    def test_single_clip_assembly_grounds_copy_and_boundary_evidence(self):
        structural = {
            "silence": {"gaps": [{"start": 5.0, "end": 6.0}]},
            "scene_cuts": {"cuts": [12.0]},
            "envelope": {},
        }
        plan = direction.deterministic_plan(
            "Educational clips about habits", "educational", [30],
            single_clip=True, structural=structural,
        )
        result = highlights.generate(
            self.transcript, structural, plan["durations"], count=5,
            brief=plan["brief"], single_clip=True,
        )
        candidate = result["candidates"][0]
        self.assertEqual(len(result["candidates"]), 1)
        self.assertGreaterEqual(len(candidate["segments"]), 2)
        self.assertTrue(candidate["copy"]["grounding"]["all_grounded"])
        self.assertTrue(any(
            segment["boundary_evidence"]["support"] for segment in candidate["segments"]
        ))
        self.assertGreaterEqual(candidate["assembly"]["pause_boundaries"], 1)
        self.assertGreaterEqual(candidate["assembly"]["scene_cut_boundaries"], 1)
        self.assertEqual(candidate["assembly"]["segment_count"], len(candidate["segments"]))
        self.assertEqual(result["stats"]["directed_segments"], 0)

    def test_single_clip_clamps_transcript_to_short_source(self):
        result = highlights.generate(
            self.transcript, self.structural, [15], single_clip=True,
            source_duration=3.0,
        )
        candidate = result["candidates"][0]
        segments = candidate["segments"]
        self.assertEqual(len(result["candidates"]), 1)
        self.assertTrue(segments)
        self.assertLessEqual(max(s["end"] for s in segments), 3.0)
        self.assertTrue(candidate["assembly"]["clamped_to_source_duration"])
        self.assertIn("shorter", candidate["assembly"]["notice"] or "")
        self.assertTrue(candidate["copy"]["grounding"]["all_grounded"])

    def test_single_clip_supports_a_single_sentence_source(self):
        transcript = {
            "timing": "words",
            "sentences": [
                {"start": 0.0, "end": 2.0, "text": "One tiny habit you can repeat every morning."},
            ],
        }
        result = highlights.generate(
            transcript, self.structural, [15], single_clip=True,
            source_duration=2.0,
        )
        candidate = result["candidates"][0]
        self.assertEqual(len(candidate["segments"]), 1)
        self.assertLessEqual(candidate["segments"][0]["end"], 2.0)
        self.assertIn("one transcript-grounded scene", candidate["assembly"]["notice"] or "")
        self.assertTrue(candidate["copy"]["grounding"]["all_grounded"])


if __name__ == '__main__':
    unittest.main()
