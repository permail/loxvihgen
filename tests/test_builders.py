from loxvihgen.core import ObjKey, ArrIdx, Path
from loxvihgen.builders import TitleBuilder, JSONCheckStringBuilder, XMLCheckStringBuilder
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


def test_cmd_build_missing_response(tmp_path, monkeypatch, capsys):
    project = "proj"
    monkeypatch.chdir(tmp_path)
    exit_code = cmd_build(project, title=None, prefixes=[], sep=None, poll=None, address_url=None, output=None)
    captured = capsys.readouterr()
    assert exit_code == 6
    assert "response missing" in captured.out


def test_cmd_build_multiple_prefixes(tmp_path, monkeypatch):
    project = "proj"
    resp = tmp_path / f"{project}.response.json"
    resp.write_text('{"a": 1}')
    monkeypatch.chdir(tmp_path)
    exit_code = cmd_build(project, title=None, prefixes=["p1", "p2"], sep=".", poll=None, address_url=None, output=None)
    assert exit_code == 0
    xml1 = (tmp_path / "VI_proj--p1.xml").read_text()
    xml2 = (tmp_path / "VI_proj--p2.xml").read_text()
    assert 'VirtualInHttpCmd Title="p1.a"' in xml1
    assert 'VirtualInHttpCmd Title="p2.a"' in xml2
