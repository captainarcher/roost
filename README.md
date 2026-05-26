NOTE: I am no longer maintaining this software. I have switched to Guesty - it meets 80% of my needs and provides an option for having an offshore support team handling day-to-day guest communications.

# Roost

Self-hosted vacation rental operations platform.

[![License: Apache 2.0](https://img.shields.io/github/license/captainarcher/roost)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue)](https://www.python.org/)
[![Docker Compose ready](https://img.shields.io/badge/docker--compose-ready-blue?logo=docker)](https://docs.docker.com/compose/)
[![FastAPI 0.115+](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi)](https://fastapi.tiangolo.com/)

Roost automates end-to-end vacation rental operations — from booking notification to accounting entry — with zero manual intervention after initial configuration. It supports multi-platform booking ingestion (Airbnb, VRBO, RVshare, Mercury bank), runs entirely on your own infrastructure via Docker, and requires no cloud services.

## Features

- **Multi-platform booking ingestion** — Airbnb Transaction History CSV, VRBO Payments Report CSV, RVshare manual entry, and Mercury bank statement CSV
- **Double-entry accounting** — automated revenue recognition, chart of accounts, journal entries, and balanced ledger
- **Financial reports** — profit & loss, balance sheet, and income statement with period filtering (YTD, year, quarter, month, date range)
- **Resort compliance automation** — PDF form filling, email submission to resort, urgency tracking, and operator approval workflow
- **Guest communication orchestration** — welcome messages and pre-arrival messages with platform-aware delivery (Airbnb native triggers, VRBO/RVshare operator-assisted)
- **Interactive dashboard** — real-time financial metrics, occupancy charts, booking calendar, and action item queue
- **Natural language query interface** — powered by a local Ollama instance (text-to-SQL with streaming narrative response); optional
- **Config-driven architecture** — all property-specific data lives in YAML config files; no hardcoded values
- **Docker Compose deployment** — single `docker compose up` brings up the API and database

## Screenshots

*Screenshots coming soon — the three primary views are the dashboard (key metrics and occupancy overview), booking detail (guest info, compliance status, communication log), and accounting (journal entries, balances, and financial reports).*

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Ollama (optional — required only for natural language query)

### Setup

**1. Clone the repository:**

```bash
git clone https://github.com/captainarcher/roost.git
cd roost
```

**2. Configure environment variables:**

```bash
cp .env.example .env
```

Edit `.env` and set:
- `POSTGRES_PASSWORD` — choose a secure password
- `DATABASE_URL` — update the password in the URL to match (e.g., `postgresql+psycopg://rental:yourpassword@roost-db:5432/rental_management`)
- SMTP settings — required for resort form email submission

**3. Configure properties:**

```bash
cp config/base.example.yaml config/base.yaml
cp config/config.example.yaml config/{your-property-slug}.yaml
```

Edit `config/base.yaml` with your system-wide settings (Ollama URL, PDF template paths, resort contact name).

Edit `config/{your-property-slug}.yaml` with your property details (slug, display name, lock code, site number, resort contact email, guest communication fields).

To create a new property interactively:

```bash
python manage.py setup
```

**4. Start the system:**

```bash
docker compose up
```

On first start, the database schema is created automatically via Alembic migrations.

**5. Verify:**

```bash
curl http://localhost:8000/health
```

Expected response includes `"status": "ok"`, database status, configured properties, and Ollama availability.

See [docs/deployment.md](docs/deployment.md) for the full deployment walkthrough including SMTP setup, Ollama configuration, and production hardening.

## Documentation

| Document | Description |
|----------|-------------|
| [docs/deployment.md](docs/deployment.md) | Full step-by-step deployment guide |
| [docs/architecture.md](docs/architecture.md) | System design, data flow, and component overview |
| [docs/api.md](docs/api.md) | API reference — workflow-oriented with curl examples |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Development environment, code style, and PR process |
| [CHANGELOG.md](CHANGELOG.md) | Release history |

## Configuration

| File | Purpose | Tracked in git |
|------|---------|----------------|
| `.env` | Database credentials, SMTP credentials, Ollama URL | No — secrets |
| `config/base.yaml` | System-wide settings (Ollama model, archive paths, compliance thresholds) | No — copy from `base.example.yaml` |
| `config/{slug}.yaml` | Per-property settings (one file per property) | No — copy from `config.example.yaml` |
| `config/base.example.yaml` | System-wide settings template | Yes |
| `config/config.example.yaml` | Per-property settings template | Yes |
| `templates/default/` | Default Jinja2 message templates | Yes |
| `templates/{slug}/` | Per-property template overrides (optional) | Yes |
| `pdf_mappings/` | PDF form field mapping schemas (JSON) | Yes |

Config changes require a container restart: `docker compose restart roost-api`

See [docs/deployment.md](docs/deployment.md) for a full walkthrough of every configuration field.

## CLI

```bash
python manage.py setup            # Interactive wizard to create a new property config
python manage.py list-properties  # List all configured properties
```

The setup wizard prompts for all required property fields and writes the YAML config file to `config/`.

## Tech Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, Pydantic Settings
- **Database:** PostgreSQL 16
- **Frontend:** React, Vite, TypeScript, shadcn/ui
- **AI/LLM:** Ollama (local, optional)
- **Container:** Docker, Docker Compose
- **Key libraries:** Polars (CSV ingestion), pypdf (PDF form filling), APScheduler (compliance scheduling), aiosmtplib (email), structlog

## License

Apache 2.0 — see [LICENSE](LICENSE).
