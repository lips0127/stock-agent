import unittest
from unittest.mock import patch

from flask import Flask

from backend.api import middleware
from backend.api.middleware import generate_token
from backend.api.routes.market import market_bp


class MarketAuthTests(unittest.TestCase):
    ROUTES = (
        "/api/indices",
        "/api/indices/live",
        "/api/top_stocks",
        "/api/all_stocks",
    )
    RATE_LIMITED_ROUTES = (
        "/api/top_stocks",
        "/api/all_stocks",
    )

    def setUp(self):
        app = Flask(__name__)
        app.config["TESTING"] = True
        app.register_blueprint(market_bp)
        self.client = app.test_client()
        middleware._request_times.clear()

    def tearDown(self):
        middleware._request_times.clear()

    def test_market_routes_require_bearer_token(self):
        for route in self.ROUTES:
            with self.subTest(route=route):
                response = self.client.get(route)

                self.assertEqual(response.status_code, 401)
                self.assertEqual(
                    response.get_json(),
                    {"error": "Missing or invalid token"},
                )

    @patch.object(middleware, "RATE_LIMIT_PER_MINUTE", 0)
    def test_auth_runs_before_rate_limit(self):
        for route in self.RATE_LIMITED_ROUTES:
            with self.subTest(route=route):
                middleware._request_times.clear()
                response = self.client.get(route)

                self.assertEqual(response.status_code, 401)

    @patch.object(middleware, "RATE_LIMIT_PER_MINUTE", 0)
    def test_authenticated_requests_still_use_rate_limit(self):
        token = generate_token("test_user")
        headers = {"Authorization": f"Bearer {token}"}

        for route in self.RATE_LIMITED_ROUTES:
            with self.subTest(route=route):
                middleware._request_times.clear()
                response = self.client.get(route, headers=headers)

                self.assertEqual(response.status_code, 429)
                self.assertEqual(
                    response.get_json(),
                    {"error": "Rate limit exceeded"},
                )


if __name__ == "__main__":
    unittest.main()
