import secrets
import tempfile
import traceback
import unittest
from pathlib import Path

from huicode.server.config import ServerConfigError, load_server_settings


class ServerSettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = {
            "HUICODE_DATABASE_URL": "postgresql+asyncpg://user:private-db-password@localhost/studio",
            "HUICODE_REDIS_URL": "redis://:private-redis-password@localhost:6379/0",
            "HUICODE_JWT_SECRET": secrets.token_urlsafe(32),
            "HUICODE_PROJECT_ROOT": self.directory.name,
        }

    def test_valid_modes_and_no_secret_in_repr(self):
        for mode in ("development", "test", "production"):
            config = load_server_settings({**self.env, "HUICODE_SERVER_ENV": mode})
            self.assertEqual(config.environment, mode)
            self.assertEqual(config.project_root, Path(self.directory.name).resolve())
            self.assertEqual(config.limits.max_run_seconds, 1800)
            for key in ("HUICODE_DATABASE_URL", "HUICODE_REDIS_URL", "HUICODE_JWT_SECRET"):
                self.assertNotIn(self.env[key], repr(config))

    def test_missing_required_fields_fail_in_all_modes(self):
        for mode in ("development", "test", "production"):
            for name in self.env:
                env = {**self.env, "HUICODE_SERVER_ENV": mode}
                del env[name]
                with self.subTest(mode=mode, name=name), self.assertRaisesRegex(ServerConfigError, name):
                    load_server_settings(env)

    def test_malformed_urls_never_leak_in_traceback(self):
        for name, value in (
            ("HUICODE_DATABASE_URL", "postgresql+asyncpg://user:private-secret@localhost:private-port/db"),
            ("HUICODE_REDIS_URL", "redis://[private-secret"),
            ("HUICODE_DATABASE_URL", "sqlite:///private-secret"),
        ):
            with self.subTest(name=name):
                try:
                    load_server_settings({**self.env, name: value})
                except ServerConfigError:
                    self.assertNotIn("private-secret", traceback.format_exc())
                    self.assertNotIn("private-port", traceback.format_exc())
                else:
                    self.fail("无效 URL 应被拒绝")

    def test_weak_secret_rejected(self):
        for value in ("short", "a" * 64):
            with self.assertRaisesRegex(ServerConfigError, "HUICODE_JWT_SECRET"):
                load_server_settings({**self.env, "HUICODE_JWT_SECRET": value})

    def test_project_directory_boundary(self):
        for value in ("relative", str(Path(self.directory.name) / "missing"), Path(self.directory.name).anchor):
            with self.subTest(value=value), self.assertRaisesRegex(ServerConfigError, "HUICODE_PROJECT_ROOT"):
                load_server_settings({**self.env, "HUICODE_PROJECT_ROOT": value})

    def test_limits_validate_numbers_and_order(self):
        for value in ("0", "-1", "1.5", "secret-limit", "9" * 20):
            with self.assertRaisesRegex(ServerConfigError, "HUICODE_MAX_ITERATIONS"):
                load_server_settings({**self.env, "HUICODE_MAX_ITERATIONS": value})
        with self.assertRaisesRegex(ServerConfigError, "时限"):
            load_server_settings({**self.env, "HUICODE_MAX_RUN_SECONDS": "1"})
        config = load_server_settings({**self.env, "HUICODE_MAX_ITERATIONS": "7"})
        self.assertEqual(config.limits.max_iterations, 7)

    def test_cors_rejects_wildcards_credentials_paths_and_http_in_production(self):
        for value in ("*", "https://*.example.com", "https://user:secret@example.com", "https://example.com/path", "http://example.com"):
            # 子域通配符也不是浏览器 Origin。
            with self.subTest(value=value), self.assertRaises(ServerConfigError):
                load_server_settings({**self.env, "HUICODE_SERVER_ENV": "production", "HUICODE_CORS_ORIGINS": value})

    def test_cors_deduplicates(self):
        config = load_server_settings({**self.env, "HUICODE_CORS_ORIGINS": "http://localhost:5173, http://localhost:5173"})
        self.assertEqual(config.cors_origins, ("http://localhost:5173",))

    def test_invalid_environment_and_log_level(self):
        for key in ("HUICODE_SERVER_ENV", "HUICODE_LOG_LEVEL"):
            with self.assertRaisesRegex(ServerConfigError, key):
                load_server_settings({**self.env, key: "invalid"})
