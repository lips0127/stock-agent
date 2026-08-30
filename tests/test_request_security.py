from contextlib import contextmanager
import logging
import sqlite3
import unittest
from unittest.mock import patch

from backend.api.app import create_app


@contextmanager
def _healthy_test_connection():
    connection = sqlite3.connect(":memory:")
    try:
        yield connection
    finally:
        connection.close()


class _LogCapture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.INFO)
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())


class RequestSecurityTests(unittest.TestCase):
    CONTROLLED_ORIGIN = "http://localhost:3000"

    def setUp(self):
        with (
            patch("backend.api.app.setup_logging"),
            patch("backend.api.app.init_db"),
            patch("backend.api.middleware.CORS_ORIGINS", self.CONTROLLED_ORIGIN),
        ):
            self.app = create_app(testing=True)
        self.client = self.app.test_client()
        self.capture = _LogCapture()
        self.app_logger = logging.getLogger("backend.api.app")
        self.previous_level = self.app_logger.level
        self.app_logger.setLevel(logging.INFO)
        self.app_logger.addHandler(self.capture)

    def tearDown(self):
        self.app_logger.removeHandler(self.capture)
        self.app_logger.setLevel(self.previous_level)

    def _logs(self) -> str:
        return "\n".join(self.capture.messages)

    @patch("backend.api.routes.auth.authenticate_user", return_value=False)
    def test_login_request_body_is_never_logged(self, _authenticate_user):
        password_sentinel = "PASSWORD_SENTINEL_7c91f63a"
        raw_body = (
            '{"username":"security-test","password":"'
            + password_sentinel
            + '"}'
        )

        response = self.client.post(
            "/api/login",
            data=raw_body,
            content_type="application/json",
            headers={
                "Authorization": "Bearer AUTH_HEADER_SENTINEL",
                "Cookie": "session=COOKIE_SENTINEL",
            },
        )

        self.assertEqual(response.status_code, 401)
        logs = self._logs()
        self.assertNotIn(password_sentinel, logs)
        self.assertNotIn(raw_body, logs)
        self.assertNotIn("AUTH_HEADER_SENTINEL", logs)
        self.assertNotIn("COOKIE_SENTINEL", logs)
        self.assertIn("POST /api/login", logs)
        self.assertIn(f"content_length={len(raw_body.encode('utf-8'))}", logs)

    @patch("backend.api.routes.auth.generate_token", return_value="JWT_RESPONSE_SENTINEL")
    @patch("backend.api.routes.auth.authenticate_user", return_value=True)
    def test_successful_login_token_is_returned_but_never_logged(
        self, _authenticate_user, _generate_token
    ):
        response = self.client.post(
            "/api/login",
            json={"username": "security-test", "password": "valid-password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["token"], "JWT_RESPONSE_SENTINEL")
        self.assertNotIn("JWT_RESPONSE_SENTINEL", self._logs())

    def test_sensitive_query_value_is_redacted_and_safe_value_remains_diagnostic(self):
        token_sentinel = "QUERY_TOKEN_SENTINEL_1a42e2c9"

        with patch(
            "backend.api.routes.ops.get_connection",
            side_effect=_healthy_test_connection,
        ):
            response = self.client.get(
                "/health",
                query_string={"token": token_sentinel, "code": "600000"},
            )

        self.assertEqual(response.status_code, 200)
        logs = self._logs()
        self.assertNotIn(token_sentinel, logs)
        self.assertIn("[REDACTED]", logs)
        self.assertIn("600000", logs)

    def test_cors_preflight_allows_patch_delete_and_auth_headers(self):
        for method in ("PATCH", "DELETE"):
            with self.subTest(method=method):
                response = self.client.options(
                    "/health",
                    headers={
                        "Origin": self.CONTROLLED_ORIGIN,
                        "Access-Control-Request-Method": method,
                        "Access-Control-Request-Headers": "Authorization, Content-Type",
                    },
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.headers.get("Access-Control-Allow-Origin"),
                    self.CONTROLLED_ORIGIN,
                )
                allowed_methods = {
                    value.strip()
                    for value in response.headers.get(
                        "Access-Control-Allow-Methods", ""
                    ).split(",")
                }
                self.assertIn(method, allowed_methods)
                allowed_headers = {
                    value.strip().lower()
                    for value in response.headers.get(
                        "Access-Control-Allow-Headers", ""
                    ).split(",")
                }
                self.assertIn("authorization", allowed_headers)
                self.assertIn("content-type", allowed_headers)


if __name__ == "__main__":
    unittest.main()
