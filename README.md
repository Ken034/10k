# SEC Financial Analyst Agent

An agentic web app for Mulerun that monitors SEC EDGAR for new 10-K and 20-F filings and provides AI-powered qualitative + quantitative analysis for any US-listed ticker.

## Features

- **Dark-themed professional UI** with ticker search and a "10-K / 20-F released this week" feed.
- **Qualitative analysis** via Qwen LLM:
  - History & development of the company.
  - Business description by segment.
  - MD&A operating-factor analysis with financial evidence.
- **Quantitative analysis** — 15 years of audited financials pulled directly from SEC EDGAR, validated with Pydantic, color-coded green/red.
- **Industry routing** — regular companies vs. banking/insurance use separate financial templates.
- **CAGR summary** — 5/10/15-year compound growth.
- **Background pre-fetch** — caches S&P 500 companies daily.
- **PostgreSQL storage** with analyst-friendly views.

## Tech Stack

- Backend: Python 3.11+, FastAPI, SQLAlchemy 2 (async), asyncpg, Pydantic v2, APScheduler, OpenAI client for Qwen.
- Frontend: React 18, Tailwind CSS, Vite, react-markdown.
- Data: SEC EDGAR API (`data.sec.gov`).
- Database: PostgreSQL 15.
- Deployment: Single Docker container.

## Quick Start (Local)

1. Copy environment file and fill in your values:
   ```bash
   cp .env.example .env
   ```

2. Update `.env`:
   - `SEC_USER_AGENT` — your name and email (required by SEC).
   - `QWEN_BASE_URL` — your DashScope / ModelStudio endpoint.
   - `QWEN_API_KEY` — your API key.
   - `QWEN_MODEL` — model/deployment name (default: `qwen-plus`).

3. Start with Docker Compose:
   ```bash
   docker-compose up --build
   ```

4. Open http://localhost:8000.

## Manual Development

### Backend

```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r backend/requirements.txt
cd backend
DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/sec_analyst" uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The Vite dev server proxies `/api` to `http://localhost:8000`.

## Deploying on Mulerun

1. Build the Docker image:
   ```bash
   docker build -t sec-analyst:latest .
   ```

2. Push to your container registry (Docker Hub, GitHub Container Registry, etc.).

3. On Mulerun, create a new VM/app and configure environment variables from `.env`.

4. Run the container, exposing port `8000`.

5. Mulerun should serve the app at the VM's public URL.

## Data Sources & Reliability

- All financial numbers come from `data.sec.gov` XBRL Company Facts API.
- Metrics are validated with Pydantic before storage/display.
- Missing XBRL data is shown as gray/blank rather than estimated.
- "Long-term debt" is defined as short-term debt + long-term debt/loan, per user specification.

## Notes

- SEC EDGAR requires a descriptive `User-Agent` header.
- The free SEC API is rate-limited; the app uses polite delays.
- LLM qualitative analysis depends on the configured Qwen endpoint.
