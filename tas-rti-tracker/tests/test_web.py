from datetime import date

from fastapi.testclient import TestClient

from rti_tracker import config
from rti_tracker.applications import create
from rti_tracker.registry import load_registry, sync


def test_routes_render(tmp_path, monkeypatch):
    monkeypatch.setenv("RTI_WEB_USER", "kurt")
    monkeypatch.setenv("RTI_WEB_PASSWORD", "pw")
    config._settings = None
    st = config.Settings(db_path=tmp_path / "w.db", archive_dir=tmp_path / "a")
    monkeypatch.setattr(config, "_settings", st)
    from rti_tracker.web.app import app, conn
    c = conn()
    sync(c, load_registry())
    create(c, authority_id="stt", authority_name=None, lodged=date(2026, 8, 3), accepted=date(2026, 8, 3), scope="coupe plans", reference="R1")
    client = TestClient(app)
    assert client.get("/").status_code == 401  # auth gate
    auth = ("kurt", "pw")
    for path in ["/", "/authorities", "/authority/stt", "/search?q=forest", "/applications", "/applications/1", "/changes", "/campaigns", "/health.json", "/campaigns/forestry/pack.md"]:
        r = client.get(path, auth=auth)
        assert r.status_code == 200, (path, r.status_code, r.text[:200])
    r = client.get("/applications/1", auth=auth)
    assert "What you can do next" in r.text and "s 15" in r.text
    assert client.get("/authority/nope", auth=auth).status_code == 404
    config._settings = None
