import csv
import math
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
ML_DIR = BASE_DIR / "ml"

FORECAST_WEEKS = ["2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19"]


def load_data():
    sales_rows = list(csv.DictReader(open(DATA_DIR / "sales_history.csv", encoding="utf-8")))
    lead_rows = list(csv.DictReader(open(DATA_DIR / "lead_times.csv", encoding="utf-8")))
    promo_rows = list(csv.DictReader(open(DATA_DIR / "promo_calendar.csv", encoding="utf-8")))
    festival_rows = list(csv.DictReader(open(DATA_DIR / "festival_calendar.csv", encoding="utf-8")))

    lead_skus = [r["sku"].strip() for r in lead_rows]
    lead_times = {r["sku"].strip(): int(r["lead_time_weeks"]) for r in lead_rows}

    # SKU -> list of (week_start, units_sold, promo_flag)
    history_by_sku = defaultdict(list)
    for r in sales_rows:
        history_by_sku[r["sku"].strip()].append((
            r["week_start"].strip(),
            float(r["units_sold"]),
            int(r["promo_flag"]),
        ))

    for s in history_by_sku:
        history_by_sku[s].sort(key=lambda x: x[0])

    # Planned promo flags for forecast weeks: (sku, week_start) -> promo_flag
    forecast_promos = {}
    for r in promo_rows:
        forecast_promos[(r["sku"].strip(), r["week_start"].strip())] = int(r["promo_flag"])

    festivals = [datetime.strptime(r["date"].strip(), "%Y-%m-%d") for r in festival_rows]

    return lead_skus, lead_times, history_by_sku, forecast_promos, festivals


def festival_lift(week_str: str, festivals: list) -> float:
    tw_dt = datetime.strptime(week_str, "%Y-%m-%d")
    for d in festivals:
        days_before = (d - tw_dt).days
        if 0 <= days_before <= 14:
            return 1.25
        elif 15 <= days_before <= 28:
            return 1.10
    return 1.0


def compute_forecast_for_sku(sku: str, history: list, target_weeks: list, planned_promos: dict, festivals: list) -> list:
    """Predicts future weekly sales using depromoted recent baseline,

    SKU-specific promotional elasticity, and festival proximity lift.
    Strictly uses historical observations before target_weeks to prevent leakage.
    """
    promo_sales = [h[1] for h in history if h[2] == 1]
    nonpromo_sales = [h[1] for h in history if h[2] == 0]

    base_avg = (sum(nonpromo_sales) / len(nonpromo_sales)) if nonpromo_sales else (sum(promo_sales) / len(promo_sales) if promo_sales else 1.0)
    promo_avg = (sum(promo_sales) / len(promo_sales)) if promo_sales else (base_avg * 2.04)
    multiplier = (promo_avg / base_avg) if base_avg > 0 else 2.04
    multiplier = max(1.2, min(multiplier, 3.5))

    # Base sales normalized for promo and festival (last 8 weeks)
    depromoted_recent = []
    recent_slice = history[-8:] if len(history) >= 8 else history
    for w, u, p in recent_slice:
        f_lift = festival_lift(w, festivals)
        base_val = (u / multiplier) if p == 1 else u
        base_val = base_val / f_lift
        depromoted_recent.append(base_val)

    if not depromoted_recent:
        base_level = history[-1][1] if history else 0.0
    else:
        weights = [1.0 + 0.1 * i for i in range(len(depromoted_recent))]
        base_level = sum(v * w for v, w in zip(depromoted_recent, weights)) / sum(weights)

    predictions = []
    for tw in target_weeks:
        p_flag = planned_promos.get((sku, tw), 0)
        f_mult = festival_lift(tw, festivals)
        p_mult = multiplier if p_flag == 1 else 1.0
        pred = max(0.0, base_level * p_mult * f_mult)
        predictions.append(round(pred, 1))

    return predictions


def run_chronological_backtests():
    lead_skus, lead_times, history_by_sku, _, festivals = load_data()
    all_weeks = sorted(list(set(w for hist in history_by_sku.values() for w, _, _ in hist)))

    cutoffs = [92, 96, 100]
    models = {
        "Baseline 1 (Last Value)": lambda sku, hist, tw, sp: [hist[-1][1]] * len(tw),
        "Baseline 2 (Recent 4-Wk Avg)": lambda sku, hist, tw, sp: [sum(h[1] for h in hist[-4:]) / len(hist[-4:])] * len(tw),
        "Baseline 3 (Same Wk Last Year)": lambda sku, hist, tw, sp: [
            next((h[1] for h in hist if h[0] == (datetime.strptime(w, "%Y-%m-%d") - timedelta(days=364)).strftime("%Y-%m-%d")), sum(h[1] for h in hist[-4:]) / len(hist[-4:]))
            for w in tw
        ],
        "Proposed (Decomposition + Promo Uplift + Festival)": lambda sku, hist, tw, sp: compute_forecast_for_sku(sku, hist, tw, sp, festivals),
    }

    results = {}
    print("=" * 70)
    print("CHRONOLOGICAL ROLLING-ORIGIN BACKTEST VALIDATION RESULTS (NO LEAKAGE)")
    print("=" * 70)

    for name, model_fn in models.items():
        total_ae = 0.0
        total_actual = 0.0
        sq_err = 0.0
        n = 0

        for c_idx in cutoffs:
            train_weeks = all_weeks[:c_idx]
            test_weeks = all_weeks[c_idx:c_idx + 4]

            for sku in lead_skus:
                hist = [h for h in history_by_sku[sku] if h[0] in train_weeks]
                if not hist:
                    continue

                sp = {(sku, h[0]): h[2] for h in history_by_sku[sku]}
                preds = model_fn(sku, hist, test_weeks, sp)

                actuals = {h[0]: h[1] for h in history_by_sku[sku] if h[0] in test_weeks}
                for tw, pred in zip(test_weeks, preds):
                    if tw in actuals:
                        act = actuals[tw]
                        ae = abs(act - max(0.0, pred))
                        total_ae += ae
                        sq_err += (act - max(0.0, pred)) ** 2
                        total_actual += act
                        n += 1

        wape = (total_ae / total_actual) * 100.0 if total_actual else 0.0
        mae = total_ae / n if n else 0.0
        rmse = math.sqrt(sq_err / n) if n else 0.0
        results[name] = {"WAPE": wape, "MAE": mae, "RMSE": rmse}
        print(f"{name:50s} | WAPE: {wape:6.2f}% | MAE: {mae:6.2f} | RMSE: {rmse:6.2f}")

    print("=" * 70)
    return results


def generate_and_save_forecast():
    lead_skus, lead_times, history_by_sku, forecast_promos, festivals = load_data()

    rows = []
    for sku in lead_skus:
        hist = history_by_sku[sku]
        preds = compute_forecast_for_sku(sku, hist, FORECAST_WEEKS, forecast_promos, festivals)
        for week_start, units in zip(FORECAST_WEEKS, preds):
            rows.append({
                "sku": sku,
                "week_start": week_start,
                "forecast_units": units,
            })

    output_file = ML_DIR / "forecast.csv"
    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["sku", "week_start", "forecast_units"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Successfully generated {len(rows)} forecast rows in {output_file}")
    return len(rows)


if __name__ == "__main__":
    run_chronological_backtests()
    generate_and_save_forecast()
