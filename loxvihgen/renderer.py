# SPDX-License-Identifier: GPL-3.0-only
from __future__ import annotations
from typing import List
from .builders import Command

class ViHttpXmlRenderer:
    def __init__(self, miniserver_min_version: str = "16000610"):
        self.miniserver_min_version = miniserver_min_version

    @staticmethod
    def _xml_attr_escape(s: str) -> str:
        # Minimal escape for attributes; commands provide &quot;/&lt; already
        return (s.replace("&", "&amp;")
                 .replace("\"", "&quot;")
                 .replace("<", "&lt;")
                 .replace(">", "&gt;"))

    def render(self, commands: List[Command], title: str, address_url: str, polling_time: int, comment_json: str) -> str:
        title_attr = self._xml_attr_escape(title)
        addr_attr = self._xml_attr_escape(address_url)
        comment_attr = self._xml_attr_escape(comment_json) if comment_json else ""
        lines: List[str] = []
        if comment_json:
            lines.append(f"<!-- {comment_json} -->")
        lines.append(f"<VirtualInHttp Title=\"{title_attr}\" Comment=\"{comment_attr}\" Address=\"{addr_attr}\" HintText=\"\" PollingTime=\"{polling_time}\">")
        lines.append(f"	<Info templateType=\"2\" minVersion=\"{self.miniserver_min_version}\"/>")
        for c in commands:
            unit_attr = self._xml_attr_escape(c.unit)
            lines.append(
                "	<VirtualInHttpCmd "
                f"Title=\"{self._xml_attr_escape(c.title)}\" "
                f"Unit=\"{unit_attr}\" "
                f"Check=\"{c.check}\" "  # check string contains &quot; and &lt; already
                f"Signed=\"true\" Analog=\"true\" "
                f"SourceValLow=\"0\" DestValLow=\"0\" "
                f"SourceValHigh=\"100\" DestValHigh=\"100\" "
                f"Comment=\"\"/>"
            )
        lines.append("</VirtualInHttp>")
        body = "\n".join(lines) + "\n"
        return f"<?xml version=\"1.0\" encoding=\"utf-8\"?>{body}"
