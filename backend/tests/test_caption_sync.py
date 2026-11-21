"""Regression tests for burned-in caption synchronization.

Covers two previously-broken behaviours:
1. ASS timestamp format — libass ignores Dialogue lines with 3-decimal
   (SRT-style) times, so captions never appeared at all in rendered MP4s.
2. Word-level caption alignment — clipped sentences used to display their
   full text from the clip's first frame, showing words not yet audible.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.clip import render, transcribe
from app.core.config import settings
from app.services import subtitles


class AssTimestampTest(unittest.TestCase):
    def test_fmt_ass_uses_centiseconds(self):
        self.assertEqual(subtitles._fmt_ass(0.5), "0:00:00.50")
        self.assertEqual(subtitles._fmt_ass(1.234), "0:00:01.23")
        self.assertEqual(subtitles._fmt_ass(65.7), "0:01:05.70")
        self.assertEqual(subtitles._fmt_ass(3661.99), "1:01:01.99")

    def test_build_ass_writes_libass_compatible_times(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = subtitles.build_ass(
                [{"start": 0.5, "end": 2.5, "text": "test"}],
                Path(tmp) / "cap.ass",
                width=720, height=1280,
            )
            dialogue = next(line for line in path.read_text().splitlines()
                            if line.startswith("Dialogue:"))
            self.assertIn("0:00:00.50", dialogue)
            self.assertIn("0:00:02.50", dialogue)
            # Must NOT use SRT/VTT 3-decimal format
            self.assertNotIn("00:00:00.500", dialogue)

    @unittest.skipUnless(Path(settings.ffmpeg).exists(), "ffmpeg not installed")
    def test_rendered_ass_actually_shows_captions_at_right_times(self):
        """End-to-end: build ASS, burn it into a video, sample frames."""
        import subprocess

        ff = settings.ffmpeg
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            ass = subtitles.build_ass(
                [{"start": 0.5, "end": 2.5, "text": "SYNC_TEST"}],
                tmp / "cap.ass",
                style={"font": "Arial", "size": 60, "bold": True},
                width=720, height=1280,
            )
            out = tmp / "out.mp4"
            subprocess.run(
                [ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                 "color=c=black:s=720x1280:r=30", "-t", "4",
                 "-vf", f"subtitles={ass}", "-c:v", "libx264",
                 "-pix_fmt", "yuv420p", str(out), "-y"],
                check=True,
            )

            def bright_pixels_at(t: float) -> int:
                frame = tmp / "frame.raw"
                subprocess.run(
                    [ff, "-hide_banner", "-loglevel", "error", "-ss", str(t),
                     "-i", str(out), "-frames:v", "1",
                     "-vf", "crop=720:400:0:880,scale=72:40",
                     "-f", "rawvideo", "-pix_fmt", "gray", str(frame), "-y"],
                    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                return sum(1 for b in frame.read_bytes() if b > 30)

            self.assertEqual(bright_pixels_at(0.3), 0, "caption appears too early")
            self.assertGreater(bright_pixels_at(1.0), 0, "caption missing during cue")
            self.assertGreater(bright_pixels_at(2.0), 0, "caption missing during cue")
            self.assertEqual(bright_pixels_at(2.8), 0, "caption lingers past cue")


class WordCueAlignmentTest(unittest.TestCase):
    def _transcript(self):
        words = [
            {"start": 0.0, "end": 0.4, "text": "Welcome"},
            {"start": 0.4, "end": 0.7, "text": "to"},
            {"start": 0.7, "end": 1.1, "text": "our"},
            {"start": 1.1, "end": 1.5, "text": "show"},
            {"start": 1.6, "end": 2.0, "text": "Today"},
            {"start": 2.0, "end": 2.3, "text": "we"},
            {"start": 2.3, "end": 2.7, "text": "talk"},
            {"start": 2.7, "end": 3.0, "text": "about"},
            {"start": 3.0, "end": 3.5, "text": "sync"},
        ]
        return {
            "timing": "native", "word_timing": "native", "language": "en",
            "words": words,
            "sentences": transcribe.build_sentences(words),
        }

    def test_clipped_cue_contains_only_words_within_clip(self):
        cues = transcribe.caption_segments(self._transcript(), 0.8, 2.5)
        self.assertTrue(cues)
        # Words spoken before 0.8 ("Welcome to") must not appear.
        for cue in cues:
            self.assertNotIn("Welcome", cue["text"])
            self.assertNotIn("to ", cue["text"])
        # Words spoken after 2.5 ("about sync") must not appear.
        for cue in cues:
            self.assertNotIn("sync", cue["text"])
        all_text = " ".join(c["text"] for c in cues)
        self.assertIn("our", all_text)
        self.assertIn("show", all_text)

    def test_cue_times_match_word_times(self):
        cues = transcribe.caption_segments(self._transcript(), 1.0, 3.0)
        first = cues[0]
        # "our" starts at 0.7 but clip starts at 1.0 -> cue should start at 0.0
        self.assertAlmostEqual(first["start"], 0.0, places=2)
        # Last cue ends at clip end (3.0 - 1.0 = 2.0)
        self.assertAlmostEqual(cues[-1]["end"], 2.0, places=2)

    def test_sentence_only_transcript_still_produces_cues(self):
        transcript = {"sentences": [{"start": 0.0, "end": 2.0, "text": "A timed sentence here."}]}
        cues = transcribe.caption_segments(transcript, 0.0, 2.0)
        self.assertTrue(cues)
        self.assertEqual(" ".join(c["text"] for c in cues), "A timed sentence here.")

    def test_crossfade_trims_cue_text_to_audible_words(self):
        """Words outside the crossfade half-window are dropped from text."""
        source_cues = [[
            {"start": 1.6, "end": 2.0, "text": "to the show", "_words": [
                {"start": 1.6, "end": 1.75, "text": "to"},
                {"start": 1.75, "end": 1.9, "text": "the"},
                {"start": 1.9, "end": 2.0, "text": "show"},
            ]},
        ], []]
        cues = render.shift_combine_cues(
            source_cues,
            [{"duration": 2.0}, {"duration": 2.0}],
            [0.6], [1.4], 3.4,
        )
        # visible_end for source 0 = 2.0 - 0.3 = 1.7, so only "to" survives.
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0]["text"], "to")
        self.assertAlmostEqual(cues[0]["end"], 1.7, places=2)


if __name__ == "__main__":
    unittest.main()
