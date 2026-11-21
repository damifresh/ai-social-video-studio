"""Regression tests for manifest-based exact-stage resume."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.services import resume, project_store as ps


class FakeProject:
    id = "resume-test"
    aspect_ratio = "16:9"
    fps = 30
    style = "cinematic"
    topic = "topic"
    prompt = "prompt"
    title = "title"
    duration_min = 1
    language = "en"
    voice = "say:Samantha"
    voice_speed = 0
    subtitle_enabled = True
    subtitle_style = "{}"
    music_track = "none"
    music_volume = 0.10
    burn_subs = True


class ResumeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.pdir = self.root / "resume-test"
        self.patcher = patch.object(ps, "project_dir", return_value=self.pdir)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.project = FakeProject()
        self.scene = {
            "narration": "Hello world",
            "tts_text": "Hello world",
            "render_dur": 2.0,
            "camera": "slow_zoom_in",
            "transition": "cut",
            "image_path": str(self.pdir / "images" / "scene_01.png"),
        }
        self.scenes = [self.scene]
        self._make_artifacts()

    def _write(self, rel: str, data: str = "x"):
        p = self.pdir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data.encode("utf-8"))
        return p

    def _make_artifacts(self):
        for rel in (
            "script.json", "scenes.json",
            "images/scene_01.png",
            "audio/scene_01.wav", "audio/narration_full.wav", "audio/final_mix.wav",
            "video/scenes/scene_01.mp4", "renders/final_16x9_720p.mp4",
            "subs/subtitles.srt", "subs/subtitles.vtt", "subs/subtitles.ass",
            "timings.json", "result.json",
        ):
            self._write(rel)
        self._write("result.json", '{"final_video": "%s"}' % (self.pdir / "renders" / "final_16x9_720p.mp4"))

    def _plan(self):
        return resume.build_plan(self.project.id, self.project, self.scenes, self.pdir)

    def test_no_stage_is_skipped_without_a_manifest(self):
        plan = self._plan()
        self.assertTrue(all(not stage["skip"] for stage in plan.values()))

    def test_marked_stages_with_present_artifacts_are_skipped(self):
        plan = self._plan()
        for stage in resume.STAGES:
            resume.mark_stage(self.project.id, stage, plan[stage]["signature"], self.pdir)
        refreshed = self._plan()
        self.assertTrue(all(stage["skip"] for stage in refreshed.values()), refreshed)

    def test_changed_input_invalidates_affected_stages(self):
        plan = self._plan()
        for stage in resume.STAGES:
            resume.mark_stage(self.project.id, stage, plan[stage]["signature"], self.pdir)

        self.scene["narration"] = "Different words"
        refreshed = self._plan()
        self.assertFalse(refreshed["script"]["skip"])
        self.assertFalse(refreshed["visuals"]["skip"])
        self.assertFalse(refreshed["tts"]["skip"])

    def test_replaced_artifact_invalidates_downstream_stages(self):
        plan = self._plan()
        for stage in resume.STAGES:
            resume.mark_stage(self.project.id, stage, plan[stage]["signature"], self.pdir)

        self._write("audio/scene_01.wav", "replaced audio bytes")
        refreshed = self._plan()
        self.assertFalse(refreshed["tts"]["skip"])
        self.assertFalse(refreshed["scenes"]["skip"])
        self.assertFalse(refreshed["audio_mix"]["skip"])
        self.assertFalse(refreshed["compose"]["skip"])

    def test_missing_artifact_invalidates_its_stage(self):
        plan = self._plan()
        for stage in resume.STAGES:
            resume.mark_stage(self.project.id, stage, plan[stage]["signature"], self.pdir)
        (self.pdir / "video" / "scenes" / "scene_01.mp4").unlink()
        refreshed = self._plan()
        self.assertFalse(refreshed["scenes"]["skip"])
        self.assertFalse(refreshed["compose"]["skip"])


if __name__ == "__main__":
    unittest.main()
