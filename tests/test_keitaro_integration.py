from uuid import uuid4

import pytest

from app.campaigns import create_campaign
from app.keitaro import KeitaroClient


@pytest.mark.integration
def test_creates_campaign_on_live_keitaro():
    client = KeitaroClient()
    assert client.api_key, "Set KEITARO_API_KEY in .env and run pytest with uv run --env-file .env"
    name = f"pytest-campaign-{uuid4().hex}"
    campaign_id = create_campaign(client, name, "GM", 18001)

    try:
        path = f"/campaigns/{campaign_id}"
        campaign = client._request("GET", path)
        assert campaign["name"] == name
        assert campaign["domain_id"] == 1813
        assert campaign["group_id"] == 10332
        assert campaign["traffic_source_id"] == 836

        streams = client._request("GET", f"{path}/streams")
        assert [stream["type"] for stream in streams] == ["regular", "default"]
        geo, fallback = [client._request("GET", f"/streams/{stream['id']}") for stream in streams]
        assert geo["schema"] == "redirect"
        assert geo["action_payload"] == "https://google.com"
        (country_filter,) = geo["filters"]
        assert (country_filter["name"], country_filter["mode"], country_filter["payload"]) == (
            "country",
            "accept",
            ["GM"],
        )

        assert fallback["schema"] == "landings"
        (offer,) = fallback["offers"]
        assert (offer["offer_id"], offer["share"], offer["state"]) == (18001, 100, "active")
    finally:
        client.delete_campaign(campaign_id)
