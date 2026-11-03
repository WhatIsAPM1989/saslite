import unittest

import pandas as pd

from saslite import SasInterpreter
from saslite.ast.expressions import FunctionCallNode, UnaryOpNode
from saslite.parser.program_parser import ProgramParser
from saslite.runtime.dataset import Dataset


class ParenthesizedNotTests(unittest.TestCase):
    def _execute(self, source, frame=None):
        sas = SasInterpreter()
        if frame is not None:
            sas.session.put_dataset("WORK", "SOURCE", Dataset.from_dataframe(frame, "SOURCE"))
        result = sas.execute(source)
        self.assertTrue(result.success, result.error)
        return sas

    def test_parser_creates_unary_not_instead_of_function_call(self):
        program = ProgramParser().parse("data wanted; flag=not (x>0); run;")
        expression = program.steps[0].statements[0].expr
        self.assertIsInstance(expression, UnaryOpNode)
        self.assertEqual(expression.op.upper(), "NOT")

    def test_spacing_and_case_variants_execute(self):
        for expression in ("not(x>0)", "not (x>0)", "NOT (x>0)", "NoT(x>0)"):
            with self.subTest(expression=expression):
                sas = self._execute(f"data wanted; x=0; flag={expression}; run;")
                self.assertEqual(sas.get_dataset("WORK", "WANTED")["flag"].tolist(), [1])

    def test_truth_values_include_missing_and_nested_negation(self):
        frame = pd.DataFrame({"x": [0.0, 2.0, -3.0, float('nan')]})
        sas = self._execute("""
            data wanted; set source;
              negated=not (x);
              twice=not (not (x));
            run;
        """, frame)
        data = sas.get_dataset("WORK", "WANTED")
        self.assertEqual(data.negated.tolist(), [1, 0, 0, 1])
        self.assertEqual(data.twice.tolist(), [0, 1, 1, 0])

    def test_compound_and_or_expressions_keep_logical_operands(self):
        frame = pd.DataFrame({"x": [0, 0, 1, 1], "y": [0, 1, 0, 1]})
        sas = self._execute("""
            data wanted; set source;
              flag=(x>0 and not (y>0)) or (not (x>0) and y>0);
            run;
        """, frame)
        self.assertEqual(sas.get_dataset("WORK", "WANTED")["flag"].tolist(), [0, 1, 1, 0])

    def test_sql_projection_and_where_support_parenthesized_not(self):
        frame = pd.DataFrame({"x": [0, 1, 2]})
        sas = self._execute("""
            proc sql;
              create table wanted as
              select x, not (x>0) as flag from source
              where not (x>1);
            quit;
        """, frame)
        data = sas.get_dataset("WORK", "WANTED")
        self.assertEqual(data.x.tolist(), [0, 1])
        self.assertEqual(data.flag.tolist(), [1, 0])

    def test_ordinary_functions_and_name_prefixes_remain_function_calls(self):
        program = ProgramParser().parse("data wanted; flag=notify(x); run;")
        expression = program.steps[0].statements[0].expr
        self.assertIsInstance(expression, FunctionCallNode)
        self.assertEqual(expression.name, "NOTIFY")
        sas = self._execute("data wanted; x=abs(-3); flag=not (missing(x)); run;")
        data = sas.get_dataset("WORK", "WANTED")
        self.assertEqual(data.x.tolist(), [3])
        self.assertEqual(data.flag.tolist(), [1])


if __name__ == "__main__":
    unittest.main()
