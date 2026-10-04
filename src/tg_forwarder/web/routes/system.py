"""Runtime settings, deployment information and resources."""
from flask import Blueprint, request
from .common import body, invoke, limit

blueprint = Blueprint("system", __name__, url_prefix="/api")


@blueprint.route("/config", methods=["GET", "PUT"])
def config():
    return invoke("config") if request.method == "GET" else invoke("config.update", {"data": body()})


@blueprint.get("/deployment")
def deployment():
    return invoke("deployment")


@blueprint.get("/system")
def system():
    return invoke("system")


@blueprint.get("/logs")
def logs():
    return invoke("logs", {"limit": limit()})


@blueprint.post("/cleanup")
def cleanup():
    return invoke("cleanup")


@blueprint.get("/download")
def transfers():
    return invoke("transfers")


@blueprint.get("/status")
def status():
    return invoke("tasks")
