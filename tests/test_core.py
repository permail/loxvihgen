import json
from loxvihgen.core import ObjKey, ArrIdx, Path
from loxvihgen.sources import JSONSource

sample = {"a": {"b": [1.2, 3, {"c": 4.56}]}}

def test_path_signature():
    p = Path([ObjKey("a"), ObjKey("b"), ArrIdx("b", 2), ObjKey("c")])
    assert p.signature() == ("a","b","b[]","c")

def test_json_numeric_leaves_and_decimals():
    src = JSONSource(sample)
    leaves = list(src.iter_numeric_leaves())
    # expect 3 numeric leaves (1.2, 3, 4.56)
    assert len(leaves) == 3
    decs = sorted(d for _p, _v, d in leaves)
    assert decs == [0,1,2]
