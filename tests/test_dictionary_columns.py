import unittest

from saslite import SasInterpreter


class DictionaryColumnsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sas = SasInterpreter()
        result = self.sas.execute(
            """
            data subjects;
                length studyid $12 age 8;
                studyid="ABC";
                age=34;
                label studyid="Study identifier";
                format age 8.2;
            run;
            """
        )
        self.assertTrue(result.success, result.error)

    def test_columns_view_exposes_session_metadata(self) -> None:
        result = self.sas.execute(
            """
            proc sql;
                create table subject_columns as
                select libname, memname, name, type,
                       length, varnum, label, format
                from dictionary.columns
                where libname="WORK" and memname="SUBJECTS"
                order by varnum;
            quit;
            """
        )

        self.assertTrue(result.success, result.error)
        frame = self.sas.get_dataset("WORK", "SUBJECT_COLUMNS")
        self.assertEqual(frame["NAME"].tolist(), ["studyid", "age"])
        self.assertEqual(frame["TYPE"].tolist(), ["char", "num"])
        self.assertEqual(frame["LENGTH"].tolist(), [12, 8])
        self.assertEqual(frame["VARNUM"].tolist(), [1, 2])
        self.assertEqual(frame["LABEL"].tolist(), ["Study identifier", ""])
        self.assertEqual(frame["FORMAT"].tolist(), ["", "8.2"])

    def test_where_order_outobs_and_into_use_normal_sql_path(self) -> None:
        result = self.sas.execute(
            """
            proc sql noprint outobs=1;
                select name, type, length, varnum, label, format
                  into :name trimmed, :type trimmed, :length trimmed,
                       :varnum trimmed, :label trimmed, :format trimmed
                from dictionary.columns
                where libname="WORK" and memname="SUBJECTS"
                  and index(upcase(label), "STUDY") > 0
                order by varnum;
            quit;
            """
        )

        self.assertTrue(result.success, result.error)
        expected = {
            "NAME": "studyid",
            "TYPE": "char",
            "LENGTH": "12",
            "VARNUM": "1",
            "LABEL": "Study identifier",
            "FORMAT": "",
        }
        for name, value in expected.items():
            self.assertEqual(self.sas.session.get_macro_var(name), value)

    def test_dictionary_columns_is_read_only(self) -> None:
        result = self.sas.execute(
            """
            proc sql;
                create table dictionary.columns as
                select * from subjects;
            quit;
            """
        )

        self.assertFalse(result.success)
        self.assertTrue(result.steps)
        self.assertIn(
            "Library DICTIONARY is not defined",
            result.steps[-1].error or "",
        )


if __name__ == "__main__":
    unittest.main()
