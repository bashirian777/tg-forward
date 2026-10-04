"""Expected management errors with stable codes shared by all adapters."""


class OperationError(ValueError):
    def __init__(self, code, message, status=409, fields=None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.fields = fields or {}


class TaskNotFound(OperationError):
    def __init__(self, task_id):
        super().__init__("task_not_found", f"任务 {task_id} 不存在", 404)


class RuntimeUnavailable(OperationError):
    def __init__(self, message="转发服务暂不可用，请稍后重试"):
        super().__init__("runtime_unavailable", message, 503)
