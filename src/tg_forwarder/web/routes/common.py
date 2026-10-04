"""Small request adapters; mutable state belongs to the runtime."""
from flask import current_app, jsonify, request
from tg_forwarder.web.auth import COOKIE_NAME


def body():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ValueError("请求必须包含 JSON 对象")
    return value


def limit(default=100):
    try:
        return max(1, min(int(request.args.get("limit", default)), 500))
    except ValueError:
        raise ValueError("limit 必须是整数")


def invoke(operation, params=None, status=200):
    result = current_app.extensions["runtime"].call(operation, params,
        token=request.cookies.get(COOKIE_NAME, ""), csrf=request.headers.get("X-CSRF-Token"),
        write=request.method not in {"GET", "HEAD", "OPTIONS"})
    return jsonify(result), 202 if isinstance(result, dict) and result.get("pending") else status
