import unittest

from saslite import SasInterpreter
from saslite.functions.char_funcs import prxchange


class PrxchangeFunctionTests(unittest.TestCase):
    def test_replaces_all_or_a_limited_number_of_matches(self) -> None:
        self.assertEqual(prxchange(r"s/\s+/-/", -1, "a  b c"), "a-b-c")
        self.assertEqual(prxchange(r"s/\s+/-/", 1, "a  b c"), "a-b c")
        self.assertEqual(prxchange(r"s/\s+/-/", 0, "a  b c"), "a  b c")

    def test_supports_sas_backreferences_modifiers_and_delimiters(self) -> None:
        self.assertEqual(
            prxchange(r"s#(\w+),\s*(\w+)#$2 $1#i", -1, "Smith, Ada"),
            "Ada Smith",
        )
        self.assertEqual(
            prxchange(r"s/foo/BAR/i", -1, "Foo and fOO"),
            "BAR and BAR",
        )

    def test_invalid_expression_leaves_source_unchanged(self) -> None:
        self.assertEqual(prxchange("not-a-substitution", -1, "source"), "source")
        self.assertEqual(prxchange("s/[broken/value/", -1, "source"), "source")

    def test_is_available_in_a_data_step(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            r'''
data changed;
  original="Alpha   beta";
  compact=prxchange("s/\s+/ /", -1, original);
run;
'''
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "CHANGED")
        self.assertEqual(frame.loc[0, "compact"], "Alpha beta")


class SymgetFunctionTests(unittest.TestCase):
    def test_reads_macro_variable_by_runtime_character_name(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            '''
%let study=ABC-123;
data macro_value;
  macro_name="study";
  value=symget(macro_name);
  uppercase_lookup=symget("STUDY");
run;
'''
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "MACRO_VALUE")
        self.assertEqual(frame.loc[0, "value"], "ABC-123")
        self.assertEqual(frame.loc[0, "uppercase_lookup"], "ABC-123")

    def test_unknown_or_blank_macro_variable_name_returns_blank(self) -> None:
        sas = SasInterpreter()
        result = sas.execute(
            '''
data macro_value;
  unknown=symget("does_not_exist");
  blank=symget("   ");
run;
'''
        )

        self.assertTrue(result.success, result.error)
        frame = sas.get_dataset("WORK", "MACRO_VALUE")
        self.assertEqual(frame.loc[0, "unknown"], "")
        self.assertEqual(frame.loc[0, "blank"], "")


if __name__ == "__main__":
    unittest.main()
