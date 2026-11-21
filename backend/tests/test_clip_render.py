"""Tests for transcript-grounded multi-scene assembly rendering."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.clip import render


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/clip_projects/991d729f-26ce-4375-9f38-8d8eccc1c6b3/source/c8e1e91ebb.mp4"


class RenderAssemblyTest(unittest.TestCase):
    def test_overlapping_segments_are_rejected(self):
        with patch.object(render, "probe_media",
                          return_value={"width": 1280, "height": 720, "duration": 30}):
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaisesRegex(ValueError, "non-overlapping"):
                    render.render_assembly(
                        source=Path("source.mp4"),
                        out_path=Path(tmp) / "out.mp4",
                        segments=[
                            {"start": 0.0, "end": 5.0, "role": "hook"},
                            {"start": 4.0, "end": 9.0, "role": "payoff"},
                        ],
                    )

    @unittest.skipUnless(SOURCE.exists(), "synthetic clip source fixture not present")
    def test_renders_two_scenes_into_one_validated_video(self):
        if not Path(render.settings.ffmpeg).exists():
            self.skipTest("ffmpeg is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            result = render.render_assembly(
                source=SOURCE,
                out_path=Path(tmp) / "assembled.mp4",
                segments=[
                    {"start": 0.5, "end": 2.0, "role": "hook", "text": "Most people quit habits."},
                    {"start": 3.0, "end": 4.5, "role": "payoff", "text": "One tiny habit you can repeat."},
                ],
                cues=[{"start": 0.0, "end": 0.8, "text": "Most people quit habits."}],
                audio={"normalize": True, "music": None},
            )
            self.assertTrue(Path(result["output"]).exists())
            self.assertEqual(result["assembly"]["segment_count"], 2)
            self.assertEqual(result["assembly"]["source_ranges"], [[0.5, 2.0], [3.0, 4.5]])
            self.assertEqual(result["assembly"]["roles"], ["hook", "payoff"])
            self.assertAlmostEqual(result["requested_duration"], 3.0, places=2)
            validation = render.validate_render(result, "9:16", result["requested_duration"])
            self.assertTrue(validation["ok"], validation)
            self.assertTrue(result["captions"])
            source_info = render.probe_media(SOURCE)
            expected = f"{source_info['width']}x{source_info['height']}"
            self.assertEqual(result["resolution"], expected)
            self.assertEqual(result["source_resolution"], expected)
            self.assertEqual(result["resolution_mode"], "source-native")
            self.assertIsNone(result["crop"])


class NativeCanvasTest(unittest.TestCase):
    """Final previews must show the full source frame, not a cover-crop zoom."""

    def test_native_chain_fits_and_pads_without_zoom(self):
        chain = render._video_chain(1280, 720, "9:16", None, 30, None, (1280, 720))
        self.assertNotIn("force_original_aspect_ratio=increase", chain)
        self.assertNotIn("crop=", chain)
        self.assertIn("scale=1280:720:force_original_aspect_ratio=decrease:flags=lanczos", chain)
        self.assertIn("pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=black", chain)

    def test_only_an_explicit_custom_crop_survives(self):
        self.assertIsNone(render.resolve_custom_crop({"mode": "center"}))
        self.assertIsNone(render.resolve_custom_crop({"mode": "left"}))
        rect = render.resolve_custom_crop({
            "mode": "custom", "x": 0.1, "y": 0.2, "w": 0.5, "h": 0.4,
        })
        self.assertEqual(rect, {"mode": "custom", "x": 0.1, "y": 0.2, "w": 0.5, "h": 0.4})
        chain = render._video_chain(1280, 720, "9:16", rect, 30, None, (1280, 720))
        self.assertIn("crop=trunc(iw*0.5/2)*2:trunc(ih*0.4/2)*2", chain)
        self.assertIn("trunc(iw*0.1/2)*2:trunc(ih*0.2/2)*2", chain)
        self.assertIn("force_original_aspect_ratio=decrease", chain)

    def test_out_of_bounds_custom_crop_is_clamped(self):
        rect = render.resolve_custom_crop({
            "mode": "custom", "x": 0.9, "y": 0.9, "w": 5, "h": 5,
        })
        self.assertEqual(rect["w"], 1.0)
        self.assertEqual(rect["h"], 1.0)
        self.assertEqual(rect["x"], 0.0)
        self.assertEqual(rect["y"], 0.0)

    @unittest.skipUnless(SOURCE.exists(), "synthetic clip source fixture not present")
    def test_real_clip_render_keeps_source_resolution_and_full_frame(self):
        if not Path(render.settings.ffmpeg).exists():
            self.skipTest("ffmpeg is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            result = render.render_clip(
                SOURCE.resolve(), Path(tmp) / "clip.mp4", 0.5, 2.0,
                aspect="9:16", audio={"normalize": True, "music": None},
            )
            info = render.probe_media(SOURCE)
            expected = f"{info['width']}x{info['height']}"
            self.assertEqual(result["resolution"], expected)
            self.assertEqual(result["source_resolution"], expected)
            self.assertEqual(result["resolution_mode"], "source-native")
            self.assertIsNone(result["crop"])
            self.assertEqual(f"{result['probe']['width']}x{result['probe']['height']}", expected)
            graph = " ".join(result["command"])
            self.assertIn("force_original_aspect_ratio=decrease", graph)
            self.assertNotIn("force_original_aspect_ratio=increase", graph)
            self.assertNotIn("crop=", graph)
            self.assertTrue(render.validate_render(result, "9:16", result["requested_duration"])["ok"])


if __name__ == "__main__":
    unittest.main()
