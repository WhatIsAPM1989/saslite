import pandas as pd
import pytest

from saslite import SasInterpreter


def join_frames(left, right, on, kind="left", where=""):
    sas = SasInterpreter()
    sas.reporter.configure(quiet=True)
    sas.create_dataset("left_rows", left)
    sas.create_dataset("right_rows", right)
    result = sas.execute(f"""
        proc sql;
          create table result as
          select a.row_id, a.arm, b.value
          from left_rows as a {kind} join right_rows as b on {on}
          {where}
          order by row_id, value;
        quit;
    """)
    assert result.success, result.error
    return sas.get_dataset("WORK", "RESULT")


@pytest.mark.parametrize("on", [
    "a.key=b.key and a.arm=1",
    "a.key=b.key and b.value>0",
    "a.key=b.key and a.arm<b.value",
])
def test_left_join_preserves_rows_when_all_candidates_fail_on(on):
    left = pd.DataFrame({"row_id": [1, 2], "key": [1, 2], "arm": [1, 2]})
    right = pd.DataFrame({"key": [1, 2, 2], "value": [5, -1, -2]})
    out = join_frames(left, right, on)
    assert out["row_id"].tolist() == [1, 2]
    assert out["value"].iloc[0] == 5
    assert pd.isna(out["value"].iloc[1])


def test_left_join_keeps_only_passing_matches_and_preserves_duplicate_left_rows():
    left = pd.DataFrame({"row_id": [1, 1, 2], "key": [1, 1, 2], "arm": [1, 1, 2]})
    right = pd.DataFrame({"key": [1, 1, 1, 2], "value": [5, -1, 7, -2]})
    out = join_frames(left, right, "a.key=b.key and b.value>0")
    assert out["row_id"].tolist() == [1, 1, 1, 1, 2]
    assert out["value"].iloc[:4].tolist() == [5, 5, 7, 7]
    assert pd.isna(out["value"].iloc[4])


@pytest.mark.parametrize("empty_side", ["left", "right", "both"])
def test_left_join_on_filter_with_empty_tables(empty_side):
    left = pd.DataFrame({"row_id": [1, 2], "key": [1, 2], "arm": [1, 2]})
    right = pd.DataFrame({"key": [1], "value": [5]})
    if empty_side in ("left", "both"):
        left = left.iloc[:0]
    if empty_side in ("right", "both"):
        right = right.iloc[:0]
    out = join_frames(left, right, "a.key=b.key and a.arm=1")
    assert len(out) == len(left)
    assert out["value"].isna().all()


def test_left_join_on_filter_does_not_change_where_semantics():
    left = pd.DataFrame({"row_id": [1, 2], "key": [1, 2], "arm": [1, 2]})
    right = pd.DataFrame({"key": [1, 2], "value": [5, 9]})
    out = join_frames(left, right, "a.key=b.key and a.arm=1", where="where a.arm=1")
    assert out["row_id"].tolist() == [1]


def test_inner_join_still_filters_failed_candidates():
    left = pd.DataFrame({"row_id": [1, 2], "key": [1, 2], "arm": [1, 2]})
    right = pd.DataFrame({"key": [1, 2], "value": [5, 9]})
    out = join_frames(left, right, "a.key=b.key and a.arm=1", kind="inner")
    assert out["row_id"].tolist() == [1]


@pytest.mark.parametrize("kind", ["right", "full"])
def test_other_outer_joins_preserve_unmatched_input_rows(kind):
    left = pd.DataFrame({"row_id": [1], "key": [1], "arm": [2]})
    right = pd.DataFrame({"key": [1], "value": [5]})
    out = join_frames(left, right, "a.key=b.key and a.arm=1", kind=kind)
    assert len(out) == (2 if kind == "full" else 1)
    assert out.loc[out["row_id"].isna(), "value"].tolist() == [5]
    if kind == "full":
        assert out.loc[out["row_id"] == 1, "value"].isna().all()
