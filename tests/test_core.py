import copy
import json
from pathlib import Path
import unittest

from core import job_id, normalize_transcript, source_link, source_url, validate_notes

SAMPLE = json.loads((Path(__file__).resolve().parents[1] / "sample/lectures/vectors-sample.json").read_text(encoding="utf-8"))


class CoreTests(unittest.TestCase):
    def test_chapters_cover_every_segment_once(self):
        value = copy.deepcopy(SAMPLE)
        notes = validate_notes(value["notes"], value["transcript"])
        boundaries = [chapter["segment_index"] for chapter in notes["chapters"]] + [len(value["transcript"]["segments"])]
        covered = [s["id"] for i in range(len(boundaries) - 1)
                   for s in value["transcript"]["segments"][boundaries[i]:boundaries[i + 1]]]
        self.assertEqual(covered, [s["id"] for s in value["transcript"]["segments"]])

    def test_chapters_cannot_skip_first_passage_or_reorder(self):
        for refs in (("S0002", "S0004"), ("S0001", "S0001"), ("S0001", "S0004", "S0003")):
            with self.subTest(refs=refs):
                value = copy.deepcopy(SAMPLE)
                value["notes"]["chapters"] = [{"title":"Chapter", "start_segment_id":ref} for ref in refs]
                with self.assertRaises(ValueError):
                    validate_notes(value["notes"], value["transcript"])

    def test_unknown_and_missing_references_rejected(self):
        for refs in ([], ["S9999"], [3], "S0001"):
            with self.subTest(refs=refs):
                value = copy.deepcopy(SAMPLE)
                value["notes"]["overview"][0]["segment_ids"] = refs
                with self.assertRaises(ValueError):
                    validate_notes(value["notes"], value["transcript"])

    def test_full_lecture_source_offsets(self):
        link = source_link("https://www.youtube.com/watch?v=fNk_zzaMoSs&t=2s", 15.9, 2520)
        self.assertIn("t=2535s", link)
        self.assertEqual(source_link("https://example.com/lecture.mp4", 2520), "https://example.com/lecture.mp4#t=2520")

    def test_unsafe_or_unsupported_source_urls(self):
        for value in ("javascript:alert(1)", "https://user:secret@example.com/video.mp4",
                      "https://example.com/page", "https://youtube.com/watch?v=invalid"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                source_url(value)

    def test_deduplication_and_explicit_experiments(self):
        a = job_id(b"media", "en-US")
        self.assertEqual(a, job_id(b"media", "en-US"))
        self.assertNotEqual(a, job_id(b"media", "de-DE"))
        self.assertNotEqual(a, job_id(b"media", "en-US", "run-01"))

    def test_normalization_rejects_out_of_range_or_unordered_speech(self):
        cases = [(0, -1), (-1, 10), (55001, 1000), (float("nan"), 10)]
        for start, duration in cases:
            with self.subTest(start=start), self.assertRaises(ValueError):
                normalize_transcript({"phrases":[{"text":"hello", "offsetMilliseconds":start, "durationMilliseconds":duration}]}, 55)
        with self.assertRaises(ValueError):
            normalize_transcript({"phrases":[{"text":"a", "offsetMilliseconds":500, "durationMilliseconds":100},
                {"text":"b", "offsetMilliseconds":100, "durationMilliseconds":100}]}, 55)

    def test_empty_transcript_rejected(self):
        with self.assertRaises(ValueError):
            normalize_transcript({"phrases":[]}, 55)
