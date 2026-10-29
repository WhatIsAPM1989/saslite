import io
import unittest

import pandas as pd

from saslite import SasInterpreter
from saslite.diagnostics.reporter import Reporter
from saslite.macro.expander import MacroExpander


class MacroPercentQuotingTests(unittest.TestCase):
    def _interpreter(self, empty=False):
        sas = SasInterpreter()
        sas._reporter = Reporter(stream=io.StringIO())
        frame = pd.DataFrame({
            "FASFL": ["Y", "Y", "Y", "Y", "Y", "N"],
            "TC25RSBL": ["TC25>=25%", "TC>=25%", "TC25<25%", "TC<25%", "", "TC25>=25%"],
        })
        sas.create_dataset("source", frame.iloc[:0] if empty else frame)
        return sas

    @staticmethod
    def _selection(argument):
        return """
            %macro select_rows(subset=);
              data selected;
                set source(where=(&subset.));
              run;
            %mend;
            %select_rows(subset=""" + argument + """);
        """

    def test_tc25_original_percent_quote_cannot_succeed(self):
        # This exact macro argument failed in corporate SAS. No local source
        # rows are needed to detect the syntax error introduced by quoting.
        for function in ("str", "nrstr"):
            for empty in (False, True):
                with self.subTest(function=function, empty=empty):
                    sas = self._interpreter(empty)
                    result = sas.execute(self._selection(
                        '%' + function + '(FASFL="Y" and upcase(compress(TC25RSBL)) '
                        'in ("TC25>=25%","TC>=25%"))'
                    ))
                    self.assertFalse(result.success)
                    self.assertTrue(result.error)

    def test_tc25_literal_percent_and_single_quoted_filters(self):
        for function in ("str", "nrstr"):
            for lower in (False, True):
                for empty in (False, True):
                    for single_quoted in (False, True):
                        with self.subTest(function=function, lower=lower, empty=empty,
                                          single_quoted=single_quoted):
                            operator = '<' if lower else '>='
                            quote = "'" if single_quoted else '"'
                            percent = '%' if single_quoted else '%%'
                            values = ','.join(quote + prefix + operator + '25' + percent + quote
                                              for prefix in ('TC25', 'TC'))
                            argument = ('%' + function + '(FASFL="Y" and '
                                        'upcase(compress(TC25RSBL)) in (' + values + '))')
                            sas = self._interpreter(empty)
                            result = sas.execute(self._selection(argument))
                            self.assertTrue(result.success, result.error)
                            actual = sas.get_dataset('WORK', 'SELECTED')['TC25RSBL'].tolist()
                            expected = [] if empty else [prefix + operator + '25%'
                                                        for prefix in ('TC25', 'TC')]
                            self.assertEqual(actual, expected)

    def test_unquoted_macro_argument_preserves_single_quoted_percent(self):
        sas = self._interpreter()
        result = sas.execute(self._selection(
            "FASFL='Y' and upcase(compress(TC25RSBL)) in ('TC25>=25%','TC>=25%')"
        ))
        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset('WORK', 'SELECTED')['TC25RSBL'].tolist(),
                         ['TC25>=25%', 'TC>=25%'])

    def test_static_quoting_percent_and_unmatched_delimiters(self):
        # Examples of the compile-time escape rules in the SAS Macro
        # Language Reference, including quoted text sent only to the log.
        cases = [
            ("%str(%%%%)", "%%"),
            ("%str('%')", "'%'"),
            ("%str(a%')", "a'"),
            ('%str(title %"first)', 'title "first'),
            ("%str(log%(12)", "log(12"),
            ("%str(345%))", "345)"),
            ("%str(%%%')", "%'"),
            ('%str(TITLE "20%%";)', 'TITLE "20%";'),
        ]
        for expression, expected in cases:
            for function in ('str', 'nrstr'):
                with self.subTest(expression=expression, function=function):
                    sas = self._interpreter()
                    expression = expression.replace('%str(', '%' + function + '(')
                    result = sas.execute('%let captured=' + expression + '; %put &captured;')
                    self.assertTrue(result.success, result.error)
                    self.assertEqual(sas._reporter._stream.getvalue(), expected + "\n")

    def test_explicit_unquote_restores_marked_quote_delimiters(self):
        result = MacroExpander().expand("%unquote(%str(a%'))")
        self.assertEqual(result, "a'")

    def test_single_literal_with_marked_closing_quote_is_an_error(self):
        sas = self._interpreter()
        result = sas.execute(self._selection('%str(TC25RSBL="TC25>=25%")'))
        self.assertFalse(result.success)
        self.assertIn("Use %%", result.error)

    def test_marked_inner_quotes_are_string_content(self):
        sas = self._interpreter()
        result = sas.execute('data result; value=%str("He said %"yes%""); run;')
        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset('WORK', 'RESULT')['value'].tolist(), ['He said "yes"'])

    def test_percent_quote_in_ordinary_sas_string_is_unchanged(self):
        sas = self._interpreter()
        result = sas.execute('data result; value="20%"; run;')
        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset('WORK', 'RESULT')['value'].tolist(), ['20%'])


if __name__ == '__main__':
    unittest.main()
