import io
import unittest

import pandas as pd

from saslite import SasInterpreter


class SqlWeakEmptyCountTests(unittest.TestCase):
    def test_empty_weak_source_counts_zero_and_keeps_expectations(self):
        for via_work in (False, True):
            with self.subTest(via_work=via_work):
                sas = SasInterpreter()
                sas.reporter._stream = io.StringIO()
                prefix = "data copied; set raw.absent; run;" if via_work else ""
                source = "copied" if via_work else "raw.absent"
                result = sas.execute(prefix + f"""
proc sql noprint;
  create table counts as select count(usubjid) as n,
    count(distinct usubjid) as unique_n, sum(usubjid) as total
  from {source};
quit;
""")
                self.assertTrue(result.success, result.error)
                frame = sas.get_dataset("WORK", "COUNTS")
                self.assertEqual(len(frame), 1)
                self.assertEqual(frame.iloc[0]["n"], 0)
                self.assertEqual(frame.iloc[0]["unique_n"], 0)
                self.assertTrue(pd.isna(frame.iloc[0]["total"]))
                self.assertEqual(sas.session.dataset_expectations, ["RAW.ABSENT"])
                expectation = sas.session.schema_expectations[0]
                self.assertEqual(expectation.variable, "USUBJID")
                self.assertEqual(expectation.sources, ("RAW.ABSENT",))

    def test_empty_weak_count_into_is_consumable_in_macro(self):
        sas = SasInterpreter()
        sas.reporter._stream = io.StringIO()
        result = sas.execute("""
%macro build;
  %local n;
  data copied; set raw.absent; run;
  proc sql noprint;
    select count(distinct usubjid) into :n trimmed from copied;
  quit;
  data result;
    n=&n.;
    if &n.>0 then pct=100;
    else pct=.;
  run;
%mend;
%build;
""")
        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "RESULT")
        self.assertEqual(frame.iloc[0]["n"], 0)
        self.assertTrue(pd.isna(frame.iloc[0]["pct"]))
