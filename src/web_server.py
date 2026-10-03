"""Simple web server for viewing forwarding progress."""
import hmac
import json
import logging
import os
import secrets
import shutil
import time
from pathlib import Path
from aiohttp import web

from .models import ForwardTask
from .validators import validate_channel_id, validate_delay_range, validate_task_id

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent / "static"


class WebServer:
    """Simple HTTP server for viewing task progress (read-only)."""

    def __init__(self, progress_tracker, task_manager, host: str = "127.0.0.1", port: int = 10082,
                 web_password: str = ""):
        self.progress_tracker = progress_tracker
        self.task_manager = task_manager
        self.host = host
        self.port = port
        self.web_password = web_password or ""
        self._auth_tokens = {}
        self._auth_token_ttl = 24 * 60 * 60
        self._started_at = time.time()
        self._app = None
        self._runner = None

    async def start(self):
        """Start the web server."""
        self._app = web.Application()
        self._app.router.add_get("/", self.handle_index)
        self._app.router.add_get("/static/{name}", self.handle_static)
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
        self._app.router.add_post("/api/config/sync-json", self.handle_api_sync_json)
        self._app.router.add_post("/api/config/backup", self.handle_api_backup)

        self._runner = web.AppRunner(self._app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        logger.info(f"Web server started at http://{self.host}:{self.port}")

    async def stop(self):
        """Stop the web server."""
        if self._runner:
            await self._runner.cleanup()

    def _is_authorized(self, request) -> bool:
        """Validate a short-lived browser token for protected API calls."""
        if not self.web_password:
            return True

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
            payload = await request.json()
            password = str(payload.get("password", ""))
        except (json.JSONDecodeError, TypeError, ValueError):
            password = ""

        if not hmac.compare_digest(password, self.web_password):
            return web.json_response({"error": "invalid_password"}, status=401)

        token = secrets.token_urlsafe(32)
        self._auth_tokens[token] = time.time() + self._auth_token_ttl
        return web.json_response({
            "auth_required": True,
            "token": token,
            "expires_in": self._auth_token_ttl
        })

    async def handle_index(self, request):
        """Serve the admin page. no-cache keeps file edits visible after refresh."""
        return web.FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    async def handle_static(self, request):
        """Serve static assets from the whitelisted set."""
        name = request.match_info.get("name", "")
        allowed = {"app.css": "text/css", "app.js": "application/javascript"}
        if name not in allowed:
            raise web.HTTPNotFound()
        return web.FileResponse(
            STATIC_DIR / name,
            headers={"Content-Type": allowed[name], "Cache-Control": "no-cache"},
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
        valid, error = validate_task_id(values.get("task_id"))
        if not valid:
            raise ValueError(error)
        for key in ("source_channel", "target_channel"):
            try:
                values[key] = int(values[key])
            except (KeyError, TypeError, ValueError):
                raise ValueError(f"{key} must be an integer")
            valid, error = validate_channel_id(values[key])
            if not valid:
                raise ValueError(error)
        try:
            values["min_delay"] = float(values.get("min_delay", 10.0))
            values["max_delay"] = float(values.get("max_delay", 20.0))
        except (TypeError, ValueError):
            raise ValueError("Delay values must be numbers")
        valid, error = validate_delay_range(values["min_delay"], values["max_delay"])
        if not valid:
            raise ValueError(error)
        defaults = ForwardTask(
            task_id=values["task_id"], source_channel=values["source_channel"],
            target_channel=values["target_channel"], min_delay=values["min_delay"],
            max_delay=values["max_delay"]
        ).to_dict()
        defaults.update(values)
        for key in ("filter_keywords", "required_hashtags"):
            if not isinstance(defaults[key], list) or not all(isinstance(item, str) for item in defaults[key]):
                raise ValueError(f"{key} must be a string array")
        for key in ("enabled", "hide_source", "remove_hashtags", "send_as_channel", "deduplicate"):
            defaults[key] = bool(defaults.get(key, False))
        if defaults.get("target_topic_id") is not None:
            try:
                defaults["target_topic_id"] = int(defaults["target_topic_id"])
            except (TypeError, ValueError):
                raise ValueError("target_topic_id must be an integer or null")
            if defaults["target_topic_id"] < 1:
                raise ValueError("target_topic_id must be a positive integer or null")
        if defaults.get("source_topic_id") is not None:
            try:
                defaults["source_topic_id"] = int(defaults["source_topic_id"])
            except (TypeError, ValueError):
                raise ValueError("source_topic_id must be an integer or null")
            if defaults["source_topic_id"] < 1:
                raise ValueError("source_topic_id must be a positive integer or null")
        return ForwardTask.from_dict(defaults)

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
            task = self._task_from_data(data, task_id=task_id)
            self.task_manager.update_task(task)
            return web.json_response({"success": True, "task": task.to_dict()})
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
            if self.task_manager.has_running_tasks():
                return web.json_response({"error": "stop_all_tasks_before_editing_config"}, status=409)
            if "temp_dir" in data:
                current.temp_dir = str(data["temp_dir"])
            if "temp_max_age_hours" in data:
                current.temp_max_age_hours = max(0.0, float(data["temp_max_age_hours"]))
            if "max_concurrent_tasks" in data:
                current.max_concurrent_tasks = max(1, int(data["max_concurrent_tasks"]))
            if "min_free_disk_mb" in data:
                current.min_free_disk_mb = max(0, int(data["min_free_disk_mb"]))
            if "web_password" in data and data["web_password"]:
                current.web_password = str(data["web_password"])
                self.web_password = current.web_password
                self._auth_tokens.clear()
            self.task_manager.config_manager.save_config(current)
            self.task_manager.refresh_runtime_limits()
            self.task_manager.config_manager.db.log_operation("update_app_config", after_data={
                "temp_dir": current.temp_dir,
                "temp_max_age_hours": current.temp_max_age_hours,
                "max_concurrent_tasks": current.max_concurrent_tasks,
                "min_free_disk_mb": current.min_free_disk_mb,
            })
            return web.json_response({"success": True})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def handle_api_backup(self, request):
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            output_dir = os.path.join(
                os.path.dirname(self.task_manager.config_manager.db.path),
                "backups", time.strftime("%Y%m%d-%H%M%S")
            )
            self.task_manager.config_manager.db.export_legacy(output_dir)
            self.task_manager.config_manager.db.log_operation("export_backup", after_data={"path": output_dir})
            return web.json_response({"success": True, "path": output_dir})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_api_sync_json(self, request):
        """Write the current SQLite snapshot to the legacy JSON layout."""
        if not self._is_authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        try:
            config_path = self.task_manager.config_manager.config_path
            backup_dir = self.task_manager.config_manager.db.sync_legacy(config_path)
            return web.json_response({"success": True, "backup_dir": backup_dir})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

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
        """Legacy compatibility: no longer inlined; served from /static files."""
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")
