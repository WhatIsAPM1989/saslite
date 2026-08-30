import base64
import unittest

from saslite import SasInterpreter
from saslite.parser.program_parser import ProgramParser


class ProcGraphicsTests(unittest.TestCase):
    DATA = """
data sales;
  input sex $ age height weight lower upper;
  datalines;
F 20 60 115 108 122
F 30 64 130 120 140
F 40 66 145 134 156
M 20 68 160 150 172
M 30 72 180 167 194
M 40 74 195 180 210
;
run;
"""

    def assert_png(self, step) -> None:
        self.assertEqual(len(step.artifacts), 1)
        artifact = step.artifacts[0]
        self.assertEqual(artifact.kind, "image")
        self.assertEqual(artifact.mime_type, "image/png")
        self.assertTrue(base64.b64decode(artifact.data).startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(artifact.width, 100)
        self.assertGreater(artifact.height, 100)

    def test_sgplot_renders_common_plot_statements(self) -> None:
        result = SasInterpreter().execute(
            self.DATA
            + """
proc sgplot data=sales;
  band x=height lower=lower upper=upper / fillattrs=(color=lightblue);
  scatter x=height y=weight / group=sex markerattrs=(symbol=circlefilled size=7);
  reg x=height y=weight / lineattrs=(pattern=dash thickness=2);
  xaxis label="Height" grid;
  yaxis label="Weight" grid;
  title "SGPLOT demo";
run;
"""
        )

        self.assertTrue(result.success, result.error)
        self.assert_png(result.steps[-1])
        self.assertEqual(result.steps[-1].dataset_name, "WORK.SALES")

    def test_sgpanel_renders_panelby(self) -> None:
        result = SasInterpreter().execute(
            self.DATA
            + """
proc sgpanel data=sales;
  panelby sex / columns=2;
  vbar age / response=weight stat=mean;
  rowaxis grid;
  title "SGPANEL demo";
run;
"""
        )

        self.assertTrue(result.success, result.error)
        self.assert_png(result.steps[-1])

    def test_gtl_template_is_compiled_and_rendered(self) -> None:
        result = SasInterpreter().execute(
            self.DATA
            + """
proc template;
  define statgraph graphs.demo;
    begingraph;
      entrytitle graph_title;
      layout overlay / xaxisopts=(label="Height") yaxisopts=(label="Weight");
        scatterplot x=height y=weight / group=sex;
        seriesplot x=height y=weight / group=sex;
      endlayout;
    endgraph;
  end;
run;
proc sgrender data=sales template=graphs.demo;
  dynamic graph_title="GTL demo";
run;
"""
        )

        self.assertTrue(result.success, result.error)
        self.assert_png(result.steps[-1])
        self.assertEqual(result.steps[-1].artifacts[0].title, "GTL demo")

    def test_gtl_nested_lattice_renders_each_overlay_cell(self) -> None:
        result = SasInterpreter().execute(
            self.DATA
            + """
proc template;
  define statgraph graphs.nested;
    begingraph;
      entrytitle "Nested lattice";
      layout lattice / columns=2 columnweights=(.4 .6)
                       rowdatarange=unionall columndatarange=unionall;
        layout overlay / xaxisopts=(label="Height") yaxisopts=(label="Weight");
          entry "Scatter";
          scatterplot x=height y=weight / group=sex;
        endlayout;
        layout lattice / rows=2 columns=1 rowweights=(.55 .45) rowgutter=8;
          layout overlay / xaxisopts=(label="Age") yaxisopts=(label="Weight");
            entry "Series";
            seriesplot x=age y=weight / group=sex;
          endlayout;
          layout overlay / xaxisopts=(label="Weight");
            entry "Distribution";
            histogram weight;
          endlayout;
        endlayout;
      endlayout;
    endgraph;
  end;
run;
proc sgrender data=sales template=graphs.nested;
run;
"""
        )

        self.assertTrue(result.success, result.error)
        self.assert_png(result.steps[-1])
        self.assertEqual(result.steps[-1].artifacts[0].title, "Nested lattice")

    def test_parser_preserves_graph_options(self) -> None:
        program = ProgramParser().parse(
            "proc sgplot data=sales; scatter x=height y=weight / "
            "group=sex markerattrs=(symbol=diamondfilled size=9); run;"
        )

        proc = program.steps[0]
        plot = proc.statements[0]
        self.assertEqual(plot["args"], {"X": "height", "Y": "weight"})
        self.assertEqual(plot["options"]["GROUP"], "sex")
        self.assertEqual(
            plot["options"]["MARKERATTRS"],
            {"SYMBOL": "diamondfilled", "SIZE": 9},
        )


if __name__ == "__main__":
    unittest.main()
