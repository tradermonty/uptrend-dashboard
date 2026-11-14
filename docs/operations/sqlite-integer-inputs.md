# SQLite count/total input contract

Both `DBClient.upsert_raw_data()` and `upsert_bulk()` accept typed Python/NumPy integers and finite whole-valued Python/NumPy floats. Booleans (including NumPy bools), missing/non-finite values, fractions, numeric strings, Decimal/Fraction/complex objects, NumPy duration scalars (including NaT) and values outside SQLite's signed 64-bit range are rejected with `ValueError` before writing. Counts must also be non-negative and no greater than total. The largest accepted count/total is `2**63 - 1`.

Every accepted value is converted to an exact native Python `int` before binding. NumPy integers therefore use SQLite INTEGER, not BLOB. Integer inputs above `2**53` remain exact; they are not routed through float conversion. A float already rounded to `2**63` is out of range, even if it was constructed by converting `2**63 - 1` to float.

Bulk input must have one each of `date`, `worksheet`, `count` and `total`. Duplicate required column names are ambiguous and rejected. Duplicate/non-default/MultiIndex row labels are supported; values are validated and bound by row position. Duplicate primary keys still follow input row order, with the last row replacing earlier rows for the same `(date, worksheet)`.

Compatibility change: bulk-only automatic numeric-string conversion is removed. Callers must validate/convert external text explicitly before invoking the DB API, applying their own source format and error policy. Existing collection and Excel-import producers supply typed numeric values. Do not use blanket float conversion: it can round large integers and may turn booleans into numbers before validation sees them. When constructing mixed-type DataFrames, preserve integer/object dtypes where exact large values matter; the DB layer cannot recover precision lost by the caller beforehand.

The entire batch is validated before opening its write transaction. An invalid final row cannot replace an existing row or leave an earlier insertion behind. SQL execution failures also roll back the complete transaction. These protections apply to future API writes; DB initialization behavior is unchanged.

No schema migration or historical BLOB repair is performed by this change. Existing invalid rows require a separately reviewed provenance/backup/correction plan (Issue #8); opening a DB must not silently reinterpret or rewrite them. Raw `sqlite3` checks such as `SELECT typeof(count), typeof(total) FROM uptrend_raw` can distinguish storage types, but storage type alone does not establish a row's correct values or source.
