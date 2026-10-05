import json
import unittest
import urllib.error
from unittest.mock import MagicMock, patch
from uuid import uuid4

import cloud_uploader as uploader


class UploaderTests(unittest.TestCase):
    def setUp(self):
        self.config = uploader.UploadConfig(
            "https://cloud.example", uuid4(), "test-machine-credential-at-least-32",
            "private-router-token",
        )
        self.snapshot = {
            "observed_at": "2026-10-05T00:00:00+00:00",
            "devices": [], "alerts": [], "model": {"available": False},
        }

    def test_credentials_are_sent_only_to_their_respective_endpoints(self):
        with patch.object(uploader, "request_json", side_effect=[
            self.snapshot, {"success": True, "snapshot_updated": True},
        ]) as request:
            uploader.upload_once(self.config, MagicMock())
        local, cloud = [call.args[1] for call in request.call_args_list]
        self.assertEqual(local.get_header("X-gateway-token"), "private-router-token")
        self.assertIsNone(local.get_header("X-gateway-credential"))
        self.assertEqual(cloud.get_header("X-gateway-credential"), self.config.credential)
        self.assertIsNone(cloud.get_header("X-gateway-token"))
        self.assertEqual(cloud.method, "PUT")
        self.assertEqual(json.loads(cloud.data), self.snapshot)

    def test_unexpected_snapshot_fields_are_not_uploaded(self):
        with patch.object(uploader, "request_json", return_value={**self.snapshot, "training_rows": []}) as request:
            with self.assertRaises(uploader.PermanentUploadError):
                uploader.upload_once(self.config, MagicMock())
        self.assertEqual(request.call_count, 1)

    def test_success_requires_explicit_cloud_acknowledgement(self):
        for response in ({}, {"success": False}, {"success": True, "snapshot_updated": 1}):
            with patch.object(uploader, "request_json", side_effect=[self.snapshot, response]):
                with self.assertRaises(uploader.PermanentUploadError):
                    uploader.upload_once(self.config, MagicMock())

    def test_http_errors_do_not_echo_secret_response_body(self):
        for code, error_type in ((401, uploader.PermanentUploadError),
                                 (302, uploader.PermanentUploadError),
                                 (503, uploader.UploadError), (409, uploader.UploadError)):
            opener = MagicMock()
            opener.open.side_effect = urllib.error.HTTPError(
                "https://secret-url", code, "private body", {}, None,
            )
            with self.assertRaises(error_type) as caught:
                uploader.request_json(opener, MagicMock())
            self.assertNotIn("private body", str(caught.exception))
            self.assertNotIn("secret-url", str(caught.exception))

    def test_http_errors_and_reconnect_are_retried_with_backoff(self):
        with (
            patch.object(uploader, "upload_once", side_effect=[
                uploader.UploadError("offline"), None, uploader.PermanentUploadError("stop"),
            ]),
            patch.object(uploader.time, "sleep") as sleep,
            patch.object(uploader.random, "uniform", return_value=0),
        ):
            with self.assertRaises(uploader.PermanentUploadError):
                uploader.run(self.config)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [30, 30])
        with patch.object(uploader.random, "uniform", return_value=0):
            self.assertEqual(uploader.retry_delay(2, 30), 60)
            self.assertEqual(uploader.retry_delay(1000, 30), 300)

    def test_https_cloud_and_loopback_source_required(self):
        for cloud, local in (
            ("http://cloud.example", "http://127.0.0.1:8001"),
            ("https://user:password@cloud.example", "http://127.0.0.1:8001"),
            ("https://cloud.example", "http://192.168.50.1:8001"),
            ("https://cloud.example?secret=x", "http://127.0.0.1:8001"),
        ):
            with self.assertRaises(ValueError):
                uploader.UploadConfig(cloud, uuid4(), self.config.credential, "token", local)

    def test_redirects_are_never_followed(self):
        self.assertIsNone(uploader.NoRedirect().redirect_request(
            MagicMock(), MagicMock(), 302, "", {}, "https://other.example",
        ))

    def test_invalid_json_and_oversized_responses_fail_explicitly(self):
        for body in (b"not json", b"[]", b"x" * (uploader.MAX_RESPONSE_BYTES + 1)):
            opener = MagicMock()
            opener.open.return_value.__enter__.return_value.read.return_value = body
            with self.assertRaises(uploader.PermanentUploadError):
                uploader.request_json(opener, MagicMock())


if __name__ == "__main__":
    unittest.main()
