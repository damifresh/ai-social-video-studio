"""Tests for the project-level Captions toggle in Engine B."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.clip import api, jobs


class CaptionToggleTest(unittest.TestCase):
    def test_project_create_defaults_to_captions_on(self):
        self.assertTrue(api.ClipProjectCreate().burn_captions)
        self.assertFalse(api.ClipProjectCreate(burn_captions=False).burn_captions)

    def test_project_detail_exposes_captions_from_settings(self):
        project = MagicMock(
            settings_json=json.dumps({"burn_captions": False, "transitions": True}),
        )
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(api, "_ordered_sources", return_value=[]), \
             patch.object(api.store, "clip_paths", return_value={"analysis": Path(tmp)}), \
             patch.object(api.clip_transcribe, "load_transcript", return_value=None):
            detail = api.proj_dict(project, MagicMock())
        self.assertFalse(detail["burn_captions"])

    def test_highlight_defaults_follow_project_setting_then_job_meta(self):
        project = MagicMock(settings_json=json.dumps({"burn_captions": False}))
        self.assertFalse(jobs._highlight_edit_defaults(project)["burn_captions"])
        self.assertTrue(jobs._highlight_edit_defaults(project, {"burn_captions": True})["burn_captions"])
        self.assertTrue(jobs._highlight_edit_defaults(
            MagicMock(settings_json="{}"), {},
        )["burn_captions"])

    def test_update_project_propagates_to_transcript_and_combine_candidates(self):
        project = MagicMock(
            id="proj",
            settings_json=json.dumps({"burn_captions": True, "source_order": ["s1"]}),
        )
        transcript_clip = MagicMock(
            state="rendered", edit_json=json.dumps({"burn_captions": True}),
            score_json={"assembly": {"kind": "one_clip"}},
        )
        combine_clip = MagicMock(
            state="rendered", edit_json=json.dumps({"burn_captions": True}),
            score_json={"assembly": {"kind": "source_combine"}},
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [transcript_clip, combine_clip]
        body = api.ClipProjectUpdate(settings={"burn_captions": False})

        with patch.object(api, "_project", return_value=project), \
             patch.object(api, "_ordered_sources", return_value=[]):
            api.update_project("proj", body, db)

        settings = json.loads(project.settings_json)
        self.assertFalse(settings["burn_captions"])
        self.assertEqual(settings["source_order"], ["s1"])  # partial settings merge
        self.assertFalse(json.loads(transcript_clip.edit_json)["burn_captions"])
        self.assertEqual(transcript_clip.state, "stale")
        self.assertFalse(json.loads(combine_clip.edit_json)["burn_captions"])
        self.assertEqual(combine_clip.state, "stale")


class CombineCaptionTest(unittest.TestCase):
    def test_source_transcript_import_is_cached_per_source(self):
        source = MagicMock(
            id="s1", clip_project_id="proj", duration_sec=3.0,
            original_name="one.mp4",
        )
        db = MagicMock()
        db.get.return_value = source
        db.query.return_value.filter.return_value.all.return_value = []
        srt = "1\n00:00:00,100 --> 00:00:01,200\nHello from source one\n\n"
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(api.store, "source_transcript_path", return_value=Path(tmp) / "transcript.json"):
            result = api.import_source_transcript(
                "s1", api.TranscriptImportBody(content=srt, filename="one.srt"), db,
            )
            transcript = result["transcript"]
            self.assertEqual(transcript["sentences"][0]["text"], "Hello from source one")
            cached = json.loads((Path(tmp) / "transcript.json").read_text())
            self.assertEqual(cached["sentences"][0]["text"], "Hello from source one")
        db.commit.assert_called_once()

    def test_combine_job_records_burned_caption_metadata(self):
        source_one = MagicMock(
            id="one", clip_project_id="proj", original_name="one.mp4",
            original_path="one.mp4", duration_sec=2.0, audio_streams=1,
        )
        source_two = MagicMock(
            id="two", clip_project_id="proj", original_name="two.mp4",
            original_path="two.mp4", duration_sec=2.0, audio_streams=1,
        )
        ctx = MagicMock()
        ctx.project.id = "proj"
        ctx.project.language = "en"
        ctx.project.settings_json = json.dumps({"burn_captions": True})
        ctx.job.meta = {
            "source_ids": ["one", "two"], "transitions": True,
            "transition_seconds": 0.6, "target_duration": None, "aspect": "9:16",
            "burn_captions": True,
        }
        ctx.db.get.side_effect = lambda _model, sid: {"one": source_one, "two": source_two}.get(sid)
        candidates = MagicMock()
        candidates.filter.return_value.all.return_value = []
        renders = MagicMock()
        renders.filter.return_value.first.return_value = None
        ctx.db.query.side_effect = lambda model: renders if model is jobs.ClipRender else candidates
        transcripts = {
            "one": {"sentences": [{"start": 0.0, "end": 1.0, "text": "First source line."}]},
            "two": {"sentences": [{"start": 0.0, "end": 1.0, "text": "Second source line."}]},
        }

        def load(path):
            return transcripts.get(Path(path).parent.name)

        fake = {
            "requested_duration": 3.4, "cue_count": 2,
            "probe": {"duration": 3.4, "size_bytes": 1000},
            "combine": {"source_timeline_duration": 3.4},
        }
        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(jobs.store, "clip_paths", return_value={
                 "clips": Path(tmp), "exports": Path(tmp), "analysis": Path(tmp),
             }), \
             patch.object(jobs.store, "source_transcript_path", side_effect=lambda _pid, sid: Path(tmp) / sid / "transcript.json"), \
             patch.object(jobs.clip_transcribe, "load_transcript", side_effect=load), \
             patch.object(jobs.clip_render, "render_combine", return_value=fake) as combine, \
             patch.object(jobs.clip_render, "validate_render", return_value={"ok": True}):
            result = jobs._job_combine(ctx)

        kwargs = combine.call_args.kwargs
        self.assertEqual(len(kwargs["source_cues"]), 2)
        self.assertEqual(kwargs["source_cues"][0][0]["text"], "First source line.")
        self.assertEqual(result["cue_count"], 2)
        self.assertTrue(result["captions"]["enabled"])
        self.assertEqual(result["captions"]["cue_count"], 2)


if __name__ == "__main__":
    unittest.main()
