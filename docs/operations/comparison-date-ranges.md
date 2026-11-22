# Comparison date ranges

Sector Comparison and Industry Comparison (Within Sector and Cross-Sector) use the union of dated observations across the selected datasets. The earliest and latest dates are available regardless of selection order; a stale first series cannot hide newer dates. The default window uses the existing `DEFAULT_DISPLAY_YEARS` setting (two years), clamped to these bounds.

Selecting a different set of series or refreshing data that changes the bounds resets the range to this default. Reordering the same selection and ordinary reruns preserve a manual range. Incomplete input pauses the chart until both endpoints are selected.

The coverage table lists the number of observed rows and their first/last dates in the chosen inclusive range for every selected series. Endpoints do not imply continuous daily coverage. Missing series and series without observations in that range are named explicitly and omitted from chart input. Disjoint histories remain comparable under the union policy; a notice identifies absence of any shared observation date. When the range contains no observations, choose another range or selection. If all selected series lack dated observations, no date selector or chart is shown.

These controls do not fill missing dates, alter indicators, repair stored history, or establish dataset freshness. In smoothed display mode the existing MA series can still be unavailable despite observed raw dates; switch to Raw Ratio to inspect those observations.
