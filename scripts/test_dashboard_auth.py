import http.client
import json
import os
import tempfile
import unittest
from pathlib import Path
from threading import Thread
from unittest.mock import patch

import dashboard
import dashboard_auth

RECOVERY_PASSWORD = "r" * 24


class AuthStoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.patches = [
            patch.object(dashboard_auth.innovation, "STATE", Path(self.directory.name)),
            patch.object(dashboard_auth, "PBKDF2_ITERATIONS", 1000),
            patch.dict(os.environ, {"AES_DASHBOARD_USER": "aes", "AES_DASHBOARD_PASSWORD": RECOVERY_PASSWORD}),
        ]
        for item in self.patches:
            item.start()
        dashboard_auth._failures.clear()
        dashboard_auth._sessions.clear()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()

    def test_passwords_are_hashed_and_verified(self):
        stored = dashboard_auth.hash_password("correct horse battery")
        self.assertNotIn("correct horse battery", stored)
        self.assertTrue(dashboard_auth.verify_password("correct horse battery", stored))
        self.assertFalse(dashboard_auth.verify_password("wrong", stored))
        self.assertFalse(dashboard_auth.verify_password("x", "garbage"))

    def test_user_lifecycle_requires_password_change_and_stores_no_plaintext(self):
        temp = dashboard_auth.create_user("Maria.Silva", "member", "aes")
        raw = dashboard_auth.users_path().read_text(encoding="utf-8")
        self.assertNotIn(temp, raw)
        user = dashboard_auth.authenticate("maria.silva", temp, "1.2.3.4")
        self.assertTrue(user["must_change"])
        with self.assertRaises(dashboard_auth.AuthError):
            dashboard_auth.change_password("maria.silva", temp, "short")
        dashboard_auth.change_password("maria.silva", temp, "a much longer passphrase")
        self.assertFalse(dashboard_auth.authenticate("maria.silva", "a much longer passphrase", "1.2.3.4")["must_change"])
        new_temp = dashboard_auth.reset_password("maria.silva", "aes")
        with self.assertRaises(dashboard_auth.AuthError):
            dashboard_auth.authenticate("maria.silva", "a much longer passphrase", "1.2.3.4")
        self.assertTrue(dashboard_auth.authenticate("maria.silva", new_temp, "1.2.3.4")["must_change"])
        dashboard_auth.delete_user("maria.silva", "aes")
        self.assertEqual([u["username"] for u in dashboard_auth.list_users()], ["aes"])

    def test_invalid_names_duplicates_and_recovery_account_are_rejected(self):
        for name in ("a", "has space", "aes", "x" * 40):
            with self.assertRaises(dashboard_auth.AuthError):
                dashboard_auth.create_user(name, "member", "aes")
        dashboard_auth.create_user("joao", "admin", "aes")
        with self.assertRaises(dashboard_auth.AuthError):
            dashboard_auth.create_user("joao", "member", "aes")
        with self.assertRaises(dashboard_auth.AuthError):
            dashboard_auth.create_user("ana", "owner", "aes")
        with self.assertRaises(dashboard_auth.AuthError):
            dashboard_auth.change_password("aes", RECOVERY_PASSWORD, "another long password")
        with self.assertRaises(dashboard_auth.AuthError):
            dashboard_auth.delete_user("joao", "joao")

    def test_recovery_account_always_authenticates_as_admin(self):
        user = dashboard_auth.authenticate("aes", RECOVERY_PASSWORD, "1.2.3.4")
        self.assertEqual((user["role"], user["builtin"]), ("admin", True))

    def test_repeated_failures_lock_the_account(self):
        temp = dashboard_auth.create_user("ana", "member", "aes")
        for _ in range(dashboard_auth.MAX_FAILURES):
            with self.assertRaises(dashboard_auth.AuthError):
                dashboard_auth.authenticate("ana", "wrong password", "9.9.9.9")
        with self.assertRaisesRegex(dashboard_auth.AuthError, "Muitas tentativas"):
            dashboard_auth.authenticate("ana", temp, "8.8.8.8")

    def test_sessions_follow_deletion_and_reset(self):
        dashboard_auth.create_user("ana", "member", "aes")
        token = dashboard_auth.create_session("ana")
        self.assertEqual(dashboard_auth.session_user(token)["username"], "ana")
        dashboard_auth.reset_password("ana", "aes")
        self.assertIsNone(dashboard_auth.session_user(token))
        token = dashboard_auth.create_session("ana")
        dashboard_auth.delete_user("ana", "aes")
        self.assertIsNone(dashboard_auth.session_user(token))

    def test_cli_creates_and_resets_users(self):
        with patch("builtins.print") as out:
            self.assertEqual(dashboard_auth.cli(["add", "ops", "--admin"]), 0)
            self.assertEqual(dashboard_auth.cli(["reset", "ops"]), 0)
            self.assertEqual(dashboard_auth.cli(["reset", "missing"]), 2)
        self.assertIn("Senha temporária", out.call_args_list[0].args[0])
        self.assertEqual(dashboard_auth.load_users()["ops"]["role"], "admin")


class AuthHttpTests(AuthStoreTests):
    def setUp(self):
        super().setUp()
        self.server = dashboard.ThreadingHTTPServer(("127.0.0.1", 0), dashboard.DashboardHandler)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        super().tearDown()

    def call(self, method, path, body=None, cookie=None):
        host, port = self.server.server_address
        conn = http.client.HTTPConnection(host, port, timeout=5)
        headers = {"Content-Type": "application/json"} if body is not None else {}
        if cookie:
            headers["Cookie"] = cookie
        conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        response = conn.getresponse()
        raw = response.read()
        conn.close()
        set_cookie = response.getheader("Set-Cookie") or ""
        data = json.loads(raw) if response.getheader("Content-Type", "").startswith("application/json") else raw
        return response.status, data, set_cookie.split(";")[0], response

    def login(self, username, password):
        status, data, cookie, response = self.call("POST", "/api/login", {"username": username, "password": password})
        return status, data, cookie, response.getheader("Set-Cookie") or ""

    def test_full_session_flow(self):
        status, _, _, response = self.call("GET", "/")
        self.assertEqual((status, response.getheader("Location")), (303, "/login"))
        self.assertEqual(self.call("GET", "/login")[0], 200)
        self.assertEqual(self.login("aes", "wrong")[0], 401)

        status, me, admin, raw_cookie = self.login("aes", RECOVERY_PASSWORD)
        self.assertEqual((status, me["role"]), (200, "admin"))
        for flag in ("HttpOnly", "Secure", "SameSite=Strict"):
            self.assertIn(flag, raw_cookie)
        self.assertEqual(self.call("GET", "/", cookie=admin)[0], 200)

        status, created, _, _ = self.call("POST", "/api/users/create", {"username": "ana", "role": "member"}, admin)
        self.assertEqual(status, 201)
        status, _, member, _ = self.login("ana", created["password"])
        self.assertEqual(status, 200)
        status, data, _, _ = self.call("GET", "/api/status", cookie=member)
        self.assertEqual((status, data["error"]), (403, "password change required"))
        self.assertEqual(self.call("POST", "/api/password",
                                   {"current": created["password"], "new": "ana's long passphrase"}, member)[0], 200)
        self.assertEqual(self.call("GET", "/api/status", cookie=member)[0], 200)
        self.assertEqual(self.call("GET", "/api/users", cookie=member)[0], 403)
        self.assertEqual(self.call("POST", "/api/users/create", {"username": "eve", "role": "admin"}, member)[0], 403)

        self.assertEqual(self.call("POST", "/api/logout", {}, member)[0], 200)
        self.assertEqual(self.call("GET", "/api/status", cookie=member)[0], 401)
        users = self.call("GET", "/api/users", cookie=admin)[1]["users"]
        self.assertEqual([u["username"] for u in users], ["aes", "ana"])


if __name__ == "__main__":
    unittest.main()
