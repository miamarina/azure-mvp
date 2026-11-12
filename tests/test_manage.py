import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import manage


class DeploymentTests(unittest.TestCase):
    @patch("manage.Cloud")
    def test_cleanup_requires_exact_group_confirmation_before_azure_access(self, cloud):
        cfg = {"subscription_id":"11111111-1111-1111-1111-111111111111", "project_name":"studynotes-one"}
        with self.assertRaises(ValueError):
            manage.destroy(cfg, "some-other-group")
        cloud.assert_not_called()

    def test_function_hostname_supports_both_cli_response_shapes(self):
        self.assertEqual(manage.function_hostname({"defaultHostName":"app.example"}), "app.example")
        self.assertEqual(manage.function_hostname({"properties":{"defaultHostName":"app.example"}}), "app.example")

    def test_config_is_parameterized_and_names_are_subscription_specific(self):
        a = {"subscription_id":"11111111-1111-1111-1111-111111111111", "project_name":"studynotes-one"}
        b = {**a, "subscription_id":"22222222-2222-2222-2222-222222222222"}
        self.assertNotEqual(manage.names(a)["storage"], manage.names(b)["storage"])
        self.assertNotEqual(manage.names(a)["function_app"], manage.names(b)["function_app"])

    def test_backend_archive_contains_only_source_and_selected_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "app.zip"
            manage.backend_package({"hosting":"consumption"}, target)
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(set(archive.namelist()), set(manage.BACKEND_FILES))
                self.assertEqual(json.loads(archive.read("host.json"))["functionTimeout"], "00:10:00")
                for entry in archive.infolist():
                    self.assertEqual(entry.create_system, 3)
                    self.assertEqual(entry.external_attr >> 16, 0o100644,
                                     f"{entry.filename} must be readable by the Linux runtime user")

    def test_personal_config_is_not_in_share_allowlist(self):
        self.assertNotIn("config.json", manage.SHARE_FILES)
        self.assertNotIn(".local", manage.SHARE_DIRS)
        self.assertNotIn(".venv", manage.SHARE_DIRS)
