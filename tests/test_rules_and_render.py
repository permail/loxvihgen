import json
from pathlib import Path
from loxvihgen.sources import FormatAdapter
from loxvihgen.rules import Rules
from loxvihgen.builders import TitleBuilder, VIHBuilder, JSONCheckStringBuilder
from loxvihgen.renderer import ViHttpXmlRenderer

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
    assert any(c.title.startswith('pref.a.b') for c in cmds)
    xml = ViHttpXmlRenderer().render(cmds, title='T', address_url='http://...', polling_time=1200, comment_json='')
    assert '<VirtualInHttp' in xml and '</VirtualInHttp>' in xml
