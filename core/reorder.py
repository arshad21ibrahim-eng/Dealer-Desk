import csv
import math
import statistics
from pathlib import Path
from django.conf import settings
from core.models import Product
from core.exceptions import NotFound


FORECAST_CSV_PATH = settings.BASE_DIR / "ml" / "forecast.csv"
LEAD_TIMES_CSV_PATH = settings.DATA_DIR / "lead_times.csv"
SALES_HISTORY_CSV_PATH = settings.DATA_DIR / "sales_history.csv"


class ReorderService:
    def __init__(self):
        self._forecast_data = None
        self._lead_times = None
        self._historical_sigma = None
        self._skus_order = None

    def _load_data_if_needed(self):
        if self._forecast_data is not None:
            return

        # Load lead times
        lead_times = {}
        skus_order = []
        with open(LEAD_TIMES_CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sku = row["sku"].strip()
                skus_order.append(sku)
                lead_times[sku] = int(row["lead_time_weeks"].strip())

        # Load forecast data
        forecast_by_sku = {}
        if FORECAST_CSV_PATH.exists():
            with open(FORECAST_CSV_PATH, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    sku = row["sku"].strip()
                    if sku not in forecast_by_sku:
                        forecast_by_sku[sku] = []
                    forecast_by_sku[sku].append({
                        "week_start": row["week_start"].strip(),
                        "forecast_units": float(row["forecast_units"].strip()),
                    })

        # Load sales history to calculate 12-week sample standard deviation (n-1)
        # Most recent 12 weeks per SKU (all available if fewer than 12)
        sales_by_sku = {}
        with open(SALES_HISTORY_CSV_PATH, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sku = row["sku"].strip()
                if sku in lead_times:
                    if sku not in sales_by_sku:
                        sales_by_sku[sku] = []
                    sales_by_sku[sku].append((row["week_start"].strip(), float(row["units_sold"].strip())))

        sigma_by_sku = {}
        for sku in lead_times:
            rows = sales_by_sku.get(sku, [])
            rows.sort(key=lambda x: x[0])
            recent_12 = [units for _, units in rows[-12:]]
            if len(recent_12) > 1:
                sigma_by_sku[sku] = statistics.stdev(recent_12)
            else:
                sigma_by_sku[sku] = 0.0

        self._lead_times = lead_times
        self._skus_order = skus_order
        self._forecast_data = forecast_by_sku
        self._historical_sigma = sigma_by_sku

    def get_forecast_for_sku(self, sku: str) -> dict:
        self._load_data_if_needed()
        if sku not in self._forecast_data or sku not in self._lead_times:
            raise NotFound(f"No forecast found for SKU '{sku}'")

        weeks_data = self._forecast_data[sku]
        return {
            "sku": sku,
            "forecast": weeks_data,
        }

    def get_reorder_suggestions(self) -> list:
        self._load_data_if_needed()

        # Query live available stock from PostgreSQL database
        live_products = {p.sku: p.stock for p in Product.objects.filter(sku__in=self._skus_order)}

        results = []
        for sku in self._skus_order:
            L = self._lead_times[sku]
            current_stock = live_products.get(sku, 0)

            # Sum forecast units for first L weeks
            forecast_rows = self._forecast_data.get(sku, [])
            # Sort by week_start to ensure exact chronological order
            forecast_rows_sorted = sorted(forecast_rows, key=lambda x: x["week_start"])
            first_L_weeks = forecast_rows_sorted[:L]
            lead_time_demand = round(sum(item["forecast_units"] for item in first_L_weeks), 1)

            sigma = self._historical_sigma.get(sku, 0.0)
            safety_stock = math.ceil(1.65 * sigma * math.sqrt(L))
            reorder_point = round(lead_time_demand + safety_stock, 1)
            reorder_qty = max(0, math.ceil(reorder_point - current_stock))

            results.append({
                "sku": sku,
                "current_stock": current_stock,
                "lead_time_weeks": L,
                "lead_time_demand": lead_time_demand,
                "safety_stock": safety_stock,
                "reorder_point": reorder_point,
                "reorder_qty": reorder_qty,
            })

        return results


reorder_service = ReorderService()
