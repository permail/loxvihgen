from loxvihgen.core import ObjKey, ArrIdx, Path
from loxvihgen.builders import TitleBuilder, JSONCheckStringBuilder, XMLCheckStringBuilder

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
