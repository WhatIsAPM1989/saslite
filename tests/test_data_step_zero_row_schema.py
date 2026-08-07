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


if __name__ == "__main__":
    unittest.main()
