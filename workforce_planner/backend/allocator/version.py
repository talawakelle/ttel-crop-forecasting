MODEL_SCHEMA_VERSION = 3
DYNAMIC_MODEL_SCHEMA_VERSION = 3
SELECTIVE_HYBRID_MODEL_SCHEMA_VERSION = 5
TRAINING_STRATEGY = "forecast-aware scarcity MaskablePPO v3"
DYNAMIC_TRAINING_STRATEGY = "event-driven two-round MaskablePPO tournament curriculum v3"
SELECTIVE_HYBRID_TRAINING_STRATEGY = (
    "budgeted dynamic-greedy primary planner + calibrated high-confidence MaskablePPO veto gate v2"
)
APPLICATION_VERSION = "1.5.0"
ALLOCATION_STRATEGY = (
    "estate crop-demand forecast + CatBoost employee productivity + "
    "CP-SAT morning plan + budgeted dynamic greedy intraday plan + "
    "calibrated high-confidence RL veto gate with greedy default and conservative fallback"
)
