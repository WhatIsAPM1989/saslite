import unittest

import pandas as pd

from saslite import SasInterpreter
from saslite.runtime.dataset import Dataset


class ProcReportTransposeCompatibilityTests(unittest.TestCase):
    def test_transpose_prefix_with_numeric_id_keeps_character_cells(self):
        sas = SasInterpreter()
        sas.create_dataset('source', pd.DataFrame({'ARM': [1, 2], 'CELL': ['NC', '0']}))
        result = sas.execute('''
proc transpose data=source out=wide prefix=col;
  id arm;
  var cell;
run;
data copied;
  set wide;
  array cells{2} $ col1-col2;
  do i=1 to 2;
    cells{i}=strip(cells{i});
  end;
run;
''')
        self.assertTrue(result.success, result.error)
        self.assertEqual([warning for step in result.steps for warning in step.warnings], [])
        frame = sas.get_dataset('WORK', 'COPIED')
        self.assertEqual(frame[['COL1', 'COL2']].iloc[0].tolist(), ['NC', '0'])

    def test_sql_numeric_object_values_do_not_become_character(self):
        sas = SasInterpreter()
        frame = pd.DataFrame({'BLOCK': pd.Series([0, 1, None], dtype=object),
                              'TEXT': pd.Series(['0', '1', None], dtype=object)})
        source = Dataset.from_dataframe(frame, name='SOURCE')
        # SAS numeric values can have object storage after concatenating SET inputs.
        source.metadata.get_variable('BLOCK').dtype = 'numeric'
        sas.session.put_dataset('WORK', 'SOURCE', source)
        result = sas.execute('''
proc sql;
  create table selected as select block, text from source;
quit;
data copied;
  set selected;
  if not missing(block) then block=block+1;
run;
''')
        self.assertTrue(result.success, result.error)
        self.assertEqual([warning for step in result.steps for warning in step.warnings], [])
        selected = sas.session.get_dataset('WORK', 'SELECTED')
        self.assertEqual(selected.metadata.get_variable('BLOCK').dtype, 'numeric')
        self.assertEqual(selected.metadata.get_variable('TEXT').dtype, 'character')
        self.assertEqual(sas.get_dataset('WORK', 'COPIED')['BLOCK'].iloc[:2].tolist(), [1, 2])

    def test_report_computed_character_and_numeric_values_reach_output(self):
        sas = SasInterpreter()
        sas.create_dataset('source', pd.DataFrame({'VALUE': [2, 4]}))
        result = sas.execute('''
proc report data=source out=reported nowd;
  column value miss short twice;
  define value / display;
  define miss / computed " ";
  define short / computed;
  define twice / computed;
  compute miss / character length=1;
    miss=" ";
  endcomp;
  compute short / character length=2;
    short="ABC";
  endcomp;
  compute twice;
    twice=value*2;
  endcomp;
run;
''')
        self.assertTrue(result.success, result.error)
        self.assertEqual([warning for step in result.steps for warning in step.warnings], [])
        frame = sas.get_dataset('WORK', 'REPORTED')
        self.assertEqual(frame['MISS'].tolist(), [' ', ' '])
        self.assertEqual(frame['SHORT'].tolist(), ['AB', 'AB'])
        self.assertEqual(frame['TWICE'].tolist(), [4, 8])
