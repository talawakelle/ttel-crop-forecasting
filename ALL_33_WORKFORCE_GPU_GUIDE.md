# All-33-Estate Workforce Productivity GPU Candidates

This batch trains a separate CatBoost productivity candidate for each of the 33
estate accounts. It does not copy Clarendon's employee profile, model or policy
to another estate. Employee aliases, fields, divisions, temporal splits and
untouched tests remain estate-specific.

Run it only after `CHECK_ALL_33_GPU_RESULTS.ps1` confirms the crop batch has
finished. The script refuses to start while the crop GPU candidate run is
incomplete.

Alternatively, start `START_ALL_33_WORKFORCE_PRODUCTIVITY_GPU.ps1` with
`-WaitForCrop` in a second PowerShell window. It keeps the PC awake, waits for
the crop batch and starts only after the crop summary contains 33 PASS results.

The output is written to
`workforce_planner\v2\model_candidates\productivity_gpu_<timestamp>`. Existing
Clarendon models and the live portal are not replaced.

The crop archives support productivity-model comparison. They do not contain
confirmed daily attendance, leave, skills, medical/legal restrictions, future
field work demand or supervisor approvals. Consequently, this batch does not
authorize 33 live RL allocation policies. Approved productivity candidates must
still pass deterministic planning, safety and estate-specific shadow mode.

The batch keeps Windows awake during model preparation and training. In the
morning, run `CHECK_ALL_33_WORKFORCE_PRODUCTIVITY_RESULTS.ps1` to view approved,
rejected and failed candidates. Accuracy rejection is an expected safety result,
not a reason to force a model into service.
