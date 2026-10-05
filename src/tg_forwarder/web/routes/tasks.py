"""Task, checkpoint and transfer HTTP routes."""
from flask import Blueprint, request
from .common import body, invoke, limit

blueprint = Blueprint("tasks", __name__, url_prefix="/api")


@blueprint.route("/tasks", methods=["GET", "POST"])
def tasks():
    if request.method == "GET":
        return invoke("tasks.view" if request.args.get("view") == "1" else "tasks")
    return invoke("task.create", {"data": body()}, 201)


@blueprint.put("/task-order")
def order():
    return invoke("tasks.sort", {"data": body()})


@blueprint.post("/tasks/<task_id>/move")
def move(task_id):
    return invoke("task.move", {"task_id": task_id, "data": body()})


@blueprint.route("/tasks/<task_id>", methods=["GET", "PUT", "DELETE"])
def task(task_id):
    operation = {"GET": "task", "PUT": "task.update", "DELETE": "task.delete"}[request.method]
    return invoke(operation, {"task_id": task_id, **({"data": body()} if request.method == "PUT" else {})})


@blueprint.post("/tasks/<task_id>/action")
def action(task_id):
    return invoke("task.action", {"task_id": task_id, "data": body()})


@blueprint.route("/tasks/<task_id>/progress", methods=["GET", "PUT"])
def progress(task_id):
    return invoke("progress" if request.method == "GET" else "progress.set",
        {"task_id": task_id, **({"data": body()} if request.method == "PUT" else {})})


@blueprint.post("/tasks/<task_id>/progress/reset")
def reset_progress(task_id):
    return invoke("progress.reset", {"task_id": task_id})


@blueprint.route("/tasks/<task_id>/dedup", methods=["GET", "DELETE"])
def dedup(task_id):
    return invoke("dedup" if request.method == "GET" else "dedup.clear", {"task_id": task_id, "limit": limit(500)})


@blueprint.route("/tasks/<task_id>/errors", methods=["GET", "DELETE"])
def errors(task_id):
    return invoke("errors" if request.method == "GET" else "errors.clear", {"task_id": task_id, "limit": limit()})


@blueprint.delete("/tasks/<task_id>/transfer")
def retry(task_id):
    return invoke("transfer.retry", {"task_id": task_id})


@blueprint.post("/tasks/<task_id>/transfer/skip")
def skip(task_id):
    return invoke("transfer.skip", {"task_id": task_id})


@blueprint.post("/tasks/<task_id>/cleanup")
def cleanup(task_id):
    return invoke("cleanup.task", {"task_id": task_id})
