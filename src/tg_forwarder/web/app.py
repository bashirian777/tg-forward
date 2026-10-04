"""Flask application with runtime-owned operations and same-origin assets."""
import time
from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from tg_forwarder.storage.database import ConfigurationConflict
from tg_forwarder.tasks.errors import OperationError
from .auth import COOKIE_NAME


def create_app(runtime, dist_dir=None):
    app = Flask(__name__, static_folder=None)
    app.json.ensure_ascii = False
    app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024
    app.extensions["runtime"] = runtime

    @app.before_request
    def check_origin():
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("Origin")
            if origin and urlsplit(origin).netloc != request.host:
                raise OperationError("invalid_origin", "请求来源不匹配", 403)

    @app.errorhandler(OperationError)
    def operation_error(error):
        return jsonify(error=error.code, message=str(error), fields=error.fields), error.status

    @app.errorhandler(ConfigurationConflict)
    def conflict(error):
        return jsonify(error="configuration_conflict", message=str(error)), 409

    @app.errorhandler(ValueError)
    def invalid(error):
        return jsonify(error="invalid_input", message=str(error)), 400

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error="http_error", message=error.description), error.code

    @app.errorhandler(Exception)
    def unexpected(error):
        app.logger.exception("HTTP request failed")
        return jsonify(error="internal_error", message="服务内部错误，请查看运行日志"), 500

    @app.after_request
    def response_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    from .routes.tasks import blueprint as tasks
    from .routes.system import blueprint as system
    app.register_blueprint(tasks)
    app.register_blueprint(system)

    @app.route("/api/auth", methods=["GET", "POST", "DELETE"])
    def auth():
        token = request.cookies.get(COOKIE_NAME, "")
        if request.method == "GET":
            return jsonify(runtime.call("auth.info", token=token))
        if request.method == "POST":
            from .routes.common import body
            data = body()
            result = runtime.call("auth.login", {"password": data.get("password", ""), "address": request.remote_addr or "local"})
            session_token = result.pop("token")
            response = jsonify(result)
            response.set_cookie(COOKIE_NAME, session_token, httponly=True, secure=request.is_secure,
                samesite="Strict", max_age=max(1, int(result["expires_at"] - time.time())))
            return response
        result = runtime.call("auth.logout", token=token, csrf=request.headers.get("X-CSRF-Token"), write=True)
        response = jsonify(result)
        response.delete_cookie(COOKIE_NAME)
        return response

    @app.get("/api/operations/<operation_id>")
    def operation_result(operation_id):
        token = request.cookies.get(COOKIE_NAME, "")
        runtime.call("auth.check", token=token)
        return jsonify(runtime.result(operation_id, token))

    @app.route("/api/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    def missing_api(path):
        from flask import abort
        abort(404)

    root = Path(dist_dir) if dist_dir is not None else Path(__file__).parent / "dist"

    @app.get("/assets/<path:filename>")
    def assets(filename):
        response = send_from_directory(root / "assets", filename)
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response

    @app.get("/")
    @app.get("/<path:path>")
    def frontend(path=""):
        from flask import abort
        if path.startswith(("api/", "assets/")) or path == "api":
            abort(404)
        if path and path not in {"tasks", "resources", "settings", "activity"}:
            abort(404)
        if not (root / "index.html").is_file():
            return jsonify(error="frontend_not_built", message="请先构建前端：npm --prefix frontend run build"), 503
        response = send_from_directory(root, "index.html")
        response.headers["Cache-Control"] = "no-store"
        return response

    return app
