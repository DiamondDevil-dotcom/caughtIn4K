import json
import os
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import cloud_accounts
import cloud_account_security
import cloud_assistant
from cloud_account_api import build_router


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "GHOST_ASSISTANT_ENABLED": "true",
            "OPENAI_API_KEY": "test-not-a-real-api-key",
            "GHOST_ASSISTANT_MODEL": "test-model",
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_disabled_or_missing_configuration_never_calls_provider(self):
        for missing in ("GHOST_ASSISTANT_ENABLED", "OPENAI_API_KEY", "GHOST_ASSISTANT_MODEL"):
            with patch.dict(os.environ, {missing: ""}), \
                    patch.object(cloud_assistant.http.client, "HTTPSConnection") as connect:
                with self.assertRaises(HTTPException) as failure:
                    cloud_assistant.answer("How do I set up?")
                self.assertEqual(failure.exception.status_code, 503)
                connect.assert_not_called()

    def provider(self, result=None, status=200):
        connection = MagicMock()
        response = connection.getresponse.return_value
        response.status = status
        response.read.return_value = json.dumps(result or {
            "status": "completed",
            "output": [{"type": "message", "content": [
                {"type": "output_text", "text": "Use the setup wizard."},
            ]}],
        }).encode()
        return connection

    def test_text_only_bounded_request_does_not_store_or_send_account_context(self):
        connection = self.provider()
        with patch.object(cloud_assistant.http.client, "HTTPSConnection", return_value=connection) as connect:
            self.assertEqual(cloud_assistant.answer(" Setup help "), {"reply": "Use the setup wizard."})
        connect.assert_called_once_with("api.openai.com", timeout=20)
        args, kwargs = connection.request.call_args
        self.assertEqual(args, ("POST", "/v1/responses"))
        body = json.loads(kwargs["body"])
        self.assertEqual(set(body), {"model", "instructions", "input", "max_output_tokens", "store"})
        self.assertEqual(body["input"], "Setup help")
        self.assertFalse(body["store"])
        self.assertEqual(body["max_output_tokens"], 500)
        connection.close.assert_called_once()

    def test_provider_errors_are_explicit_and_do_not_echo_sensitive_body(self):
        connection = self.provider(status=401)
        with patch.object(cloud_assistant.http.client, "HTTPSConnection", return_value=connection):
            with self.assertRaises(HTTPException) as failure:
                cloud_assistant.answer("Help")
        self.assertEqual(failure.exception.status_code, 503)
        self.assertNotIn("api-key", failure.exception.detail)
        connection.close.assert_called_once()

    def test_timeout_and_malformed_incomplete_empty_or_oversize_replies_fail(self):
        for result in (
            {"status": "incomplete", "output": []},
            {"status": "completed", "output": None},
            {"status": "completed", "output": []},
            {"status": "completed", "output": [{"type": "message", "content": [
                {"type": "output_text", "text": 12},
            ]}]},
        ):
            connection = self.provider(result)
            with patch.object(cloud_assistant.http.client, "HTTPSConnection", return_value=connection):
                with self.assertRaises(HTTPException):
                    cloud_assistant.answer("Help")
        for raw in (b"invalid json", b"x" * 131073):
            connection = self.provider()
            connection.getresponse.return_value.read.return_value = raw
            with patch.object(cloud_assistant.http.client, "HTTPSConnection", return_value=connection):
                with self.assertRaises(HTTPException):
                    cloud_assistant.answer("Help")
        connection = self.provider()
        connection.getresponse.side_effect = TimeoutError()
        with patch.object(cloud_assistant.http.client, "HTTPSConnection", return_value=connection):
            with self.assertRaises(HTTPException):
                cloud_assistant.answer("Help")
        connection.close.assert_called_once()

    def test_route_auth_verification_limits_and_strict_message_only_input(self):
        app = FastAPI()
        secret = "test-session-secret-at-least-32-characters"
        app.include_router(build_router(secret))
        client = TestClient(app)
        path = "/cloud/assistant/chat"
        self.assertEqual(client.post(path, json={"message": "Help"}).status_code, 401)
        account = {"id": uuid4(), "email_verified_at": None}
        with patch.object(cloud_accounts, "authenticate", return_value=account), \
                patch.object(cloud_account_security, "limit") as limit, \
                patch.object(cloud_assistant, "answer", return_value={"reply": "Help"}) as answer:
            self.assertEqual(client.post(path, json={"message": "Help"}).status_code, 403)
            limit.assert_not_called()
            account["email_verified_at"] = "verified"
            for body in (
                {"message": ""}, {"message": " "}, {"message": "x" * 2001},
                {"message": "help", "gateway_id": str(uuid4())},
                {"message": "help", "model": "unrestricted"},
            ):
                self.assertEqual(client.post(path, json=body).status_code, 422)
            answer.assert_not_called()
            self.assertEqual(client.post(path, json={"message": "Help"}).json(), {"reply": "Help"})
            self.assertEqual(limit.call_args_list[0].args, ("assistant:" + str(account["id"]), secret, 10, 60))
            self.assertEqual(limit.call_args_list[1].args, ("assistant:global", secret, 100, 60))
            answer.assert_called_once_with("Help")
            limit.side_effect = HTTPException(429, "Too many requests")
            self.assertEqual(client.post(path, json={"message": "Help"}).status_code, 429)
            self.assertEqual(answer.call_count, 1)


if __name__ == "__main__":
    unittest.main()
