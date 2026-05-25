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
    assert "fetch(\"/imports\"" in js_response.text
    assert "fetch(\"/index\"" in js_response.text
    assert "getJson(\"/index/status\"" in js_response.text
    assert "getJson(\"/sources\"" in js_response.text
    assert "parseSseDataLine" in js_response.text
