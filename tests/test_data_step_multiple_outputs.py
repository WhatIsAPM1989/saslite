import unittest

from saslite import SasInterpreter


class DataStepMultipleOutputTests(unittest.TestCase):
    @staticmethod
    def _interpreter_with_source() -> SasInterpreter:
        sas = SasInterpreter()
        result = sas.execute(
            """
data source;
  input id category $;
  label id="Record identifier";
  datalines;
1 A
2 B
3 A
;
run;
"""
        )
        if not result.success:
            raise AssertionError(result.error)
        return sas

    def test_named_output_routes_rows_to_space_separated_targets(self) -> None:
        sas = self._interpreter_with_source()
        result = sas.execute(
            """
data accepted rejected;
  set source;
  if category="A" then output accepted;
  else output rejected;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        accepted = sas.get_dataset("WORK", "ACCEPTED")
        rejected = sas.get_dataset("WORK", "REJECTED")
        self.assertEqual(accepted["ID"].tolist(), [1, 3])
        self.assertEqual(rejected["ID"].tolist(), [2])
        self.assertEqual(
            sas.session.get_dataset("WORK", "ACCEPTED")
            .metadata.get_variable("ID").label,
            "Record identifier",
        )

    def test_implicit_output_is_broadcast_to_every_target(self) -> None:
        sas = self._interpreter_with_source()
        result = sas.execute(
            """
data copy_one copy_two;
  set source;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset("WORK", "COPY_ONE")["ID"].tolist(), [1, 2, 3])
        self.assertEqual(sas.get_dataset("WORK", "COPY_TWO")["ID"].tolist(), [1, 2, 3])

    def test_unnamed_explicit_output_is_broadcast_to_every_target(self) -> None:
        sas = self._interpreter_with_source()
        result = sas.execute(
            """
data broadcast_one broadcast_two;
  set source;
  output;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            sas.get_dataset("WORK", "BROADCAST_ONE")["ID"].tolist(),
            [1, 2, 3],
        )
        self.assertEqual(
            sas.get_dataset("WORK", "BROADCAST_TWO")["ID"].tolist(),
            [1, 2, 3],
        )


if __name__ == "__main__":
    unittest.main()
