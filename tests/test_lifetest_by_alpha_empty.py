import unittest
import pandas as pd
from saslite import SasInterpreter


class LifetestByAlphaEmptyTests(unittest.TestCase):
    def test_empty_quartiles_keeps_numeric_descriptor(self):
        sas = SasInterpreter()
        sas.create_dataset('tte', pd.DataFrame({
            'ARM': pd.Series(dtype=float), 'MONTH': pd.Series(dtype=float),
            'CNSR': pd.Series(dtype=float)}))
        result = sas.execute('''
        ods output Quartiles=q SurvivalPlot=s;
        proc lifetest data=tte; time month*cnsr(1); strata arm; run;
        ods output close;
        data medians; set q(where=(percent=50)); value=estimate; run;
        ''')
        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.reporter.warning_count, 0)
        q = sas.get_dataset('WORK', 'Q')
        self.assertEqual(list(q.columns), ['ARM', 'PERCENT', 'ESTIMATE', 'LOWERLIMIT', 'UPPERLIMIT'])
        self.assertTrue(q.empty)
        self.assertTrue(all(pd.api.types.is_numeric_dtype(q[c]) for c in q.columns))
        self.assertIn('SURVIVAL', sas.get_dataset('WORK', 'S').columns)

    def test_by_and_numeric_alpha(self):
        sas = SasInterpreter()
        result = sas.execute('''
        data tte;
          input subgroup arm month cnsr;
          datalines;
1 1 5 0
1 1 6 1
1 2 8 0
1 2 10 0
2 1 4 0
2 1 9 0
2 2 10 0
2 2 12 1
;
        run;
        ods output Quartiles=q SurvivalPlot=s HomTests=h;
        proc lifetest data=tte conftype=loglog atrisk reduceout alpha=0.05;
          by subgroup;
          time month*cnsr(1);
          strata arm;
        run;
        ods output close;
        ''')
        self.assertTrue(result.success, result.error)
        q = sas.get_dataset('WORK', 'Q')
        m = q[q.PERCENT == 50]
        self.assertEqual(m.SUBGROUP.tolist(), [1, 1, 2, 2])
        self.assertEqual(m.ESTIMATE.tolist(), [5, 8, 4, 10])
        h = sas.get_dataset('WORK', 'H')
        self.assertEqual(h.SUBGROUP.tolist(), [1, 2])
        self.assertEqual(h.DF.tolist(), [1, 1])
        s = sas.get_dataset('WORK', 'S')
        self.assertEqual(s.groupby('SUBGROUP').STRATUMNUM.max().tolist(), [2, 2])

    def test_by_without_strata(self):
        sas = SasInterpreter()
        result = sas.execute('''
        data tte;
          input subgroup month cnsr;
          datalines;
1 5 0
1 6 1
2 8 0
2 10 0
;
        run;
        ods output Quartiles=q;
        proc lifetest data=tte; by subgroup; time month*cnsr(1); run;
        ods output close;
        ''')
        self.assertTrue(result.success, result.error)
        q = sas.get_dataset('WORK', 'Q')
        self.assertEqual(q.loc[q.PERCENT == 50, 'ESTIMATE'].tolist(), [5, 8])

    def test_alpha_changes_confidence_limits(self):
        sas = SasInterpreter()
        sas.create_dataset('tte', pd.DataFrame({'MONTH': range(1, 31), 'CNSR': [0]*30}))
        for alpha, name in [(0.05, 'q95'), (0.2, 'q80')]:
            result = sas.execute(f'''
            ods output Quartiles={name};
            proc lifetest data=tte alpha={alpha}; time month*cnsr(1); run;
            ods output close;
            ''')
            self.assertTrue(result.success, result.error)
        q95 = sas.get_dataset('WORK', 'Q95').query('PERCENT == 50').iloc[0]
        q80 = sas.get_dataset('WORK', 'Q80').query('PERCENT == 50').iloc[0]
        self.assertEqual(q95.ESTIMATE, q80.ESTIMATE)
        self.assertLess(q95.LOWERLIMIT, q80.LOWERLIMIT)
        self.assertGreater(q95.UPPERLIMIT, q80.UPPERLIMIT)


if __name__ == '__main__':
    unittest.main()
