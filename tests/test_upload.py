import json
import unittest
from unittest.mock import patch
from urllib.parse import quote

import azure.functions as func
import function_app
from test_pipeline import MemoryStore

upload = function_app.upload._function.get_user_function()


def request(body=b"recording", **overrides):
    headers = {"Content-Type":"application/octet-stream", "X-Filename":"lecture.mp4",
               "X-Title":"Lecture", "X-Source-Url":quote("https://www.youtube.com/watch?v=fNk_zzaMoSs", safe="")}
    headers.update(overrides)
    return func.HttpRequest(method="POST", url="http://localhost/api/jobs", headers=headers, body=body)


class UploadTests(unittest.TestCase):
    @patch("function_app.storage")
    def test_anonymous_upload_and_duplicate_queue_once(self, storage):
        store = MemoryStore(); storage.return_value = store
        first = upload(request()); second = upload(request())
        self.assertEqual(first.status_code, 202)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(json.loads(second.get_body())["duplicate"])
        self.assertEqual(len(store.queued), 1)
        self.assertEqual(len(store.uploads), 1)

    @patch("function_app.storage")
    def test_invalid_headers_rejected_before_any_storage(self, storage):
        for headers in ({"Content-Length":"bad"}, {"X-Source-Offset":"nan"}, {"X-Filename":"bad.exe"},
                        {"X-Source-Url":"javascript%3Aalert%281%29"}):
            with self.subTest(headers=headers):
                self.assertEqual(upload(request(**headers)).status_code, 400)
        storage.assert_not_called()

    @patch("function_app.storage")
    @patch.dict("os.environ", {"MAX_UPLOAD_BYTES":"10"})
    def test_size_limits_are_checked_before_storage(self, storage):
        self.assertEqual(upload(request(b"a" * 11)).status_code, 413)
        self.assertEqual(upload(request(**{"Content-Length":"11"})).status_code, 413)
        storage.assert_not_called()
