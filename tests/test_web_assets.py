"""SPA asset delivery must not fall back to index.html for missing resources."""
from tg_forwarder.web.app import create_app


def test_missing_dist_reports_build_instruction(tmp_path):
    client = create_app(None, tmp_path / "missing").test_client()
    response = client.get("/")
    assert response.status_code == 503
    assert response.json["error"] == "frontend_not_built"


def test_missing_assets_and_api_are_404(tmp_path):
    (tmp_path / "index.html").write_text("<html>test</html>")
    client = create_app(None, tmp_path).test_client()
    for path in ("/api/missing", "/assets/missing.css", "/unknown", "/.env"):
        assert client.get(path).status_code == 404


def test_cross_origin_login_is_rejected():
    client = create_app(None).test_client()
    response = client.post("/api/auth", json={"password": ""}, headers={"Origin": "https://other.invalid"})
    assert response.status_code == 403
