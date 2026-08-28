# TTE Workforce Planner v2 — Multi-Estate Integration Layer

This layer extends the preserved Clarendon v1.5 pilot into a controlled 33-estate programme. It does not copy the Clarendon model into other estates and it does not authorize live employee movement.

## Components

- `config/estate_source_manifest.csv` — 33 canonical plantation/estate identities and source locations.
- `config/estate_alias_mapping.csv` — controlled spelling aliases; IDs remain authoritative.
- `scripts/audit_multi_estate.py` — streaming source audit with privacy-safe aggregate outputs.
- `backend/multi_estate/registry.py` — canonical identity and cross-estate isolation.
- `backend/multi_estate/crop_adapter.py` — crop-demand bridge that rejects stale or incomplete forecasts.
- `backend/multi_estate/contracts.py` — operational categories, lifecycle gates and immutable safety ceilings.
- `audit/` — the checkpoint readiness results used by the integrated portal.

## Estate lifecycle

1. Data and identity audit.
2. Estate-specific deterministic model comparison using chronological validation and an untouched test.
3. Conservative planner simulation against current crop demand.
4. Optional RL evaluation only as a high-confidence accept/veto gate.
5. Shadow mode with manager and supervisor review.
6. Controlled live use only after estate-specific approval.

The deterministic budgeted dynamic greedy planner is always the intraday fallback. GPU or RL training is not authorized by a data audit.

## Required daily inputs not present in the crop archives

- actual attendance and leave;
- skills, medical or legal restrictions;
- supervisor and task eligibility;
- field-level crop and sundry-work demand;
- completed work and approved reassignment outcomes.

Until these inputs are connected, the portal reports readiness and demand gates but does not generate an executable daily employee movement list.

