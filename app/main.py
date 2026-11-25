from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import (
    BaseModel,
    Field,
    PositiveInt,
    StringConstraints,
    ValidationError,
    field_validator,
)
from sqlalchemy.exc import SQLAlchemyError

from app.campaigns import create_campaign
from app.countries import COUNTRIES
from app.editor import EditorAction, EditorError, edit_stream, fetch_streams
from app.keitaro import KeitaroClient, KeitaroError

app = FastAPI(title="Keitaro Test Task")
templates = Jinja2Templates(directory=Path(__file__).with_name("templates"))

_MISSING_KEY = "Задайте переменную окружения KEITARO_API_KEY и перезапустите приложение"


class CampaignInput(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    geo: str
    offer_id: Annotated[int, Field(gt=0)]

    @field_validator("geo")
    @classmethod
    def validate_geo(cls, value: str) -> str:
        prefix = value.partition(" — ")[0].strip()
        code = prefix.upper()
        if not prefix.isascii() or code not in COUNTRIES:
            raise ValueError("Неизвестный код страны")
        return code


class EditorInput(BaseModel):
    action: EditorAction
    offer_id: PositiveInt | None = None


def _render_form(
    request: Request,
    client: KeitaroClient,
    *,
    values: dict[str, str] | None = None,
    created: int | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    offers = []
    catalog_error = None
    if client.api_key:
        try:
            offers = client.list_offers()
        except KeitaroError as exc:
            catalog_error = str(exc)
    else:
        catalog_error = _MISSING_KEY

    return templates.TemplateResponse(
        request=request,
        name="new_campaign.html",
        context={
            "countries": COUNTRIES,
            "offers": offers,
            "catalog_error": catalog_error,
            "values": values or {},
            "created": created,
            "campaign_url": client.campaign_url(created) if created is not None else None,
            "error": error,
        },
        status_code=status_code,
    )


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/campaigns/new", response_class=HTMLResponse, include_in_schema=False)
def new_campaign(request: Request, created: int | None = None) -> HTMLResponse:
    return _render_form(request, KeitaroClient(), created=created)


@app.get("/campaigns/edit", response_class=HTMLResponse, include_in_schema=False)
def campaign_editor(
    request: Request, campaign_id: Annotated[int | None, Query(gt=0)] = None
) -> HTMLResponse:
    return _render_editor(request, KeitaroClient(), campaign_id)


def _render_editor(
    request: Request,
    client: KeitaroClient,
    campaign_id: int | None,
    *,
    error: str | None = None,
    error_stream_id: int | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    campaigns = []
    streams = []
    offers = []
    has_offer_stream = False
    try:
        if not client.api_key:
            raise KeitaroError(_MISSING_KEY, status=503)
        campaigns = client.list_campaigns()
        if campaign_id is not None:
            streams = [
                stream
                for stream in fetch_streams(client, campaign_id)
                if stream.schema != "redirect"
            ]
            has_offer_stream = any(stream.editable for stream in streams)
            if has_offer_stream:
                offers = client.list_offers()
    except KeitaroError as exc:
        if error is None:
            error, status_code = str(exc), exc.status
    except SQLAlchemyError:
        if error is None:
            error, status_code = "Не удалось загрузить состояние редактора.", 503

    if error_stream_id is not None and not any(
        stream.editable and stream.id == error_stream_id for stream in streams
    ):
        error_stream_id = None
    selected = next((campaign for campaign in campaigns if campaign["id"] == campaign_id), None)
    return templates.TemplateResponse(
        request=request,
        name="campaign_editor.html",
        context={
            "campaigns": campaigns,
            "campaign_id": campaign_id,
            "campaign_name": selected["name"] if selected else None,
            "campaign_url": client.campaign_url(selected["id"]) if selected else None,
            "streams": streams,
            "has_offer_stream": has_offer_stream,
            "offers": offers,
            "offer_names": {offer["id"]: offer["name"] for offer in offers},
            "error": error,
            "error_stream_id": error_stream_id,
        },
        status_code=status_code,
    )


@app.post("/campaigns/edit", response_class=HTMLResponse, include_in_schema=False)
def update_campaign_editor(
    request: Request,
    campaign_id: Annotated[int, Form(gt=0)],
    stream_id: Annotated[int, Form(gt=0)],
    command: Annotated[str, Form()],
    offer: Annotated[str, Form()] = "",
) -> Response:
    client = KeitaroClient()
    action, _, offer_id = command.partition(":")
    if action == "add":
        offer_id = offer.partition(" — ")[0].strip()
    try:
        data = EditorInput.model_validate({"action": action, "offer_id": offer_id or None})
    except ValidationError:
        return _render_editor(
            request,
            client,
            campaign_id,
            error="Изменение не применено. Проверьте данные формы.",
            error_stream_id=stream_id,
            status_code=422,
        )

    try:
        if not client.api_key:
            raise KeitaroError(_MISSING_KEY, status=503)
        edit_stream(client, campaign_id, stream_id, data.action, data.offer_id)
    except (KeitaroError, EditorError) as exc:
        return _render_editor(
            request,
            client,
            campaign_id,
            error=str(exc),
            error_stream_id=stream_id,
            status_code=exc.status if isinstance(exc, KeitaroError) else 409,
        )

    url = request.url_for("campaign_editor").include_query_params(campaign_id=campaign_id)
    return RedirectResponse(url, status_code=303)


@app.post("/campaigns/new", response_class=HTMLResponse)
def campaigns(
    request: Request,
    name: Annotated[str, Form()] = "",
    geo: Annotated[str, Form()] = "",
    offer: Annotated[str, Form()] = "",
) -> Response:
    client = KeitaroClient()
    values = {"name": name, "geo": geo, "offer": offer}
    try:
        data = CampaignInput.model_validate(
            {"name": name, "geo": geo, "offer_id": offer.partition(" — ")[0].strip()}
        )
    except ValidationError:
        return _render_form(
            request,
            client,
            values=values,
            error="Проверьте название кампании, геокод страны и ID оффера.",
            status_code=422,
        )

    try:
        if not client.api_key:
            raise KeitaroError(_MISSING_KEY, status=503)
        campaign_id = create_campaign(client, data.name, data.geo, data.offer_id)
    except KeitaroError as exc:
        return _render_form(request, client, values=values, error=str(exc), status_code=exc.status)

    url = request.url_for("new_campaign").include_query_params(created=campaign_id)
    return RedirectResponse(url, status_code=303)
