import json
import os
from http.client import HTTPException, HTTPSConnection
from typing import Any

_KEITARO_HOST = "keitaro-for-tests.etolegko.com"


class KeitaroError(Exception):
    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


class KeitaroClient:
    def __init__(self) -> None:
        self.api_key = os.getenv("KEITARO_API_KEY", "").strip()

    def list_offers(self) -> list[dict]:
        return self._request("GET", "/offers")

    def get_offer(self, offer_id: int) -> dict:
        return self._request(
            "GET", f"/offers/{offer_id}", not_found=f"Оффер {offer_id} не найден в Keitaro"
        )

    def list_campaigns(self) -> list[dict]:
        campaigns = []
        while True:
            page = self._request("GET", f"/campaigns?offset={len(campaigns)}&limit=100")
            campaigns.extend(page)
            if len(page) < 100:
                return campaigns

    def list_campaign_streams(self, campaign_id: int) -> list[dict]:
        return self._request(
            "GET", f"/campaigns/{campaign_id}/streams", not_found="Кампания не найдена"
        )

    def get_stream(self, stream_id: int) -> dict:
        return self._request("GET", f"/streams/{stream_id}", not_found="Поток не найден")

    def replace_stream_offers(self, stream_id: int, offers: list[dict]) -> None:
        self._request(
            "PUT", f"/streams/{stream_id}", {"offers": offers}, not_found="Поток не найден"
        )

    def create_campaign(
        self, name: str, *, domain_id: int, group_id: int, traffic_source_id: int
    ) -> dict:
        payload = {
            "name": name,
            "type": "position",
            "domain_id": domain_id,
            "group_id": group_id,
            "traffic_source_id": traffic_source_id,
        }
        return self._request("POST", "/campaigns", payload)

    def create_country_redirect_stream(
        self, campaign_id: int, *, country: str, url: str, position: int
    ) -> dict:
        payload = {
            "campaign_id": campaign_id,
            "name": f"Geo {country}",
            "type": "regular",
            "position": position,
            "schema": "redirect",
            "action_type": "http",
            "action_payload": url,
            "filters": [{"name": "country", "mode": "accept", "payload": [country]}],
        }
        return self._request("POST", "/streams", payload)

    def create_default_offer_stream(
        self, campaign_id: int, *, offer_id: int, position: int
    ) -> dict:
        payload = {
            "campaign_id": campaign_id,
            "name": "Офферы",
            "type": "default",
            "position": position,
            "schema": "landings",
            "offers": [{"offer_id": offer_id, "share": 100, "state": "active"}],
        }
        return self._request("POST", "/streams", payload)

    def delete_campaign(self, campaign_id: int) -> None:
        self._request("DELETE", f"/campaigns/{campaign_id}")

    def campaign_url(self, campaign_id: int) -> str:
        return f"https://{_KEITARO_HOST}/admin/#!/campaign/{campaign_id}/main"

    def _request(
        self, method: str, path: str, payload: dict | None = None, *, not_found: str | None = None
    ) -> Any:
        headers = {
            "Accept": "application/json",
            "Api-Key": self.api_key,
            "User-Agent": "KeitaroCampaignCreator/0.1",
        }
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode()

        connection = HTTPSConnection(_KEITARO_HOST, timeout=10)
        try:
            connection.request(method, f"/admin_api/v1{path}", body, headers)
            with connection.getresponse() as response:
                if response.status == 404 and not_found is not None:
                    raise KeitaroError(not_found, status=404)
                if not 200 <= response.status < 300:
                    raise KeitaroError(f"Keitaro: {method} {path} вернул HTTP {response.status}")
                data = response.read()
                return json.loads(data) if data else None
        except (OSError, HTTPException, ValueError) as error:
            raise KeitaroError(f"Не удалось получить ответ Keitaro на {method} {path}") from error
        finally:
            connection.close()
