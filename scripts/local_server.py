"""
local_server.py — CycleSync local dev server (auth-free mode).

All auth is bypassed. Every request runs as a single hardcoded test user.
Uses moto in-memory DynamoDB — no AWS account needed.

Usage:
    pip install flask boto3 "moto[dynamodb]" bcrypt
    python scripts/local_server.py
    open http://localhost:5000
"""

import importlib.util
import json
import os
import sys

# ── 1. Start moto BEFORE any boto3 import ─────────────────────────────────
from moto import mock_aws
import boto3

_mock = mock_aws()
_mock.start()

os.environ["AWS_ACCESS_KEY_ID"]     = "local"
os.environ["AWS_SECRET_ACCESS_KEY"] = "local"
os.environ["AWS_DEFAULT_REGION"]    = "us-east-1"
os.environ["USERS_TABLE"]           = "cyclesync-users"
os.environ["SESSIONS_TABLE"]        = "cyclesync-sessions"
os.environ["MOOD_TABLE"]            = "cyclesync-mood-entries"
os.environ["MOOD_TABLE_NAME"]       = "cyclesync-mood-entries"
os.environ["CONTENT_TABLE_NAME"]    = "cyclesync-content-items"
os.environ["NOTIFICATIONS_TABLE"]   = "cyclesync-notifications"
os.environ["NOTIFICATION_LOGS_TABLE"] = "cyclesync-notification-logs"
os.environ["CONFIG_TABLE"]          = "cyclesync-config"
os.environ["ENVIRONMENT"]           = "local"

# ── 2. Create tables + seed a test user ───────────────────────────────────
_TEST_USER_ID = "local-test-user-001"

def _bootstrap():
    ddb = boto3.resource("dynamodb", region_name="us-east-1")

    ddb.create_table(TableName="cyclesync-config",
        KeySchema=[{"AttributeName":"config_key","KeyType":"HASH"}],
        AttributeDefinitions=[{"AttributeName":"config_key","AttributeType":"S"}],
        BillingMode="PAY_PER_REQUEST")

    ddb.create_table(TableName="cyclesync-users",
        KeySchema=[{"AttributeName":"user_id","KeyType":"HASH"}],
        AttributeDefinitions=[
            {"AttributeName":"user_id","AttributeType":"S"},
            {"AttributeName":"email","AttributeType":"S"},
        ],
        GlobalSecondaryIndexes=[{
            "IndexName":"email-index",
            "KeySchema":[{"AttributeName":"email","KeyType":"HASH"}],
            "Projection":{"ProjectionType":"ALL"},
        }],
        BillingMode="PAY_PER_REQUEST")

    ddb.create_table(TableName="cyclesync-sessions",
        KeySchema=[{"AttributeName":"token","KeyType":"HASH"}],
        AttributeDefinitions=[{"AttributeName":"token","AttributeType":"S"}],
        BillingMode="PAY_PER_REQUEST")

    ddb.create_table(TableName="cyclesync-mood-entries",
        KeySchema=[
            {"AttributeName":"user_id","KeyType":"HASH"},
            {"AttributeName":"entry_date","KeyType":"RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName":"user_id","AttributeType":"S"},
            {"AttributeName":"entry_date","AttributeType":"S"},
        ],
        BillingMode="PAY_PER_REQUEST")

    ddb.create_table(TableName="cyclesync-content-items",
        KeySchema=[{"AttributeName":"item_id","KeyType":"HASH"}],
        AttributeDefinitions=[{"AttributeName":"item_id","AttributeType":"S"}],
        BillingMode="PAY_PER_REQUEST")

    ddb.create_table(TableName="cyclesync-notifications",
        KeySchema=[
            {"AttributeName":"user_id","KeyType":"HASH"},
            {"AttributeName":"created_at","KeyType":"RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName":"user_id","AttributeType":"S"},
            {"AttributeName":"created_at","AttributeType":"S"},
        ],
        BillingMode="PAY_PER_REQUEST")

    ddb.create_table(TableName="cyclesync-notification-logs",
        KeySchema=[
            {"AttributeName":"user_id","KeyType":"HASH"},
            {"AttributeName":"sent_at","KeyType":"RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName":"user_id","AttributeType":"S"},
            {"AttributeName":"sent_at","AttributeType":"S"},
        ],
        BillingMode="PAY_PER_REQUEST")

    # Seed test user with sample profile data
    from datetime import date, timedelta
    ddb.Table("cyclesync-users").put_item(Item={
        "user_id": _TEST_USER_ID,
        "email": "test@cyclesync.local",
        "display_name": "Test User",
        "age": 28,
        "last_period_date": (date.today() - timedelta(days=10)).isoformat(),
        "cycle_length_days": 28,
        "language_preference": "en",
        "hobby_preferences": ["Songs", "Movies", "Poetry", "Digital Colouring"],
        "notifications_on": True,
    })
    print(f"  [seed] test user: {_TEST_USER_ID}")
    print(f"  [seed] last_period_date: {(date.today() - timedelta(days=10)).isoformat()} (day 11 → Follicular)")

print("[local] Bootstrapping...")
_bootstrap()
print("[local] Done.\n")

# ── 3. Load handlers ───────────────────────────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _load(name, rel):
    path = os.path.join(_ROOT, rel)
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

print("[local] Loading handlers...")
auth_handler  = _load("auth_h",  "lambdas/auth/handler.py")
cycle_handler = _load("cycle_h", "lambdas/cycle_tracker/handler.py")
mood_handler  = _load("mood_h",  "lambdas/mood_tracker/handler.py")
pred_handler  = _load("pred_h",  "lambdas/prediction_engine/handler.py")
rec_handler   = _load("rec_h",   "lambdas/recommendation_engine/handler.py")
dash_handler  = _load("dash_h",  "lambdas/dashboard/handler.py")
print("[local] Handlers loaded.\n")

# ── 4. Patch shared DynamoDB resource into all handlers ────────────────────
_ddb = boto3.resource("dynamodb", region_name="us-east-1")
_JWT_SECRET = "local-dev-secret-do-not-use-in-prod"

# Seed jwt_secret into config table so auth_handler._get_jwt_secret() works
_ddb.Table("cyclesync-config").put_item(Item={
    "config_key": "jwt_secret",
    "value": _JWT_SECRET,
})

for _m in [auth_handler, cycle_handler, mood_handler, dash_handler, rec_handler]:
    if hasattr(_m, "_ddb"):     _m._ddb     = _ddb
    if hasattr(_m, "_ddb_res"): _m._ddb_res = _ddb
    # Pre-populate JWT secret cache so no DynamoDB lookup needed
    if hasattr(_m, "_jwt_secret_cache"): _m._jwt_secret_cache = _JWT_SECRET
    # Fix table name attributes (read at import time from env)
    for attr, val in [
        ("USERS_TABLE_NAME",    "cyclesync-users"),
        ("SESSIONS_TABLE_NAME", "cyclesync-sessions"),
        ("CONFIG_TABLE_NAME",   "cyclesync-config"),
        ("MOOD_TABLE_NAME",     "cyclesync-mood-entries"),
        ("CONTENT_TABLE_NAME",  "cyclesync-content-items"),
    ]:
        if hasattr(_m, attr): setattr(_m, attr, val)

# Also patch _dynamodb() factory functions that create a new resource each call
def _shared_dynamodb():
    return _ddb

for _m in [mood_handler, rec_handler]:
    if hasattr(_m, "_dynamodb"):
        _m._dynamodb = _shared_dynamodb

# ── 5. Patch dashboard to call handlers directly (no lambda.invoke) ────────
def _unwrap(resp):
    """Unwrap a Lambda HTTP response to get the body dict."""
    if isinstance(resp, dict) and "body" in resp:
        try:
            return json.loads(resp["body"])
        except Exception:
            return resp
    return resp

def _direct_invoke(fn_name, payload):
    uid = payload.get("user_id", _get_active_user_id())
    if "cycle-tracker" in fn_name:
        return _unwrap(cycle_handler._get_phase_for_user(uid))
    if "prediction-engine" in fn_name:
        return pred_handler.lambda_handler(payload, {})
    if "mood-tracker" in fn_name:
        return _unwrap(mood_handler._get_today_for_user(uid))
    if "recommendation-engine" in fn_name:
        return rec_handler._handle_direct_recommendations(payload)
    return {}

dash_handler._invoke = _direct_invoke

# ── 6. Flask app ───────────────────────────────────────────────────────────
from flask import Flask, request, Response

app = Flask(__name__, static_folder=os.path.join(_ROOT, "frontend"), static_url_path="")
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0  # disable static file caching
app.secret_key = "local-dev-only"  # for Flask session cookie

# ── Active user tracking ───────────────────────────────────────────────────
# In local mode we track the logged-in user_id in a Flask session cookie
# so profile/dashboard/mood all use the registered user's data.

from flask import session as _flask_session

def _get_active_user_id():
    return _flask_session.get("user_id", _TEST_USER_ID)

def _set_active_user_id(uid):
    _flask_session["user_id"] = uid

def _event(req, user_id=None):
    """Build a Lambda event from a Flask request. Auth is bypassed."""
    path = req.path
    if path.startswith("/api"):
        path = path[4:] or "/"
    uid = user_id or _get_active_user_id()
    return {
        "httpMethod": req.method,
        "path": path,
        "rawPath": path,
        "headers": {k: v for k, v in req.headers},
        "queryStringParameters": req.args.to_dict() or None,
        "pathParameters": {},
        "body": req.get_data(as_text=True) or None,
        "requestContext": {
            "http": {"method": req.method, "path": path},
            "authorizer": {"claims": {"sub": uid}},
        },
        "user_id": uid,
    }

def _resp(result):
    body    = result.get("body", "")
    status  = result.get("statusCode", 200)
    headers = {**result.get("headers", {}), "Access-Control-Allow-Origin": "*"}
    return Response(body, status=status, headers=headers, mimetype="application/json")

def _cors():
    return Response("", 204, headers={
        "Access-Control-Allow-Origin":  "*",
        "Access-Control-Allow-Headers": "*",
        "Access-Control-Allow-Methods": "*",
    })

def _call(handler_mod, req, user_id=None):
    ev = _event(req, user_id)
    uid = user_id or _get_active_user_id()
    if hasattr(handler_mod, "_require_auth"):
        handler_mod._require_auth = lambda event: (uid, None)
    result = handler_mod.lambda_handler(ev, {})

    # After register or login, capture the user_id into the Flask session
    if result.get("statusCode") in (200, 201):
        path = req.path
        if "/auth/register" in path or "/auth/login" in path:
            try:
                body = json.loads(result.get("body", "{}"))
                new_uid = body.get("user_id")
                if new_uid:
                    _set_active_user_id(new_uid)
                    print(f"  [session] active user set to {new_uid}")
            except Exception:
                pass

    print(f"  {req.method} {req.path} -> {result.get('statusCode')} | {result.get('body','')[:80]}")
    return _resp(result)

# ── Routes ─────────────────────────────────────────────────────────────────

@app.route("/api/auth/<path:sub>", methods=["GET","POST","PUT","DELETE","OPTIONS"])
def r_auth(sub):
    if request.method == "OPTIONS": return _cors()
    return _call(auth_handler, request)

@app.route("/api/profile",          methods=["GET","PUT","OPTIONS"])
@app.route("/api/profile/<path:sub>", methods=["GET","PUT","OPTIONS"])
def r_profile(sub=""):
    if request.method == "OPTIONS": return _cors()
    return _call(auth_handler, request)

@app.route("/api/cycle/<path:sub>", methods=["GET","OPTIONS"])
def r_cycle(sub):
    if request.method == "OPTIONS": return _cors()
    return _call(cycle_handler, request)

@app.route("/api/mood",             methods=["GET","POST","OPTIONS"])
@app.route("/api/mood/<path:sub>",  methods=["GET","OPTIONS"])
def r_mood(sub=""):
    if request.method == "OPTIONS": return _cors()
    return _call(mood_handler, request)

@app.route("/api/recommendations",          methods=["GET","OPTIONS"])
@app.route("/api/admin/content",            methods=["GET","POST","OPTIONS"])
@app.route("/api/admin/content/<item_id>",  methods=["PUT","DELETE","OPTIONS"])
def r_rec(item_id=None):
    if request.method == "OPTIONS": return _cors()
    return _call(rec_handler, request)

@app.route("/api/dashboard", methods=["GET","OPTIONS"])
def r_dashboard():
    if request.method == "OPTIONS": return _cors()
    return _call(dash_handler, request)

@app.route("/")
def index():
    resp = app.send_static_file("index.html")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return resp

@app.route("/<path:p>")
def static_files(p):
    resp = app.send_static_file(p)
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return resp

# ── Boot ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("[local] http://localhost:5000")
    print("[local] Auth bypassed — all requests run as test user\n")
    app.run(port=5000, debug=False)
