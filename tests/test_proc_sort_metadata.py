import unittest

from saslite import SasInterpreter


class ProcSortMetadataTests(unittest.TestCase):
    def test_empty_dataset_keeps_declared_types_and_lengths(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data empty_model;
  length order 8 result_text $40;
  stop;
run;
proc sort data=empty_model;
  by order;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        dataset = sas.session.get_dataset("WORK", "EMPTY_MODEL")
        order = dataset.metadata.get_variable("order")
        result_text = dataset.metadata.get_variable("result_text")
        self.assertEqual((order.dtype, order.length), ("numeric", 8))
        self.assertEqual(
            (result_text.dtype, result_text.length),
            ("character", 40),
        )

    def test_nonempty_sort_preserves_metadata(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data source;
  length id 8 response $12;
  id=1;
  response="Yes";
run;
proc sort data=source out=sorted;
  by id;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        dataset = sas.session.get_dataset("WORK", "SORTED")
        response = dataset.metadata.get_variable("response")
        self.assertIsNotNone(response)
        self.assertEqual((response.dtype, response.length), ("character", 12))

    def test_by_prefix_list_expands_in_column_order(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data source;
  input group col1 col2 unrelated;
  datalines;
1 2 1 9
1 1 2 8
1 1 1 7
;
run;
proc sort data=source out=sorted;
  by group col:;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "SORTED")
        self.assertEqual(frame["UNRELATED"].tolist(), [7.0, 8.0, 9.0])

    def test_out_drop_option_removes_column_and_metadata(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            """
data source;
  length secret $12;
  id=2; secret="hidden"; output;
  id=1; secret="removed"; output;
run;
proc sort data=source out=sorted(drop=secret);
  by id;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        source = sas.get_dataset("WORK", "SOURCE")
        sorted_frame = sas.get_dataset("WORK", "SORTED")
        sorted_dataset = sas.session.get_dataset("WORK", "SORTED")
        self.assertEqual({column.upper() for column in source.columns}, {"ID", "SECRET"})
        self.assertEqual([column.upper() for column in sorted_frame.columns], ["ID"])
        id_column = next(column for column in sorted_frame.columns if column.upper() == "ID")
        self.assertEqual(sorted_frame[id_column].tolist(), [1, 2])
        self.assertIsNone(sorted_dataset.metadata.get_variable("SECRET"))


if __name__ == "__main__":
    unittest.main()
