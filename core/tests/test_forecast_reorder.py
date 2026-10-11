import csv
import math
from pathlib import Path
from django.conf import settings
from django.test import TestCase
from rest_framework.test import APIClient
from core.models import Product


class ForecastAndReorderTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.forecast_path = settings.BASE_DIR / "ml" / "forecast.csv"
        self.lead_times_path = settings.DATA_DIR / "lead_times.csv"

        # Ensure a forecast SKU exists in DB
        self.fsku = "FIL-1016"
        self.product = Product.objects.create(
            sku=self.fsku,
            name="Air Filter Element",
            category="Filters",
            brand="Elofic",
            vehicle_fitment="Bajaj Pulsar 150",
            price="450.00",
            stock=20,
        )

    def test_forecast_file_schema_and_rows(self):
        self.assertTrue(self.forecast_path.exists(), "ml/forecast.csv must exist")

        with open(self.forecast_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames)
            self.assertEqual(fieldnames[:3], ["sku", "week_start", "forecast_units"])
            rows = list(reader)

        self.assertEqual(len(rows), 160, "ml/forecast.csv must contain exactly 160 rows")

        lead_skus = set(r["sku"].strip() for r in csv.DictReader(open(self.lead_times_path, encoding="utf-8")))
        self.assertEqual(len(lead_skus), 40)

        expected_weeks = ["2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19"]
        seen_pairs = set()

        for r in rows:
            sku = r["sku"]
            w = r["week_start"]
            u = float(r["forecast_units"])

            self.assertIn(sku, lead_skus)
            self.assertIn(w, expected_weeks)
            self.assertGreaterEqual(u, 0.0, "forecast_units must be non-negative")
            self.assertNotIn((sku, w), seen_pairs, "Duplicate SKU-week pair found")
            seen_pairs.add((sku, w))

        self.assertEqual(len(seen_pairs), 160)

    def test_get_forecast_endpoint(self):
        res = self.client.get(f"/api/forecast/{self.fsku}/")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertEqual(data["sku"], self.fsku)
        self.assertEqual(len(data["forecast"]), 4)

        weeks = [item["week_start"] for item in data["forecast"]]
        self.assertEqual(weeks, ["2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19"])

        # Unknown / non-forecast SKU -> 404 NOT_FOUND
        res_404 = self.client.get("/api/forecast/NON-EXISTENT-SKU/")
        self.assertEqual(res_404.status_code, 404)
        self.assertEqual(res_404.json()["error"]["code"], "NOT_FOUND")

    def test_reorder_suggestions_endpoint(self):
        res = self.client.get("/api/reorder-suggestions/")
        self.assertEqual(res.status_code, 200)
        data = res.json()

        self.assertIn("results", data)
        results = data["results"]
        self.assertEqual(len(results), 40, "Must return exactly 40 reorder suggestion items")

        first = results[0]
        for field in ("sku", "current_stock", "lead_time_weeks", "lead_time_demand", "safety_stock", "reorder_point", "reorder_qty"):
            self.assertIn(field, first)

        self.assertIsInstance(first["current_stock"], int)
        self.assertIsInstance(first["lead_time_weeks"], int)
        self.assertIsInstance(first["safety_stock"], int)
        self.assertIsInstance(first["reorder_qty"], int)
        self.assertGreaterEqual(first["reorder_qty"], 0)

        # Verify formula consistency
        self.assertAlmostEqual(first["reorder_point"], round(first["lead_time_demand"] + first["safety_stock"], 1))
        expected_qty = max(0, math.ceil(first["reorder_point"] - first["current_stock"]))
        self.assertEqual(first["reorder_qty"], expected_qty)

    def test_reorder_suggestions_reacts_to_live_stock(self):
        # Initial call
        res1 = self.client.get("/api/reorder-suggestions/").json()
        item1 = next(it for it in res1["results"] if it["sku"] == self.fsku)
        initial_stock = item1["current_stock"]

        # Update inventory to 500 (ample stock)
        self.client.put(f"/api/inventory/{self.fsku}/", {"quantity": 500, "reason": "Restocked"}, format="json")

        res2 = self.client.get("/api/reorder-suggestions/").json()
        item2 = next(it for it in res2["results"] if it["sku"] == self.fsku)
        self.assertEqual(item2["current_stock"], 500)
        self.assertEqual(item2["reorder_qty"], 0)

        # Update inventory to 0 (stockout)
        self.client.put(f"/api/inventory/{self.fsku}/", {"quantity": 0, "reason": "Stockout"}, format="json")

        res3 = self.client.get("/api/reorder-suggestions/").json()
        item3 = next(it for it in res3["results"] if it["sku"] == self.fsku)
        self.assertEqual(item3["current_stock"], 0)
        self.assertEqual(item3["reorder_qty"], math.ceil(item3["reorder_point"]))

    def test_forecast_endpoint_returns_exact_csv_values(self):
        csv_rows = []
        with open(self.forecast_path, "r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["sku"].strip() == self.fsku:
                    csv_rows.append({
                        "week_start": r["week_start"].strip(),
                        "forecast_units": float(r["forecast_units"].strip()),
                    })

        res = self.client.get(f"/api/forecast/{self.fsku}/")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["sku"], self.fsku)
        self.assertEqual(data["forecast"], csv_rows)

    def test_forecast_endpoint_non_forecast_sku_in_catalogue_returns_404(self):
        # Create a valid catalogue product that is NOT one of the 40 forecast SKUs
        non_forecast_sku = "CAT-NONFORECAST-01"
        Product.objects.create(
            sku=non_forecast_sku,
            name="Non Forecast Part",
            category="Accessories",
            brand="Generic",
            vehicle_fitment="Universal",
            price="999.00",
            stock=10,
        )

        res = self.client.get(f"/api/forecast/{non_forecast_sku}/")
        self.assertEqual(res.status_code, 404)
        err = res.json().get("error", {})
        self.assertEqual(err.get("code"), "NOT_FOUND")

    def test_reorder_formula_exact_calculation_against_data_files(self):
        import statistics

        sales_history_path = settings.DATA_DIR / "sales_history.csv"

        # Read lead time L
        L = None
        with open(self.lead_times_path, "r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["sku"].strip() == self.fsku:
                    L = int(r["lead_time_weeks"].strip())
                    break
        self.assertIsNotNone(L)

        # Read forecast units for first L weeks
        forecast_weeks = []
        with open(self.forecast_path, "r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["sku"].strip() == self.fsku:
                    forecast_weeks.append((r["week_start"].strip(), float(r["forecast_units"].strip())))
        forecast_weeks.sort(key=lambda x: x[0])
        expected_ltd = round(sum(units for _, units in forecast_weeks[:L]), 1)

        # Read sales history for SKU and calculate sigma over most recent 12 weeks
        sales = []
        with open(sales_history_path, "r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["sku"].strip() == self.fsku:
                    sales.append((r["week_start"].strip(), float(r["units_sold"].strip())))
        sales.sort(key=lambda x: x[0])
        recent_12 = [u for _, u in sales[-12:]]
        sigma = statistics.stdev(recent_12) if len(recent_12) > 1 else 0.0

        expected_safety_stock = math.ceil(1.65 * sigma * math.sqrt(L))
        expected_reorder_point = round(expected_ltd + expected_safety_stock, 1)

        prod = Product.objects.get(sku=self.fsku)
        expected_reorder_qty = max(0, math.ceil(expected_reorder_point - prod.stock))

        res = self.client.get("/api/reorder-suggestions/").json()
        item = next(it for it in res["results"] if it["sku"] == self.fsku)

        self.assertEqual(item["lead_time_weeks"], L)
        self.assertEqual(item["lead_time_demand"], expected_ltd)
        self.assertEqual(item["safety_stock"], expected_safety_stock)
        self.assertEqual(item["reorder_point"], expected_reorder_point)
        self.assertEqual(item["reorder_qty"], expected_reorder_qty)

    def test_reorder_suggestions_contains_all_40_forecast_skus_in_order(self):
        lead_skus = []
        with open(self.lead_times_path, "r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                lead_skus.append(r["sku"].strip())

        res = self.client.get("/api/reorder-suggestions/").json()
        returned_skus = [it["sku"] for it in res["results"]]
        self.assertEqual(len(returned_skus), 40)
        self.assertEqual(returned_skus, lead_skus)
