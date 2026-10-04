"""Frontend delivery checks without Telegram or production storage."""
import re
from pathlib import Path
from html.parser import HTMLParser
import pytest
from aiohttp.test_utils import TestClient, TestServer
from src.web_server import WebServer
from src.web_assets import ASSET_TYPES, WebAssets


@pytest.mark.asyncio
async def test_frontend_modules_and_styles_are_versioned_and_public():
    server = WebServer(None, None)
    async with TestClient(TestServer(server.create_app())) as client:
        response = await client.get("/")
        html = await response.text()
        assert response.headers["Cache-Control"] == "no-store"
        assert "<!-- include:" not in html
        assert 'type="module"' in html
        pending = re.findall(r'["\'](/static/[^"\']+)["\']', html)
        seen = set()
        while pending:
            url = pending.pop()
            if url in seen:
                continue
            seen.add(url)
            assert re.search(r"\?v=[a-f0-9]{16}$", url)
            response = await client.get(url)
            assert response.status == 200
            assert response.headers["Cache-Control"] == "no-cache"
            text = await response.text()
            pending.extend(re.findall(r'["\'](/static/[^"\']+)["\']', text))
        assert {url.split("?")[0].removeprefix("/static/") for url in seen} == set(ASSET_TYPES)
        for name in ("index.html", "views/tasks.html", "dialogs/task.html", "js/missing.js", "js/../../.env"):
            assert (await client.get("/static/" + name)).status == 404


def test_nested_module_change_versions_importers(tmp_path):
    (tmp_path / "js").mkdir()
    (tmp_path / "app.js").write_text('import { get } from "./js/core.js";')
    (tmp_path / "js/core.js").write_text('export const get = () => "old";')
    (tmp_path / "app.css").write_text("body { color: black; }")
    before = WebAssets(tmp_path)
    script_version = before.version("app.js")
    css_version = before.version("app.css")
    (tmp_path / "js/core.js").write_text('export const get = () => "new";')
    after = WebAssets(tmp_path)
    assert after.version("app.js") != script_version
    assert after.version("app.css") == css_version
    assert after.render("app.js") == f'import {{ get }} from "/static/js/core.js?v={after.version("js/core.js")}";'


def test_composed_page_has_unique_ids_and_valid_static_element_references():
    root = Path(__file__).resolve().parents[1] / "src/static"
    class Elements(HTMLParser):
        ids = []
        def handle_starttag(self, tag, attrs):
            self.ids.extend(value for key, value in attrs if key == "id")
    parser = Elements()
    parser.feed(WebAssets(root).render("index.html"))
    assert len(parser.ids) == len(set(parser.ids))
    refs = set()
    for file in (root / "app.js", *sorted((root / "js").glob("*.js"))):
        refs.update(re.findall(r'\bget\("([^"]+)"\)', file.read_text()))
    assert refs <= set(parser.ids), refs - set(parser.ids)
