from unittest.mock import create_autospec

import pytest
from fastapi import Request
from sqlalchemy import create_engine

from app import editor, main
from app.keitaro import KeitaroClient, KeitaroError
from utils import migrate


def _binding(offer_id, share):
    return {"offer_id": offer_id, "share": share, "state": "active"}


@pytest.fixture
def keitaro(tmp_path, monkeypatch):
    path = tmp_path / "editor.sqlite3"
    monkeypatch.setattr(migrate, "DATABASE_PATH", path)
    migrate.main()
    engine = create_engine(f"sqlite:///{path}")
    monkeypatch.setattr(editor, "_engine", engine)

    client = create_autospec(KeitaroClient, instance=True)
    client.api_key = "test-key"
    stream = {
        "id": 8,
        "campaign_id": 42,
        "name": "Офферы",
        "schema": "landings",
        "offers": [_binding(18001, 25), _binding(18002, 38), _binding(18003, 37)],
    }
    client.list_campaigns.return_value = [{"id": 42, "name": "Demo"}]
    client.campaign_url.side_effect = KeitaroClient().campaign_url
    client.list_campaign_streams.return_value = [
        {"id": 7, "name": "На Google", "schema": "redirect"},
        stream,
    ]
    client.get_stream.return_value = stream
    client.list_offers.return_value = [{"id": 18004, "name": "Test offer"}]
    client.replace_stream_offers.side_effect = lambda _, offers: stream.update(offers=offers)
    yield client, stream
    engine.dispose()


def _offer_stream(client):
    redirect, offers = editor.fetch_streams(client, 42)
    assert redirect.name == "На Google" and redirect.offers == []
    return offers


def test_add_and_cancel_keep_draft_local_until_push(keitaro):
    client, stream = keitaro
    _offer_stream(client)

    editor.edit_stream(client, 42, 8, "add", 18004)
    draft = _offer_stream(client)
    assert draft.dirty
    assert [offer.share for offer in draft.offers] == [25, 25, 25, 25]
    assert len(stream["offers"]) == 3
    client.replace_stream_offers.assert_not_called()

    editor.edit_stream(client, 42, 8, "cancel")
    assert not _offer_stream(client).dirty
    assert [offer.offer_id for offer in _offer_stream(client).offers] == [18001, 18002, 18003]

    editor.edit_stream(client, 42, 8, "add", 18004)
    editor.edit_stream(client, 42, 8, "push")
    assert not _offer_stream(client).dirty
    client.replace_stream_offers.assert_called_once_with(
        8, [_binding(offer_id, 25) for offer_id in range(18001, 18005)]
    )


def test_removed_offers_stay_available_for_restore_after_publish_and_fetch(keitaro):
    client, stream = keitaro
    _offer_stream(client)

    editor.edit_stream(client, 42, 8, "remove", 18002)
    assert next(offer for offer in _offer_stream(client).offers if offer.offer_id == 18002).removed
    editor.edit_stream(client, 42, 8, "push")
    assert [offer["offer_id"] for offer in stream["offers"]] == [18001, 18003]
    assert next(offer for offer in _offer_stream(client).offers if offer.offer_id == 18002).removed

    stream["offers"].pop()
    assert {offer.offer_id for offer in _offer_stream(client).offers if offer.removed} == {
        18002,
        18003,
    }
    editor.edit_stream(client, 42, 8, "restore", 18003)
    editor.edit_stream(client, 42, 8, "push")
    assert stream["offers"] == [_binding(18001, 50), _binding(18003, 50)]


def test_pinned_shares_stay_fixed_when_rebalancing(keitaro):
    client, _ = keitaro
    _offer_stream(client)
    editor.edit_stream(client, 42, 8, "pin", 18001)
    assert _offer_stream(client).dirty
    editor.edit_stream(client, 42, 8, "add", 18004)
    editor.edit_stream(client, 42, 8, "push")
    editor.edit_stream(client, 42, 8, "remove", 18002)

    active = [offer for offer in _offer_stream(client).offers if not offer.removed]
    assert active[0].pinned
    assert [offer.share for offer in active] == [25, 38, 37]


def test_push_refuses_to_overwrite_external_change(keitaro):
    client, stream = keitaro
    _offer_stream(client)
    editor.edit_stream(client, 42, 8, "add", 18004)
    stream["offers"].pop()

    assert _offer_stream(client).conflict
    with pytest.raises(editor.EditorError, match="Поток изменился"):
        editor.edit_stream(client, 42, 8, "push")
    client.replace_stream_offers.assert_not_called()
    assert _offer_stream(client).dirty
    editor.edit_stream(client, 42, 8, "cancel")
    assert {offer.offer_id for offer in _offer_stream(client).offers if offer.removed} == {18003}


def test_push_can_retry_after_keitaro_applied_a_write_without_returning_a_response(keitaro):
    client, stream = keitaro
    _offer_stream(client)
    editor.edit_stream(client, 42, 8, "add", 18004)

    def lose_response(_, offers):
        stream["offers"] = offers
        raise KeitaroError("Не удалось получить ответ")

    client.replace_stream_offers.side_effect = lose_response
    with pytest.raises(KeitaroError):
        editor.edit_stream(client, 42, 8, "push")

    assert _offer_stream(client).dirty
    editor.edit_stream(client, 42, 8, "push")
    client.replace_stream_offers.assert_called_once()
    assert not _offer_stream(client).dirty


def test_editor_form_adds_selected_offer_and_redirects_to_the_campaign(keitaro, monkeypatch):
    client, _ = keitaro
    monkeypatch.setattr(main, "KeitaroClient", lambda: client)
    request = Request(
        {"type": "http", "path": "/campaigns/edit", "router": main.app.router, "headers": []}
    )
    first = main.campaign_editor(request, 42)
    assert first.status_code == 200
    html = first.body.decode()
    assert "<h1>Demo</h1>" in html and "<h2>Офферы</h2>" in html
    assert "На Google" not in html
    assert 'href="https://keitaro-for-tests.etolegko.com/admin/#!/campaign/42/main"' in html
    client.campaign_url.assert_called_once_with(42)

    response = main.update_campaign_editor(request, 42, 8, "add", "18004 — Test offer")
    assert response.status_code == 303
    assert response.headers["location"].endswith("/campaigns/edit?campaign_id=42")
    html = main.campaign_editor(request, 42).body.decode()
    assert "Есть неопубликованные изменения" in html and "18004" in html


@pytest.mark.parametrize(
    ("command", "offer", "status", "message"),
    [
        ("add", "", 409, "Укажите ID оффера."),
        ("add", "invalid", 422, "Изменение не применено. Проверьте данные формы."),
        ("add", "18099", 404, "Оффер 18099 не найден в Keitaro"),
        ("remove:18099", "", 409, "Оффер не найден в потоке."),
    ],
)
def test_editor_shows_stream_errors_above_add(
    keitaro, monkeypatch, command, offer, status, message
):
    client, _ = keitaro
    client.get_offer.side_effect = KeitaroError("Оффер 18099 не найден в Keitaro", status=404)
    monkeypatch.setattr(main, "KeitaroClient", lambda: client)
    request = Request(
        {"type": "http", "path": "/campaigns/edit", "router": main.app.router, "headers": []}
    )
    _offer_stream(client)

    response = main.update_campaign_editor(request, 42, 8, command, offer)

    html = response.body.decode()
    assert response.status_code == status
    assert html.count(message) == 1
    assert html.index('name="offer"') < html.index(message) < html.index('value="add"')


def test_editor_requires_a_campaign_selection_and_preserves_drafts(keitaro, monkeypatch):
    client, _ = keitaro
    monkeypatch.setattr(main, "KeitaroClient", lambda: client)
    request = Request(
        {"type": "http", "path": "/campaigns/edit", "router": main.app.router, "headers": []}
    )
    selected = main.campaign_editor(request, 42)
    assert "set-cookie" not in selected.headers
    editor.edit_stream(client, 42, 8, "add", 18004)

    client.list_campaign_streams.reset_mock()
    response = main.campaign_editor(request)
    assert response.status_code == 200 and "Выберите кампанию" in response.body.decode()
    client.list_campaign_streams.assert_not_called()

    html = main.campaign_editor(request, 42).body.decode()
    assert "<h1>Demo</h1>" in html and "Есть неопубликованные изменения" in html


def test_editor_can_add_first_offer_to_empty_stream(keitaro, monkeypatch):
    client, stream = keitaro
    stream["offers"] = []
    monkeypatch.setattr(main, "KeitaroClient", lambda: client)
    request = Request(
        {"type": "http", "path": "/campaigns/edit", "router": main.app.router, "headers": []}
    )

    response = main.campaign_editor(request, 42)
    assert response.status_code == 200
    html = response.body.decode()
    assert 'name="stream_id" value="8"' in html and 'name="stream_id" value="7"' not in html
    assert "В потоке пока нет офферов." in html and "18004 — Test offer" in html

    assert main.update_campaign_editor(request, 42, 8, "add", "18004").status_code == 303
    (first_offer,) = _offer_stream(client).offers
    assert (first_offer.offer_id, first_offer.share) == (18004, 100)
    assert main.update_campaign_editor(request, 42, 8, "push").status_code == 303
    client.replace_stream_offers.assert_called_once_with(8, [_binding(18004, 100)])


@pytest.mark.parametrize("has_redirect", [True, False])
def test_editor_shows_offers_section_without_an_offer_stream(keitaro, monkeypatch, has_redirect):
    client, _ = keitaro
    client.list_campaign_streams.return_value = (
        [{"id": 7, "name": "Geo GM", "schema": "redirect"}] if has_redirect else []
    )
    monkeypatch.setattr(main, "KeitaroClient", lambda: client)
    request = Request(
        {"type": "http", "path": "/campaigns/edit", "router": main.app.router, "headers": []}
    )

    response = main.campaign_editor(request, 42)
    html = response.body.decode()
    assert response.status_code == 200 and "<h2>Офферы</h2>" in html
    assert "В кампании нет потока для офферов." in html
    assert "Geo GM" not in html
    client.list_offers.assert_not_called()


def test_editor_shows_publish_after_pinning_and_unpinning(keitaro, monkeypatch):
    client, _ = keitaro
    monkeypatch.setattr(main, "KeitaroClient", lambda: client)
    request = Request(
        {"type": "http", "path": "/campaigns/edit", "router": main.app.router, "headers": []}
    )
    assert 'value="push"' not in main.campaign_editor(request, 42).body.decode()

    assert main.update_campaign_editor(request, 42, 8, "pin:18001").status_code == 303
    assert 'value="push"' in main.campaign_editor(request, 42).body.decode()
    assert main.update_campaign_editor(request, 42, 8, "push").status_code == 303
    assert 'value="push"' not in main.campaign_editor(request, 42).body.decode()
    client.replace_stream_offers.assert_not_called()

    assert main.update_campaign_editor(request, 42, 8, "unpin:18001").status_code == 303
    assert 'value="push"' in main.campaign_editor(request, 42).body.decode()
    assert main.update_campaign_editor(request, 42, 8, "cancel").status_code == 303
    assert _offer_stream(client).offers[0].pinned
