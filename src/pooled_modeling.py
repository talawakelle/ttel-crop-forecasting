from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor


WEATHER_COLUMNS = [
    "rainfall_mm",
    "air_temp_mean",
    "air_temp_min",
    "air_temp_max",
    "humidity_mean",
    "soil_moisture_mean",
    "soil_temp_mean",
    "sunshine_duration",
    "light_mean",
    "wind_speed_mean",
]


def _metrics(actual, predicted):
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    error = predicted - actual
    denominator = np.abs(actual).sum()
    return {
        "mae_kg": float(np.abs(error).mean()),
        "rmse_kg": float(np.sqrt(np.mean(error ** 2))),
        "wape_pct": float(np.abs(error).sum() / denominator * 100) if denominator else np.nan,
    }


def _candidate_models(random_state=42, accelerator="cpu"):
    candidates = {
        "Gradient Boosting": HistGradientBoostingRegressor(
            loss="squared_error",
            learning_rate=0.05,
            max_iter=300,
            max_leaf_nodes=15,
            min_samples_leaf=12,
            l2_regularization=1.0,
            random_state=random_state,
        ),
        "Random Forest": RandomForestRegressor(
            n_estimators=400,
            min_samples_leaf=4,
            max_features=0.75,
            random_state=random_state,
            n_jobs=-1,
        ),
    }
    if accelerator == "gpu":
        try:
            from catboost import CatBoostRegressor
        except ImportError as exc:
            raise RuntimeError(
                "GPU pooled forecasting requires CatBoost. Run setup_windows.ps1 first."
            ) from exc
        candidates["GPU CatBoost"] = CatBoostRegressor(
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
    return candidates


def _feature_rows(weekly: pd.DataFrame, estate: str, horizon: int) -> pd.DataFrame:
    weekly = weekly.sort_index().copy()
    crop = weekly["crop_net_kg"].astype(float)
    scale = crop.rolling(13, min_periods=6).mean().replace(0, np.nan)
    frame = pd.DataFrame(index=weekly.index)
    frame["estate"] = estate
    frame["origin_week_ending"] = frame.index
    frame["target_week_ending"] = frame.index + pd.to_timedelta(7 * horizon, unit="D")
    frame["scale_kg"] = scale
    frame["log_scale"] = np.log1p(scale)
    for lag in [0, 1, 2, 3, 4, 8, 13]:
        frame[f"crop_ratio_lag_{lag}"] = crop.shift(lag) / scale
    for window in [4, 8, 13]:
        frame[f"crop_mean_ratio_{window}"] = crop.rolling(window, min_periods=max(2, window // 2)).mean() / scale
        frame[f"crop_std_ratio_{window}"] = crop.rolling(window, min_periods=max(2, window // 2)).std() / scale
    frame["crop_days"] = weekly["crop_days"].astype(float)
    frame["crop_records_log"] = np.log1p(weekly["crop_records"].astype(float))
    frame["weather_days"] = weekly.get("weather_days", 0)
    frame["origin_week_sin"] = np.sin(2 * np.pi * frame.index.isocalendar().week.astype(float) / 52.1775)
    frame["origin_week_cos"] = np.cos(2 * np.pi * frame.index.isocalendar().week.astype(float) / 52.1775)
    target_week = pd.DatetimeIndex(frame["target_week_ending"])
    frame["target_week_number"] = target_week.isocalendar().week.to_numpy(dtype=int)
    frame["target_week_sin"] = np.sin(2 * np.pi * frame["target_week_number"] / 52.1775)
    frame["target_week_cos"] = np.cos(2 * np.pi * frame["target_week_number"] / 52.1775)

    for column in [c for c in WEATHER_COLUMNS if c in weekly.columns]:
        values = weekly[column].astype(float)
        frame[f"{column}_lag_0"] = values
        frame[f"{column}_lag_1"] = values.shift(1)
        frame[f"{column}_mean_4"] = values.rolling(4, min_periods=2).mean()
        frame[f"{column}_mean_13"] = values.rolling(13, min_periods=6).mean()

    frame["actual_kg"] = crop.shift(-horizon)
    frame["target_ratio"] = frame["actual_kg"] / scale
    frame["recent_mean_prediction_kg"] = crop.rolling(4, min_periods=2).mean()
    return frame.reset_index(drop=True)


def _feature_columns(frame: pd.DataFrame, use_weather: bool) -> list[str]:
    excluded = {
        "estate",
        "origin_week_ending",
        "target_week_ending",
        "target_week_number",
        "scale_kg",
        "actual_kg",
        "target_ratio",
        "recent_mean_prediction_kg",
    }
    columns = [c for c in frame.columns if c not in excluded]
    if not use_weather:
        columns = [
            c for c in columns
            if not any(c.startswith(f"{weather}_") for weather in WEATHER_COLUMNS)
            and c != "weather_days"
        ]
    return columns


def _prepare_matrix(frame: pd.DataFrame, columns: list[str], medians=None):
    matrix = frame[columns].replace([np.inf, -np.inf], np.nan).astype(float)
    if medians is None:
        medians = matrix.median().dropna()
        columns = [c for c in columns if c in medians.index]
        matrix = matrix[columns]
        medians = medians[columns]
    else:
        columns = list(medians.index)
        matrix = matrix[columns]
    return matrix.fillna(medians), medians


def _balanced_weights(frame: pd.DataFrame, target_estate: str):
    counts = frame.groupby("estate")["estate"].transform("size").astype(float)
    weights = 1.0 / counts
    weights.loc[frame["estate"].eq(target_estate)] *= 2.0
    return (weights / weights.mean()).to_numpy()


def _seasonal_ratio(training: pd.DataFrame, target_week_numbers: pd.Series):
    seasonal = training.groupby("target_week_number")["target_ratio"].median()
    overall = float(training["target_ratio"].median())
    values = []
    for week in target_week_numbers.astype(int):
        nearby = [((week - 2 - 1) % 52) + 1, ((week - 1 - 1) % 52) + 1, week, (week % 52) + 1, ((week + 1) % 52) + 1]
        available = seasonal.reindex(nearby).dropna()
        values.append(float(available.median()) if len(available) else overall)
    return np.asarray(values)


@dataclass
class PooledForecastResult:
    forecast: pd.DataFrame
    metrics: pd.DataFrame
    backtest: pd.DataFrame
    importance: pd.DataFrame


def train_pooled_forecasts(
    estate_weekly: dict[str, pd.DataFrame],
    target_estate: str,
    donor_estates: list[str],
    model_dir: str | Path,
    horizons=(1, 2, 3, 4),
    validation_weeks=13,
    accelerator="cpu",
) -> PooledForecastResult:
    if accelerator not in {"cpu", "gpu"}:
        raise ValueError("accelerator must be 'cpu' or 'gpu'")
    model_dir = Path(model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    target_weekly = estate_weekly[target_estate].sort_index()
    forecast_origin = target_weekly.index.max()
    forecasts = []
    metric_rows = []
    backtests = []
    importance_rows = []

    for horizon in horizons:
        rows = pd.concat(
            [_feature_rows(estate_weekly[estate], estate, horizon) for estate in [target_estate, *donor_estates]],
            ignore_index=True,
            sort=False,
        )
        rows["origin_week_ending"] = pd.to_datetime(rows["origin_week_ending"])
        rows["target_week_ending"] = pd.to_datetime(rows["target_week_ending"])
        valid = rows[
            rows["actual_kg"].notna()
            & rows["target_ratio"].replace([np.inf, -np.inf], np.nan).notna()
            & rows["crop_ratio_lag_13"].notna()
        ].copy()
        target_valid = valid[valid["estate"].eq(target_estate)].sort_values("origin_week_ending")
        if len(target_valid) < validation_weeks + 8:
            raise ValueError(
                f"{target_estate} has only {len(target_valid)} pooled-feature rows for horizon {horizon}; "
                f"at least {validation_weeks + 8} are required."
            )
        validation = target_valid.tail(validation_weeks).copy()
        validation_start = validation["origin_week_ending"].min()
        training = valid[valid["target_week_ending"] < validation_start].copy()
        if target_estate not in set(training["estate"]):
            raise ValueError(f"No pre-validation target-estate observations for {target_estate} horizon {horizon}.")

        candidate_predictions = {}
        fitted_validation = {}
        for use_weather, prefix in [
            (True, "Weather + Crop Pooled"),
            (False, "Crop-Only Pooled"),
        ]:
            columns = _feature_columns(rows, use_weather=use_weather)
            x_train, medians = _prepare_matrix(training, columns)
            x_validation, _ = _prepare_matrix(validation, list(medians.index), medians=medians)
            weights = _balanced_weights(training, target_estate)
            for short_name, model in _candidate_models(accelerator=accelerator).items():
                method = f"{prefix} {short_name}"
                model.fit(x_train, training["target_ratio"].astype(float), sample_weight=weights)
                ratio = np.clip(model.predict(x_validation), 0, None)
                candidate_predictions[method] = ratio * validation["scale_kg"].to_numpy()
                fitted_validation[method] = (model, medians)

        candidate_predictions["Peer Seasonal Index"] = (
            _seasonal_ratio(training, validation["target_week_number"])
            * validation["scale_kg"].to_numpy()
        )
        candidate_predictions["Recent 4-Week Mean"] = validation["recent_mean_prediction_kg"].to_numpy()
        scores = {
            method: _metrics(validation["actual_kg"], prediction)
            for method, prediction in candidate_predictions.items()
        }
        selected_method = min(scores, key=lambda name: scores[name]["wape_pct"])
        selected_validation = np.clip(candidate_predictions[selected_method], 0, None)
        residuals = validation["actual_kg"].to_numpy() - selected_validation

        for method, score in scores.items():
            metric_rows.append({
                "horizon_weeks": horizon,
                "method": method,
                "selected": method == selected_method,
                **score,
                "training_rows": len(training),
                "validation_rows": len(validation),
                "history_class": "short-history pooled provisional",
                "accelerator": "GPU" if "GPU CatBoost" in method else "CPU_OR_BASELINE",
                "gpu_candidate_run": accelerator == "gpu",
            })

        for (_, row), prediction in zip(validation.iterrows(), selected_validation):
            backtests.append({
                "horizon_weeks": horizon,
                "origin_week_ending": row["origin_week_ending"],
                "target_week_ending": row["target_week_ending"],
                "actual_kg": row["actual_kg"],
                "selected_prediction_kg": prediction,
                "year_ago_prediction_kg": np.nan,
                "recent_mean_prediction_kg": row["recent_mean_prediction_kg"],
                "selected_method": selected_method,
            })

        final_training = valid[valid["target_week_ending"] <= forecast_origin].copy()
        forecast_row = _feature_rows(target_weekly, target_estate, horizon).iloc[[-1]].copy()
        if selected_method.startswith("Weather + Crop Pooled") or selected_method.startswith("Crop-Only Pooled"):
            use_weather = selected_method.startswith("Weather + Crop Pooled")
            columns = _feature_columns(rows, use_weather=use_weather)
            x_final, medians = _prepare_matrix(final_training, columns)
            x_forecast, _ = _prepare_matrix(forecast_row, list(medians.index), medians=medians)
            if selected_method.endswith("GPU CatBoost"):
                short_name = "GPU CatBoost"
            elif selected_method.endswith("Random Forest"):
                short_name = "Random Forest"
            else:
                short_name = "Gradient Boosting"
            model = _candidate_models(accelerator=accelerator)[short_name]
            model.fit(
                x_final,
                final_training["target_ratio"].astype(float),
                sample_weight=_balanced_weights(final_training, target_estate),
            )
            ratio_forecast = float(max(0, model.predict(x_forecast)[0]))
            point_forecast = ratio_forecast * float(forecast_row["scale_kg"].iloc[0])
            artifact = {
                "model": model,
                "features": list(medians.index),
                "imputation_medians": medians.to_dict(),
                "horizon_weeks": horizon,
                "selected_method": selected_method,
                "training_mode": "short-history pooled provisional",
                "target_estate": target_estate,
                "donor_estates": donor_estates,
                "normalization": "future crop kg divided by the origin's trailing 13-week mean",
            }
            temporary = model_dir / f"horizon_{horizon}.joblib.tmp"
            joblib.dump(artifact, temporary)
            temporary.replace(model_dir / f"horizon_{horizon}.joblib")
            if hasattr(model, "feature_importances_"):
                for feature, importance in zip(medians.index, model.feature_importances_):
                    importance_rows.append({
                        "horizon_weeks": horizon,
                        "selected_method": selected_method,
                        "feature": feature,
                        "importance": float(importance),
                    })
        elif selected_method == "Peer Seasonal Index":
            point_forecast = (
                _seasonal_ratio(final_training, forecast_row["target_week_number"])[0]
                * float(forecast_row["scale_kg"].iloc[0])
            )
        else:
            point_forecast = float(forecast_row["recent_mean_prediction_kg"].iloc[0])

        low_residual, high_residual = np.quantile(residuals, [0.1, 0.9])
        lower = max(0.0, min(point_forecast, point_forecast + low_residual))
        upper = max(point_forecast, point_forecast + high_residual)
        target_ending = forecast_origin + pd.Timedelta(weeks=horizon)
        forecasts.append({
            "estate": target_estate,
            "horizon_weeks": horizon,
            "forecast_origin_week_ending": forecast_origin,
            "forecast_week_starting": target_ending - pd.Timedelta(days=6),
            "forecast_week_ending": target_ending,
            "forecast_kg": float(max(0, point_forecast)),
            "lower_80_kg": float(lower),
            "upper_80_kg": float(upper),
            "selected_method": selected_method,
            "validation_wape_pct": scores[selected_method]["wape_pct"],
            "forecast_status": "PROVISIONAL POOLED—SHORT ESTATE HISTORY",
        })

    return PooledForecastResult(
        forecast=pd.DataFrame(forecasts),
        metrics=pd.DataFrame(metric_rows),
        backtest=pd.DataFrame(backtests),
        importance=pd.DataFrame(importance_rows),
    )
