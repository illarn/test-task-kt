# Эмулятор Keitaro Admin API

## Что это

Учебный стенд отвечает как Admin API трекера Keitaro в той части, что нужна для задания. Пишите обёртку так, будто ходите в настоящий Keitaro. Поля запросов и ответов описаны в [документации Admin API](https://admin-api.docs.keitaro.io/).

## Как ходить

Войти на стенд можно через GitHub. Логином станет ваш ник. Ключ доступен по кнопке «API ключ» вверху страницы. Передавайте его в заголовке `Api-Key`. Вы видите только свои кампании.

- Адрес API — `https://keitaro-for-tests.etolegko.com/admin_api/v1`
- Ссылка на кампанию в админке — `https://keitaro-for-tests.etolegko.com/admin/#!/campaign/<id>/main`

```bash
curl -H "Api-Key: <ваш ключ>" https://keitaro-for-tests.etolegko.com/admin_api/v1/offers

# Поток «страна → Google»
curl -X POST https://keitaro-for-tests.etolegko.com/admin_api/v1/streams \
  -H "Api-Key: <ваш ключ>" -H "Content-Type: application/json" \
  -d '{"campaign_id": 1, "name": "Geo GM", "type": "regular", "schema": "redirect",
       "action_type": "http", "action_payload": "https://google.com",
       "filters": [{"name": "country", "mode": "accept", "payload": ["GM"]}]}'

# Поток с офферами
curl -X POST https://keitaro-for-tests.etolegko.com/admin_api/v1/streams \
  -H "Api-Key: <ваш ключ>" -H "Content-Type: application/json" \
  -d '{"campaign_id": 1, "name": "Офферы", "type": "default", "schema": "landings",
       "offers": [{"offer_id": 18001, "share": 100, "state": "active"}]}'
```

## Что поддержано

| Метод и путь | Поведение |
| --- | --- |
| `GET /campaigns` | Ваши кампании, новые сверху. Параметры `offset` и `limit`. |
| `POST /campaigns` | Создать кампанию. Поле `name` обязательно. Стенд сгенерирует `alias`, если его не передать. |
| `GET /campaigns/{id}` | Получить одну кампанию. |
| `PUT /campaigns/{id}` | Изменить только переданные поля кампании. |
| `DELETE /campaigns/{id}` | Удалить кампанию вместе с потоками. Удаление без архива. |
| `POST /campaigns/{id}/enable` и `POST /campaigns/{id}/disable` | Включить или выключить кампанию. |
| `GET /campaigns/{id}/streams` | Получить потоки кампании по порядку `position`. |
| `POST /streams` | Создать поток. Поля `campaign_id` и `name` обязательны. |
| `GET /streams/{id}` | Получить один поток с фильтрами и офферами. |
| `PUT /streams/{id}` | Изменить поток. Поле `offers` заменяет состав целиком, поле `filters` — фильтры целиком. |
| `DELETE /streams/{id}` | Удалить поток. |
| `POST /streams/{id}/enable` и `POST /streams/{id}/disable` | Включить или выключить поток. |
| `GET /offers` и `GET /offers/{id}` | Офферы. Только чтение. |
| `GET /groups?type=campaigns` | Группы кампаний. Только чтение. |
| `GET /domains` | Домены. Только чтение. |
| `GET /traffic_sources` | Источники. Только чтение. |

## Что уже есть на стенде

Общий каталог доступен только для чтения.

- 170 офферов
- Домен с ID `1813`
- Группа кампаний `FORTESTS` с ID `10332`
- Источник `FORTESTS` с ID `836`

## Чего нет

- Кликов и статистики. Ссылка кампании никуда не ведёт.
- Лендингов, триггеров, постбэков, отчётов и архива удалённого.
- Справочников `/stream_filters`, `/streams_actions`, `/stream_types`, `/stream_schemas`.
- Остальных путей Admin API. Стенд вернёт на них ошибку.

## Журнал

Раздел «Журнал» показывает время, путь, тело и код ответа каждого запроса вашей обёртки к API. Проверяющий видит тот же журнал.
