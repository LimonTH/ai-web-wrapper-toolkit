# AI Web Wrapper Toolkit

Turn any AI website into an OpenAI-compatible API.

## What It Does

Transforms web-based AI interfaces (ChatGPT, Claude, DeepSeek, and others) into fully-functional OpenAI-compatible agents accessible via standard API endpoints.

## Quick Start

```bash
# Install dependencies
uv sync

# Run the server
uv run python -m src.main
```

### Docker

```bash
docker build -t ai-web-wrapper .
docker run -p 8000:8000 -v ./data:/app/data ai-web-wrapper
```

## Usage

Set your OpenAI client to point to the proxy:

```bash
export OPENAI_BASE_URL=http://localhost:8000/v1
export OPENAI_API_KEY=wsk_live_xxx  # Your virtual key
```

Provider-specific endpoints also available:

```bash
# Direct provider routing (bypasses key resolution)
curl http://localhost:8000/v1/<site-provider>/chat/completions
```

## Core Components

| Component     | Purpose                                                                    |
|---------------|----------------------------------------------------------------------------|
| **Providers** | Registered adapters for AI websites (ChatGPT, Claude, DeepSeek, etc.)      |
| **Cookies**   | Authentication profiles with login sessions captured via Playwright        |
| **Recorder**  | Browser-based action recorder for reverse-engineering site APIs            |
| **Proxy**     | OpenAI-compatible `/v1/chat/completions` endpoint that routes to providers |

### Adding a new provider

See the **[developer guide](docs/ADDING_PROVIDERS.md)** for step-by-step instructions on creating adapters for new AI websites.

## Tech Stack

- **Backend**: FastAPI + Uvicorn + SQLAlchemy + Pydantic v2
- **Automation**: Playwright (browser login)
- **HTTP**: httpx (proxy forwarding)
- **UI**: Jinja2 + HTMX + Alpine.js
- **Auth**: python-jose (JWT for virtual keys)

## License

MIT