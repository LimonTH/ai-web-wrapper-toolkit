# Adding New Web AI Providers

Guide for developers on how to add support for new AI websites.

## Overview

The toolkit uses a **YAML-driven architecture**. Each AI website needs:

1. **YAML config** in [`data/providers/{provider_id}.yaml`](data/providers/) — **обязательно**, единственный источник правды для API сайта
2. **Python adapter** (optional) — только если нужна кастомная логика (RSC decoding, нестандартный формат)

## Quick Path

1. **Create a YAML config** — опишите API сайта (endpoints, body, extract rules)
2. **Create cookie profile** — через UI (Cookies → Browser Login)
3. **Create API key** — через UI (Keys → Create Key)
4. **Test** via `/v1/{provider_id}/chat/completions`

## YAML Config (обязательно)

Создайте файл [`data/providers/{provider_id}.yaml`](data/providers/).

### Формат

```yaml
# data/providers/mysite.yaml
provider_id: mysite            # уникальный slug, используется для routing
name: My AI Site               # отображаемое имя
base_url: https://mysite.com   # базовый URL сайта

endpoints:
  chat:                        # ключ = functional_block
    path: /api/chat/send       # путь эндпоинта (относительно base_url)
    method: POST               # HTTP метод
    headers:                   # опциональные заголовки
      content-type: application/json
    body:                      # шаблон тела запроса
      messages: ${messages}    # ${messages} = body["messages"] из OpenAI запроса
      model: ${body.model}     # ${body.field} = body["field"]
      stream: ${body.stream}   # ${body.stream} = body["stream"]
    extract:                   # правила извлечения ответа
      content:                 # массив fallback-путей JSONPath
        - "$.choices[0].message.content"
        - "$.text"
      stream: "$.choices[0].delta.content"  # JSONPath для SSE-чанков
```

### Синтаксис body

| Синтаксис        | Что даёт                                                      |
|------------------|---------------------------------------------------------------|
| `${messages}`    | `openai_body["messages"]` (сокращение для `${body.messages}`) |
| `${body.model}`  | `openai_body.get("model")`                                    |
| `${body.stream}` | `openai_body.get("stream")`                                   |
| `/${project_id}` | статическая строка с плейсхолдером                            |
| Всё остальное    | статические значения                                          |

### Синтаксис extract (JSONPath)

| Путь             | Что извлекает                                  |
|------------------|------------------------------------------------|
| `"$.key"`        | `data["key"]`                                  |
| `"$.key.subkey"` | `data["key"]["subkey"]`                        |
| `"$.arr[0].key"` | `data["arr"][0]["key"]`                        |
| Массив путей     | fallback'и — первое не-null значение побеждает |

### Поддерживаемые блоки (endpoint keys)

| Блок        | Описание              | OpenAI аналог           |
|-------------|-----------------------|-------------------------|
| `chat`      | Текстовый чат         | `/chat/completions`     |
| `image_gen` | Генерация изображений | `/images/generations`   |
| `tts`       | Text-to-speech        | `/audio/speech`         |
| `stt`       | Speech-to-text        | `/audio/transcriptions` |

### Пример: OpenAI-совместимый API

```yaml
provider_id: my-openai-provider
name: My OpenAI Provider
base_url: https://api.mysite.com

endpoints:
  chat:
    path: /v1/chat/completions
    method: POST
    headers:
      content-type: application/json
      authorization: "Bearer ${body.api_key}"
    body:
      messages: ${messages}
      model: ${body.model}
      stream: ${body.stream}
      temperature: ${body.temperature}
      max_tokens: ${body.max_tokens}
    extract:
      content:
        - "$.choices[0].message.content"
      stream: "$.choices[0].delta.content"
```

### Пример: кастомный формат

```yaml
provider_id: mysite
name: My Custom AI
base_url: https://mysite.com

endpoints:
  chat:
    path: /chat/api/send
    method: POST
    headers:
      content-type: application/json
    body:
      messages: ${messages}
      model: ${body.model}
      stream: ${body.stream}
    extract:
      content:
        - "$.choices[0].message.content"
        - "$.text"
        - "$.content"
      stream: "$.choices[0].delta.content"
```

## Python Adapter (опционально)

Создавайте Python-адаптер **только если** нужна кастомная логика, которую нельзя выразить в YAML (например, декодинг RSC, нестандартные форматы ответа).

Файл: [`src/proxy/providers/adapters/{provider_id}.py`](src/proxy/providers/adapters/)

```python
from src.proxy.providers.base import BaseProviderAdapter
from src.proxy.providers.registry import register_adapter


@register_adapter
class MySiteAdapter(BaseProviderAdapter):
    provider_id = "mysite"          # должно совпадать с provider_id в YAML
    provider_name = "My AI Site"
    url_pattern = "mysite.com"      # legacy: для auto-mapping
    supports = {"chat"}

    # Всё! build_payload, extract_content, extract_stream_chunk —
    # дефолтные из BaseProviderAdapter, который читает YAML.

    # Если нужна кастомная логика — переопределите метод:
    # def build_payload(self, endpoint_key, body, block="chat") -> dict:
    #     ...
```

### Когда нужен Python-адаптер

- Декодинг RSC (React Server Components) из streaming-ответа
- Нестандартный формат запроса/ответа (protobuf, XML)
- Необходимость агрегировать несколько эндпоинтов
- Любая логика, не выразимая через `${body.field}` и JSONPath

## Запись API через Recorder

Если сайт уже работает, но вы не знаете точный формат эндпоинтов:

1. Создайте минимальный адаптер + YAML (хотя бы `provider_id` и `base_url`)
2. Создайте cookie profile через **Cookies** → **Browser Login**
3. Перейдите в **Recorder**, выберите провайдера и профиль
4. Нажмите **Start Recording**
5. Выполните действия на сайте, закройте браузер
6. Recorder автоматически экспортирует [`data/providers/{provider_id}.yaml`](data/providers/) с сырыми эндпоинтами
7. Отредактируйте YAML вручную: добавьте `extract`, `body` с `${...}`, удалите лишние эндпоинты

## Auto-discovery

На старте сервера:

1. Сканируются все `data/providers/*.yaml` → создаются `ProviderConfig`
2. Сканируются Python-адаптеры в [`src/proxy/providers/adapters/`](src/proxy/providers/adapters/)
3. Адаптеры линкуются с YAML-конфигами по `provider_id`
4. В UI отображаются только провайдеры, у которых есть YAML

## Тестирование

```bash
uv run python -m src.main

curl http://localhost:8000/v1/mysite/chat/completions \
  -H "Authorization: Bearer wsk_live_xxx" \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello"}],"stream":false}'
```

## Существующие конфиги

- [`v0.yaml`](data/providers/v0.yaml) — V0 by Vercel (кастомный формат)
- [`deepseek.yaml`](data/providers/deepseek.yaml) — DeepSeek (OpenAI-совместимый)
