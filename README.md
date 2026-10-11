Track: aiml

# Deals and Dealers — VIKMO DealerDesk Take-Home Assignment

Deals and Dealers is an enterprise dealership management and parts intelligence platform built for the VIKMO DealerDesk take-home assignment on the **AI / ML track (`aiml`)**.

---

## 1. Track Scope and Implementation Status

Per the assignment specification for Track `aiml`, the scope focuses on backend correctness, native LLM tool calling, and chronological demand forecasting:

| Component | Status | Details |
|---|---|---|
| **A1 — Backend Core** | **Implemented** | Relational PostgreSQL schema, Product catalogue (600 items), Inventory adjustments, Dealer management (25 dealers), DRAFT order creation with tax & validation, uniform contract error formatting, and idempotent `seed_data`. |
| **C — Dealer Assistant** | **Implemented** | Conversational parts assistant with genuine native LLM tool/function calling (`search_parts`, `check_stock`, `create_draft_order`), live database stock/price grounding, multi-turn session isolation, and untrusted data prompt-injection defense. |
| **D — Forecasting & Reorder** | **Implemented** | Chronological rolling-origin backtested demand forecasting for 40 SKUs across the 4 contract weeks (`ml/forecast.csv`, 160 rows), and `GET /api/reorder-suggestions/` using live stock and contract formula. |
| **A2 — Order Confirmation Engine** | *Not Attempted* | Optional for `aiml` track per contract §2. |
| **B — Supplier Sync** | *Not Attempted* | Optional for `aiml` track per contract §2. |
| **E — Frontend UI** | *Not Attempted* | Optional for `aiml` track per brief. |

---

## 2. Technical Stack and Environment

* **Language & Framework:** Python 3.11+, Django 5.2+, Django REST Framework 3.15+
* **Database:** PostgreSQL only (tested on hosted Neon PostgreSQL; SQLite is prohibited)
* **Time Zone:** `Asia/Kolkata`
* **Currency:** Indian Rupee (INR) with pure Decimal 2-decimal string representation (`"1459.50"`)
* **LLM Provider:** Groq (`openai/gpt-oss-120b` or `llama-3.3-70b-versatile`) / Google Gemini (`gemini-1.5-flash`) / OpenAI (`gpt-4o-mini`) / Anthropic (`claude-3-5-haiku-20241022`). Native function calling over HTTP using standard schemas.

### Required Environment Variables

Documented in `.env.example`:
```bash
# Database connection string (PostgreSQL only)
DATABASE_URL=postgres://user:pass@host:5432/dealerdesk

# Django Secret Key & Debug
DJANGO_SECRET_KEY=dev-only-secret-key
DJANGO_DEBUG=0

# Supplier API (Optional for aiml track)
SUPPLIER_API_URL=http://127.0.0.1:8099
SUPPLIER_API_KEY=dev-supplier-key

# LLM Provider Key (set one of the following; the grader provides its own key)
GEMINI_API_KEY=
GROQ_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
```

---

## 3. Installation and Setup

### A. Clone and Install Dependencies
```bash
python -m venv .venv
source .venv/bin/activate       # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### B. Environment Configuration
Copy `.env.example` to `.env` and configure `DATABASE_URL` and your LLM provider key:
```bash
cp .env.example .env
```

### C. Database Migration & Seeding
```bash
python manage.py migrate --noinput
python manage.py seed_data
python manage.py seed_data       # Safe to run repeatedly; verified zero duplicates
```

### D. Run Application (Grader Command)
```bash
python manage.py runserver 0.0.0.0:8000 --noreload
```

---

## 4. Verification and Test Results

### A. Automated Django Test Suite Against PostgreSQL
```bash
python manage.py test core --keepdb
```
**Result:** 22/22 tests passed (OK).
* 10 tests for A1 core endpoints, validation errors, duplicate keys (409), and idempotency.
* 8 tests for C assistant tools, multi-step LLM tool-calling loops, session isolation, and prompt injection defense.
* 4 tests for D forecast schema, 160-row count, 4-week date horizon, live-stock reorder suggestions, and exact contract formula.

### B. Smoke Test Verification
```bash
python smoke_test.py --base-url http://localhost:8000 --track aiml
```
**Result:** 10/10 checks passed:
* `[PASS]` GET /api/health/
* `[PASS]` GET /api/products/ (pagination, fields, 600 seeded)
* `[PASS]` GET /api/products/{sku}/ and 404 error shape
* `[PASS]` Dealers: list (25 seeded) and create
* `[PASS]` PUT /api/inventory/{sku}/
* `[PASS]` POST /api/orders/ creates a DRAFT (shape, money format)
* `[PASS]` Validation error shape (empty items)
* `[PASS]` POST /api/assistant/chat/ (response shape only)
* `[PASS]` ml/forecast.csv (columns, 160 rows, weeks)
* `[PASS]` GET /api/forecast/{sku}/ and /api/reorder-suggestions/ (shape only)

### C. Forecast Generation Command
To regenerate and backtest the forecast model:
```bash
python ml/generate_forecast.py
```
**Backtest Metrics (Chronological Rolling-Origin Backtests across 3 horizons):**
* Baseline 1 (Last Value): WAPE = 32.88%, MAE = 11.45, RMSE = 17.64
* Baseline 2 (Recent 4-Wk Avg): WAPE = 26.80%, MAE = 9.34, RMSE = 14.50
* Baseline 3 (Same Wk Last Year): WAPE = 32.88%, MAE = 11.45, RMSE = 17.70
* Proposed Decomposition + Promo Uplift + Festival: **WAPE = 20.06%, MAE = 6.99, RMSE = 9.94**

---

## 5. Verified Endpoint Examples

### 1. Product Detail (`GET /api/products/BRK-1044/`)
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

### 2. Create Draft Order (`POST /api/orders/`)
**Request:**
```json
{
  "dealer_id": 7,
  "items": [{"sku": "BRK-1044", "quantity": 3}]
}
```
**Response (201 Created):**
```json
{
  "order_number": "ORD-20261011-0001",
  "dealer_id": 7,
  "status": "DRAFT",
  "items": [
    {
      "sku": "BRK-1044",
      "name": "Brake Pad Set - Bajaj Pulsar 150",
      "quantity": 3,
      "unit_price": "1459.50",
      "line_subtotal": "4378.50",
      "line_tax": "788.13",
      "line_total": "5166.63"
    }
  ],
  "subtotal": "4378.50",
  "tax_total": "788.13",
  "grand_total": "5166.63",
  "created_at": "2026-10-11T18:03:43+05:30",
  "updated_at": "2026-10-11T18:03:43+05:30"
}
```

### 3. Dealer Assistant (`POST /api/assistant/chat/`)
**Request:**
```json
{
  "session_id": "session-dealer-7",
  "dealer_id": 7,
  "message": "Do you have brake pads for a Pulsar 150?"
}
```
**Response (200 OK):**
```json
{
  "reply": "Yes, we have the Endurance Brake Pad Set (BRK-1044) for Bajaj Pulsar 150 in stock. Current price is ₹1459.50 with 136 units available.",
  "cited_skus": ["BRK-1044"],
  "tool_calls": [
    {"name": "search_parts", "arguments": {"query": "brake pads", "vehicle": "Bajaj Pulsar 150"}},
    {"name": "check_stock", "arguments": {"skus": ["BRK-1044"]}}
  ],
  "actions": []
}
```

### 4. Reorder Suggestions (`GET /api/reorder-suggestions/`)
**Response (200 OK):**
```json
{
  "results": [
    {
      "sku": "FIL-1016",
      "current_stock": 20,
      "lead_time_weeks": 3,
      "lead_time_demand": 117.4,
      "safety_stock": 25,
      "reorder_point": 142.4,
      "reorder_qty": 123
    }
  ]
}
```

---

## 6. Video Walkthrough Link
* Status: Pending recording by user.
