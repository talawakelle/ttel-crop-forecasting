# Calsay provisional forecast status

## Decision

Calsay is suitable for a provisional crop-and-weather trend model using the recovered 2021–2025 workbooks. It is not suitable for a current 2026 forecast or the GAP best-practice scenario until the complete 2026 crop workbook and practice data are supplied.

## Archive finding

The uploaded `Calsay_output(1).zip` is truncated inside `Calsay_2026.xlsx` and has no ZIP central directory. The 2021–2025 workbook streams were complete and recovered without modifying their contents. The incomplete 2026 stream was excluded.

## Source quality

- Crop rows: 524,305
- Crop date range: 2021-04-01 to 2025-12-30
- Divisions: 2
- Fields: 31
- Duplicate weighing IDs removed: 0
- Zero or negative net-weight rows: 0
- Annual reconciliation difference: 0 kg for every recovered year
- Weather coverage: 92.68% across the TRI-TW station history
- Joined complete weeks: 248
- Weeks with fewer than five observed weather days: 13

## Provisional validation

| Horizon | Selected method | Validation WAPE |
| --- | --- | ---: |
| Week 1 | Weather + crop gradient boosting | 19.93% |
| Week 2 | Crop-only random forest | 21.16% |
| Week 3 | Crop-only random forest | 23.54% |
| Week 4 | Weather + crop random forest | 21.64% |

These errors are based on the most recent 26-week chronological holdout. They are evidence of pilot performance, not guarantees.

## Required next inputs

1. Recreated or re-uploaded complete Calsay 2026 crop archive.
2. Confirmed Calsay-to-weather-station mapping.
3. Field master with hectares, elevation, tea type, bush age and pruning cycle.
4. Fertilizer and foliar application dates, rates and products.
5. Manager diary events and sundry-work man-days.
6. Monthly financial data if profit impact is required.
