import pytest

from saslite import SasInterpreter


def test_label_is_assigned_to_each_output_member():
    sas = SasInterpreter()
    result = sas.execute(
        """
data first(label='Patient''s counts' keep=id)
     work.second(label="Other counts")
     unlabeled;
  id=1;
  value=2;
  label id='Record identifier';
run;
data copy;
  set first;
run;
proc contents data=first;
run;
"""
    )

    assert result.success, result.error
    first = sas.session.get_dataset("WORK", "FIRST")
    second = sas.session.get_dataset("WORK", "SECOND")
    assert first.metadata.label == "Patient's counts"
    assert first.metadata.logical_variable_names() == ["ID"]
    assert first.metadata.get_variable("ID").label == "Record identifier"
    assert second.metadata.label == "Other counts"
    assert second.metadata.logical_variable_names() == ["ID", "VALUE"]
    assert sas.session.get_dataset("WORK", "UNLABELED").metadata.label is None
    assert sas.session.get_dataset("WORK", "COPY").metadata.label is None
    assert "Patient's counts" in result.steps[-1].output_messages[0]


@pytest.mark.parametrize(
    ("label", "stored_label"),
    [("Stored counts", "Stored counts"), ("a" * 39 + "é", "a" * 39), (" ", None)],
)
def test_label_round_trips_through_a_sas_library(tmp_path, label, stored_label):
    libname = f'libname saved "{tmp_path}";'
    writer = SasInterpreter()
    result = writer.execute(
        f"""
{libname}
data saved.example(label='{label}');
  id=1;
run;
"""
    )
    assert result.success, result.error

    reader = SasInterpreter()
    result = reader.execute(libname)
    assert result.success, result.error
    dataset = reader.session.get_dataset("SAVED", "EXAMPLE")
    assert dataset.metadata.label == stored_label
    assert dataset.data["ID"].tolist() == [1]
