from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor


def metrics(actual, predicted):
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    error = predicted - actual
    mae = np.mean(np.abs(error))
    rmse = np.sqrt(np.mean(error ** 2))
    denom = np.sum(np.abs(actual))
    wape = np.sum(np.abs(error)) / denom * 100 if denom else np.nan
    return {"mae_kg": float(mae), "rmse_kg": float(rmse), "wape_pct": float(wape)}


def feature_frame(weekly: pd.DataFrame, use_weather: bool = True) -> pd.DataFrame:
    y = weekly["crop_net_kg"].astype(float)
    x = pd.DataFrame(index=weekly.index)
    crop_lags = [0, 1, 2, 3, 4, 8, 13, 26]
    if len(weekly) >= 120:
        crop_lags.append(52)
    for lag in crop_lags:
        x[f"crop_lag_{lag}"] = y.shift(lag)
    for window in [4, 8, 13, 26]:
        x[f"crop_mean_{window}"] = y.rolling(window, min_periods=max(2, window // 2)).mean()
        x[f"crop_std_{window}"] = y.rolling(window, min_periods=max(2, window // 2)).std()

    weather_base = [
        "rainfall_mm", "air_temp_mean", "air_temp_min", "air_temp_max",
        "humidity_mean", "soil_moisture_mean", "soil_temp_mean",
        "sunshine_duration", "light_mean", "wind_speed_mean",
    ]
    for col in [c for c in weather_base if use_weather and c in weekly.columns]:
        x[f"{col}_lag_0"] = weekly[col]
        x[f"{col}_lag_1"] = weekly[col].shift(1)
        x[f"{col}_mean_4"] = weekly[col].rolling(4, min_periods=2).mean()
        x[f"{col}_mean_13"] = weekly[col].rolling(13, min_periods=6).mean()

    x["crop_days"] = weekly["crop_days"]
    x["weather_days"] = weekly["weather_days"]
    x["origin_week_sin"] = np.sin(2 * np.pi * weekly.index.isocalendar().week.astype(float) / 52.1775)
    x["origin_week_cos"] = np.cos(2 * np.pi * weekly.index.isocalendar().week.astype(float) / 52.1775)
    return x


def _gpu_catboost(random_state=42):
    try:
        from catboost import CatBoostRegressor
    except ImportError as exc:
        raise RuntimeError(
            "GPU forecasting requires CatBoost. Run setup_windows.ps1 after installing the GPU upgrade."
        ) from exc
    return CatBoostRegressor(
        loss_function="RMSE",
        iterations=700,
        depth=6,
        learning_rate=0.035,
        l2_leaf_reg=5.0,
        random_seed=random_state,
        task_type="GPU",
        devices="0",
        verbose=False,
        allow_writing_files=False,
    )


def _candidate_models(random_state=42, use_weather=True, accelerator="cpu"):
    prefix = "Weather + Crop" if use_weather else "Crop"
    candidates = {
        f"{prefix} Gradient Boosting": HistGradientBoostingRegressor(
            loss="squared_error", learning_rate=0.05, max_iter=300,
            max_leaf_nodes=15, min_samples_leaf=10, l2_regularization=1.0,
            random_state=random_state,
        ),
        f"{prefix} Random Forest": RandomForestRegressor(
            n_estimators=350, min_samples_leaf=4, max_features=0.75,
            random_state=random_state, n_jobs=-1,
        ),
    }
    if accelerator == "gpu":
        candidates[f"{prefix} GPU CatBoost"] = _gpu_catboost(random_state=random_state)
    return candidates


@dataclass
class ForecastResult:
    forecast: pd.DataFrame
    backtest: pd.DataFrame
    model_rows: list[dict]


def train_direct_forecasts(
    weekly: pd.DataFrame,
    horizons=(1, 2, 3, 4),
    validation_weeks=26,
    model_dir=None,
    use_weather=True,
    accelerator="cpu",
    minimum_training_weeks=52,
    minimum_validation_weeks=13,
    history_class_override=None,
) -> ForecastResult:
    if accelerator not in {"cpu", "gpu"}:
        raise ValueError("accelerator must be 'cpu' or 'gpu'")
    weather_columns = {
        "rainfall_mm", "air_temp_mean", "air_temp_min", "air_temp_max",
        "humidity_mean", "soil_moisture_mean", "soil_temp_mean",
        "sunshine_duration", "light_mean", "wind_speed_mean",
    }
    use_weather = bool(use_weather and weather_columns.intersection(weekly.columns))
    x_base = feature_frame(weekly, use_weather=use_weather)
    y_series = weekly["crop_net_kg"].astype(float)
    forecasts = []
    all_backtests = []
    model_rows = []

    for horizon in horizons:
        x = x_base.copy()
        target_index = x.index + pd.to_timedelta(7 * horizon, unit="D")
        x["target_week_sin"] = np.sin(2 * np.pi * pd.Index(target_index).isocalendar().week.astype(float) / 52.1775)
        x["target_week_cos"] = np.cos(2 * np.pi * pd.Index(target_index).isocalendar().week.astype(float) / 52.1775)
        y = y_series.shift(-horizon)
        year_ago = y_series.shift(52 - horizon)
        recent_mean = y_series.rolling(4, min_periods=2).mean()
        available_lags = [lag for lag in [52, 26, 13] if f"crop_lag_{lag}" in x.columns]
        required_lag = available_lags[0]
        valid = y.notna() & x[f"crop_lag_{required_lag}"].notna()
        data_x = x.loc[valid]
        data_y = y.loc[valid]
        data_year_ago = year_ago.loc[valid]
        data_recent = recent_mean.loc[valid]
        if minimum_training_weeks < 26:
            raise ValueError("minimum_training_weeks must be at least 26 because the model uses a 26-week crop lag")
        if minimum_validation_weeks < 8:
            raise ValueError("minimum_validation_weeks must be at least 8")
        effective_validation_weeks = min(validation_weeks, len(data_x) - minimum_training_weeks)
        if effective_validation_weeks < minimum_validation_weeks:
            raise ValueError(
                f"Insufficient weekly history for horizon {horizon}: {len(data_x)} usable rows; "
                f"at least {minimum_training_weeks + minimum_validation_weeks} are required."
            )
        split = len(data_x) - effective_validation_weeks
        x_train, x_test = data_x.iloc[:split], data_x.iloc[split:]
        y_train, y_test = data_y.iloc[:split], data_y.iloc[split:]

        crop_only_cols = [
            c for c in data_x.columns
            if c.startswith("crop_") or c.startswith("origin_week_") or c.startswith("target_week_")
        ]
        candidates = {}
        feature_sets = {}
        candidate_models = _candidate_models(use_weather=use_weather, accelerator=accelerator)
        crop_only_candidate_models = {}
        for name, model in candidate_models.items():
            model.fit(x_train, y_train)
            candidates[name] = np.clip(model.predict(x_test), 0, None)
            feature_sets[name] = list(x_train.columns)
        if use_weather:
            for crop_name, crop_model in _candidate_models(
                use_weather=False, accelerator=accelerator
            ).items():
                display_name = crop_name.replace("Crop ", "Crop-Only ", 1)
                crop_model.fit(x_train[crop_only_cols], y_train)
                crop_only_candidate_models[display_name] = crop_model
                candidates[display_name] = np.clip(
                    crop_model.predict(x_test[crop_only_cols]), 0, None
                )
                feature_sets[display_name] = crop_only_cols
        year_ago_values = data_year_ago.iloc[split:].to_numpy(dtype=float)
        if np.isfinite(year_ago_values).all():
            candidates["Same Week Last Year"] = np.clip(year_ago_values, 0, None)
        candidates["Recent 4-Week Mean"] = np.clip(data_recent.iloc[split:].to_numpy(), 0, None)

        scores = {name: metrics(y_test, pred) for name, pred in candidates.items()}
        selected_name = min(scores, key=lambda name: scores[name]["wape_pct"])
        selected_pred = candidates[selected_name]
        residuals = y_test.to_numpy() - selected_pred

        year_backtest = candidates.get("Same Week Last Year", np.full(len(y_test), np.nan))
        for origin, actual, year_pred, recent_pred, selected in zip(
            x_test.index, y_test, year_backtest, candidates["Recent 4-Week Mean"], selected_pred,
        ):
            all_backtests.append({
                "horizon_weeks": horizon,
                "origin_week_ending": origin,
                "target_week_ending": origin + pd.Timedelta(weeks=horizon),
                "actual_kg": actual,
                "selected_prediction_kg": selected,
                "year_ago_prediction_kg": year_pred,
                "recent_mean_prediction_kg": recent_pred,
                "selected_method": selected_name,
            })

        latest_x = x.loc[[x.index.max()]]
        fitted_model_candidates = {**candidate_models, **crop_only_candidate_models}
        if selected_name in fitted_model_candidates:
            final_model = clone(fitted_model_candidates[selected_name])
            selected_features = feature_sets[selected_name]
            final_model.fit(data_x[selected_features], data_y)
            prediction = float(np.clip(final_model.predict(latest_x[selected_features])[0], 0, None))
            if model_dir is not None:
                model_path = Path(model_dir) / f"horizon_{horizon}.joblib"
                temporary_model_path = model_path.with_suffix(".joblib.tmp")
                joblib.dump(
                    {
                        "model": final_model,
                        "features": selected_features,
                        "horizon_weeks": horizon,
                        "selected_method": selected_name,
                    },
                    temporary_model_path,
                )
                temporary_model_path.replace(model_path)
                if temporary_model_path.exists():
                    temporary_model_path.unlink()
        elif selected_name == "Same Week Last Year":
            prediction = float(max(0, y_series.shift(52 - horizon).iloc[-1]))
        else:
            prediction = float(max(0, recent_mean.iloc[-1]))

        if model_dir is not None and selected_name in {"Same Week Last Year", "Recent 4-Week Mean"}:
            stale_model_path = Path(model_dir) / f"horizon_{horizon}.joblib"
            if stale_model_path.exists():
                stale_model_path.unlink()

        lower_resid = float(np.quantile(residuals, 0.10))
        upper_resid = float(np.quantile(residuals, 0.90))
        forecast_origin = x.index.max()
        target_end = forecast_origin + pd.Timedelta(weeks=horizon)
        forecasts.append({
            "horizon_weeks": horizon,
            "forecast_origin_week_ending": forecast_origin,
            "forecast_week_starting": target_end - pd.Timedelta(days=6),
            "forecast_week_ending": target_end,
            "forecast_kg": prediction,
            "lower_80_kg": max(0.0, prediction + lower_resid),
            "upper_80_kg": max(0.0, prediction + upper_resid),
            "selected_method": selected_name,
            "validation_wape_pct": scores[selected_name]["wape_pct"],
        })
        for method, score in scores.items():
            model_rows.append({
                "horizon_weeks": horizon,
                "method": method,
                "selected": method == selected_name,
                **score,
                "training_rows": len(x_train),
                "validation_rows": len(x_test),
                "history_class": (
                    history_class_override
                    if history_class_override
                    else ("standard" if len(x_test) == validation_weeks else "short-history provisional")
                ),
                "accelerator": "GPU" if "GPU CatBoost" in method else "CPU_OR_BASELINE",
                "gpu_candidate_run": accelerator == "gpu",
            })

    return ForecastResult(
        forecast=pd.DataFrame(forecasts),
        backtest=pd.DataFrame(all_backtests),
        model_rows=model_rows,
    )
