import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as betting_app
from werkzeug.security import check_password_hash, generate_password_hash


class BettingAppTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_admin_password = os.environ.get("GOBET_ADMIN_PASSWORD")
        os.environ["GOBET_ADMIN_PASSWORD"] = "TestAdminPassword123!"
        betting_app.STORE_PATH = Path(self.temp_dir.name) / "users.json"
        self.client = betting_app.app.test_client()
        self.csrf_token = self.client.get("/api/session").get_json()["csrf_token"]

    def tearDown(self):
        self.temp_dir.cleanup()
        if self.previous_admin_password is None:
            os.environ.pop("GOBET_ADMIN_PASSWORD", None)
        else:
            os.environ["GOBET_ADMIN_PASSWORD"] = self.previous_admin_password

    def headers(self):
        return {"X-CSRF-Token": self.csrf_token}

    def login(self, username, password):
        response = self.client.post(
            "/api/login",
            json={"username": username, "password": password},
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.csrf_token = response.get_json()["csrf_token"]
        return response.get_json()["user"]

    def create_user_as_admin(self, username="player"):
        self.login("zero5", "TestAdminPassword123!")
        response = self.client.post(
            "/api/admin/users",
            json={
                "username": username,
                "display_name": "Test Player",
                "password": "StrongPlayerPass123!",
                "currency": "EUR",
                "age_confirmed": True,
            },
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()["user"]

    def test_first_run_creates_only_zero5_as_admin(self):
        self.login("zero5", "TestAdminPassword123!")
        users = self.client.get("/api/admin/users").get_json()["users"]
        self.assertEqual([user["username"] for user in users], ["zero5"])
        self.assertEqual(users[0]["role"], "admin")

    def test_legacy_migration_persists_once_and_preserves_user_history(self):
        store = {
            "users": [
                {
                    "username": "player", "display_name": "Legacy Player",
                    "password_hash": generate_password_hash("Player123!"),
                    "role": "user", "balance": "162.00", "currency": "EUR",
                    "bets": [{"id": "OLD-TICKET", "stake": "88.00", "status": "Open (old)"}],
                },
                {
                    "username": "admin", "display_name": "GObet Admin",
                    "password_hash": generate_password_hash("Admin123!"),
                    "role": "admin", "balance": "1000.00", "currency": "EUR", "bets": [],
                },
            ]
        }
        betting_app.STORE_PATH.write_text(json.dumps(store), encoding="utf-8")
        with patch.object(betting_app.secrets, "token_urlsafe", return_value="MigratedPlayerPassword123!"):
            self.client.get("/api/session")
            migrated = json.loads(betting_app.STORE_PATH.read_text(encoding="utf-8"))
            player = betting_app.find_user(migrated, "player")
            admin = betting_app.find_user(migrated, "zero5")
            self.client.get("/api/session")
            reloaded = json.loads(betting_app.STORE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(migrated["schema_version"], 4)
        self.assertEqual(player["display_name"], "Player")
        self.assertEqual(player["balance"], "162.00")
        self.assertEqual(player["bets"][0]["id"], "OLD-TICKET")
        self.assertEqual(player["bets"][0]["status"], "Open")
        self.assertEqual(migrated["transactions"][0]["reference"], "ticket:OLD-TICKET")
        self.assertTrue(check_password_hash(player["password_hash"], "MigratedPlayerPassword123!"))
        self.assertEqual(admin["role"], "admin")
        self.assertTrue(check_password_hash(admin["password_hash"], "TestAdminPassword123!"))
        self.assertEqual(reloaded["users"][0]["password_hash"], player["password_hash"])

    def test_admin_created_user_can_place_a_bet_and_balance_is_debited(self):
        self.create_user_as_admin()
        self.login("player", "StrongPlayerPass123!")
        response = self.client.post(
            "/api/bets",
            json={"stake": "10", "selections": [{"event_id": "f-101", "market_id": "result", "outcome_key": "home"}]},
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["user"]["balance"], "90.00")
        self.assertEqual(len(self.client.get("/api/bets").get_json()["bets"]), 1)

    def test_admin_can_wager_without_finite_balance_debit(self):
        self.login("zero5", "TestAdminPassword123!")
        response = self.client.post(
            "/api/bets",
            json={"stake": "100000", "selections": [{"event_id": "f-101", "market_id": "result", "outcome_key": "home"}]},
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["user"]["balance"], "UNLIMITED")
        ledger = self.client.get("/api/admin/transactions").get_json()["transactions"]
        self.assertEqual(ledger[0]["type"], "wager")
        self.assertIsNone(ledger[0]["balance_before"])
        all_bets = self.client.get("/api/admin/bets").get_json()["bets"]
        self.assertEqual(all_bets[0]["username"], "zero5")
        actions = [entry["action"] for entry in self.client.get("/api/admin/activity").get_json()["activity"]]
        self.assertIn("wager_placed", actions)

    def test_non_admin_cannot_view_or_change_account_balances(self):
        self.create_user_as_admin()
        self.login("player", "StrongPlayerPass123!")
        self.assertEqual(self.client.get("/api/admin/users").status_code, 403)
        response = self.client.post(
            "/api/admin/balance",
            json={"username": "player", "operation": "add", "amount": "100"},
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 403)
        response = self.client.post(
            "/api/admin/password",
            json={"username": "player", "new_password": "EasyPass88"},
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 403)

    def test_zero5_can_create_regular_accounts_and_adjust_balance(self):
        self.login("zero5", "TestAdminPassword123!")
        created = self.client.post(
            "/api/admin/users",
            json={
                "username": "newuser", "display_name": "New User",
                "password": "StrongNewPass123!", "currency": "ALL", "age_confirmed": True,
            },
            headers=self.headers(),
        )
        self.assertEqual(created.status_code, 201, created.get_json())
        self.assertEqual(created.get_json()["user"]["role"], "user")
        self.assertEqual(created.get_json()["user"]["currency"], "ALL")
        accounts = self.client.get("/api/admin/users").get_json()["users"]
        self.assertEqual(sum(user["role"] == "admin" for user in accounts), 1)
        response = self.client.post(
            "/api/admin/balance",
            json={"username": "newuser", "operation": "add", "amount": "1000005"},
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()["user"]["balance"], "1000105.00")
        response = self.client.post(
            "/api/admin/balance",
            json={"username": "newuser", "operation": "remove", "amount": "1000106"},
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 409)
        reset = self.client.post(
            "/api/admin/password",
            json={"username": "newuser", "new_password": "EasyPass88"},
            headers=self.headers(),
        )
        self.assertEqual(reset.status_code, 200, reset.get_json())
        ledger = self.client.get("/api/admin/transactions").get_json()["transactions"]
        self.assertEqual([entry["type"] for entry in ledger[:2]], ["admin_credit", "account_credit"])
        self.assertEqual(ledger[0]["amount"], "1000005.00")
        self.client.post("/api/logout", json={}, headers=self.headers())
        self.csrf_token = self.client.get("/api/session").get_json()["csrf_token"]
        self.login("newuser", "EasyPass88")

    def test_public_registration_is_disabled(self):
        response = self.client.post(
            "/api/register",
            json={
                "username": "new_user", "display_name": "New Player",
                "password": "StrongPass123!", "currency": "ALL", "age_confirmed": True,
            },
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 403)

    def test_player_cannot_change_password(self):
        self.create_user_as_admin()
        self.login("player", "StrongPlayerPass123!")
        response = self.client.post(
            "/api/password",
            json={"current_password": "StrongPlayerPass123!", "new_password": "OtherPlayerPass123!"},
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 403)

    def test_password_change_requires_current_password(self):
        self.login("zero5", "TestAdminPassword123!")
        response = self.client.post(
            "/api/password",
            json={"current_password": "wrong-password", "new_password": "ChangedAdminPass123!"},
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 403)
        response = self.client.post(
            "/api/password",
            json={"current_password": "TestAdminPassword123!", "new_password": "ChangedAdminPass123!"},
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.csrf_token = response.get_json()["csrf_token"]
        self.client.post("/api/logout", json={}, headers=self.headers())
        self.csrf_token = self.client.get("/api/session").get_json()["csrf_token"]
        self.login("zero5", "ChangedAdminPass123!")


if __name__ == "__main__":
    unittest.main()