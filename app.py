import hmac
import json
import os
import re
import secrets
import threading
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory, session
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
STORE_PATH = Path(os.environ.get("GOBET_USERS_FILE", BASE_DIR / "data" / "users.json"))
STORE_LOCK = threading.Lock()
CENT = Decimal("0.01")

SPORTS = ["Football", "Basketball", "Tennis", "Volleyball", "Cricket"]


def market(market_id, label, outcomes):
    return {
        "id": market_id,
        "label": label,
        "outcomes": [
            {"key": key, "label": name, "odds": odds}
            for key, name, odds in outcomes
        ],
    }


EVENTS = [
    {
        "id": "f-101", "sport": "Football", "league": "Premier League",
        "home": "Arsenal", "away": "Liverpool", "time": "19:45",
        "markets": [
            market("result", "Match result", [("home", "Arsenal", 2.25), ("draw", "Draw", 3.35), ("away", "Liverpool", 2.90)]),
            market("goals", "Total goals 2.5", [("over", "Over", 1.82), ("under", "Under", 1.98)]),
            market("btts", "Both teams to score", [("yes", "Yes", 1.72), ("no", "No", 2.08)]),
        ],
    },
    {
        "id": "f-102", "sport": "Football", "league": "La Liga",
        "home": "Real Madrid", "away": "Barcelona", "time": "20:00",
        "markets": [
            market("result", "Match result", [("home", "Real Madrid", 2.05), ("draw", "Draw", 3.55), ("away", "Barcelona", 3.10)]),
            market("goals", "Total goals 2.5", [("over", "Over", 1.76), ("under", "Under", 2.02)]),
            market("btts", "Both teams to score", [("yes", "Yes", 1.66), ("no", "No", 2.18)]),
        ],
    },
    {
        "id": "f-103", "sport": "Football", "league": "Serie A",
        "home": "Inter", "away": "AC Milan", "time": "20:30",
        "markets": [
            market("result", "Match result", [("home", "Inter", 1.94), ("draw", "Draw", 3.25), ("away", "AC Milan", 3.65)]),
            market("goals", "Total goals 2.5", [("over", "Over", 1.91), ("under", "Under", 1.88)]),
            market("btts", "Both teams to score", [("yes", "Yes", 1.79), ("no", "No", 1.98)]),
        ],
    },
    {
        "id": "b-201", "sport": "Basketball", "league": "EuroLeague",
        "home": "Real Madrid", "away": "Olympiacos", "time": "18:30",
        "markets": [market("winner", "Match winner", [("home", "Real Madrid", 1.78), ("away", "Olympiacos", 2.02)])],
    },
    {
        "id": "t-301", "sport": "Tennis", "league": "ATP Tour",
        "home": "J. Sinner", "away": "C. Alcaraz", "time": "16:00",
        "markets": [market("winner", "Match winner", [("home", "J. Sinner", 1.90), ("away", "C. Alcaraz", 1.90)])],
    },
    {
        "id": "v-401", "sport": "Volleyball", "league": "CEV Champions League",
        "home": "Trentino", "away": "ZAKSA", "time": "19:00",
        "markets": [market("winner", "Match winner", [("home", "Trentino", 1.67), ("away", "ZAKSA", 2.16)])],
    },
    {
        "id": "c-501", "sport": "Cricket", "league": "T20 International",
        "home": "India", "away": "Australia", "time": "14:00",
        "markets": [market("winner", "Match winner", [("home", "India", 1.85), ("away", "Australia", 1.95)])],
    },
]

app = Flask(__name__)
app.secret_key = os.environ.get("GOBET_SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("GOBET_COOKIE_SECURE", "0").lower() in {"1", "true", "yes"},
    PERMANENT_SESSION_LIFETIME=60 * 60 * 12,
)


def money(value):
    try:
        amount = Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Enter a valid amount.") from None
    if not amount.is_finite():
        raise ValueError("Enter a valid amount.")
    return amount


def save_store(store):
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = STORE_PATH.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(store, indent=2), encoding="utf-8")
    temporary_path.replace(STORE_PATH)


def new_admin_password():
    configured_password = os.environ.get("GOBET_ADMIN_PASSWORD")
    if configured_password:
        if len(configured_password) < 12:
            raise RuntimeError("GOBET_ADMIN_PASSWORD must be at least 12 characters.")
        return configured_password, False
    return secrets.token_urlsafe(18), True


def create_user(username, display_name, password, currency, balance="100.00", role="user"):
    return {
        "username": username,
        "display_name": display_name,
        "password_hash": generate_password_hash(password),
        "role": role,
        "balance": balance,
        "currency": currency,
        "bets": [],
    }


def record_transaction(store, transaction_type, amount, currency, actor, username, balance_before, balance_after, reference, note):
    entry = {
        "id": secrets.token_hex(6).upper(),
        "occurred_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "type": transaction_type,
        "amount": str(money(amount)),
        "currency": currency,
        "actor": actor,
        "username": username,
        "balance_before": str(balance_before) if balance_before is not None else None,
        "balance_after": str(balance_after) if balance_after is not None else None,
        "reference": reference,
        "note": note,
    }
    store.setdefault("transactions", []).insert(0, entry)
    return entry


def record_audit(store, actor, action, target=None, details=None):
    entry = {
        "id": secrets.token_hex(6).upper(),
        "occurred_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "actor": actor,
        "action": action,
        "target": target,
        "details": details or {},
    }
    store.setdefault("audit_log", []).insert(0, entry)
    return entry


def normalize_store(store):
    if store.get("schema_version") == 4:
        return store
    users = store.setdefault("users", [])
    store.setdefault("transactions", [])
    store.setdefault("audit_log", [])
    admin = find_user(store, "zero5")
    old_admin = find_user(store, "admin")
    generated_password = None
    should_print_password = False

    if not admin:
        generated_password, should_print_password = new_admin_password()
        if old_admin:
            old_admin["username"] = "zero5"
            old_admin["display_name"] = "Zero5 Admin"
            old_admin["password_hash"] = generate_password_hash(generated_password)
            admin = old_admin
        else:
            admin = create_user("zero5", "Zero5 Admin", generated_password, "EUR", "0.00", "admin")
            users.append(admin)

    admin["role"] = "admin"
    if admin["display_name"] == "GObet Admin":
        admin["display_name"] = "Zero5 Admin"

    for user in users:
        if user is not admin and user.get("role") == "admin":
            user["role"] = "user"
        if user.get("username") == "player" and user.get("display_name") != "Player":
            user["display_name"] = "Player"
        if user.get("username") == "player" and check_password_hash(user["password_hash"], "Player123!"):
            temporary_password = secrets.token_urlsafe(18)
            user["password_hash"] = generate_password_hash(temporary_password)
            print(f"Migrated player login: player / {temporary_password}", flush=True)
        for ticket in user.get("bets", []):
            if isinstance(ticket.get("status"), str) and ticket["status"].casefold().startswith("open"):
                ticket["status"] = "Open"
            reference = f"ticket:{ticket.get('id', '')}"
            if ticket.get("id") and not any(entry.get("reference") == reference for entry in store["transactions"]):
                record_transaction(
                    store, "wager", ticket.get("stake", "0"), ticket.get("currency", user["currency"]),
                    user["username"], user["username"], None, None, reference,
                    "Imported historical ticket; balance was already applied.",
                )

    record_audit(store, "system", "account_store_migrated", details={"schema_version": 4})
    store["schema_version"] = 4
    if should_print_password:
        print(f"Initial admin login: zero5 / {generated_password}", flush=True)
    return store


def load_store():
    if not STORE_PATH.exists():
        store = normalize_store({"users": []})
        save_store(store)
        return store
    store = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    if store.get("schema_version") != 4:
        store = normalize_store(store)
        save_store(store)
    return store


def public_user(user):
    return {
        "username": user["username"],
        "display_name": user["display_name"],
        "role": user["role"],
        "balance": "UNLIMITED" if user["username"] == "zero5" else user["balance"],
        "currency": user["currency"],
    }


def find_user(store, username):
    return next((user for user in store["users"] if user["username"] == username), None)


def current_user():
    username = session.get("username")
    if not username:
        return None
    with STORE_LOCK:
        user = find_user(load_store(), username)
        return public_user(user) if user else None


def validate_account_fields(body):
    username = str(body.get("username", "")).strip().lower()
    display_name = str(body.get("display_name", "")).strip()
    password = str(body.get("password", ""))
    currency = str(body.get("currency", "EUR")).upper()
    if not re.fullmatch(r"[a-z0-9_]{3,20}", username):
        return None, "Username must be 3-20 characters: letters, numbers, or underscores."
    if username in {"admin", "zero5"}:
        return None, "That username is reserved."
    if not 2 <= len(display_name) <= 30:
        return None, "Display name must be 2-30 characters."
    if not 8 <= len(password) <= 128:
        return None, "Password must contain 8-128 characters."
    if currency not in {"EUR", "ALL"}:
        return None, "Choose EUR or ALL."
    return (username, display_name, password, currency), None


def error(message, status=400):
    return jsonify({"error": message}), status


@app.before_request
def protect_api_posts():
    if request.path.startswith("/api/") and request.method == "POST":
        expected = session.get("csrf_token", "")
        supplied = request.headers.get("X-CSRF-Token", "")
        if not expected or not hmac.compare_digest(expected, supplied):
            return error("Your session expired. Refresh and try again.", 403)


@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    if request.path.startswith("/api/") or request.path in {"/", "/style.css", "/app.js"}:
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/style.css")
def stylesheet():
    return send_from_directory(BASE_DIR, "style.css")


@app.get("/app.js")
def javascript():
    return send_from_directory(BASE_DIR, "app.js")


@app.get("/api/session")
def session_info():
    with STORE_LOCK:
        load_store()
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return jsonify({"csrf_token": session["csrf_token"], "user": current_user()})


@app.post("/api/login")
def login():
    body = request.get_json(silent=True) or {}
    username = str(body.get("username", "")).strip().lower()
    password = str(body.get("password", ""))
    with STORE_LOCK:
        store = load_store()
        user = find_user(store, username)
        if not user or not check_password_hash(user["password_hash"], password):
            record_audit(store, username or "unknown", "login_failed")
            save_store(store)
            return error("That username and password do not match.", 401)
        record_audit(store, username, "login_succeeded")
        save_store(store)
        session.clear()
        session.permanent = True
        session["username"] = user["username"]
        session["csrf_token"] = secrets.token_urlsafe(32)
        return jsonify({"user": public_user(user), "csrf_token": session["csrf_token"]})


@app.post("/api/register")
def register():
    return error("Accounts can only be created by zero5.", 403)


@app.post("/api/password")
def change_password():
    username = session.get("username")
    if not username:
        return error("Sign in to change your password.", 401)
    if username != "zero5":
        return error("Only zero5 can change a password.", 403)
    body = request.get_json(silent=True) or {}
    current_password = str(body.get("current_password", ""))
    new_password = str(body.get("new_password", ""))
    if not 8 <= len(new_password) <= 128:
        return error("New password must contain 8-128 characters.")
    with STORE_LOCK:
        store = load_store()
        user = find_user(store, username)
        if not user or not check_password_hash(user["password_hash"], current_password):
            return error("Your current password is incorrect.", 403)
        user["password_hash"] = generate_password_hash(new_password)
        record_audit(store, username, "password_changed", username)
        save_store(store)
    session["csrf_token"] = secrets.token_urlsafe(32)
    return jsonify({"ok": True, "csrf_token": session["csrf_token"]})


@app.post("/api/logout")
def logout():
    username = session.get("username")
    if username:
        with STORE_LOCK:
            store = load_store()
            record_audit(store, username, "logout")
            save_store(store)
    session.clear()
    return jsonify({"ok": True})


@app.get("/api/events")
def events():
    selected_sport = request.args.get("sport", "All")
    if selected_sport not in {"All", *SPORTS}:
        return error("Unknown sport.")
    filtered = EVENTS if selected_sport == "All" else [event for event in EVENTS if event["sport"] == selected_sport]
    return jsonify({"sports": SPORTS, "events": filtered})


@app.get("/api/bets")
def bet_history():
    user = current_user()
    if not user:
        return error("Sign in to view your tickets.", 401)
    with STORE_LOCK:
        stored = find_user(load_store(), user["username"])
        return jsonify({"bets": stored["bets"]})


@app.post("/api/bets")
def place_bet():
    username = session.get("username")
    if not username:
        return error("Sign in before placing a simulated bet.", 401)
    body = request.get_json(silent=True) or {}
    selections = body.get("selections")
    if not isinstance(selections, list) or not 1 <= len(selections) <= 8:
        return error("Choose between 1 and 8 selections.")
    try:
        stake = money(body.get("stake"))
    except ValueError as exc:
        return error(str(exc))
    if stake <= 0 or stake > Decimal("100000"):
        return error("Stake must be greater than zero and no more than 100,000.")

    verified = []
    seen = set()
    combined_odds = Decimal("1")
    for selection in selections:
        if not isinstance(selection, dict):
            return error("One of your selections is invalid.")
        event = next((item for item in EVENTS if item["id"] == selection.get("event_id")), None)
        market_data = next((item for item in event["markets"] if item["id"] == selection.get("market_id")), None) if event else None
        outcome = next((item for item in market_data["outcomes"] if item["key"] == selection.get("outcome_key")), None) if market_data else None
        if not event or not market_data or not outcome:
            return error("One of your selections is no longer available. Refresh the markets.", 409)
        unique_key = (event["id"], market_data["id"])
        if unique_key in seen:
            return error("Choose only one outcome for each match market.")
        seen.add(unique_key)
        combined_odds *= Decimal(str(outcome["odds"]))
        verified.append({
            "event_id": event["id"], "sport": event["sport"], "league": event["league"],
            "match": f"{event['home']} vs {event['away']}", "market": market_data["label"],
            "selection": outcome["label"], "odds": outcome["odds"],
        })

    potential_return = (stake * combined_odds).quantize(CENT, rounding=ROUND_HALF_UP)
    with STORE_LOCK:
        store = load_store()
        user = find_user(store, username)
        balance = money(user["balance"])
        is_admin = user["username"] == "zero5"
        if not is_admin and stake > balance:
            return error("Your balance is too low for that stake.", 409)
        updated_balance = balance if is_admin else balance - stake
        if not is_admin:
            user["balance"] = str(updated_balance)
        ticket = {
            "id": secrets.token_hex(4).upper(),
            "placed_at": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "status": "Open",
            "stake": str(stake),
            "combined_odds": float(combined_odds.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)),
            "potential_return": str(potential_return),
            "currency": user["currency"],
            "selections": verified,
        }
        user["bets"].insert(0, ticket)
        record_transaction(
            store, "wager", stake, user["currency"], username, username,
            None if is_admin else balance, None if is_admin else updated_balance,
            f"ticket:{ticket['id']}", "Virtual wager placed.",
        )
        record_audit(store, username, "wager_placed", username, {"ticket_id": ticket["id"], "stake": str(stake)})
        save_store(store)
    return jsonify({"ticket": ticket, "user": public_user(user)}), 201


@app.get("/api/admin/users")
def admin_users():
    user = current_user()
    if not user:
        return error("Sign in to continue.", 401)
    if user["username"] != "zero5" or user["role"] != "admin":
        return error("Admin access is required.", 403)
    with STORE_LOCK:
        store = load_store()
        users = [
            {**public_user(item), "ticket_count": len(item["bets"])}
            for item in store["users"]
        ]
    return jsonify({"users": users})


def require_zero5():
    user = current_user()
    if not user:
        return None, error("Sign in to continue.", 401)
    if user["username"] != "zero5" or user["role"] != "admin":
        return None, error("Admin access is required.", 403)
    return user, None


@app.get("/api/admin/bets")
def admin_bets():
    admin, denied = require_zero5()
    if denied:
        return denied
    with STORE_LOCK:
        store = load_store()
        bets = [
            {**ticket, "username": user["username"], "display_name": user["display_name"]}
            for user in store["users"]
            for ticket in user.get("bets", [])
        ]
    bets.sort(key=lambda ticket: ticket.get("placed_at", ""), reverse=True)
    return jsonify({"bets": bets})


@app.get("/api/admin/transactions")
def admin_transactions():
    admin, denied = require_zero5()
    if denied:
        return denied
    with STORE_LOCK:
        store = load_store()
        return jsonify({"transactions": store.get("transactions", [])})


@app.get("/api/admin/activity")
def admin_activity():
    admin, denied = require_zero5()
    if denied:
        return denied
    with STORE_LOCK:
        store = load_store()
        return jsonify({"activity": store.get("audit_log", [])})


@app.post("/api/admin/users")
def admin_create_user():
    admin = current_user()
    if not admin:
        return error("Sign in to continue.", 401)
    if admin["username"] != "zero5" or admin["role"] != "admin":
        return error("Admin access is required.", 403)
    body = request.get_json(silent=True) or {}
    fields, message = validate_account_fields(body)
    if message:
        return error(message)
    if body.get("age_confirmed") is not True:
        return error("Confirm that this person meets the legal age requirement.")
    username, display_name, password, currency = fields
    with STORE_LOCK:
        store = load_store()
        if find_user(store, username):
            return error("That username is already taken.", 409)
        user = create_user(username, display_name, password, currency)
        store["users"].append(user)
        record_transaction(store, "account_credit", user["balance"], currency, admin["username"], username, "0.00", user["balance"], f"account:{username}", "Initial virtual credits.")
        record_audit(store, admin["username"], "account_created", username, {"currency": currency})
        save_store(store)
    return jsonify({"user": public_user(user)}), 201


@app.post("/api/admin/password")
def admin_reset_password():
    admin = current_user()
    if not admin:
        return error("Sign in to continue.", 401)
    if admin["username"] != "zero5" or admin["role"] != "admin":
        return error("Only zero5 can reset account passwords.", 403)
    body = request.get_json(silent=True) or {}
    target_username = str(body.get("username", "")).strip().lower()
    new_password = str(body.get("new_password", ""))
    if target_username == "zero5":
        return error("Use My Account to change the zero5 password.")
    if not 8 <= len(new_password) <= 128:
        return error("Password must contain 8-128 characters.")
    with STORE_LOCK:
        store = load_store()
        target = find_user(store, target_username)
        if not target:
            return error("User not found.", 404)
        if target["role"] == "admin":
            return error("zero5 is the only administrator.", 403)
        target["password_hash"] = generate_password_hash(new_password)
        record_audit(store, admin["username"], "password_reset", target_username)
        save_store(store)
    return jsonify({"username": target_username, "ok": True})


@app.post("/api/admin/balance")
def adjust_balance():
    admin = current_user()
    if not admin:
        return error("Sign in to continue.", 401)
    if admin["username"] != "zero5" or admin["role"] != "admin":
        return error("Admin access is required.", 403)
    body = request.get_json(silent=True) or {}
    target_username = str(body.get("username", "")).strip().lower()
    operation = body.get("operation")
    try:
        amount = money(body.get("amount"))
    except ValueError as exc:
        return error(str(exc))
    if operation not in {"add", "remove"} or amount <= 0:
        return error("Enter a valid adjustment amount.")
    with STORE_LOCK:
        store = load_store()
        target = find_user(store, target_username)
        if not target:
            return error("User not found.", 404)
        if target_username == "zero5":
            return error("zero5 has unlimited virtual credit authority and is not a player balance.")
        balance = money(target["balance"])
        updated = balance + amount if operation == "add" else balance - amount
        if updated < 0:
            return error("That adjustment would make the balance negative.", 409)
        target["balance"] = str(updated)
        record_transaction(
            store, "admin_credit" if operation == "add" else "admin_debit", amount,
            target["currency"], admin["username"], target_username, balance, updated,
            f"balance:{secrets.token_hex(6).upper()}", f"Admin {operation} adjustment.",
        )
        record_audit(store, admin["username"], "balance_adjusted", target_username, {"operation": operation, "amount": str(amount)})
        save_store(store)
        return jsonify({"user": public_user(target)})


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")), debug=False)