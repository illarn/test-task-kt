from app.keitaro import KeitaroClient, KeitaroError

_DOMAIN_ID = 1813
_GROUP_ID = 10332
_TRAFFIC_SOURCE_ID = 836


def create_campaign(client: KeitaroClient, name: str, geo: str, offer_id: int) -> int:
    client.get_offer(offer_id)
    campaign = client.create_campaign(
        name, domain_id=_DOMAIN_ID, group_id=_GROUP_ID, traffic_source_id=_TRAFFIC_SOURCE_ID
    )
    campaign_id = campaign.get("id") if isinstance(campaign, dict) else None
    if not isinstance(campaign_id, int) or campaign_id < 1:
        raise KeitaroError("Keitaro вернул кампанию без ID. Проверьте список кампаний в админке.")

    try:
        client.create_country_redirect_stream(
            campaign_id, country=geo, url="https://google.com", position=1
        )
        client.create_default_offer_stream(campaign_id, offer_id=offer_id, position=2)
    except KeitaroError as error:
        try:
            client.delete_campaign(campaign_id)
        except KeitaroError as cleanup_error:
            raise KeitaroError(
                f"Не удалось настроить потоки и удалить кампанию {campaign_id}. "
                "Проверьте её в админке Keitaro."
            ) from cleanup_error
        raise KeitaroError(
            f"Не удалось настроить потоки. Кампания {campaign_id} удалена."
        ) from error

    return campaign_id
