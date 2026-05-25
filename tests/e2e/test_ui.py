from fastapi.testclient import TestClient

from app.main import create_app


def test_ui_serves_three_column_workbench() -> None:
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert "Chat" in response.text
    assert "Mindmap" in response.text
    assert "Admin Uploads" in response.text
    assert "selected sources" in response.text.lower()
    assert 'role="tabpanel"' in response.text
    assert 'aria-controls="panel-chat"' in response.text

    css_response = client.get("/static/app.css")
    js_response = client.get("/static/app.js")

    assert css_response.status_code == 200
    assert js_response.status_code == 200
    assert "fetch(\"/chat/stream\"" in js_response.text
    assert "event.event === \"error\"" in js_response.text
    assert "fetch(\"/imports\"" in js_response.text
    assert "fetch(\"/index\"" in js_response.text
    assert "X-KB-Admin-Key" in js_response.text
    assert "getJson(\"/index/status\"" in js_response.text
    assert "getJson(\"/sources\"" in js_response.text
    assert "parseSseDataLine" in js_response.text


def test_ui_exposes_mindmap_on_demand_wiring() -> None:
    client = TestClient(create_app())

    response = client.get("/")
    js_response = client.get("/static/app.js")

    assert response.status_code == 200
    assert 'id="load-mindmap"' in response.text
    assert "getJson(\"/mindmap\"" in js_response.text
    assert "loadMindmap" in js_response.text
    assert "refreshMindmapAfterContentChange" in js_response.text
    init_body = js_response.text.split("function init() {", 1)[1].split("}", 1)[0]
    assert "loadMindmap" not in init_body
