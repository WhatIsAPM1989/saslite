import unittest

import pandas as pd

from saslite import SasInterpreter


class GroupedDistinctAggregateTests(unittest.TestCase):
    def test_grouped_count_distinct_uses_sas_semantics(self) -> None:
        sas = SasInterpreter()
        sas.create_dataset(
            "x",
            pd.DataFrame(
                {
                    "grp": ["A", "A", "A", "A", "B", "B"],
                    "id": [1, 2, 2, None, 3, 3],
                }
            ),
        )

        result = sas.execute(
            """
            proc sql;
              create table work.result as
              select grp, count(distinct id) as cnt
              from work.x
              group by grp
              order by grp;
            quit;
            """
        )

        self.assertTrue(result.success, result.error)
        actual = sas.get_dataset("WORK", "RESULT")
        self.assertEqual(actual.columns.tolist(), ["grp", "cnt"])
        self.assertEqual(
            actual.to_dict("records"),
            [{"grp": "A", "cnt": 2}, {"grp": "B", "cnt": 1}],
        )

    def test_grouped_count_distinct_complex_expression(self) -> None:
        sas = SasInterpreter()
        sas.create_dataset(
            "x",
            pd.DataFrame(
                {
                    "grp": ["A", "A", "A"],
                    "value": [" x ", "x", " y "],
                }
            ),
        )

        result = sas.execute(
            """
            proc sql;
              create table work.result as
              select grp, count(distinct strip(value)) as cnt
              from work.x
              group by grp;
            quit;
            """
        )

        self.assertTrue(result.success, result.error)
        actual = sas.get_dataset("WORK", "RESULT")
        self.assertEqual(actual.columns.tolist(), ["grp", "cnt"])
        self.assertEqual(actual.to_dict("records"), [{"grp": "A", "cnt": 2}])


if __name__ == "__main__":
    unittest.main()
