import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from azure.core.exceptions import ResourceModifiedError
from pipeline import Store, paid_request, process
from test_core import SAMPLE


class MemoryStore:
    def __init__(self):
        self.values, self.uploads, self.queued, self.catalog = {}, {}, [], []

    def read(self, name, public=False):
        return copy.deepcopy(self.values.get((public, name)))

    def write(self, name, value, public=False, create=False):
        key = (public, name)
        if create and key in self.values:
            return False
        self.values[key] = copy.deepcopy(value)
        return True

    def upload(self, name, content, *args):
        self.uploads[name] = content

    def register(self, meta):
        self.catalog.append(meta["id"])

    def enqueue(self, job):
        self.queued.append(job)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        self.job = "a" * 40
        self.store.write(f"jobs/{self.job}/metadata.json", {**SAMPLE["job"], "id":self.job, "status":"queued"})

    def test_duplicate_delivery_cannot_repeat_processing(self):
        prepare = Mock(return_value={"duration_seconds":55})
        speech = Mock(return_value=SAMPLE["transcript"])
        notes = Mock(return_value=SAMPLE["notes"])
        for _ in range(2):
            process(self.job, self.store, prepare, speech, notes)
        prepare.assert_called_once(); speech.assert_called_once(); notes.assert_called_once()
        result = self.store.read(f"lectures/{self.job}.json", public=True)
        self.assertEqual(result["job"]["status"], "ready")
        self.assertEqual(len(result["transcript"]["segments"]), 8)

    def test_failure_stops_later_stages_and_preserves_claim(self):
        prepare = Mock(return_value={"duration_seconds":55})
        speech = Mock(side_effect=ValueError("Invalid speech timestamps"))
        notes = Mock()
        with self.assertLogs(level="ERROR"):
            process(self.job, self.store, prepare, speech, notes)
        result = self.store.read(f"lectures/{self.job}.json", public=True)
        self.assertEqual(result["job"]["status"], "failed")
        notes.assert_not_called()
        process(self.job, self.store, prepare, speech, notes)
        speech.assert_called_once()

    @patch("pipeline.credential")
    def test_uncertain_ai_request_is_not_resubmitted(self, credential):
        credential.return_value.get_token.return_value.token = "fake-unit-test-token"
        request = Mock(side_effect=TimeoutError("connection lost"))
        with self.assertRaises(TimeoutError):
            paid_request(self.store, self.job, "speech", request)
        with self.assertRaises(ValueError):
            paid_request(self.store, self.job, "speech", request)
        request.assert_called_once()

    @patch("pipeline.credential")
    def test_saved_ai_response_is_reused_without_credentials_or_call(self, credential):
        self.store.write(f"jobs/{self.job}/summary-raw.json", {"saved":True})
        request = Mock()
        self.assertEqual(paid_request(self.store, self.job, "summary", request), {"saved":True})
        credential.assert_not_called(); request.assert_not_called()

    @patch("pipeline.credential")
    def test_credential_failure_does_not_reserve_paid_attempt(self, credential):
        credential.return_value.get_token.side_effect = RuntimeError("identity unavailable")
        with self.assertRaises(RuntimeError):
            paid_request(self.store, self.job, "speech", Mock())
        self.assertIsNone(self.store.read(f"jobs/{self.job}/speech-attempt.json"))

    def test_catalog_conflict_reloads_and_preserves_other_upload(self):
        old = {"lectures":[{"id":"old", "title":"Old"}]}
        newer = {"lectures":[{"id":"other", "title":"Other"}, *old["lectures"]]}
        target = Mock()
        target.download_blob.side_effect = [SimpleNamespace(readall=lambda:json.dumps(old).encode(), properties=SimpleNamespace(etag="one")),
            SimpleNamespace(readall=lambda:json.dumps(newer).encode(), properties=SimpleNamespace(etag="two"))]
        target.upload_blob.side_effect = [ResourceModifiedError("conflict"), None]
        store = Store.__new__(Store); store.blob = Mock(return_value=target)
        store.register({"id":"new", "title":"New", "created_at":"today"})
        final = json.loads(target.upload_blob.call_args.args[0])
        self.assertEqual([item["id"] for item in final["lectures"]], ["new", "other", "old"])
