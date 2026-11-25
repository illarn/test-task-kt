from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from typing import Literal

from sqlalchemy import JSON, Integer, column, select, table
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

from app.database import engine as _engine
from app.keitaro import KeitaroClient

type EditorAction = Literal["add", "remove", "restore", "pin", "unpin", "push", "cancel"]

_stream_state = table(
    "stream_state",
    column("stream_id", Integer),
    column("campaign_id", Integer),
    column("published_offers", JSON),
    column("draft_offers", JSON(none_as_null=True)),
)


class EditorError(ValueError):
    pass


@dataclass(frozen=True)
class _Offer:
    offer_id: int
    share: int = 0
    state: str = "active"
    pinned: bool = False
    removed: bool = False


@dataclass(frozen=True)
class _StreamState:
    published_offers: list[_Offer]
    draft_offers: list[_Offer] | None = None

    @property
    def offers(self) -> list[_Offer]:
        return self.published_offers if self.draft_offers is None else self.draft_offers


@dataclass(frozen=True)
class EditorStream:
    id: int
    name: str
    offers: list[_Offer]
    dirty: bool = False
    conflict: bool = False
    editable: bool = False
    schema: str | None = None


@contextmanager
def _transaction() -> Iterator[Connection]:
    with _engine.begin() as db:
        # Serialize local draft edits with publication, including across processes.
        db.exec_driver_sql("BEGIN IMMEDIATE")
        yield db


def _load(db: Connection, campaign_id: int, stream_id: int) -> _StreamState | None:
    row = db.execute(
        select(_stream_state.c.published_offers, _stream_state.c.draft_offers).where(
            _stream_state.c.campaign_id == campaign_id, _stream_state.c.stream_id == stream_id
        )
    ).one_or_none()
    if row is None:
        return None
    published_offers, draft_offers = row
    return _StreamState(
        [_Offer(**offer) for offer in published_offers],
        None if draft_offers is None else [_Offer(**offer) for offer in draft_offers],
    )


def _save(db: Connection, campaign_id: int, stream_id: int, state: _StreamState) -> None:
    values = {
        "campaign_id": campaign_id,
        "published_offers": [asdict(offer) for offer in state.published_offers],
        "draft_offers": None
        if state.draft_offers is None
        else [asdict(offer) for offer in state.draft_offers],
    }
    db.execute(
        insert(_stream_state)
        .values(stream_id=stream_id, **values)
        .on_conflict_do_update(index_elements=[_stream_state.c.stream_id], set_=values)
    )


def _remote_offers(stream: dict) -> list[_Offer]:
    return [
        _Offer(offer["offer_id"], offer["share"], offer.get("state", "active"))
        for offer in (stream.get("offers") or [])
    ]


def _shares(offers: list[_Offer]) -> dict[int, tuple[int, str]]:
    return {offer.offer_id: (offer.share, offer.state) for offer in offers if not offer.removed}


def _sync(published_offers: list[_Offer], remote: list[_Offer]) -> list[_Offer]:
    pinned = {offer.offer_id for offer in published_offers if offer.pinned}
    present = {offer.offer_id for offer in remote}
    return [replace(offer, pinned=offer.offer_id in pinned) for offer in remote] + [
        replace(offer, removed=True) for offer in published_offers if offer.offer_id not in present
    ]


def fetch_streams(client: KeitaroClient, campaign_id: int) -> list[EditorStream]:
    result = []
    with _transaction() as db:
        for stream in client.list_campaign_streams(campaign_id):
            stream_id = stream["id"]
            source = stream
            if "offers" not in stream and stream.get("schema") == "landings":
                source = client.get_stream(stream_id)
            schema = source.get("schema", stream.get("schema"))
            remote = _remote_offers(source)
            state = _load(db, campaign_id, stream_id)
            if state is None:
                if not remote and schema != "landings":
                    result.append(EditorStream(stream_id, stream["name"], [], schema=schema))
                    continue
                state = _StreamState(remote)
                _save(db, campaign_id, stream_id, state)
            elif state.draft_offers is None:
                synced = _sync(state.published_offers, remote)
                if synced != state.published_offers:
                    state = _StreamState(synced)
                    _save(db, campaign_id, stream_id, state)

            dirty = state.draft_offers is not None
            conflict = state.draft_offers is not None and _shares(remote) not in (
                _shares(state.published_offers),
                _shares(state.draft_offers),
            )
            result.append(
                EditorStream(
                    stream_id,
                    stream["name"],
                    state.offers,
                    dirty,
                    conflict,
                    editable=True,
                    schema=schema,
                )
            )
    return result


def _rebalance(offers: list[_Offer]) -> list[_Offer]:
    active = [offer for offer in offers if not offer.removed and offer.state == "active"]
    if not active:
        return offers
    available = 100 - sum(offer.share for offer in active if offer.pinned)
    flexible = [offer for offer in active if not offer.pinned]
    if available < 0 or (not flexible and available != 0):
        raise EditorError("Доли должны составлять 100%. Открепите один из офферов.")
    if not flexible:
        return offers

    share, extra = divmod(available, len(flexible))
    shares = {offer.offer_id: share + (i < extra) for i, offer in enumerate(flexible)}
    return [replace(offer, share=shares.get(offer.offer_id, offer.share)) for offer in offers]


def _change_offer(
    client: KeitaroClient, state: _StreamState, action: EditorAction, offer_id: int | None
) -> _StreamState:
    if offer_id is None:
        raise EditorError("Укажите ID оффера.")
    offers = state.offers.copy()
    index = next((i for i, offer in enumerate(offers) if offer.offer_id == offer_id), None)
    if action == "add":
        if index is not None:
            if offers[index].removed:
                raise EditorError("Этот оффер в архиве. Используйте «Восстановить».")
            raise EditorError("Оффер уже есть в потоке.")
        client.get_offer(offer_id)
        offers.append(_Offer(offer_id))
    else:
        if index is None:
            raise EditorError("Оффер не найден в потоке.")
        offer = offers[index]
        if action == "restore":
            if not offer.removed:
                raise EditorError("Оффер уже есть в потоке.")
            offers[index] = replace(offer, removed=False)
        elif offer.removed:
            raise EditorError("Оффер в архиве.")
        elif action == "remove":
            if any(item.offer_id == offer_id for item in state.published_offers):
                offers[index] = replace(offer, removed=True)
            else:
                offers.pop(index)
        else:
            if offer.state != "active":
                raise EditorError("Долю можно закрепить только для активного оффера.")
            offers[index] = replace(offer, pinned=action == "pin")

    if action in {"add", "remove", "restore"}:
        offers = _rebalance(offers)
    draft_offers = None if offers == state.published_offers else offers
    return _StreamState(state.published_offers, draft_offers)


def edit_stream(
    client: KeitaroClient,
    campaign_id: int,
    stream_id: int,
    action: EditorAction,
    offer_id: int | None = None,
) -> None:
    try:
        with _transaction() as db:
            state = _load(db, campaign_id, stream_id)
            if state is None:
                raise EditorError("Обновите потоки кампании и выберите поток с офферами.")
            if action == "cancel":
                updated = _StreamState(state.published_offers)
            elif action == "push":
                if state.draft_offers is None:
                    raise EditorError("Нет изменений для публикации.")
                stream = client.get_stream(stream_id)
                if stream["campaign_id"] != campaign_id:
                    raise EditorError("Поток не принадлежит выбранной кампании.")
                remote = _shares(_remote_offers(stream))
                desired = _shares(state.draft_offers)
                if remote != desired:
                    if remote != _shares(state.published_offers):
                        raise EditorError(
                            "Поток изменился в Keitaro. Отмените черновик и обновите потоки."
                        )
                    client.replace_stream_offers(
                        stream_id,
                        [
                            {"offer_id": offer_id, "share": share, "state": offer_state}
                            for offer_id, (share, offer_state) in desired.items()
                        ],
                    )
                updated = _StreamState(state.draft_offers)
            else:
                updated = _change_offer(client, state, action, offer_id)
            _save(db, campaign_id, stream_id, updated)
    except SQLAlchemyError as exc:
        raise EditorError("Не удалось сохранить состояние редактора.") from exc
