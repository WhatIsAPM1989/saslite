import unittest

from saslite import SasInterpreter


class DataStepZeroRowSchemaTests(unittest.TestCase):
    def test_declarations_compile_schema_before_stop(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data empty_model;
  length order 8 estimate interval text_value $40;
  attrib score length=4 format=8.2 label="Score label";
  format order z3. formatted_value 10.2;
  label estimate="Estimate label" described_value="Description";
  stop;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "EMPTY_MODEL")
        self.assertEqual(len(frame), 0)
        self.assertEqual(
            [str(column).upper() for column in frame.columns],
            [
                "ORDER", "ESTIMATE", "INTERVAL", "TEXT_VALUE", "SCORE",
                "FORMATTED_VALUE", "DESCRIBED_VALUE",
            ],
        )

        dataset = sas.session.get_dataset("WORK", "EMPTY_MODEL")
        order = dataset.metadata.get_variable("order")
        estimate = dataset.metadata.get_variable("estimate")
        interval = dataset.metadata.get_variable("interval")
        text_value = dataset.metadata.get_variable("text_value")
        score = dataset.metadata.get_variable("score")
        formatted = dataset.metadata.get_variable("formatted_value")
        described = dataset.metadata.get_variable("described_value")

        self.assertEqual((order.dtype, order.length, order.format), ("numeric", 8, "z3."))
        self.assertEqual((estimate.dtype, estimate.length, estimate.label),
                         ("character", 40, "Estimate label"))
        self.assertEqual((interval.dtype, interval.length), ("character", 40))
        self.assertEqual((text_value.dtype, text_value.length), ("character", 40))
        self.assertEqual((score.dtype, score.length, score.format, score.label),
                         ("numeric", 4, "8.2", "Score label"))
        self.assertEqual((formatted.dtype, formatted.format), ("numeric", "10.2"))
        self.assertEqual((described.dtype, described.label), ("numeric", "Description"))

    def test_assignment_targets_compile_for_zero_row_set_input(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data empty_source;
  length grade $8;
  stop;
run;

data empty_result;
  set empty_source;
  if grade='Any' then sort_ord=0;
  else if grade='Unknown' then sort_ord=1;
  if missing(grade) then display_value='Missing';
run;

proc sort data=empty_result out=sorted_result;
  by sort_ord display_value;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "SORTED_RESULT")
        self.assertEqual(len(frame), 0)
        self.assertEqual(
            [str(column).upper() for column in frame.columns],
            ["GRADE", "SORT_ORD", "DISPLAY_VALUE"],
        )
        metadata = sas.session.get_dataset("WORK", "EMPTY_RESULT").metadata
        self.assertEqual(metadata.get_variable("sort_ord").dtype, "numeric")
        self.assertEqual(metadata.get_variable("display_value").dtype, "character")

    def test_proc_statement_implicitly_ends_data_step(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data source;
  value=2;
run;

data copied;
  set source;
proc sort data=copied out=sorted;
  by value;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            sas.get_dataset("WORK", "SORTED")["value"].tolist(),
            [2],
        )

    def test_proc_sort_without_data_uses_last_created_dataset(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data last_source;
  input value;
  datalines;
2
1
;
run;

proc sort;
  by value;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            sas.get_dataset("WORK", "LAST_SOURCE")["VALUE"].tolist(),
            [1, 2],
        )


if __name__ == "__main__":
    unittest.main()
