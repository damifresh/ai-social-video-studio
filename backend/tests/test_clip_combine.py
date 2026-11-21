"""Tests for multi-source combining: ordering, transitions and rendering."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.clip import api, jobs, render

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data/clip_projects/991d729f-26ce-4375-9f38-8d8eccc1c6b3/source/c8e1e91ebb.mp4"


class CombineGraphTest(unittest.TestCase):
    def test_transition_boundaries_and_offsets_are_computed(self):
        segments = [
            {"path": "a.mp4", "start": 0.0, "end": 4.0},
            {"path": "b.mp4", "start": 0.0, "end": 3.0},
            {"path": "c.mp4", "start": 0.0, "end": 5.0},
        ]
        probes = [{"width": 1920, "height": 1080, "duration": 4.0},
                  {"width": 1280, "height": 720, "duration": 3.0},
                  {"width": 720, "height": 1280, "duration": 5.0}]
        validated, boundaries, offsets, total = render.normalize_combine_segments(
            segments, probes, True, 0.6,
        )
        self.assertEqual(len(validated), 3)
        self.assertEqual(boundaries, [0.6, 0.6])
        self.assertEqual(offsets, [3.4, 5.8])
        self.assertAlmostEqual(total, 10.8)

    def test_cuts_have_no_crossfade(self):
        segments = [{"path": "a.mp4", "start": 0, "end": 2}, {"path": "b.mp4", "start": 0, "end": 3}]
        probes = [{"width": 1280, "height": 720, "duration": 2.0},
                  {"width": 1280, "height": 720, "duration": 3.0}]
        validated, boundaries, offsets, total = render.normalize_combine_segments(
            segments, probes, False, 0.6,
        )
        self.assertEqual(boundaries, [0.0])
        self.assertEqual(offsets, [2.0])
        self.assertAlmostEqual(total, 5.0)

    def test_graph_uses_crossfade_or_plain_concat(self):
        segments = [
            {"index": 0, "start": 0.0, "end": 2.0, "duration": 2.0, "width": 1280, "height": 720},
            {"index": 1, "start": 0.0, "end": 3.0, "duration": 3.0, "width": 1280, "height": 720},
        ]
        smooth = render.build_combine_graph(
            segments, "9:16", 30, [0.6], [1.4], 4.4, None,
            {"normalize": True}, False, 2,
        )
        self.assertIn("xfade=transition=fade:duration=0.600:offset=1.400", smooth)
        self.assertIn("acrossfade=d=0.600", smooth)
        self.assertNotIn("concat=n=2", smooth)
        cut = render.build_combine_graph(
            segments, "9:16", 30, [0.0], [2.0], 5.0, None,
            {"normalize": True}, False, 2,
        )
        self.assertIn("concat=n=2:v=1:a=1", cut)
        self.assertNotIn("xfade", cut)

    def test_native_graph_normalizes_every_input_to_the_canvas(self):
        segments = [
            {"index": 0, "start": 0.0, "end": 2.0, "duration": 2.0, "width": 1280, "height": 720},
            {"index": 1, "start": 0.0, "end": 2.0, "duration": 2.0, "width": 360, "height": 640},
        ]
        graph = render.build_combine_graph(
            segments, "9:16", 30, [0.0], [2.0], 4.0, None,
            {"normalize": True}, False, 2, output_size=(1280, 720),
        )
        # No cover-crop anywhere in native mode.
        self.assertNotIn("crop=", graph)
        # Both inputs go through the same fit+pad chain: xfade/concat can never
        # receive differently sized links, even if a probe was inaccurate.
        normalize = ("setsar=1,scale=1280:720:force_original_aspect_ratio=decrease:"
                     "flags=lanczos,pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=black")
        self.assertEqual(graph.count(normalize), 2)
        self.assertIn(f"[0:v]trim=start=0.000:end=2.000,setpts=PTS-STARTPTS,{normalize},"
                      "fps=30,setsar=1,settb=AVTB,format=yuv420p[v0]", graph)
        # Legacy graph (no output_size) still cover-crops to the preset.
        legacy = render.build_combine_graph(
            segments, "9:16", 30, [0.0], [2.0], 4.0, None,
            {"normalize": True}, False, 2,
        )
        self.assertIn("crop=", legacy)
        self.assertIn("scale=720:1280:force_original_aspect_ratio=increase", legacy)

    def test_validate_render_prefers_declared_native_resolution(self):
        result = {
            "output": "native.mp4",
            "resolution": "320x180",
            "probe": {"width": 320, "height": 180, "duration": 2.0,
                      "video_codec": "h264", "audio_codec": "aac",
                      "audio_streams": 1, "size_bytes": 50000},
        }
        with patch.object(render, "Path") as path:
            path.return_value.exists.return_value = True
            validation = render.validate_render(result, "9:16", 2.0)
        self.assertTrue(validation["ok"], validation)
        self.assertTrue(validation["resolution_ok"])

    def test_source_cues_shift_onto_combine_timeline(self):
        segments = [
            {"path": "a.mp4", "start": 0.0, "end": 2.0, "duration": 2.0},
            {"path": "b.mp4", "start": 0.0, "end": 2.0, "duration": 2.0},
        ]
        cues = render.shift_combine_cues(
            [
                [{"start": 0.2, "end": 1.5, "text": "first"}],
                [{"start": 0.1, "end": 1.8, "text": "second"}],
            ],
            segments, [0.6], [1.4], 3.4,
        )
        self.assertEqual([c["text"] for c in cues], ["first", "second"])
        self.assertAlmostEqual(cues[0]["start"], 0.2)
        self.assertAlmostEqual(cues[1]["start"], 1.7)  # 1.4s offset + fade midpoint

    @unittest.skipUnless(SOURCE.exists(), "synthetic clip source fixture not present")
    def test_real_render_produces_one_validated_video_in_both_modes(self):
        if not Path(render.settings.ffmpeg).exists():
            self.skipTest("ffmpeg is not installed")
        segments = [
            {"source_id": "one", "name": "one.mp4", "path": str(SOURCE.resolve()), "start": 0.0, "end": 2.0},
            {"source_id": "two", "name": "two.mp4", "path": str(SOURCE.resolve()), "start": 2.0, "end": 4.0},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for transitions in (True, False):
                out = Path(tmp) / ("fade.mp4" if transitions else "cut.mp4")
                result = render.render_combine(
                    sources=segments, out_path=out, transitions=transitions,
                    audio={"normalize": True, "music": None},
                )
                validation = render.validate_render(result, "9:16", result["requested_duration"])
                self.assertTrue(validation["ok"], validation)
                self.assertEqual(result["combine"]["source_count"], 2)
                self.assertEqual(
                    result["transition"]["mode"], "fade" if transitions else "cut",
                )
                expected = 3.4 if transitions else 4.0
                self.assertAlmostEqual(result["requested_duration"], expected, places=2)

    @unittest.skipUnless(SOURCE.exists(), "synthetic clip source fixture not present")
    def test_real_render_keeps_first_source_native_resolution(self):
        """Final preview output must be the source's own size, not a preset."""
        if not Path(render.settings.ffmpeg).exists():
            self.skipTest("ffmpeg is not installed")
        source_probe = render.probe_media(SOURCE)
        expected = f"{source_probe['width']}x{source_probe['height']}"
        segments = [
            {"source_id": "one", "name": "one.mp4", "path": str(SOURCE.resolve()),
             "start": 0.0, "end": 2.0},
            {"source_id": "two", "name": "two.mp4", "path": str(SOURCE.resolve()),
             "start": 2.0, "end": 4.0},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "native.mp4"
            result = render.render_combine(
                sources=segments, out_path=out, aspect="9:16",
                audio={"normalize": True, "music": None},
            )
            probe = render.probe_media(out)
            validation = render.validate_render(result, "9:16", result["requested_duration"])
        self.assertEqual(result["resolution"], expected)
        self.assertEqual(result["source_resolution"], expected)
        self.assertEqual(result["resolution_mode"], "source-native")
        self.assertIsNone(result["crop"])
        self.assertEqual(f"{probe['width']}x{probe['height']}", expected)
        self.assertTrue(validation["ok"], validation)

    @unittest.skipUnless(SOURCE.exists(), "synthetic clip source fixture not present")
    def test_real_render_pads_mixed_resolution_source_without_cropping(self):
        if not Path(render.settings.ffmpeg).exists():
            self.skipTest("ffmpeg is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            portrait = tmp / "portrait.mp4"
            subprocess.run([
                render.settings.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=green:s=360x640:r=15:d=2",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:d=2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(portrait),
            ], check=True)
            first = render.probe_media(SOURCE)
            expected = f"{first['width']}x{first['height']}"
            segments = [
                {"source_id": "one", "name": "one.mp4", "path": str(SOURCE.resolve()),
                 "start": 0.0, "end": 2.0},
                {"source_id": "two", "name": "two.mp4", "path": str(portrait),
                 "start": 0.0, "end": 2.0},
            ]
            out = tmp / "mixed.mp4"
            result = render.render_combine(
                sources=segments, out_path=out, aspect="9:16",
                audio={"normalize": True, "music": None},
            )
            probe = render.probe_media(out)
            validation = render.validate_render(result, "9:16", result["requested_duration"])
        self.assertEqual(f"{probe['width']}x{probe['height']}", expected)
        self.assertEqual(result["resolution"], expected)
        self.assertIsNone(result["crop"])
        self.assertTrue(validation["ok"], validation)

    @unittest.skipUnless(SOURCE.exists(), "synthetic clip source fixture not present")
    def test_real_render_survives_inaccurate_probe_dimensions(self):
        """Regression: a stale probe must not send a wrong-sized link into xfade.

        Reported symptom: "First input link main parameters (size 1080x1920) do
        not match the corresponding second input link xfade parameters (size
        1920x1080)". Every input is therefore normalised in the graph.
        """
        if not Path(render.settings.ffmpeg).exists():
            self.skipTest("ffmpeg is not installed")
        real_probe = render.probe_media

        def inaccurate_probe(path):
            info = real_probe(path)
            if info and Path(path).name == "portrait.mp4":
                # The real file decodes at 360x640; lie and claim it is already
                # the canvas size. A pass-through branch would break xfade.
                return {**info, "width": 1280, "height": 720,
                        "display_width": 1280, "display_height": 720}
            return info

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            portrait = tmp / "portrait.mp4"
            subprocess.run([
                render.settings.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=green:s=360x640:r=15:d=2",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:d=2",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(portrait),
            ], check=True)
            segments = [
                {"source_id": "one", "name": "one.mp4", "path": str(SOURCE.resolve()),
                 "start": 0.0, "end": 2.0},
                {"source_id": "two", "name": "portrait.mp4", "path": str(portrait),
                 "start": 0.0, "end": 2.0},
            ]
            with patch.object(render, "probe_media", side_effect=inaccurate_probe):
                result = render.render_combine(
                    sources=segments, out_path=tmp / "out.mp4", aspect="9:16",
                    audio={"normalize": True, "music": None},
                )
                probe = render.probe_media(tmp / "out.mp4")
                validation = render.validate_render(result, "9:16", result["requested_duration"])
        self.assertEqual(f"{probe['width']}x{probe['height']}", "1280x720")
        self.assertTrue(validation["ok"], validation)


class ExportDispatchTest(unittest.TestCase):
    """A source_combine candidate must export through the multi-source renderer."""

    def _candidate(self, transitions: bool = True, burn_captions: bool = False) -> MagicMock:
        segments = [
            {"source_id": "one", "name": "one.mp4", "path": str(SOURCE.resolve()),
             "start": 0.0, "end": 2.0, "duration": 2.0},
            {"source_id": "two", "name": "two.mp4", "path": str(SOURCE.resolve()),
             "start": 0.0, "end": 2.0, "duration": 2.0},
        ]
        assembly = {
            "kind": "source_combine", "segment_count": 2,
            "source_ids": ["one", "two"], "transitions": transitions,
            "transition_mode": "fade" if transitions else "cut",
            "transition_seconds": 0.6, "target_duration": 3.4,
            "timeline": {"start": 0.0, "end": 3.4 if transitions else 4.0},
        }
        return MagicMock(
            id="cand", clip_project_id="proj", start_sec=0.0, end_sec=3.4,
            title="Combined video", hook="", category="combine", transcript_text="",
            edit_json=json.dumps({"aspect": "9:16", "burn_captions": burn_captions}),
            score_json={
                "components": {}, "weights": {}, "metrics": {},
                "params": {"kind": "source_combine", "single_clip": True},
                "copy": {"title": "Combined video", "hashtags": []},
                "engine": "source-combine/v1", "assembly": assembly, "segments": segments,
            },
        )

    def test_render_one_dispatches_combine_instead_of_transcript_assembly(self):
        cand = self._candidate()
        fake = {
            "output": "export.mp4", "requested_duration": 3.4, "probe": {"duration": 3.4},
            "combine": {"source_count": 2}, "transition": {"mode": "fade"},
        }
        with patch.object(jobs.clip_render, "render_combine", return_value=fake) as combine, \
             patch.object(jobs.clip_render, "render_assembly") as assembly, \
             patch.object(jobs.clip_render, "validate_render", return_value={"ok": True}):
            result = jobs._render_one(
                MagicMock(), cand, MagicMock(), None, Path("export.mp4"), 5, 90,
            )
        combine.assert_called_once()
        kwargs = combine.call_args.kwargs
        self.assertEqual(len(kwargs["sources"]), 2)
        self.assertEqual([s["source_id"] for s in kwargs["sources"]], ["one", "two"])
        self.assertTrue(kwargs["transitions"])
        self.assertEqual(kwargs["transition_seconds"], 0.6)
        self.assertEqual(kwargs["target_duration"], 3.4)
        self.assertEqual(kwargs["cues"], [])
        assembly.assert_not_called()
        self.assertEqual(result["assembly"]["kind"], "source_combine")

    def test_render_one_reuses_per_source_transcripts_for_export_captions(self):
        cand = self._candidate(burn_captions=True)
        ctx = MagicMock()
        ctx.project.id = "proj"
        fake = {
            "output": "export.mp4", "requested_duration": 3.4,
            "probe": {"duration": 3.4}, "cue_count": 2,
            "combine": {"source_count": 2}, "transition": {"mode": "fade"},
        }
        transcripts = {
            "one": {"sentences": [{"start": 0.0, "end": 1.0, "text": "First line."}]},
            "two": {"sentences": [{"start": 0.0, "end": 1.0, "text": "Second line."}]},
        }

        def load(path):
            return transcripts.get(Path(path).parent.name)

        with patch.object(jobs.clip_render, "render_combine", return_value=fake) as combine, \
             patch.object(jobs.clip_transcribe, "load_transcript", side_effect=load), \
             patch.object(jobs.clip_render, "validate_render", return_value={"ok": True}):
            result = jobs._render_one(ctx, cand, MagicMock(), None, Path("export.mp4"), 5, 90)

        kwargs = combine.call_args.kwargs
        self.assertEqual(len(kwargs["source_cues"]), 2)
        self.assertEqual(kwargs["source_cues"][0][0]["text"], "First line.")
        self.assertEqual(kwargs["source_cues"][1][0]["text"], "Second line.")
        self.assertEqual(result["cues"], 2)
        self.assertTrue(result["assembly"]["captions"]["enabled"])
        self.assertEqual(result["assembly"]["captions"]["cue_count"], 2)

    def test_render_one_honours_cut_mode_from_candidate_metadata(self):
        cand = self._candidate(transitions=False)
        fake = {"output": "export.mp4", "requested_duration": 4.0, "probe": {"duration": 4.0}}
        with patch.object(jobs.clip_render, "render_combine", return_value=fake) as combine, \
             patch.object(jobs.clip_render, "validate_render", return_value={"ok": True}):
            jobs._render_one(MagicMock(), cand, MagicMock(), None, Path("export.mp4"), 5, 90)
        self.assertFalse(combine.call_args.kwargs["transitions"])

    @unittest.skipUnless(SOURCE.exists(), "synthetic clip source fixture not present")
    def test_render_one_exports_combine_with_real_ffmpeg(self):
        if not Path(render.settings.ffmpeg).exists():
            self.skipTest("ffmpeg is not installed")
        cand = self._candidate()
        transcript = {
            "sentences": [{"start": 0.0, "end": 2.0, "text": "Invented transcript caption."}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "export.mp4"
            result = jobs._render_one(
                MagicMock(), cand, MagicMock(original_path=str(SOURCE.resolve())),
                transcript, out, 5, 90,
            )
            self.assertTrue(result["validation"]["ok"], result["validation"])
            self.assertAlmostEqual(result["requested_duration"], 3.4, places=2)
            self.assertEqual(result["combine"]["source_count"], 2)
            self.assertEqual(result["transition"]["mode"], "fade")
            self.assertEqual(result["cues"], 0)  # no transcript copy invented
            self.assertEqual(result["assembly"]["kind"], "source_combine")
            self.assertTrue(out.exists())

    def test_batch_export_manifest_records_multiple_sources(self):
        cand = self._candidate()
        ctx = MagicMock()
        ctx.job.meta = {"candidate_ids": ["cand"], "aspect": "9:16"}
        ctx.project.id = "proj"
        db = MagicMock()
        db.get.return_value = cand
        ctx.db = db
        fake = {
            "probe": {"duration": 3.4, "size_bytes": 25000}, "validation": {"ok": True},
            "assembly": cand.score_json["assembly"],
            "combine": {"source_count": 2}, "transition": {"mode": "fade"},
        }
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(jobs, "_source_for", return_value=MagicMock(original_path="legacy.mp4")), \
             patch.object(jobs.clip_transcribe, "load_transcript", return_value=None), \
             patch.object(jobs.store, "clip_paths", return_value={
                 "exports": Path(tmp), "analysis": Path(tmp) / "analysis",
             }), \
             patch.object(jobs, "_render_one", return_value=fake) as render_one, \
             patch.object(jobs.clip_audio, "measure_loudness", return_value=-16.0):
            out = jobs._job_batch_export(ctx)
            manifest = json.loads((Path(tmp) / "manifest.json").read_text())
        render_one.assert_called_once()
        self.assertIsNone(render_one.call_args.args[3])  # no single-source transcript
        item = out["items"][0]
        self.assertEqual(item["hashtags"], [])
        self.assertEqual(item["combine"]["source_count"], 2)
        self.assertEqual(item["transition"]["mode"], "fade")
        self.assertEqual(len(item["source_paths"]), 2)
        self.assertTrue(manifest["source_combine"])
        self.assertEqual(len(manifest["combine_sources"]), 2)
        self.assertEqual(manifest["succeeded"], 1)


class ProjectDefaultsTest(unittest.TestCase):
    def test_create_defaults_to_automatic_transitions(self):
        body = api.ClipProjectCreate()
        self.assertTrue(body.transitions)
        self.assertTrue(api.CombineBody().transitions is None)
        self.assertTrue(api.CombineBody().target_duration is None)
        self.assertEqual(api.CombineBody(target_duration=5).target_duration, 5)

    def test_ordered_sources_honour_saved_order_then_upload_order(self):
        now = datetime.utcnow()
        one = MagicMock(id="one", created_at=now - timedelta(seconds=3))
        two = MagicMock(id="two", created_at=now - timedelta(seconds=2))
        three = MagicMock(id="three", created_at=now - timedelta(seconds=1))
        project = MagicMock(settings_json=json.dumps({"source_order": ["two", "one"]}))
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [one, two, three]
        ordered = api._ordered_sources(db, project)
        self.assertEqual([s.id for s in ordered], ["two", "one", "three"])

    def test_upload_order_is_fallback_when_no_saved_order(self):
        now = datetime.utcnow()
        one = MagicMock(id="one", created_at=now - timedelta(seconds=2))
        two = MagicMock(id="two", created_at=now - timedelta(seconds=1))
        project = MagicMock(settings_json="{}")
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [two, one]
        self.assertEqual([s.id for s in api._ordered_sources(db, project)], ["one", "two"])


class CombineTargetDurationTest(unittest.TestCase):
    """The user-facing target must drive the combine timeline, not a whole-file sum."""

    def _sources(self) -> list[dict]:
        return [
            {"source_id": "one", "name": "one.mp4", "path": "one.mp4", "duration": 3.0},
            {"source_id": "two", "name": "two.mp4", "path": "two.mp4", "duration": 3.0},
        ]

    def test_max_duration_includes_crossfade_overlap(self):
        self.assertAlmostEqual(render.max_combine_duration([3.0, 3.0], True, 0.6), 5.4)
        self.assertAlmostEqual(render.max_combine_duration([3.0, 3.0], False, 0.6), 6.0)

    def test_fit_target_trims_all_sources_and_accounts_for_fade(self):
        fitted = render.fit_combine_segments(self._sources(), 5.0, True, 0.6)
        durations = [s["duration"] for s in fitted]
        boundaries = render._combine_boundaries(durations, True, 0.6)
        self.assertEqual([s["start"] for s in fitted], [0.0, 0.0])
        self.assertEqual([s["source_id"] for s in fitted], ["one", "two"])
        self.assertTrue(all(0 < d < 3.0 for d in durations), durations)
        self.assertGreaterEqual(sum(durations) - sum(boundaries), 5.0)
        self.assertLess(sum(durations) - sum(boundaries), 5.1)

    def test_fit_rejects_target_longer_than_available_material(self):
        with self.assertRaises(ValueError) as caught:
            render.fit_combine_segments(self._sources(), 7.0, True, 0.6)
        self.assertIn("exceeds", str(caught.exception))

    @unittest.skipUnless(SOURCE.exists(), "synthetic clip source fixture not present")
    def test_real_render_trims_final_mp4_to_target_in_both_modes(self):
        if not Path(render.settings.ffmpeg).exists():
            self.skipTest("ffmpeg is not installed")
        segments = [
            {"source_id": "one", "name": "one.mp4", "path": str(SOURCE.resolve()),
             "start": 0.0, "end": 2.0, "duration": 2.0},
            {"source_id": "two", "name": "two.mp4", "path": str(SOURCE.resolve()),
             "start": 2.0, "end": 4.0, "duration": 2.0},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for transitions in (True, False):
                out = Path(tmp) / ("fade_target.mp4" if transitions else "cut_target.mp4")
                result = render.render_combine(
                    sources=segments, out_path=out, transitions=transitions,
                    target_duration=3.0, audio={"normalize": True, "music": None},
                )
                self.assertTrue(render.validate_render(result, "9:16", 3.0)["ok"])
                self.assertAlmostEqual(result["requested_duration"], 3.0, places=2)
                self.assertAlmostEqual(float(result["probe"]["duration"]), 3.0, places=1)
                self.assertEqual(result["combine"]["target_duration"], 3.0)
                self.assertGreater(result["combine"]["source_timeline_duration"], 3.0)


if __name__ == "__main__":
    unittest.main()
