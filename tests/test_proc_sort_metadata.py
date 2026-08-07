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


if __name__ == "__main__":
    unittest.main()
