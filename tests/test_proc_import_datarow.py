import tempfile
import unittest
from pathlib import Path

import pandas as pd

from saslite import SasInterpreter


class ProcImportDatarowTests(unittest.TestCase):
    def test_csv_skips_rows_without_changing_column_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'source.csv'
            path.write_text('value,label\n999,skip\n10,keep\n20,also_keep\n')
            sas = SasInterpreter()
            result = sas.execute(f'''proc import out=loaded dbms=csv datafile="{path}" replace;
                getnames=yes; datarow=3; run;''')
            self.assertTrue(result.success, result.error)
            data = sas.get_dataset('WORK', 'LOADED')
            self.assertEqual(data['value'].tolist(), [10, 20])
            self.assertEqual(data['label'].tolist(), ['keep', 'also_keep'])

    def test_csv_getnames_no_is_honored_with_datarow(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'source.csv'
            path.write_text('999,skip\n10,keep\n20,also_keep\n')
            sas = SasInterpreter()
            result = sas.execute(f'''proc import out=loaded dbms=csv datafile="{path}" replace;
                getnames=no; datarow=2; run;''')
            self.assertTrue(result.success, result.error)
            data = sas.get_dataset('WORK', 'LOADED')
            self.assertEqual(data.iloc[:, 0].tolist(), [10, 20])
            self.assertEqual(data.iloc[:, 1].tolist(), ['keep', 'also_keep'])

    def test_xlsx_skips_rows_preserving_the_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'source.xlsx'
            pd.DataFrame({'value': [999, 10, 20], 'label': ['skip', 'keep', 'also_keep']}).to_excel(path, index=False)
            sas = SasInterpreter()
            result = sas.execute(f'''proc import out=loaded dbms=xlsx datafile="{path}" replace;
                getnames=yes; datarow=3; run;''')
            self.assertTrue(result.success, result.error)
            data = sas.get_dataset('WORK', 'LOADED')
            self.assertEqual(data['value'].tolist(), [10, 20])

    def test_xlsx_datarow_two_matches_the_reference_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'source.xlsx'
            pd.DataFrame({'value': [10, 20]}).to_excel(path, index=False)
            sas = SasInterpreter()
            result = sas.execute(f'''proc import out=loaded dbms=xlsx datafile="{path}" replace;
                getnames=yes; datarow=2; run;''')
            self.assertTrue(result.success, result.error)
            self.assertEqual(sas.get_dataset('WORK', 'LOADED')['value'].tolist(), [10, 20])

    def test_datarow_must_not_overlap_the_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'source.csv'
            path.write_text('value\n10\n')
            sas = SasInterpreter()
            result = sas.execute(f'''proc import out=loaded dbms=csv datafile="{path}" replace;
                getnames=yes; datarow=1; run;''')
            self.assertFalse(result.success)
            self.assertIn('DATAROW', result.steps[-1].error or '')


if __name__ == '__main__':
    unittest.main()
