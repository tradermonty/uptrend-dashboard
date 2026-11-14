"""Issue #7: preserve exact SQLite INTEGER values and atomic bulk semantics."""

from contextlib import closing
from decimal import Decimal
from fractions import Fraction
import sqlite3

import numpy as np
import pandas as pd
import pytest

from src.db_client import DBClient

MAX_INT = 2**63 - 1
COLUMNS = ["date", "worksheet", "count", "total"]


def rows(client):
    with closing(sqlite3.connect(client.db_path)) as con:
        return con.execute("SELECT date, worksheet, count, total, typeof(count), typeof(total) "
                           "FROM uptrend_raw ORDER BY date, worksheet").fetchall()


def frame(count=1, total=10, day="2024-01-02"):
    return pd.DataFrame([[day, "all", count, total]], columns=COLUMNS, dtype=object)


def write(client, mode, count, total):
    if mode == "single":
        client.upsert_raw_data("2024-01-02", "all", count, total)
    else:
        client.upsert_bulk(frame(count, total))


@pytest.mark.parametrize("mode", ["single", "bulk"])
@pytest.mark.parametrize("value", [0, 1, np.int8(2), np.int32(3), np.int64(4), np.uint32(5),
                                    np.uint64(6), 7.0, np.float16(8), np.float32(9), np.float64(10),
                                    2**53 + 1, np.int64(MAX_INT), np.uint64(MAX_INT)])
def test_accepted_scalars_persist_exact_native_sqlite_integers(db_client, mode, value):
    write(db_client, mode, value, MAX_INT)
    stored = rows(db_client)[0]
    assert stored[2:] == (int(value), MAX_INT, "integer", "integer")


INVALID = [True, False, np.bool_(True), np.bool_(False), None, pd.NA, float("nan"),
           np.float32("nan"), float("inf"), float("-inf"), np.float64("inf"),
           1.5, np.float32(1.5), "1", "1.0", "bad", 1+0j, Decimal("1"), Fraction(1, 1),
           2**63, np.uint64(2**63), np.uint64(2**64-1), float(MAX_INT), -2**63-1, -1]


@pytest.mark.parametrize("mode", ["single", "bulk"])
@pytest.mark.parametrize("field", ["count", "total"])
@pytest.mark.parametrize("value", INVALID)
def test_scalar_and_bulk_reject_invalid_values_before_replacement(db_client, mode, field, value):
    db_client.upsert_raw_data("2024-01-02", "all", 5, 10)
    original = rows(db_client)
    count, total = (value, MAX_INT) if field == "count" else (0, value)
    with pytest.raises(ValueError):
        write(db_client, mode, count, total)
    assert rows(db_client) == original


@pytest.mark.parametrize("index", [[7, 7, 7], [9, 2, -3], ["same", "same", "other"],
                                    pd.MultiIndex.from_tuples([("a", 1), ("a", 1), ("b", 2)])])
def test_bulk_binds_positionally_without_mutating_input(db_client, index):
    data = pd.DataFrame([
        ["2024-01-02", "all", np.int64(2), 20],
        ["2024-01-03", "all", np.int64(3), 30],
        ["2024-01-04", "sec_technology", np.int64(4), 40],
    ], columns=COLUMNS, index=index)
    before = data.copy(deep=True)
    db_client.upsert_bulk(data)
    assert [(r[0], r[1], r[2], r[3]) for r in rows(db_client)] == [
        ("2024-01-02", "all", 2, 20), ("2024-01-03", "all", 3, 30),
        ("2024-01-04", "sec_technology", 4, 40),
    ]
    pd.testing.assert_frame_equal(data, before)


def test_duplicate_primary_keys_keep_last_row_wins(db_client):
    data = pd.concat([frame(2), frame(3)], ignore_index=False)
    db_client.upsert_bulk(data)
    assert rows(db_client) == [("2024-01-02", "all", 3, 10, "integer", "integer")]


@pytest.mark.parametrize("value", [True, np.bool_(True), 2**63, np.nan, "1", -1, 11])
def test_invalid_final_row_preserves_existing_and_earlier_rows(db_client, value):
    db_client.upsert_raw_data("2024-01-02", "all", 5, 10)
    original = rows(db_client)
    data = pd.concat([frame(6), frame(7, day="2024-01-03"), frame(value, day="2024-01-04")])
    with pytest.raises(ValueError):
        db_client.upsert_bulk(data)
    assert rows(db_client) == original


def test_sql_abort_rolls_back_prior_insert_and_replacement(db_client):
    db_client.upsert_raw_data("2024-01-02", "all", 5, 10)
    original = rows(db_client)
    with closing(sqlite3.connect(db_client.db_path)) as con:
        con.execute("CREATE TRIGGER abort_last BEFORE INSERT ON uptrend_raw "
                    "WHEN NEW.date = '2024-01-04' BEGIN SELECT RAISE(ABORT, 'synthetic abort'); END")
        con.commit()
    data = pd.concat([frame(6), frame(7, day="2024-01-03"), frame(8, day="2024-01-04")])
    with pytest.raises(sqlite3.IntegrityError, match="synthetic abort"):
        db_client.upsert_bulk(data)
    assert rows(db_client) == original


@pytest.mark.parametrize("dtype", ["Int64", "UInt64"])
def test_nullable_integer_columns_preserve_large_values(db_client, dtype):
    data = pd.DataFrame({"date": ["2024-01-02", "2024-01-03"], "worksheet": ["all", "all"],
                         "count": pd.Series([2**53+1, MAX_INT], dtype=dtype),
                         "total": pd.Series([MAX_INT, MAX_INT], dtype=dtype)})
    db_client.upsert_bulk(data)
    assert [r[2] for r in rows(db_client)] == [2**53+1, MAX_INT]
    assert all(r[4:] == ("integer", "integer") for r in rows(db_client))


def test_nullable_missing_final_value_rejects_entire_batch(db_client):
    data = pd.DataFrame({"date": ["2024-01-02", "2024-01-03"], "worksheet": ["all", "all"],
                         "count": pd.Series([1, pd.NA], dtype="Int64"), "total": [10, 10]})
    with pytest.raises(ValueError):
        db_client.upsert_bulk(data)
    assert rows(db_client) == []


def test_ambiguous_required_columns_fail_before_any_write(db_client):
    data = pd.DataFrame([["2024-01-02", "all", 1, 2, 10]], columns=["date", "worksheet", "count", "count", "total"])
    with pytest.raises(ValueError, match="duplicate"):
        db_client.upsert_bulk(data)
    assert rows(db_client) == []


def test_empty_valid_frame_is_noop(db_client):
    db_client.upsert_raw_data("2024-01-02", "all", 1, 10)
    original = rows(db_client)
    db_client.upsert_bulk(pd.DataFrame(columns=COLUMNS))
    assert rows(db_client) == original


def test_mixed_object_values_do_not_round_large_integer(db_client):
    data = pd.DataFrame([["2024-01-02", "all", 2**53+1, MAX_INT],
                         ["2024-01-03", "all", 1.0, MAX_INT]], columns=COLUMNS, dtype=object)
    db_client.upsert_bulk(data)
    assert [r[2] for r in rows(db_client)] == [2**53+1, 1]


@pytest.mark.parametrize("mode", ["single", "bulk"])
@pytest.mark.parametrize("field", ["count", "total"])
@pytest.mark.parametrize("value", [np.timedelta64(1, "ns"), np.timedelta64(1, "D"), np.timedelta64("NaT")])
def test_numpy_durations_are_not_count_integers(db_client, mode, field, value):
    db_client.upsert_raw_data("2024-01-02", "all", 5, 10)
    original = rows(db_client)
    count, total = (value, 10) if field == "count" else (0, value)
    with pytest.raises(ValueError):
        write(db_client, mode, count, total)
    assert rows(db_client) == original


@pytest.mark.parametrize("value", [np.timedelta64(1, "ns"), np.timedelta64(1, "D"), np.timedelta64("NaT")])
def test_duration_in_final_bulk_row_cannot_change_earlier_data(db_client, value):
    db_client.upsert_raw_data("2024-01-02", "all", 5, 10)
    original = rows(db_client)
    data = pd.concat([frame(6), frame(7, day="2024-01-03"), frame(value, day="2024-01-04")])
    with pytest.raises(ValueError):
        db_client.upsert_bulk(data)
    assert rows(db_client) == original
