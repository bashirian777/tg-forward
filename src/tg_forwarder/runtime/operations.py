"""Management operations execute only in the forwarding event loop."""
import time

from tg_forwarder.tasks.models import ForwardTask


class ManagementOperations:
    def __init__(self, startup, manager, status):
        self.startup = startup
        self.manager = manager
        self.status = status
        self.started_at = time.monotonic()

    @staticmethod
    def task_from_data(data, task_id=None):
        values = dict(data)
        if task_id is not None:
            values["task_id"] = task_id
        values.setdefault("min_delay", 10.0)
        values.setdefault("max_delay", 20.0)
        try:
            return ForwardTask(**values)
        except TypeError as error:
            raise ValueError("任务字段缺失或包含未知字段") from error

    def system(self):
        return self.manager.system_snapshot(self.started_at)

    async def invoke(self, operation, params):
        manager = self.manager
        task_id = params.get("task_id")
        if task_id is not None:
            manager.require_task(task_id)
        if operation in {"task.create", "task.update", "task.action", "progress.set", "config.update"} and not isinstance(params.get("data"), dict):
            raise ValueError("请求必须包含 JSON 对象")
        if operation == "progress.set" and "last_message_id" not in params["data"]:
            raise ValueError("必须指定 last_message_id")
        if operation == "tasks":
            return manager.task_snapshots()
        if operation == "task":
            return manager.task_snapshot(task_id)
        if operation == "config":
            return dict(manager.config_snapshot(), web_host=self.startup.web_host, web_port=self.startup.web_port)
        if operation == "deployment":
            return dict(self.startup.public_info(), services=self.status())
        if operation == "system":
            return self.system()
        if operation == "logs":
            return manager.get_logs(params.get("limit", 100))
        if operation == "progress":
            return manager.progress_snapshot(task_id)
        if operation == "dedup":
            return manager.dedup_snapshot(task_id, params.get("limit", 500))
        if operation == "errors":
            return manager.errors_snapshot(task_id, params.get("limit", 100))
        if operation == "transfers":
            return manager.get_all_transfers()
        if operation == "task.create":
            task = self.task_from_data(params["data"])
            manager.create_task(task)
            return {"success": True, "task": task.to_dict()}
        if operation == "task.update":
            data = dict(params["data"])
            revision = data.pop("revision", None)
            reset = data.pop("source_reset", None)
            task = self.task_from_data(data, task_id)
            result = await manager.edit_task(task_id, task, revision, reset)
            return {"success": True, "task": result["config"]}
        if operation == "task.action":
            action = params["data"].get("action")
            if action not in {"start", "pause", "resume", "stop"}:
                raise ValueError("不支持的任务操作")
            await getattr(manager, action + "_task")(task_id)
        elif operation == "task.delete":
            await manager.delete_task(task_id)
        elif operation in {"progress.set", "progress.reset"}:
            data = params.get("data", {})
            progress = await manager.edit_progress(task_id,
                0 if operation == "progress.reset" else data["last_message_id"],
                0 if operation == "progress.reset" else data.get("forwarded_count"))
            return {"success": True, "progress": progress}
        elif operation == "dedup.clear":
            await manager.reset_dedup(task_id)
        elif operation == "errors.clear":
            await manager.reset_errors(task_id)
        elif operation == "transfer.retry":
            return dict(await manager.retry_transfer(task_id), success=True)
        elif operation == "transfer.skip":
            return dict(await manager.skip_current_transfer(task_id), success=True)
        elif operation == "cleanup.task":
            return await manager.cleanup_task_files(task_id)
        elif operation == "cleanup":
            return manager.cleanup_files()
        elif operation == "config.update":
            await manager.update_settings(params["data"])
        elif operation == "runtime.reload":
            await manager.reload_runtime()
        else:
            raise ValueError("Unknown management operation")
        return {"success": True}
