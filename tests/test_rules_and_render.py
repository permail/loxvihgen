import json
from pathlib import Path

from loxvihgen.builders import JSONCheckStringBuilder, TitleBuilder, VIHBuilder
from loxvihgen.renderer import ViHttpXmlRenderer
from loxvihgen.rules import Rules, UnitRule
from loxvihgen.sources import FormatAdapter

sample = {
  "a": {"b": [{"x": 1.23}, {"x": 4}]}
}

def test_full_pipeline_json(tmp_path: Path):
    text = json.dumps(sample)
    adapter = FormatAdapter.sniff(text)
    rules = Rules.load(None)
    tb = TitleBuilder(sep='.', prefix='pref', width_by_key=adapter.source.index_widths())
    vih = VIHBuilder(adapter.source, tb, rules, JSONCheckStringBuilder())
    cmds = vih.build_commands()
    assert len(cmds) == 2
    assert {c.title for c in cmds} == {'pref.a.b[0].x', 'pref.a.b[1].x'}
    assert all(c.unit == '<v.2>' for c in cmds)
    xml = ViHttpXmlRenderer().render(
        cmds,
        title="T",
        address_url="http://...",
        polling_time=1200,
        comment_json="",
    )
    assert xml.count('<VirtualInHttpCmd') == 2
    assert xml.startswith('<?xml version="1.0" encoding="utf-8"?>\n')


def test_rules_longest_suffix_wins():
    rules = Rules(
        [
            UnitRule(pattern="x", tokens=["x"], unit="V", order=0),
            UnitRule(pattern="b.x", tokens=["b", "x"], unit="mV", order=1),
        ]
    )
    adapter = FormatAdapter.sniff(json.dumps(sample))
    tb = TitleBuilder(sep=".", prefix="", width_by_key=adapter.source.index_widths())
    vih = VIHBuilder(adapter.source, tb, rules, JSONCheckStringBuilder())
    units = {c.title: c.unit for c in vih.build_commands()}
    assert units["a.b[0].x"] == "<v.2> mV"
