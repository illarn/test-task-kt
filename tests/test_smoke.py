import pytest
from fastapi import Request

from app.keitaro import KeitaroClient
from app.main import app, campaign_editor, index, new_campaign


@pytest.mark.parametrize("page", [index, new_campaign, campaign_editor])
def test_smoke(page, monkeypatch):
    monkeypatch.setenv("KEITARO_API_KEY", "test-key")
    monkeypatch.setattr(
        KeitaroClient, "list_offers", lambda self: [{"id": 18001, "name": "Test offer"}]
    )
    monkeypatch.setattr(KeitaroClient, "list_campaigns", lambda self: [])
    path = app.url_path_for(page.__name__)
    request = Request({"type": "http", "path": path, "router": app.router, "headers": []})

    assert page(request).status_code == 200
