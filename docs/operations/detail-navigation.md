# Detail-page navigation

Selecting an industry from Sector Detail or the Industry Heatmap opens that exact industry and changes the Industry Detail sector filter to its parent sector. For example, selecting Semiconductors switches an existing Healthcare filter to Technology and displays Semiconductors. Returning to an already visited detail page applies the new target as well.

Sector summary chart/table selections likewise open the requested sector in Sector Detail, overriding an earlier detail selection. Ordinary manual choices remain in effect on reruns until the user changes them or follows a new navigation target.

Without a navigation request, changing the industry sector filter retains the selected industry when it still belongs to the available options. Otherwise the selector chooses the first industry in display-name order. All Sectors makes every configured industry selectable.

A configured target with no data remains selected and displays a no-data warning naming that target; the page does not show another industry's metrics as a substitute. Invalid or obsolete navigation requests produce a warning and are cleared so the user can select a valid target. Stale saved selector values recover to valid options.

This change affects selection and navigation only. It does not alter market data, calculations, DB/CSV files or the existing freshness/session policies. Navigation tests use synthetic data and do not establish live data freshness.
