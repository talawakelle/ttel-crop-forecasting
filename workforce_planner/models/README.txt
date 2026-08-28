Included:
- productivity_catboost.cbm: approved employee-field productivity forecast.
- productivity_metrics.json: validation, schema and fingerprint metadata.
- selective_hybrid_safety_benchmark.json: build-time architecture smoke benchmark; not a trained RL result.

Not included:
- maskable_ppo_allocator.zip: morning static RL must be retrained and separately approved.
- dynamic_maskable_ppo_reallocator.zip: older full-allocation dynamic RL comparison model.
- selective_hybrid_maskable_ppo.zip: v1.5 selective hybrid RL must be GPU-trained and pass all untouched-test gates.

Approved v1.5 metrics:
- selective_hybrid_training_metrics.json

Rejected v1.5 metrics:
- selective_hybrid_training_rejected.json

Rejected candidates are never silently promoted.

v1.5 rejected-candidate preservation:
- selective_hybrid_rejected_candidate.zip: best selected candidate preserved after a failed safety gate for diagnostics and controlled re-evaluation.
