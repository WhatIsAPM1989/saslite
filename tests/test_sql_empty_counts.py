import unittest

import pandas as pd

from saslite import SasInterpreter


class SqlEmptyCountTests(unittest.TestCase):
    def test_conditional_counts_zero_but_sum_missing_without_matches(self):
        for flags in ([], [0, 0]):
            with self.subTest(flags=flags):
                sas = SasInterpreter()
                sas.create_dataset("source", pd.DataFrame({
                    "FLAG": pd.Series(flags, dtype=float),
                    "ID": pd.Series(range(len(flags)), dtype=float),
                }))
                result = sas.execute("""
proc sql noprint;
  create table result as select
    count(*) as n_total,
    count(case when flag=1 then 1 end) as n_yes,
    count(distinct case when flag=1 then id end) as n_unique,
    sum(case when flag=1 then 1 end) as sum_yes
  from source;
quit;
""")
                self.assertTrue(result.success, result.error)
                frame = sas.get_dataset("WORK", "RESULT")
                self.assertEqual(len(frame), 1)
                self.assertEqual(frame.iloc[0]["n_total"], len(flags))
                self.assertEqual(frame.iloc[0]["n_yes"], 0)
                self.assertEqual(frame.iloc[0]["n_unique"], 0)
                self.assertTrue(pd.isna(frame.iloc[0]["sum_yes"]))

    def test_grouped_conditional_count_zero_for_group_without_matches(self):
        sas = SasInterpreter()
        sas.create_dataset("source", pd.DataFrame({
            "GRP": ["A", "A", "B", "B"], "FLAG": [0, 0, 0, 1],
        }))
        result = sas.execute("""
proc sql noprint;
  create table result as select grp,
    count(case when flag=1 then 1 end) as n_yes,
    sum(case when flag=1 then 1 end) as sum_yes
  from source group by grp order by grp;
quit;
""")
        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "RESULT")
        self.assertEqual(frame["n_yes"].tolist(), [0, 1])
        self.assertTrue(pd.isna(frame.iloc[0]["sum_yes"]))
        self.assertEqual(frame.iloc[1]["sum_yes"], 1)
