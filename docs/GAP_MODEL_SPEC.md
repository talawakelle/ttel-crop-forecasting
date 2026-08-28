# GAP Forecasting Model Specification

## Core rule

No estate or manager is pre-labelled as best practice. Performance must be adjusted for structural and climatic conditions before agricultural practices are compared.

The analytical unit is a **field-week**. Estate forecasts are aggregates of field forecasts.

## Forecast 1 — Your-Practice / Current-Practice Forecast

This forecast answers:

> What crop and profit trajectory is expected if the current estate manager continues the estate's observed agricultural-practice pattern?

Inputs include:

- prior field crop and plucking rounds;
- actual fertilizer and foliar-spray timing, rates and treated area;
- pruning, tipping, weeding, shade, drainage, soil-conservation and protection work;
- employee sundry-work man-days and completion quantities;
- manager assignment period;
- field extent, tea type, age, pruning cycle, elevation, soil and slope;
- weather history and forecast;
- calendar and seasonal effects.

The model uses only information available at the forecast origin. Validation is chronological and estate-aware.

## Forecast 2 — Data-Derived Best-Practice Potential

This is not the forecast of a named high-crop estate. It is a matched, feasible scenario for the same field.

### Step 1: Estimate expected crop without practice claims

Estimate the field's expected kg/ha from structural conditions, weather, seasonality and crop history. This produces a fair baseline.

### Step 2: Measure adjusted performance

Adjusted performance is actual kg/ha minus expected kg/ha. A positive value means the field outperformed its structural and climatic expectation during that period.

### Step 3: Build comparable peer groups

Fields are matched using variables such as:

- elevation and rainfall zone;
- VP, seedling or mixed tea;
- cultivar where available;
- bush/replanting age;
- pruning-cycle stage;
- soil group, slope and shade condition;
- field extent and plucking-round characteristics.

An estate name or manager reputation is never a peer-group variable.

### Step 4: Discover repeatable practice patterns

Within each peer group, identify practice combinations associated with consistently positive adjusted performance across multiple seasons and years. A practice is not promoted from a single crop spike.

Minimum controls:

- adequate sample size;
- repeated performance in different weather conditions;
- no serious negative impact on cost, labour, quality or agronomic compliance;
- approved fertilizer and chemical rates;
- stability when one estate or one manager is removed from training.

### Step 5: Produce the best-practice scenario

Keep the target field's own structural characteristics and forecast weather unchanged. Replace only feasible practice variables with the data-derived peer profile, subject to approved agronomic constraints. Predict crop and profit again.

The difference between this scenario and the current-practice forecast is the **practice opportunity gap**. It is an estimate with uncertainty, not a guaranteed causal uplift.

## Fertilizer and foliar scheduler

The scheduler combines data with hard agronomic rules:

- approved formulation and rate;
- last application and minimum interval;
- pruning-cycle stage;
- soil moisture and rainfall window;
- field accessibility;
- planned and available man-days;
- stock availability;
- planned area and unfinished work;
- agronomist approval status.

The model may recommend the best feasible application window. It must never override an approved agronomic rate or prohibited condition.

## Required validation

1. Time-based holdout: test on later unseen periods.
2. Leave-one-estate-out: confirm the model generalizes beyond the estate that supplied a pattern.
3. Crop-only and weather-only benchmarks: prove that practice variables add predictive value.
4. Manager-transfer check: distinguish manager practice from estate-specific advantage where assignment changes exist.
5. Profit check: reject practice scenarios that raise crop but reduce adjusted profit without an approved strategic reason.
6. Uncertainty: show forecast ranges and data-completeness scores.

## User-facing outputs

- current-practice crop and profit forecast;
- data-derived best-practice potential forecast;
- kg/ha and profit opportunity gap;
- practice differences driving the scenario;
- fertilizer and foliar schedule;
- required labour and cost;
- overdue, incomplete or weather-risk activities;
- confidence and data-quality warnings.

