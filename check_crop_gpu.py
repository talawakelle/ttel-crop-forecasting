from __future__ import annotations

import json

import numpy as np
from catboost import CatBoostRegressor


def main() -> None:
    rng = np.random.default_rng(42)
    x = rng.normal(size=(256, 12))
    y = 2000 + x[:, 0] * 125 - x[:, 1] * 80 + rng.normal(0, 20, 256)
    model = CatBoostRegressor(
        iterations=10,
        depth=4,
        loss_function="RMSE",
        task_type="GPU",
        devices="0",
        verbose=False,
        allow_writing_files=False,
        random_seed=42,
    )
    model.fit(x, y)
    prediction = model.predict(x[:4])
    if not np.isfinite(prediction).all():
        raise RuntimeError("GPU smoke-test predictions are not finite")
    print(json.dumps({
        "status": "PASS",
        "engine": "CatBoost GPU",
        "device": "CUDA GPU 0",
        "smoke_test_rows": len(x),
    }, indent=2))


if __name__ == "__main__":
    main()

