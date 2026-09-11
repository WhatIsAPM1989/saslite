import tempfile
import unittest
from pathlib import Path

from saslite import SasInterpreter


class ReportedCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.sas = SasInterpreter()
        self.sas.reporter.configure(quiet=True)

    def run_sas(self, code):
        result = self.sas.execute(code)
        self.assertTrue(result.success, result.error)
        return result

    def test_compress_omitted_argument_and_digit_modifier(self):
        self.run_sas('data t; grade="Grade 2"; n=input(compress(grade,,"kd"), ?? best32.); run;')
        self.assertEqual(self.sas.get_dataset('WORK', 'T')['n'].tolist(), [2])

    def test_dictionary_expressions_without_alias(self):
        self.run_sas('data t; a=1; b=2; run;')
        for expr in ("catx('=',name,cats(name,'_CSR'))", "strip(name)||'='||strip(name)||'_CSR'"):
            self.run_sas(f"proc sql noprint; select {expr} into :renlist separated by ' ' from dictionary.columns where libname='WORK' and memname='T' order by varnum; quit;")
            self.assertEqual(self.sas.session.get_macro_var('renlist'), 'a=a_CSR b=b_CSR')

    def test_macro_loop_freezes_each_local_value(self):
        self.run_sas('''%let renlist=a b c;
        %macro rename; %local i csrvar;
        %do i=1 %to %sysfunc(countw(&renlist.));
          %let csrvar=%scan(&renlist.,&i.);
          &csrvar.=&csrvar._CSR
        %end; %mend;
        data source; a=1; b=2; c=3; run;
        data target; set source(rename=(%rename)); run;''')
        self.assertEqual(list(self.sas.get_dataset('WORK', 'TARGET').columns), ['a_CSR', 'b_CSR', 'c_CSR'])

    def test_sort_dupout(self):
        self.run_sas('data t; input id value; datalines;\n1 10\n1 20\n2 30\n; run; proc sort data=t out=unique nodupkey dupout=duplicates; by id; run;')
        self.assertEqual(self.sas.get_dataset('WORK', 'DUPLICATES')['VALUE'].tolist(), [20])
        self.assertEqual(self.sas.get_dataset('WORK', 'UNIQUE')['ID'].tolist(), [1, 2])

    def test_attrib_character_length(self):
        self.run_sas('data t; attrib term label="Subject identifier" length=$200; term="ABC"; run;')
        ds = self.sas.session.get_dataset('WORK', 'T')
        self.assertEqual(ds.data['term'].tolist(), ['ABC'])
        self.assertEqual(ds.metadata.get_variable('term').length, 200)
        self.assertEqual(ds.metadata.get_variable('term').dtype, 'character')

    def test_freq_list_option(self):
        self.run_sas('data t; a=1; b=2; run; proc freq data=t; tables a*b / missing list; run;')

    def test_quiet_file_log_and_put_warning_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'program.sas'
            path.write_text("%put BEGIN; data _null_; put 'WARNING: eligibility'; run; %put FINISHED;")
            result = self.sas.execute_file(path)
        self.assertTrue(result.success, result.error)
        self.assertIn('BEGIN', result.log_lines)
        self.assertIn('FINISHED', result.log_lines)
        self.assertIn('WARNING: eligibility', result.log_lines)
        self.assertEqual(self.sas.reporter.warning_count, 1)
        next_result = self.run_sas('%put NEXT;')
        self.assertEqual(next_result.log_lines, ['NEXT'])

    def test_z2_format(self):
        self.run_sas("data t; do n=1 to 3; id=cats('QA-',put(n,z2.)); output; end; run;")
        self.assertEqual(self.sas.get_dataset('WORK','T')['id'].tolist(), ['QA-01','QA-02','QA-03'])

    def test_sql_having_macro_condition(self):
        self.run_sas('''data t; id=1; output; id=2; output; run;
        %macro check;
        proc sql noprint; create table dups as select id, count(*) as n from t group by id having count(*)>1;
        select count(*) into :ndup trimmed from dups; quit;
        %if &ndup > 0 %then %do; %put ERROR: duplicates; %abort cancel; %end;
        %put CHECK_FINISHED;
        %mend; %check;''')
        self.assertEqual(self.sas.reporter.error_count, 0)
        self.assertIn('CHECK_FINISHED', self.sas.reporter.log_lines)

    def test_abort_cancels_true_branch_and_preserves_prior_log(self):
        result = self.sas.execute("""data t; id=1; output; output; run;
        %macro check;
        proc sql noprint; create table dups as select id, count(*) as n from t group by id having count(*)>1;
        select count(*) into :ndup trimmed from dups; quit;
        %if &ndup > 0 %then %do; %put ERROR: duplicates; %abort cancel; %end;
        %put SHOULD_NOT_APPEAR;
        data should_not_exist; x=1; run;
        %mend; %check;""")
        self.assertFalse(result.success)
        self.assertIn('%ABORT CANCEL', result.error)
        self.assertIn('ERROR: duplicates', result.log_lines)
        self.assertNotIn('SHOULD_NOT_APPEAR', result.log_lines)
        self.assertFalse(self.sas.session.dataset_exists('WORK', 'SHOULD_NOT_EXIST'))

    def test_presentation_strings_and_comments_are_parsed(self):
        self.run_sas('''/* Apply after RSTART
 Footnote 10, when supplied, retains text. */
        footnote1 "Outcome: RECOVRD = Recovered; F = Fatal.";
        title1 "A ""quoted"" title";
        data t; x=1; run;''')
        self.assertEqual(self.sas.get_dataset('WORK','T')['x'].tolist(), [1])
        self.assertFalse(self.sas.execute('footnote1 "unterminated;').success)

    def test_report_grouped_columns_alias_and_compute_syntax(self):
        result = self.run_sas('''data t; value=7; run;
        proc report data=t out=reported;
          column value ("Spanning header" value=duplicate_value);
          define value / order noprint;
          compute after / style={borderbottomwidth=2}; line "done"; endcomp;
        run;''')
        self.assertEqual(self.sas.get_dataset('WORK', 'REPORTED')['duplicate_value'].tolist(), [7])
        self.assertTrue(any('syntax-checked' in line for line in result.log_lines))
        self.assertFalse(self.sas.execute('proc report data=t; compute after; invalid; endcomp; run;').success)

    def test_dupout_empty_and_noduprecs(self):
        self.run_sas('data t; id=1; output; output; run; proc sort data=t out=u noduprecs dupout=d; by id; run;')
        self.assertEqual(len(self.sas.get_dataset('WORK', 'D')), 1)
        self.run_sas('proc sort data=u nodupkey dupout=empty; by id; run;')
        ds = self.sas.session.get_dataset('WORK', 'EMPTY')
        self.assertEqual(len(ds.data), 0)
        self.assertEqual(list(ds.data.columns), ['id'])
        self.assertIsNotNone(ds.metadata.get_variable('id'))
