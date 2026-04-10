from loxvihgen.builders import JSONCheckStringBuilder, TitleBuilder, XMLCheckStringBuilder
from loxvihgen.core import ArrIdx, ObjKey, Path
from loxvihgen.service import cmd_build

widths = {"b": 2}

def test_title_builder_with_indices():
    p = Path([ObjKey("a"), ObjKey("b"), ArrIdx("b", 9), ObjKey("c")])
    tb = TitleBuilder(sep='.', prefix='pref', width_by_key=widths)
    assert tb.for_path(p) == 'pref.a.b.b[09].c'

def test_json_check_string():
    p = Path([ObjKey("a"), ObjKey("b"), ArrIdx("b", 1), ObjKey("c")])
    chk = JSONCheckStringBuilder().build(p)
    assert '\\i&quot;a&quot;:\\i' in chk and chk.endswith('\\v')

def test_xml_check_string():
    p = Path([ObjKey("root"), ArrIdx("item", 2), ObjKey("value")])
    chk = XMLCheckStringBuilder().build(p)
    assert '\\i&lt;root&gt;\\i' in chk and chk.endswith('\\v')


def test_cmd_build_missing_response(tmp_path, monkeypatch, caplog):
    workspace = tmp_path / "proj"
    workspace.mkdir()
    monkeypatch.chdir(tmp_path)
    caplog.set_level("ERROR")
    exit_code = cmd_build(
        "proj",
        title=None,
        prefixes=[],
        sep=None,
        poll=None,
        address_url=None,
        output=None,
    )
    assert exit_code == 6
    assert "response missing" in caplog.text
