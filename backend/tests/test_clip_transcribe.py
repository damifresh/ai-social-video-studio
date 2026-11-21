"""Tests for whisper.cpp ASR results, including the no-speech case."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.clip import jobs, transcribe


class _FakeProc:
    """Minimal subprocess stand-in with an iterable (already consumed) stderr."""

    def __init__(self, returncode: int = 0, stderr: str = ""):
        self.returncode = returncode
        self.stderr = io.StringIO(stderr)
        self.stdout = io.StringIO("")

    def wait(self) -> int:
        return self.returncode

    def kill(self) -> None:
        pass


class WhisperResultTest(unittest.TestCase):
    def _cap(self) -> dict:
        return {
            "available": True,
            "bin_path": "/fake/whisper-cli",
            "model_path": "/fake/ggml-base.en.bin",
            "model": "ggml-base.en.bin",
        }

    def test_no_speech_json_is_a_success_with_no_cues(self):
        """A valid empty transcription must not abort a combine job."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            wav = tmp / "audio.wav"
            wav.write_bytes(b"fake wav")
            out = tmp / "whisper.json"
            out.write_text(json.dumps({"transcription": []}), encoding="utf-8")
            with patch.object(transcribe, "capability", return_value=self._cap()), \
                 patch.object(transcribe.subprocess, "Popen", return_value=_FakeProc()):
                result = transcribe.transcribe(wav, out)
        self.assertEqual(result["segments"], [])
        self.assertEqual(result["sentences"], [])
        self.assertEqual(result["words"], [])
        self.assertEqual(result["backend"], "whisper_cpp")
        self.assertTrue(any("No speech detected" in n for n in result["notes"]))

    def test_speech_json_still_parses_native_words(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            wav = tmp / "audio.wav"
            wav.write_bytes(b"fake wav")
            out = tmp / "whisper.json"
            payload = {"transcription": [{
                "text": " Hello world.",
                "offsets": {"from": 0, "to": 1200},
                "tokens": [
                    {"text": "[_BEG_]", "offsets": {"from": 0, "to": 0}},
                    {"text": " Hello", "offsets": {"from": 10, "to": 500}},
                    {"text": " world.", "offsets": {"from": 500, "to": 1200}},
                ],
            }]}
            out.write_text(json.dumps(payload), encoding="utf-8")
            with patch.object(transcribe, "capability", return_value=self._cap()), \
                 patch.object(transcribe.subprocess, "Popen", return_value=_FakeProc()):
                result = transcribe.transcribe(wav, out)
        self.assertEqual(len(result["segments"]), 1)
        self.assertEqual(result["segments"][0]["text"], "Hello world.")
        self.assertEqual(result["word_timing"], "native")
        self.assertTrue(result["words"])

    def test_failed_process_reports_its_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            wav = tmp / "audio.wav"
            wav.write_bytes(b"fake wav")
            with patch.object(transcribe, "capability", return_value=self._cap()), \
                 patch.object(transcribe.subprocess, "Popen",
                              return_value=_FakeProc(returncode=1, stderr="model read failure\n")):
                with self.assertRaisesRegex(RuntimeError, "model read failure"):
                    transcribe.transcribe(wav, tmp / "whisper.json")


class CombineNoSpeechTest(unittest.TestCase):
    def test_empty_transcript_yields_notice_instead_of_failure(self):
        ctx = MagicMock()
        ctx.project.id = "proj"
        segments = [{"source_id": "s1", "name": "silent.mp4", "start": 0.0, "end": 2.0}]
        empty = {"segments": [], "sentences": [], "words": [], "timing": "native"}
        with patch.object(jobs.clip_transcribe, "load_transcript", return_value=empty):
            cues, notices = jobs._combine_source_cues(ctx, segments, 32)
        self.assertEqual(cues, [[]])
        self.assertEqual(len(notices), 1)
        self.assertIn("no speech detected", notices[0])


if __name__ == "__main__":
    unittest.main()
