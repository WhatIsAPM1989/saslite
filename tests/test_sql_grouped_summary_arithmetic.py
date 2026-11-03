import unittest

import pandas as pd

from saslite import SasInterpreter
from saslite.runtime.dataset import Dataset


class GroupedSummaryArithmeticTests(unittest.TestCase):
    def _run(self, query, frame=None):
        if frame is None:
            frame = pd.DataFrame({
                "category": ["A", "A", "B", "B"],
                "position": [2.0, 3.0, 8.0, 9.0],
            })
        sas = SasInterpreter()
        sas.session.put_dataset("WORK", "SOURCE", Dataset.from_dataframe(frame, "SOURCE"))
        result = sas.execute(f"proc sql; create table wanted as {query}; quit;")
        self.assertTrue(result.success, result.error)
        return sas.get_dataset("WORK", "WANTED")

    def test_summary_plus_constant_keeps_alias_and_value(self):
        data = self._run("""
            select category, min(position)+1 as ordering
            from source group by category
        """)
        self.assertEqual(list(data.columns), ["category", "ordering"])
        self.assertEqual(data.ordering.tolist(), [3, 9])

    def test_expression_before_group_column_preserves_select_order(self):
        data = self._run("""
            select min(position)+1 as ordering, category
            from source group by category
        """)
        self.assertEqual(list(data.columns), ["ordering", "category"])
        self.assertEqual(data.ordering.tolist(), [3, 9])
        self.assertEqual(data.category.tolist(), ["A", "B"])

    def test_wrapped_summaries_coexist_with_direct_summaries(self):
        data = self._run("""
            select category, count(*) as n, min(position)+1 as ordering,
                   -(max(position)-2) as negative,
                   round(min(position)/3,0.1) as rounded
            from source group by category
        """)
        self.assertEqual(data.n.tolist(), [2, 2])
        self.assertEqual(data.ordering.tolist(), [3, 9])
        self.assertEqual(data.negative.tolist(), [-1, -7])
        self.assertEqual(data.rounded.round(1).tolist(), [0.7, 2.7])

    def test_wrapped_coalesce_retains_missing_value_semantics(self):
        frame = pd.DataFrame({"category": ["A", "A"], "position": [float("nan")] * 2})
        data = self._run("""
            select category, min(position)+1 as missing_result,
                   coalesce(min(position),0)+1 as fallback,
                   coalesce(min(position),0) as direct_fallback
            from source group by category
        """, frame)
        self.assertTrue(pd.isna(data.missing_result.iloc[0]))
        self.assertEqual(data.fallback.tolist(), [1])
        self.assertEqual(data.direct_fallback.tolist(), [0])

    def test_order_by_uses_the_final_arithmetic_result(self):
        data = self._run("""
            select category, -min(position) as ordering
            from source group by category order by ordering
        """)
        self.assertEqual(data.category.tolist(), ["B", "A"])
        self.assertEqual(data.ordering.tolist(), [-8, -2])

    def test_empty_input_preserves_requested_columns(self):
        frame = pd.DataFrame({"category": pd.Series(dtype=str), "position": pd.Series(dtype=float)})
        data = self._run("""
            select category, min(position)+1 as ordering
            from source group by category
        """, frame)
        self.assertTrue(data.empty)
        self.assertEqual(list(data.columns), ["category", "ordering"])


if __name__ == "__main__":
    unittest.main()
