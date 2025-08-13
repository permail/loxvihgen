import json

from loxvihgen.rules import generate_rules_skeleton
from loxvihgen.core import Path, ObjKey


class DummySource:
    def iter_numeric_leaves(self):
        yield Path([ObjKey("$root"), ObjKey("a"), ObjKey("c")]), 1, 0
        yield Path([ObjKey("$root"), ObjKey("a"), ObjKey("b")]), 2, 0


def test_generate_rules_skeleton():
    result = generate_rules_skeleton(DummySource())
    obj = json.loads(result)
    assert obj == {"overrides": [
        {"pattern": "a.b", "unit": ""},
        {"pattern": "a.c", "unit": ""},
    ]}
    assert "/n" not in result
    assert result.count("\n") >= 5
