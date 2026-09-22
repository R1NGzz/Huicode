import secrets
import tempfile
import unittest

from fastapi.testclient import TestClient

from huicode.server.app import create_app
from huicode.server.config import load_server_settings


class FakeHealth:
    def __init__(self, settings):
        self.opened = False
        self.closed = False
        self.dependencies = {"database": "ok", "redis": "ok"}

    async def open(self):
        self.opened = True

    async def close(self):
        self.closed = True

    async def check(self):
        return self.dependencies


class AppTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = load_server_settings({
            "HUICODE_DATABASE_URL": "postgresql+asyncpg://demo:demo@localhost/demo",
            "HUICODE_REDIS_URL": "redis://localhost/0",
            "HUICODE_JWT_SECRET": secrets.token_urlsafe(32),
            "HUICODE_PROJECT_ROOT": directory.name,
            "HUICODE_CORS_ORIGINS": "http://localhost:5173",
        })
        self.app = create_app(settings, health_factory=FakeHealth)

    def test_lifespan_and_live_request_id(self):
        with TestClient(self.app) as client:
            self.assertTrue(self.app.state.health.opened)
            response = client.get("/health/live")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["request_id"], response.headers["x-request-id"])
        self.assertTrue(self.app.state.health.closed)

    def test_dependency_outage_only_affects_readiness(self):
        with TestClient(self.app) as client:
            self.assertEqual(client.get("/health/ready").status_code, 200)
            for dependency in ("database", "redis"):
                self.app.state.health.dependencies = {"database": "ok", "redis": "ok", dependency: "unavailable"}
                response = client.get("/health/ready")
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.json()["dependencies"][dependency], "unavailable")
                self.assertEqual(client.get("/health/live").status_code, 200)

    def test_unknown_route_and_validation_share_error_envelope(self):
        @self.app.get("/typed")
        async def typed(count: int):
            return {"count": count}

        with TestClient(self.app) as client:
            for url, status in (("/missing", 404), ("/typed?count=secret-input", 422)):
                response = client.get(url)
                self.assertEqual(response.status_code, status)
                self.assertIn("error", response.json())
                self.assertEqual(response.json()["request_id"], response.headers["x-request-id"])
                self.assertNotIn("secret-input", response.text)

    def test_unexpected_error_is_redacted_and_logged(self):
        @self.app.get("/broken")
        async def broken():
            raise ValueError("private-exception-secret")

        with TestClient(self.app) as client, self.assertLogs("huicode.server.requests", level="INFO") as logs:
            response = client.get("/broken?token=private-query-secret")
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["error"]["code"], "internal_error")
        joined = response.text + "".join(logs.output)
        self.assertNotIn("private-exception-secret", joined)
        self.assertNotIn("private-query-secret", joined)
        self.assertIn(response.headers["x-request-id"], "".join(logs.output))

    def test_cors_and_server_generated_request_ids(self):
        with TestClient(self.app) as client:
            response = client.get("/health/live", headers={"Origin": "http://localhost:5173", "X-Request-ID": "untrusted"})
            self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:5173")
            self.assertNotEqual(response.headers["x-request-id"], "untrusted")
            response = client.get("/health/live", headers={"Origin": "http://untrusted.test"})
            self.assertNotIn("access-control-allow-origin", response.headers)
