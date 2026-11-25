# Тестовое задание Keitaro

FastAPI-приложение для создания кампаний Keitaro и редактирования офферов.

## Настройка

Если файла `.env` ещё нет, его нужно создать из example.

```bash
cp .env.example .env
```

В файле `.env` нужно заменить `YOUR_API_KEY_HERE` в переменной `KEITARO_API_KEY` на свой ключ.

Перед первым запуском нужно установить зависимости и применить миграцию из корня проекта.

```bash
uv sync --locked
uv run python -m utils.migrate
```

## Запуск

```bash
uv run --env-file .env uvicorn app.main:app --reload
```

При успешном запуске приложение будет доступно по <http://127.0.0.1:8000/>. На странице должны быть видны `Создать кампанию` и `Редактировать кампанию`.

## Тесты

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Обычные тесты подменяют Keitaro. Интеграционный тест использует ключ из `.env`, создаёт и удаляет тестовую кампанию на стенде. Запускать его нужно отдельно.

```bash
uv run --env-file .env pytest -m integration
```
