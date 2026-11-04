import pandas as pd
import pytest

from saslite import SasInterpreter


def query(source, rows):
    sas = SasInterpreter()
    sas.reporter.configure(quiet=True)
    sas.create_dataset("rows", rows)
    result = sas.execute(f"proc sql; create table result as {source}; quit;")
    assert result.success, result.error
    return sas.get_dataset("WORK", "RESULT")


@pytest.mark.parametrize("direction,expected", [
    ("asc", [1, 2, 3, 4]),
    ("desc", [4, 3, 2, 1]),
])
@pytest.mark.parametrize("select,order", [
    ("select *", "key"),
    ("select id", "key"),
    ("select id, key as sort_key", "sort_key"),
    ("select id, key+1 as sort_key", "sort_key"),
    ("select id", "key+1"),
])
def test_numeric_missing_order_for_input_projection_alias_and_expression(direction, expected, select, order):
    rows = pd.DataFrame({"id": [1, 2, 3, 4], "key": [None, -2, 0, 3]})
    out = query(f"{select} from rows order by {order} {direction}", rows)
    assert out["id"].tolist() == expected


@pytest.mark.parametrize("directions,expected", [
    ("block asc, key desc", [3, 2, 1, 6, 5, 4]),
    ("block desc, key asc", [4, 5, 6, 1, 2, 3]),
])
def test_missing_order_respects_mixed_key_directions(directions, expected):
    rows = pd.DataFrame({
        "id": [1, 2, 3, 4, 5, 6],
        "block": [None, None, None, 1, 1, 1],
        "key": [None, -2, 3, None, -2, 3],
    })
    out = query(f"select * from rows order by {directions}", rows)
    assert out["id"].tolist() == expected


def test_missing_key_ties_retain_duplicate_rows_and_input_order():
    rows = pd.DataFrame({"id": [1, 2, 2, 3, 4], "key": [None, None, None, 0, 0]})
    out = query("select * from rows order by key", rows)
    assert out["id"].tolist() == [1, 2, 2, 3, 4]


@pytest.mark.parametrize("projection,group_column", [
    ("id, max(key) as sort_key", "id"),
    ("key as sort_key, id, sum(value) as total", "key"),
])
def test_grouped_and_remerged_order_missing_first(projection, group_column):
    rows = pd.DataFrame({"key": [None, -2, 3], "id": [1, 2, 3], "value": [1, 2, 3]})
    out = query(f"select {projection} from rows group by {group_column} order by sort_key", rows)
    assert pd.isna(out["sort_key"].iloc[0])
    assert out["sort_key"].iloc[1:].tolist() == [-2, 3]


def test_empty_ordered_query_preserves_descriptor():
    rows = pd.DataFrame({"id": pd.Series(dtype=float), "key": pd.Series(dtype=float)})
    out = query("select * from rows order by key", rows)
    assert len(out) == 0
    assert out.columns.tolist() == ["id", "key"]
