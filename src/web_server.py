"""Simple web server for viewing forwarding progress."""
import hmac
import json
import logging
import os
import secrets
import shutil
import time
from pathlib import Path
from copy import deepcopy
from aiohttp import web

from .models import ForwardTask
from .validators import validate_task, validate_runtime_config
from .database import ConfigurationConflict
from .workspace import WorkspaceStore
import asyncio

logger = logging.getLogger(__name__)

from .web_assets import ASSET_TYPES, WebAssets

STATIC_DIR = Path(__file__).resolve().parent / "static"


class WebServer:
    """Simple HTTP server for viewing task progress (read-only)."""

    def __init__(self, progress_tracker, task_manager, host: str = "127.0.0.1", port: int = 10082,
                 web_password: str = "", *, startup=None, service_status=None):
        self.progress_tracker = progress_tracker
        self.task_manager = task_manager
        self.startup = startup
        self.service_status = service_status
        self.host = host
        self.port = port
        self.web_password = web_password or ""
        self._auth_tokens = {}
        self._auth_token_ttl = 24 * 60 * 60
        config = task_manager.config_manager.get_config() if task_manager else None
        if config:
            self._auth_token_ttl = config.web_auth_ttl_hours * 3600
        self._started_at = time.time()
        self._app = None
        self._runner = None
        self._cleanup_task = None

    def create_app(self):
        """Build the same routes for production and local HTTP tests."""
        self._app = web.Application()
        self._app.router.add_get("/", self.handle_index)
        self._app.router.add_get("/static/{name:.*}", self.handle_static)
        self._app.router.add_post("/api/auth", self.handle_api_auth)
        self._app.router.add_get("/api/status", self.handle_api_status)
        self._app.router.add_get("/api/download", self.handle_api_download)
        self._app.router.add_get("/api/system", self.handle_api_system)
        self._app.router.add_get("/api/config", self.handle_api_config)
        self._app.router.add_post("/api/tasks/{task_id}/action", self.handle_api_task_action)
        self._app.router.add_get("/api/tasks", self.handle_api_tasks)
        self._app.router.add_post("/api/tasks", self.handle_api_create_task)
        self._app.router.add_get("/api/tasks/{task_id}", self.handle_api_task_detail)
        self._app.router.add_put("/api/tasks/{task_id}", self.handle_api_update_task)
        self._app.router.add_delete("/api/tasks/{task_id}", self.handle_api_delete_task)
        self._app.router.add_get("/api/tasks/{task_id}/progress", self.handle_api_task_progress)
        self._app.router.add_put("/api/tasks/{task_id}/progress", self.handle_api_set_progress)
        self._app.router.add_post("/api/tasks/{task_id}/progress/reset", self.handle_api_reset_progress)
        self._app.router.add_get("/api/tasks/{task_id}/dedup", self.handle_api_task_dedup)
        self._app.router.add_delete("/api/tasks/{task_id}/dedup", self.handle_api_clear_dedup)
        self._app.router.add_get("/api/tasks/{task_id}/errors", self.handle_api_task_errors)
        self._app.router.add_delete("/api/tasks/{task_id}/errors", self.handle_api_clear_errors)
        self._app.router.add_delete("/api/tasks/{task_id}/transfer", self.handle_api_clear_transfer)
        self._app.router.add_post("/api/tasks/{task_id}/transfer/skip", self.handle_api_skip_transfer)
        self._app.router.add_get("/api/logs", self.handle_api_logs)
        self._app.router.add_put("/api/config", self.handle_api_update_config)
        self._app.router.add_get("/api/deployment", self.handle_api_deployment)
        self._app.router.add_post("/api/cleanup", self.handle_api_cleanup)
        self._app.router.add_post("/api/tasks/{task_id}/cleanup", self.handle_api_task_cleanup)

        return self._app

    async def start(self):
        self._runner = web.AppRunner(self.create_app(), access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info(f"Web server started at http://{self.host}:{self.port}")

    async def stop(self):
        """Stop the web server."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        if self._runner:
            await self._runner.cleanup()

    async def _cleanup_loop(self):
        while True:
            await asyncio.sleep(600)
            try:
                self.task_manager.cleanup_files(expired_only=True)
            except Exception:
                logger.exception("Periodic temp cleanup failed")

    async def handle_api_cleanup(self, request):
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        return web.json_response(self.task_manager.cleanup_files())

    async def handle_api_task_cleanup(self, request):
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        return web.json_response(await self.task_manager.cleanup_task_files(request.match_info["task_id"]))

    def _is_authorized(self, request) -> bool:
        """Validate a short-lived browser token for protected API calls."""
        if not self.web_password:
            return True

        now = time.time()
        self._auth_tokens = {token: expiry for token, expiry in self._auth_tokens.items() if expiry > now}
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            return False
        token = authorization[7:].strip()
        expires_at = self._auth_tokens.get(token)
        if not expires_at:
            return False
        if expires_at <= time.time():
            self._auth_tokens.pop(token, None)
            return False
        return True

    async def handle_api_auth(self, request):
        """Authenticate the web page and issue a short-lived token."""
        if not self.web_password:
            return web.json_response({"auth_required": False, "token": ""})

        try:
            payload = await self._json_body(request)
            password = payload.get("password", "")
            if not isinstance(password, str):
                raise ValueError("Password must be a string")
        except (json.JSONDecodeError, TypeError, ValueError):
            password = ""

        if not hmac.compare_digest(password.encode("utf-8"), self.web_password.encode("utf-8")):
            return web.json_response({"error": "invalid_password"}, status=401)

        now = time.time()
        self._auth_tokens = {token: expiry for token, expiry in self._auth_tokens.items() if expiry > now}
        token = secrets.token_urlsafe(32)
        expires_at = now + self._auth_token_ttl
        self._auth_tokens[token] = expires_at
        return web.json_response({
            "auth_required": True,
            "token": token,
            "expires_in": self._auth_token_ttl,
            "expires_at": expires_at,
        })

    async def handle_index(self, request):
        """Pair the page with the current assets, even across browser caches."""
        return web.Response(text=self._generate_html(), content_type="text/html",
            headers={"Cache-Control": "no-store"})

    async def handle_static(self, request):
        """Serve static assets from the whitelisted set."""
        name = request.match_info.get("name", "")
        if name not in ASSET_TYPES:
            raise web.HTTPNotFound()
        return web.Response(
            text=WebAssets(STATIC_DIR).render(name),
            content_type=ASSET_TYPES[name],
            headers={"Cache-Control": "no-cache"},
        )

    async def handle_api_status(self, request):
        """API endpoint for task status."""
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        tasks = self.task_manager.list_tasks()
        data = []
        for ts in tasks:
            task_data = {
                "task_id": ts.task_id,
                "status": ts.status,
                "forwarded_count": ts.progress.forwarded_count if ts.progress else 0,
                "last_message_id": ts.progress.last_message_id if ts.progress else 0,
                "last_forward_time": ts.progress.last_forward_time if ts.progress else "",
            }
            if ts.config:
                task_data["note"] = ts.config.note
                task_data["source_channel"] = ts.config.source_channel
                task_data["target_channel"] = ts.config.target_channel
                task_data["enabled"] = ts.config.enabled
                task_data["min_delay"] = ts.config.min_delay
                task_data["max_delay"] = ts.config.max_delay
            data.append(task_data)
        return web.json_response(data)

    async def handle_api_system(self, request):
        """Return local resource metrics for the admin dashboard."""
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)

        config = self.task_manager.config_manager.get_config()
        temp_dir = getattr(config, "temp_dir", "temp") if config else "temp"
        root_usage = shutil.disk_usage("/")
        temp_exists = os.path.isdir(temp_dir)
        temp_usage = shutil.disk_usage(temp_dir) if temp_exists else None
        load_average = os.getloadavg() if hasattr(os, "getloadavg") else []
        return web.json_response({
            "disk": {
                "total": root_usage.total,
                "used": root_usage.used,
                "free": root_usage.free,
                "percent": round(root_usage.used * 100 / root_usage.total, 1)
            },
            "temp_dir": temp_dir,
            "temp_exists": temp_exists,
            "temp_files": WorkspaceStore(temp_dir).stats(),
            "temp_disk": {
                "total": temp_usage.total,
                "used": temp_usage.used,
                "free": temp_usage.free,
                "percent": round(temp_usage.used * 100 / temp_usage.total, 1)
            } if temp_usage else None,
            "uptime_seconds": int(time.time() - self._started_at),
            "load_average": [round(value, 2) for value in load_average]
        })

    async def handle_api_config(self, request):
        """Return non-sensitive runtime configuration."""
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)

        config = self.task_manager.config_manager.get_config()
        if not config:
            return web.json_response({"error": "config_unavailable"}, status=503)
        return web.json_response({
            "temp_dir": config.temp_dir,
            "temp_max_age_hours": config.temp_max_age_hours,
            "max_concurrent_tasks": config.max_concurrent_tasks,
            "min_free_disk_mb": config.min_free_disk_mb,
            "web_password_configured": bool(config.web_password),
            "storage_source": "SQLite",
            "revision": self.task_manager.config_manager._app_revision,
            "web_auth_ttl_hours": config.web_auth_ttl_hours,
            "web_port": self.port,
            "web_host": self.host,
            "download_workers": config.download_workers,
            "upload_workers": config.upload_workers,
        })

    async def handle_api_task_action(self, request):
        """Run a task-management action from the admin dashboard."""
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)

        task_id = request.match_info["task_id"]
        try:
            payload = await request.json()
            action = str(payload.get("action", "")).lower()
        except (json.JSONDecodeError, TypeError, ValueError):
            action = ""

        actions = {
            "start": self.task_manager.start_task,
            "pause": self.task_manager.pause_task,
            "resume": self.task_manager.resume_task,
            "stop": self.task_manager.stop_task,
        }
        try:
            if action in actions:
                await actions[action](task_id)
            elif action == "delete":
                await self.task_manager.delete_task(task_id, delete_progress=True)
            else:
                return web.json_response({"error": "invalid_action"}, status=400)
        except Exception as e:
            logger.warning("Web task action failed for %s/%s: %s", task_id, action, e)
            return web.json_response({"error": str(e)}, status=400)

        return web.json_response({"success": True, "task_id": task_id, "action": action})

    async def handle_api_tasks(self, request):
        """Return full task configuration, progress, and runtime state."""
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        return web.json_response([self._task_payload(status) for status in self.task_manager.list_tasks()])

    def _task_payload(self, status):
        task = status.config.to_dict() if status.config else {}
        progress = status.progress.to_dict() if status.progress else {}
        return {
            "task_id": status.task_id,
            "status": status.status,
            "config": task,
            "progress": progress,
            "transfer": self.task_manager.get_transfer(status.task_id),
            "dedup": self.task_manager.get_dedup_stats(status.task_id),
            "errors": self.task_manager.get_task_error_summary(status.task_id),
            "revision": self.task_manager.config_manager._task_revisions.get(status.task_id, 0),
        }

    @staticmethod
    async def _json_body(request) -> dict:
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("JSON body must be an object")
            return body
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            raise ValueError(f"Invalid JSON body: {e}")

    @staticmethod
    def _task_from_data(data: dict, task_id: str = None) -> ForwardTask:
        values = dict(data)
        if task_id is not None:
            values["task_id"] = task_id
        values.setdefault("min_delay", 10.0)
        values.setdefault("max_delay", 20.0)
        task = ForwardTask(**values)
        validate_task(task)
        return task

    async def handle_api_create_task(self, request):
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            task = self._task_from_data(await self._json_body(request))
            self.task_manager.config_manager.add_task(task)
            self.task_manager.config_manager.db.log_operation("create_task", task_id=task.task_id, after_data=task.to_dict())
            return web.json_response({"success": True, "task": task.to_dict()}, status=201)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def handle_api_task_detail(self, request):
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        status = self.task_manager.get_task_status(request.match_info["task_id"])
        if not status.config:
            return web.json_response({"error": "task_not_found"}, status=404)
        return web.json_response(self._task_payload(status))

    async def handle_api_update_task(self, request):
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        task_id = request.match_info["task_id"]
        try:
            old = self.task_manager.config_manager.get_task(task_id)
            if not old:
                return web.json_response({"error": "task_not_found"}, status=404)
            data = await self._json_body(request)
            revision = data.pop("revision", None)
            source_reset = data.pop("source_reset", None)
            task = self._task_from_data(data, task_id=task_id)
            self.task_manager.update_task(task, revision, source_reset)
            return web.json_response({"success": True, "task": task.to_dict()})
        except ConfigurationConflict as e:
            return web.json_response({"error": str(e)}, status=409)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def handle_api_delete_task(self, request):
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        task_id = request.match_info["task_id"]
        try:
            await self.task_manager.delete_task(task_id, delete_progress=True)
            return web.json_response({"success": True})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def handle_api_task_progress(self, request):
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        task_id = request.match_info["task_id"]
        if not self.task_manager.config_manager.get_task(task_id):
            return web.json_response({"error": "task_not_found"}, status=404)
        return web.json_response(self.task_manager.progress_tracker.get_task_progress(task_id).to_dict())

    async def handle_api_set_progress(self, request):
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            data = await self._json_body(request)
            progress = self.task_manager.set_progress(
                request.match_info["task_id"], data["last_message_id"], data.get("forwarded_count")
            )
            return web.json_response({"success": True, "progress": progress.to_dict()})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def handle_api_reset_progress(self, request):
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            self.task_manager.set_progress(request.match_info["task_id"], 0, 0)
            return web.json_response({"success": True})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def handle_api_task_dedup(self, request):
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        task_id = request.match_info["task_id"]
        try:
            limit = int(request.query.get("limit", "500"))
        except ValueError:
            limit = 500
        return web.json_response({
            "stats": self.task_manager.get_dedup_stats(task_id),
            "records": self.task_manager.config_manager.db.list_dedup(task_id, limit),
        })

    async def handle_api_clear_dedup(self, request):
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            self.task_manager.clear_dedup(request.match_info["task_id"])
            return web.json_response({"success": True})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def handle_api_task_errors(self, request):
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        task_id = request.match_info["task_id"]
        try:
            limit = int(request.query.get("limit", "100"))
        except ValueError:
            limit = 100
        return web.json_response({
            "summary": self.task_manager.get_task_error_summary(task_id),
            "errors": self.task_manager.get_task_errors(task_id, limit),
        })

    async def handle_api_clear_errors(self, request):
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            task_id = request.match_info["task_id"]
            self.task_manager.clear_task_errors(task_id)
            transfer = self.task_manager.get_transfer(task_id)
            if transfer and transfer.get("state") == "error":
                self.task_manager.progress_tracker.mark_transfer_state(task_id, "interrupted")
            return web.json_response({"success": True})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def handle_api_clear_transfer(self, request):
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            task_id = request.match_info["task_id"]
            was_running = task_id in self.task_manager._tasks and not self.task_manager._tasks[task_id].done()
            await self.task_manager.stop_task(task_id)
            self.task_manager.clear_transfer(task_id)
            if was_running:
                await self.task_manager.start_task(task_id)
            return web.json_response({
                "success": True,
                "resume_from": self.task_manager.progress_tracker.get_last_message_id(task_id),
                "restarted": was_running,
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def handle_api_skip_transfer(self, request):
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            task_id = request.match_info["task_id"]
            await self.task_manager.stop_task(task_id)
            highest_id = self.task_manager.skip_transfer(task_id)
            return web.json_response({"success": True, "skipped_through": highest_id})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def handle_api_update_config(self, request):
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            data = await self._json_body(request)
            current = self.task_manager.config_manager.get_config()
            if not current:
                return web.json_response({"error": "config_unavailable"}, status=503)
            candidate = deepcopy(current)
            allowed = {"temp_dir", "temp_max_age_hours", "max_concurrent_tasks", "min_free_disk_mb", "web_password", "web_auth_ttl_hours", "download_workers", "upload_workers"}
            if set(data) - allowed - {"revision"}:
                raise ValueError("Unknown configuration field")
            for key in allowed & set(data):
                if key == "web_password" and not data[key]:
                    continue
                setattr(candidate, key, data[key])
            validate_runtime_config(candidate, self.task_manager.config_manager.project_root)
            runtime_keys = {"temp_dir", "temp_max_age_hours", "max_concurrent_tasks", "min_free_disk_mb", "download_workers", "upload_workers"}
            runtime_changed = any(getattr(candidate, key) != getattr(current, key) for key in runtime_keys)
            if runtime_changed and self.task_manager.has_running_tasks():
                return web.json_response({"error": "stop_all_tasks_before_editing_config"}, status=409)
            self.task_manager.config_manager.save_app_config(candidate, data.get("revision"))
            if candidate.web_password != self.web_password:
                self.web_password = candidate.web_password
                self._auth_tokens.clear()
            self._auth_token_ttl = candidate.web_auth_ttl_hours * 3600
            if runtime_changed:
                self.task_manager.refresh_runtime_limits()
            self.task_manager.config_manager.db.log_operation("update_app_config", after_data={
                key: getattr(candidate, key) for key in runtime_keys | {"web_auth_ttl_hours"}
            })
            return web.json_response({"success": True})
        except ConfigurationConflict as e:
            return web.json_response({"error": str(e)}, status=409)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def handle_api_deployment(self, request):
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        data = self.startup.public_info() if self.startup else {"fields": {}}
        data["services"] = self.service_status() if self.service_status else {}
        return web.json_response(data)

    async def handle_api_logs(self, request):
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            limit = int(request.query.get("limit", "100"))
        except ValueError:
            limit = 100
        return web.json_response(self.task_manager.config_manager.db.list_logs(limit))

    async def handle_api_download(self, request):
        """API endpoint for live transfer state."""
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)

        downloads = self.progress_tracker.get_all_transfers()
        result = {}
        for task_id, dl_info in downloads.items():
            ts = self.task_manager.get_task_status(task_id)
            task_note = ts.config.note or task_id if ts and ts.config else task_id
            result[task_id] = {**dl_info, "task_note": task_note}
        return web.json_response(result)

    def _generate_html(self):
        return WebAssets(STATIC_DIR).render("index.html")
