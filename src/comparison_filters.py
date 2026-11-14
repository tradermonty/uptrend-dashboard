"""Shared union-date selection and explicit observation coverage for comparisons."""
from typing import Callable, Dict, Optional, Sequence, Tuple
from datetime import date

import pandas as pd
import streamlit as st

from src.data_processor import default_start_date, filter_by_date_range


def comparison_date_bounds(
    all_data: Dict[str, pd.DataFrame], selected_keys: Sequence[str]
) -> Optional[Tuple[date, date]]:
    """Return inclusive union bounds over selected dated observations, or None."""
    bounds = []
    for key in selected_keys:
        df = all_data.get(key)
        if df is None or df.empty:
            continue
        dates = df['date'].dropna()
        if not dates.empty:
            bounds.append((dates.min().date(), dates.max().date()))
    if not bounds:
        return None
    return min(lo for lo, _ in bounds), max(hi for _, hi in bounds)


def comparison_date_filter(
    all_data: Dict[str, pd.DataFrame], selected_keys: Sequence[str],
    display_name: Callable[[str], str], widget_key: str,
) -> Dict[str, pd.DataFrame]:
    """Render union date input and coverage; stop rather than chart an empty range.

    Widget dates reset only on selected-set/bounds changes. Observations are
    filtered inclusively without reindexing, filling or interpolating missing dates.
    """
    bounds = comparison_date_bounds(all_data, selected_keys)
    if bounds is None:
        names = ', '.join(display_name(k) for k in selected_keys)
        st.warning(f'No dated observations available for the selected series: {names}.')
        st.stop()
    minimum, maximum = bounds
    context = (tuple(sorted(set(selected_keys))), minimum, maximum)
    context_key = widget_key + '_context'
    if st.session_state.get(context_key) != context or widget_key not in st.session_state:
        st.session_state[widget_key] = (default_start_date(minimum, maximum), maximum)
        st.session_state[context_key] = context
    dates = st.date_input('Date Range', min_value=minimum, max_value=maximum, key=widget_key)
    st.caption('Date bounds use the union of selected series. Coverage lists observed dates and counts; missing observations are not filled.')
    if not dates or len(dates) != 2:
        st.info('Select both a start and end date to compare observations.')
        st.stop()
    start, end = dates
    filtered = {}
    coverage = []
    unavailable = []
    common_dates = None
    for key in selected_keys:
        df = all_data.get(key)
        subset = filter_by_date_range(df, start, end) if df is not None and not df.empty else None
        observed = subset['date'].dropna() if subset is not None else pd.Series(dtype='datetime64[ns]')
        if observed.empty:
            unavailable.append(display_name(key))
            row = {'Series': display_name(key), 'Observations': 0, 'First observed': None, 'Last observed': None}
        else:
            filtered[key] = subset
            row = {'Series': display_name(key), 'Observations': len(observed),
                   'First observed': str(observed.min().date()), 'Last observed': str(observed.max().date())}
        coverage.append(row)
        observed_dates = set(observed.dt.date)
        common_dates = observed_dates if common_dates is None else common_dates & observed_dates
    st.dataframe(pd.DataFrame(coverage), hide_index=True, use_container_width=True)
    if unavailable:
        st.warning('No observations in this range for: ' + ', '.join(unavailable) + '.')
    if not filtered:
        st.warning('No observations in the selected date range. Choose a different range or selection.')
        st.stop()
    if len(selected_keys) > 1 and not common_dates:
        st.info('The selected series have no common observation date in this range; available observations are shown under the union policy.')
    return filtered
