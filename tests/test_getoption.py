import io
import unittest

import pandas as pd

from saslite import SasInterpreter
from saslite.diagnostics.reporter import Reporter
from saslite.session.session import Session


class GetOptionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sas = SasInterpreter()
        self.log = io.StringIO()
        self.sas._reporter = Reporter(stream=self.log)

    def execute(self, source: str) -> None:
        result = self.sas.execute(source)
        self.assertTrue(result.success, result.error)

    def test_data_step_returns_character_values_and_metadata(self) -> None:
        self.execute("""
            options linesize=132 pagesize=55 missing='?' nomprint nodate;
            data result;
                option_name='linesize';
                value=getoption(option_name);
                keyword=getoption('pagesize', 'keyword');
                flag=getoption('mprint');
                date_flag=getoption('date');
                missing_value=getoption('missing');
                unlimited=getoption('obs');
            run;
        """)
        dataset = self.sas.session.get_dataset("WORK", "RESULT")
        row = dataset.data.iloc[0]
        self.assertEqual(row['value'], '132')
        self.assertEqual(row['keyword'], 'PAGESIZE=55')
        self.assertEqual(row['flag'], 'NOMPRINT')
        self.assertEqual(row['date_flag'], 'NODATE')
        self.assertEqual(row['missing_value'], '?')
        self.assertEqual(row['unlimited'], 'MAX')
        self.assertEqual(dataset.metadata.get_variable('value').dtype, 'character')

    def test_sql_uses_current_session_options(self) -> None:
        self.sas.create_dataset('source', pd.DataFrame({'id': [1]}))
        self.execute("""
            options ps=42;
            proc sql;
                create table result as
                select getoption('pagesize') as value,
                       getoption('ps', 'keyword') as keyword
                from source;
            quit;
        """)
        row = self.sas.get_dataset('WORK', 'RESULT').iloc[0]
        self.assertEqual(row['value'], '42')
        self.assertEqual(row['keyword'], 'PS=42')

    def test_sysfunc_observes_options_in_source_order_and_restores_keyword(self) -> None:
        self.execute(
            "%let saved=%sysfunc(getoption(ls,keyword)); "
            "options ls=150; "
            "%put NEW=%sysfunc(getoption(linesize)); "
            "options &saved; "
            "%put RESTORED=%sysfunc(getoption(ls));"
        )
        self.assertIn('NEW=150\n', self.log.getvalue())
        self.assertIn('RESTORED=80\n', self.log.getvalue())
        self.assertEqual(self.sas.session.get_option('LINESIZE'), 80)

    def test_boolean_options_can_be_saved_and_restored(self) -> None:
        self.execute(
            "%let saved=%sysfunc(getoption(notes)); "
            "option nonotes; %put OFF=%sysfunc(getoption(notes,keyword)); "
            "options &saved; %put ON=%sysfunc(getoption(nonotes));"
        )
        self.assertIn('OFF=NONOTES\n', self.log.getvalue())
        self.assertIn('ON=NOTES\n', self.log.getvalue())

    def test_macro_and_qsysfunc_use_the_same_session(self) -> None:
        self.execute('options ls=101;')
        self.execute(
            '%macro show; %put VALUE=%qsysfunc(getoption(LS)); %mend; %show;'
        )
        self.assertIn('VALUE=101\n', self.log.getvalue())

    def test_defaults_are_not_changed_by_options_and_sessions_are_isolated(self) -> None:
        self.execute('options linesize=99;')
        self.execute(
            '%put DEFAULT=%sysfunc(getoption(ls,defaultvalue)) '
            'START=%sysfunc(getoption(ls,startupvalue,keyword));'
        )
        self.assertIn('DEFAULT=80 START=LS=80\n', self.log.getvalue())
        other = SasInterpreter()
        other_log = io.StringIO()
        other._reporter = Reporter(stream=other_log)
        result = other.execute('%put OTHER=%sysfunc(getoption(ls));')
        self.assertTrue(result.success, result.error)
        self.assertEqual(other_log.getvalue(), 'OTHER=80\n')

    def test_options_scanner_ignores_strings_comments_and_inline_data(self) -> None:
        self.execute("""
            /* options ls=999; */
            options missing=';';
            data source;
                input text $;
                datalines;
options
;
            run;
            %put LS=%sysfunc(getoption(ls));
        """)
        self.assertIn('LS=80\n', self.log.getvalue())
        self.assertEqual(self.sas.session.get_option('MISSING'), ';')
        self.assertEqual(self.sas.get_dataset('WORK', 'SOURCE').iloc[0]['TEXT'], 'options')

    def test_keyword_quotes_character_values_for_options_round_trip(self) -> None:
        self.execute("options missing=';';")
        self.execute('%let saved=%sysfunc(getoption(missing,keyword));')
        self.execute("options missing='?';")
        self.execute('options &saved;')
        self.assertEqual(self.sas.session.get_option('MISSING'), ';')

    def test_keyword_restores_default_encoding_and_missing_character(self) -> None:
        self.execute(
            '%let encoding=%sysfunc(getoption(encoding,keyword)); '
            '%let missing=%sysfunc(getoption(missing,keyword)); '
            'options encoding="ascii" missing="?"; '
            'options &encoding &missing;'
        )
        self.assertEqual(self.sas.session.get_option('ENCODING'), 'utf-8')
        self.assertEqual(self.sas.session.get_option('MISSING'), '.')

    def test_invalid_option_and_modifier_fail_in_data_step(self) -> None:
        for call in ("getoption('no_such_option')", "getoption('ls','unsupported')", 'getoption()'):
            with self.subTest(call=call):
                result = self.sas.execute(f'data result; value={call}; run;')
                self.assertFalse(result.success)
                self.assertIn('GETOPTION', '\n'.join(result.log_lines))

    def test_options_generated_inside_macro_precede_getoption(self) -> None:
        self.execute(
            '%macro check; options ls=200; '
            '%put INNER=%sysfunc(getoption(ls)); %mend; %check;'
        )
        self.assertIn('INNER=200\n', self.log.getvalue())
        self.execute('%check;')
        self.assertEqual(self.log.getvalue().count('INNER=200\n'), 2)

    def test_macro_can_save_restore_and_branch_on_options(self) -> None:
        self.execute('''
            %macro check;
                %local saved;
                %let saved=%sysfunc(getoption(ls,keyword));
                options ls=200;
                %if %sysfunc(getoption(ls))=200 %then %do;
                    %put MATCH;
                %end;
                options &saved;
                %put RESTORED=%sysfunc(getoption(ls));
            %mend;
            %check;
        ''')
        self.assertIn('MATCH\n', self.log.getvalue())
        self.assertIn('RESTORED=80\n', self.log.getvalue())

    def test_macro_loop_reads_each_option_update(self) -> None:
        self.execute('''
            %macro check;
                %do i=1 %to 2;
                    options ls=&i;
                    %put VALUE=%sysfunc(getoption(ls));
                %end;
            %mend;
            %check;
        ''')
        self.assertIn('VALUE=1\n', self.log.getvalue())
        self.assertIn('VALUE=2\n', self.log.getvalue())

    def test_session_zero_and_negative_boolean_lookup(self) -> None:
        session = Session()
        session.set_option('OBS', 0)
        session.set_option('NODATE', True)
        session.set_option('DATE', True)
        self.assertEqual(session.option_text('obs'), '0')
        self.assertFalse(session.get_option('NODATE'))
        self.assertEqual(session.option_text('nodate'), 'DATE')


if __name__ == '__main__':
    unittest.main()
