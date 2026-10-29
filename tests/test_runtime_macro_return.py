import unittest

from saslite import SasInterpreter


class RuntimeMacroReturnTests(unittest.TestCase):
    def test_sql_condition_return_is_local_to_each_invocation(self):
        sas = SasInterpreter()
        result = sas.execute("""
            %macro build(flag=, out=);
                %local count;
                data input; value=&flag.; run;
                proc sql noprint;
                    select count(*) into :count trimmed from input where value=1;
                quit;
                %if &count.=0 %then %do;
                    data &out.; value=10; run;
                    %return;
                %end;
                data &out.; value=20; run;
            %mend;
            %build(flag=0,out=first);
            %build(flag=1,out=second);
            data caller; value=30; run;
        """)
        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset("WORK", "FIRST").rename(columns=str.upper)["VALUE"].tolist(), [10])
        self.assertEqual(sas.get_dataset("WORK", "SECOND").rename(columns=str.upper)["VALUE"].tolist(), [20])
        self.assertEqual(sas.get_dataset("WORK", "CALLER").rename(columns=str.upper)["VALUE"].tolist(), [30])

    def test_nested_return_else_and_quoted_text(self):
        sas = SasInterpreter()
        result = sas.execute("""
            %macro build(flag=, out=);
                %local count;
                data input; value=&flag.; run;
                proc sql noprint;
                    select count(*) into :count trimmed from input where value=1;
                quit;
                %if &count.=1 %then %do;
                    %if &flag.=1 %then %do;
                        data &out.; value=40; text='%return;'; run;
                        %return;
                    %end;
                %end;
                %else %do;
                    data &out.; value=50; run;
                    %return;
                %end;
                data &out.; value=60; run;
            %mend;
            %build(flag=1,out=first);
            %build(flag=0,out=second);
        """)
        self.assertTrue(result.success, result.error)
        self.assertEqual(sas.get_dataset("WORK", "FIRST").rename(columns=str.upper)["VALUE"].tolist(), [40])
        self.assertEqual(sas.get_dataset("WORK", "FIRST").rename(columns=str.upper)["TEXT"].tolist(), ["%return;"])
        self.assertEqual(sas.get_dataset("WORK", "SECOND").rename(columns=str.upper)["VALUE"].tolist(), [50])
