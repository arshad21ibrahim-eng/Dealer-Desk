Track: aiml

# Deals and Dealers — VIKMO DealerDesk

Deals and Dealers is an AI/ML-track implementation of the VIKMO DealerDesk take-home assignment. It provides a Django REST API for catalogue, inventory, dealers, and draft orders; a Groq-powered dealer assistant using native LLM tool calling; and demand forecasts with live-stock-based reorder suggestions.

The API contract is authoritative for endpoint paths, field names, validation, error codes, forecast dates, and reorder calculations. See [`API_CONTRACT.md`](API_CONTRACT.md).

## Contents

- [Track scope](#track-scope)
- [Technology stack](#technology-stack)
- [Project data](#project-data)
- [Environment configuration](#environment-configuration)
- [Setup and run](#setup-and-run)
- [API overview](#api-overview)
- [Forecasting and reorder logic](#forecasting-and-reorder-logic)
- [Verification and tests](#verification-and-tests)
- [Security notes](#security-notes)
- [Submission video](#submission-video)

## Track scope

The `aiml` track requires A1, C, and D. Optional components are intentionally out of scope so the required work remains the priority.

| Component | Status | Summary |
|---|---|---|
| **A1 — Backend Core** | Implemented | Products, inventory, dealers, draft orders, validation, pagination, consistent error responses, and repeatable `seed_data`. |
| **C — Dealer Assistant** | Implemented | Groq native tool calling with `search_parts`, `check_stock`, and `create_draft_order`; live database grounding for stock and prices; session memory and isolation; and protections against instructions embedded in untrusted catalogue data. |
| **D — Forecasting and Reorder** | Implemented | Forecasts for 40 SKUs over the four contract weeks, historical validation, `ml/forecast.csv` with 160 rows, forecast endpoints, and reorder suggestions based on live stock. |
| **A2 — Order Confirmation Engine** | Optional; not attempted | Optional for the `aiml` track. |
| **B — Supplier Sync** | Optional; not attempted | Optional for the `aiml` track. |
| **E — Frontend UI** | Optional; not attempted | Optional for the `aiml` track. |

## Technology stack

- **Language:** Python 3.11+
- **Backend:** Django (`>=4.2,<6` per `requirements.txt`; locally tested with Django 5.2.18), Django REST Framework (`>=3.15`)
- **Database:** PostgreSQL (hosted Neon PostgreSQL used for development). SQLite is not supported by the assignment.
- **LLM provider:** Groq, using `GROQ_API_KEY` and the configured model `openai/gpt-oss-120b`.
- **LLM integration:** HTTP requests to Groq's OpenAI-compatible chat-completions API with native tool/function calling.
- **Forecasting:** Python-based chronological rolling-origin backtesting and a reproducible forecast-generation script.
- **Timezone:** `Asia/Kolkata`
- **Money:** `Decimal`-based calculations and two-decimal string serialization, as required by the contract.

## Project data

The supplied `data/` directory is retained with its original files:

| File | Purpose |
|---|---|
| `catalogue.csv` | 600 catalogue products and starting stock |
| `dealers.csv` | 25 dealers |
| `sales_history.csv` | Historical weekly sales for the forecast SKUs |
| `promo_calendar.csv` | Known promotional periods for the forecast horizon |
| `lead_times.csv` | Supplier lead times for the 40 forecast SKUs |
| `festival_calendar.csv` | Diwali dates used for seasonal features |

The forecast output is committed at `ml/forecast.csv` with columns `sku`, `week_start`, and `forecast_units`.

## Environment configuration

Python dependencies and settings are loaded from the project environment. Start by copying `.env.example` to `.env` and editing the local values. Never commit `.env` or real credentials.

Example `.env` values (placeholders only):

```dotenv
# Required: use the PostgreSQL connection string for your database.
DATABASE_URL=postgresql://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require

# Generate a private random value for your local environment.
DJANGO_SECRET_KEY=replace-with-a-long-random-secret
DJANGO_DEBUG=0

# Required for the configured Groq assistant.
GROQ_API_KEY=replace-with-your-groq-api-key

# Optional for the aiml track; used only if you work on supplier sync.
SUPPLIER_API_URL=http://127.0.0.1:8099
SUPPLIER_API_KEY=dev-supplier-key
```

`DATABASE_URL`, `DJANGO_SECRET_KEY`, and `GROQ_API_KEY` must be configured for a normal local run. Use the actual PostgreSQL URL issued by your provider. Do not use the example credentials literally.

## Setup and run

Run commands from the repository root, where `manage.py`, `requirements.txt`, and `API_CONTRACT.md` are located.

### 1. Create a virtual environment

**Windows PowerShell:**

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation scripts, either allow activation only in the current session with `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force`, or use the environment's Python executable directly as shown below.

**Linux/macOS:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

With the virtual environment activated:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Without activation on Windows, use:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 3. Configure the environment

Copy `.env.example` to `.env`, then set the real `DATABASE_URL`, `DJANGO_SECRET_KEY`, and `GROQ_API_KEY` values. Keep `.env` local and private.

Windows PowerShell:

```powershell
Copy-Item .env.example .env
notepad .env
```

Linux/macOS:

```bash
cp .env.example .env
```

### 4. Check configuration, migrate, and seed

```bash
python manage.py check
python manage.py migrate --noinput
python manage.py seed_data
python manage.py seed_data
```

`seed_data` is intended to be safe to run more than once without duplicate catalogue products or dealers.

### 5. Start the development server

```bash
python manage.py runserver 0.0.0.0:8000 --noreload
```

The API is then available at `http://localhost:8000/`. The Django development server is for local development and testing, not production deployment.

## API overview

The exact request and response schemas are in `API_CONTRACT.md`. The main required endpoints include:

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/health/` | Health check |
| `GET` | `/api/products/` | Paginated product catalogue with supported filters |
| `POST` | `/api/products/` | Create a product; stock starts at zero |
| `GET` | `/api/products/{sku}/` | Retrieve one product and current stock |
| `PATCH` | `/api/products/{sku}/` | Update supported product fields |
| `PUT` | `/api/inventory/{sku}/` | Set the available inventory quantity |
| `GET` | `/api/dealers/` | Paginated dealer list |
| `POST` | `/api/dealers/` | Create a dealer |
| `GET` | `/api/dealers/{id}/` | Retrieve one dealer |
| `POST` | `/api/orders/` | Create a DRAFT order |
| `GET` | `/api/orders/` | Paginated order list with supported filters |
| `GET` | `/api/orders/{order_number}/` | Retrieve an order |
| `POST` | `/api/assistant/chat/` | Chat with the dealer assistant |
| `GET` | `/api/forecast/{sku}/` | Retrieve four forecast values for a forecast SKU |
| `GET` | `/api/reorder-suggestions/` | Return reorder suggestions for the 40 forecast SKUs |

Errors follow the contract's shared structure:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable error message",
    "details": []
  }
}
```

### Example: product detail

`GET /api/products/BRK-1044/`

```json
{
  "sku": "BRK-1044",
  "name": "Brake Pad Set - Bajaj Pulsar 150",
  "category": "Brakes",
  "brand": "Endurance",
  "vehicle_fitment": "Bajaj Pulsar 150",
  "price": "1459.50",
  "stock": 136,
  "description": "Endurance brake pad set made to fit the Bajaj Pulsar 150. Direct-fit replacement."
}
```

Values in this example illustrate the response shape; live values depend on the current database.

### Example: create a draft order

`POST /api/orders/`

Request:

```json
{
  "dealer_id": 7,
  "items": [
    {"sku": "BRK-1044", "quantity": 3}
  ]
}
```

A successful response is `201 Created` with a `DRAFT` order, current catalogue prices, line subtotals, GST, and totals formatted as decimal strings. Creating a draft order does not deduct stock.

### Example: dealer assistant

`POST /api/assistant/chat/`

Request:

```json
{
  "session_id": "session-dealer-7",
  "dealer_id": 7,
  "message": "Do you have brake pads for a Pulsar 150?"
}
```

The response includes `reply`, `cited_skus`, `tool_calls`, and `actions`. The supported tool names are exactly `search_parts`, `check_stock`, and `create_draft_order`. Prices and stock must be grounded in current database values, and the assistant may create draft orders only.

## Forecasting and reorder logic

### Forecast horizon

The contract requires one forecast row per SKU in `data/lead_times.csv` for each of these weeks:

- `2026-09-28`
- `2026-10-05`
- `2026-10-12`
- `2026-10-19`

This is 40 SKUs × 4 weeks = 160 rows. These dates are fixed by the assignment contract and should not be changed.

### Regenerate forecasts and run backtesting

```bash
python ml/generate_forecast.py
```

The reported chronological rolling-origin backtest metrics are:

| Method | WAPE | MAE | RMSE |
|---|---:|---:|---:|
| Last value baseline | 32.88% | 11.45 | 17.64 |
| Recent 4-week average baseline | 26.80% | 9.34 | 14.50 |
| Same week last year baseline | 32.88% | 11.45 | 17.70 |
| Proposed decomposition + promotion uplift + festival features | **20.06%** | **6.99** | **9.94** |

These metrics should match the latest output from `ml/generate_forecast.py` before submission. Backtesting is chronological; actual sales from the held-out forecast horizon must not be used to train or tune the submitted forecast.

### Reorder calculation

`GET /api/reorder-suggestions/` uses the exact formula in `API_CONTRACT.md` and reads current stock from the database at request time:

1. `L` is the supplier lead time in weeks for the SKU.
2. `lead_time_demand` is the sum of forecast units for the first `L` forecast weeks.
3. `sigma` is the sample standard deviation (`n - 1`) of units sold over the most recent 12 available sales weeks, or all available weeks if fewer than 12 exist.
4. `safety_stock = ceil(1.65 × sigma × sqrt(L))`.
5. `reorder_point = lead_time_demand + safety_stock`.
6. `reorder_qty = max(0, ceil(reorder_point - current_stock))`.

The forecast endpoint returns the same four values recorded in `ml/forecast.csv`. Unknown or non-forecast SKUs must return the contract-required `404` response.

## Verification and tests

Run tests from the repository root. The following results are the recorded local results for this implementation; rerun the commands after any code change and before submission.

### Django test suite

```bash
python manage.py test core --keepdb
```

**Recorded result:** 37 tests passed (`OK`). The reported breakdown is:

- 13 A1 tests for core endpoints, validation, duplicate handling, price validation, and idempotency.
- 16 assistant tests for tool-calling loops, session isolation and memory, text normalization, provider resilience, and prompt-injection defense.
- 8 forecasting/reorder tests for CSV schema and coverage, forecast API parity, not-found behavior, live-stock suggestions, and the contract formula.

These counts and results should match the latest output from your own test run before submission.

### Assignment smoke test

With the Django server running in a separate terminal:

```bash
python smoke_test.py --base-url http://localhost:8000 --track aiml
```

**Recorded result:** 10/10 contract-basic checks passed. The smoke test checks API response shapes and forecast-file structure; it is not a substitute for the full automated tests or the hidden grader.

### Recommended final checks

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test core --keepdb
```

Then start the server and rerun `smoke_test.py`. Also verify the Git working tree and ensure no real secrets are tracked.

## Security notes

- Never commit `.env`, the real `GROQ_API_KEY`, database passwords, or a production `DJANGO_SECRET_KEY`.
- Keep `.env.example` limited to placeholder values.
- PostgreSQL is required by the assignment; SQLite must not be used as a replacement.
- Catalogue names and descriptions are untrusted data, not instructions for the assistant.
- API validation and business rules must be enforced server-side, not delegated to the LLM.

## Submission video

The assignment requires a five-minute video walkthrough that demonstrates the implementation in your own voice, without slides. Recommended coverage:

1. Briefly explain the A1, C, and D architecture.
2. Show the backend models and a draft-order request.
3. Demonstrate the Groq tool-calling flow from the dealer's question to the final reply.
4. Show a real DRAFT order and confirm that creating the draft does not reduce stock.
5. Show the four-week forecast and reorder suggestions.
6. Show the test results and summarize the forecasting validation approach.

URL:https://drive.google.com/file/d/1P4kLZdHCQIvs1nsqH6Gn9PGgMcbnw3j5/view?usp=drivesdk

