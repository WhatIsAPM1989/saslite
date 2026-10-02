import itertools
import unittest

import pandas as pd

from saslite import SasInterpreter
from saslite.ast.sql import JoinNode
from saslite.parser.program_parser import ProgramParser


class SqlCrossJoinTests(unittest.TestCase):
    def interpreter(self, **tables) -> SasInterpreter:
        sas = SasInterpreter()
        sas.reporter.configure(quiet=True)
        for name, frame in tables.items():
            sas.create_dataset(name, frame)
        return sas

    def test_cross_join_without_on_before_left_join(self) -> None:
        program = ProgramParser().parse("""
            proc sql;
              create table result as select v.visit, c.arm, a.value
              from visits as v cross join arms as c
              left join actual as a on v.visit=a.visit and c.arm=a.arm;
            quit;
        """)
        joins = [item for item in program.steps[0].statements[0].select.from_clause
                 if isinstance(item, JoinNode)]
        self.assertEqual([join.join_type for join in joins], ["CROSS", "LEFT"])
        self.assertIsNone(joins[0].on_condition)
        self.assertIsNotNone(joins[1].on_condition)

    def test_cross_join_produces_every_pair_and_preserves_duplicates(self) -> None:
        sas = self.interpreter(
            visits=pd.DataFrame({"id": [1, 1, 2]}),
            arms=pd.DataFrame({"id": [10, 20]}),
        )
        result = sas.execute("""
            proc sql;
              create table result as select v.id as visit, c.id as arm
              from visits as v CrOsS JoIn arms as c order by visit, arm;
            quit;
        """)

        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset("WORK", "RESULT").to_dict("records"), [
            {"visit": 1, "arm": 10}, {"visit": 1, "arm": 10},
            {"visit": 1, "arm": 20}, {"visit": 1, "arm": 20},
            {"visit": 2, "arm": 10}, {"visit": 2, "arm": 20},
        ])

    def test_cross_join_where_filters_pairs_without_aliases(self) -> None:
        sas = self.interpreter(
            visits=pd.DataFrame({"id": [1, 2]}),
            arms=pd.DataFrame({"id": [1, 2, 3]}),
        )
        result = sas.execute("""
            proc sql;
              create table result as select visits.id as visit, arms.id as arm
              from visits cross join arms
              where visits.id < arms.id order by visit, arm;
            quit;
        """)

        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset("WORK", "RESULT").to_dict("records"), [
            {"visit": 1, "arm": 2}, {"visit": 1, "arm": 3},
            {"visit": 2, "arm": 3},
        ])

    def test_cross_join_followed_by_left_join_keeps_unmatched_grid_rows(self) -> None:
        sas = self.interpreter(
            visits=pd.DataFrame({"visit": [1, 2]}),
            arms=pd.DataFrame({"arm": [1, 2]}),
            actual=pd.DataFrame({"visit": [1], "arm": [2], "value": [99]}),
        )
        result = sas.execute("""
            proc sql;
              create table result as
              select v.*, c.arm, coalesce(a.value,0) as value
              from visits as v cross join arms as c
              left join actual as a on v.visit=a.visit and c.arm=a.arm
              order by visit, arm;
            quit;
        """)

        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset("WORK", "RESULT").to_dict("records"), [
            {"visit": 1, "arm": 1, "value": 0},
            {"visit": 1, "arm": 2, "value": 99},
            {"visit": 2, "arm": 1, "value": 0},
            {"visit": 2, "arm": 2, "value": 0},
        ])

    def test_empty_operand_produces_no_rows_and_keeps_columns(self) -> None:
        for syntax in ("cross join", ","):
            for left_size, right_size in ((0, 2), (2, 0), (0, 0)):
                with self.subTest(syntax=syntax, sizes=(left_size, right_size)):
                    sas = self.interpreter(
                        visits=pd.DataFrame({"visit": pd.Series(range(left_size), dtype="int64")}),
                        arms=pd.DataFrame({"arm": pd.Series(range(right_size), dtype="int64")}),
                    )
                    result = sas.execute(f"""
                        proc sql;
                          create table result as select v.*, c.arm
                          from visits as v {syntax} arms as c;
                        quit;
                    """)

                    self.assertTrue(result.success, result.error)
                    output = sas.get_dataset("WORK", "RESULT")
                    self.assertEqual(output.shape, (0, 2))
                    self.assertEqual(output.columns.tolist(), ["visit", "arm"])

    def test_chained_cross_joins_make_three_table_product(self) -> None:
        sas = self.interpreter(
            visits=pd.DataFrame({"visit": [1, 2]}),
            arms=pd.DataFrame({"arm": [10, 20]}),
            times=pd.DataFrame({"time": [100, 200]}),
        )
        result = sas.execute("""
            proc sql;
              create table result as select v.visit, c.arm, t.time
              from visits v cross join arms c cross join times t
              order by visit, arm, time;
            quit;
        """)

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            list(sas.get_dataset("WORK", "RESULT").itertuples(index=False, name=None)),
            list(itertools.product([1, 2], [10, 20], [100, 200])),
        )

    def test_cross_join_subquery_applies_dataset_options(self) -> None:
        sas = self.interpreter(
            visits=pd.DataFrame({"visit": [1, 2]}),
            arms=pd.DataFrame({"arm": [10, 20], "unused": [1, 2]}),
        )
        result = sas.execute("""
            proc sql;
              create table result as select v.visit, c.arm
              from (select visit from visits where visit=2) as v
              cross join arms(keep=arm where=(arm=20)) as c;
            quit;
        """)

        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset("WORK", "RESULT").to_dict("records"), [
            {"visit": 2, "arm": 20},
        ])


if __name__ == "__main__":
    unittest.main()
