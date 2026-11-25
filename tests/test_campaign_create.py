from unittest.mock import ANY, call, patch

import pytest
from fastapi import Request

from app.campaigns import create_campaign
from app.keitaro import KeitaroClient, KeitaroError
from app.main import CampaignInput, app, campaigns


@pytest.fixture
def keitaro():
    client = KeitaroClient()
    with patch.object(client, "_request") as transport:
        yield client, transport


@pytest.mark.parametrize("geo", ["gm", "GM — Гамбия"])
def test_campaign_form_accepts_country_code_and_suggestion(geo):
    assert CampaignInput(name="Demo", geo=geo, offer_id=18001).geo == "GM"


@pytest.mark.parametrize(("geo", "offer"), [("XX", "18001"), ("GM", "0")])
def test_campaign_form_rejects_invalid_input(monkeypatch, geo, offer):
    monkeypatch.setenv("KEITARO_API_KEY", "")
    request = Request(
        {"type": "http", "path": "/campaigns/new", "router": app.router, "headers": []}
    )
    with patch("app.main.create_campaign") as create:
        response = campaigns(request, "Demo", geo, offer)

    assert response.status_code == 422
    create.assert_not_called()


def test_creates_campaign_with_geo_redirect_then_default_offer(keitaro):
    client, transport = keitaro
    transport.side_effect = [{}, {"id": 42}, {}, {}]

    campaign_id = create_campaign(client, "Demo", "GM", 18001)

    assert campaign_id == 42
    assert transport.call_args_list == [
        call("GET", "/offers/18001", not_found=ANY),
        call(
            "POST",
            "/campaigns",
            {
                "name": "Demo",
                "type": "position",
                "domain_id": 1813,
                "group_id": 10332,
                "traffic_source_id": 836,
            },
        ),
        call(
            "POST",
            "/streams",
            {
                "campaign_id": 42,
                "name": "Geo GM",
                "type": "regular",
                "position": 1,
                "schema": "redirect",
                "action_type": "http",
                "action_payload": "https://google.com",
                "filters": [{"name": "country", "mode": "accept", "payload": ["GM"]}],
            },
        ),
        call(
            "POST",
            "/streams",
            {
                "campaign_id": 42,
                "name": "Офферы",
                "type": "default",
                "position": 2,
                "schema": "landings",
                "offers": [{"offer_id": 18001, "share": 100, "state": "active"}],
            },
        ),
    ]


def test_missing_offer_stops_before_creating_campaign(keitaro):
    client, transport = keitaro
    transport.side_effect = KeitaroError("Оффер не найден", status=404)

    with pytest.raises(KeitaroError) as raised:
        create_campaign(client, "Demo", "GM", 18001)

    assert raised.value.status == 404
    assert transport.call_count == 1


def test_campaign_without_id_stops_before_creating_streams(keitaro):
    client, transport = keitaro
    transport.side_effect = [{}, {}]

    with pytest.raises(KeitaroError):
        create_campaign(client, "Demo", "GM", 18001)

    assert transport.call_count == 2


@pytest.mark.parametrize("cleanup_error", [None, KeitaroError("Сбой удаления")])
def test_stream_failure_attempts_to_remove_incomplete_campaign(keitaro, cleanup_error):
    client, transport = keitaro
    stream_error = KeitaroError("Сбой потока")
    transport.side_effect = [{}, {"id": 42}, {}, stream_error, cleanup_error]

    with pytest.raises(KeitaroError) as raised:
        create_campaign(client, "Demo", "GM", 18001)

    assert transport.call_args == call("DELETE", "/campaigns/42")
    assert raised.value.__cause__ is (cleanup_error or stream_error)
