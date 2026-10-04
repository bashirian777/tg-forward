"""Compose frontend templates and version the complete asset dependency graph."""
import hashlib
import posixpath
import re
from pathlib import Path

ASSET_TYPES = {
    **dict.fromkeys(("app.css", "css/base.css", "css/layout.css", "css/components.css", "css/tasks.css", "css/forms.css"), "text/css"),
    **dict.fromkeys(("app.js", "js/core.js", "js/api.js", "js/ui.js", "js/tasks.js", "js/task-form.js", "js/settings.js", "js/monitor.js", "js/task-dialogs.js"), "application/javascript"),
}
TEMPLATES = {
    "views/tasks.html", "views/resources.html", "views/settings.html", "views/activity.html",
    "dialogs/task.html", "dialogs/checkpoint.html", "dialogs/settings.html", "dialogs/errors.html", "dialogs/confirm.html",
}
REFERENCE = re.compile(r'''(?P<quote>["'])(?P<path>(?:/static/|\.{1,2}/)[^"'?#]+\.(?:css|js))(?P=quote)''')
INCLUDE = re.compile(r"<!-- include: ([a-z/-]+\.html) -->")


class WebAssets:
    def __init__(self, root: Path):
        self.root = root
        self._sources = {}

    def source(self, name):
        if name not in ASSET_TYPES and name not in TEMPLATES and name != "index.html":
            raise ValueError("Unknown frontend resource")
        if name not in self._sources:
            self._sources[name] = (self.root / name).read_text(encoding="utf-8")
        return self._sources[name]

    @staticmethod
    def resolve(reference, parent):
        name = reference.removeprefix("/static/") if reference.startswith("/static/") else posixpath.normpath(posixpath.join(posixpath.dirname(parent), reference))
        return name if name in ASSET_TYPES else None

    def version(self, name):
        dependencies = set()

        def visit(current):
            if current in dependencies:
                return
            dependencies.add(current)
            for match in REFERENCE.finditer(self.source(current)):
                child = self.resolve(match["path"], current)
                if child:
                    visit(child)

        visit(name)
        digest = hashlib.sha256()
        for dependency in sorted(dependencies):
            digest.update(dependency.encode() + b"\0" + self.source(dependency).encode() + b"\0")
        return digest.hexdigest()[:16]

    def render(self, name):
        source = self.source(name)
        if name == "index.html":
            def include(match):
                if match[1] not in TEMPLATES:
                    raise ValueError("Unknown frontend template")
                return self.source(match[1])
            source = INCLUDE.sub(include, source)

        def reference(match):
            asset = self.resolve(match["path"], name)
            if not asset:
                return match[0]
            return f'{match["quote"]}/static/{asset}?v={self.version(asset)}{match["quote"]}'

        return REFERENCE.sub(reference, source)
