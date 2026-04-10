import json
from pathlib import Path

from loxvihgen.cli import main


class _FakeHeaders:
    def get_content_charset(self):
        return "utf-8"

    def get_content_type(self):
        return "application/json"


class _FakeResponse:
    def __init__(self, payload: str):
        self._payload = payload
        self.headers = _FakeHeaders()

    def read(self) -> bytes:
        return self._payload.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_cli_rules_and_build_smoke(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "weather"
    workspace.mkdir()
    monkeypatch.chdir(tmp_path)
    (workspace / "response.json").write_text(
        json.dumps({"sensor": {"temperature": 21.5, "humidity": 48}}),
        encoding="utf-8",
    )

    assert main(["rules", "weather"]) == 0
    assert main(["build", "weather", "--name-separator", ".", "--prefix", "lab"]) == 0

    xml = (workspace / "VI--lab.xml").read_text(encoding="utf-8")
    assert 'Title="lab.sensor.temperature"' in xml
    assert 'Title="lab.sensor.humidity"' in xml

    manifest = json.loads((workspace / "vih.json").read_text(encoding="utf-8"))
    assert manifest["project"] == "weather"
    assert manifest["source"]["response"] == "response.json"
    assert manifest["rules"] == "rules.json"
    assert manifest["build"]["name_separator"] == "."
    assert manifest["build"]["address_url"] is None
    assert manifest["prefixes"] == ["lab"]
    assert '"utc"' not in xml


def test_cli_build_rerun_reuses_saved_manifest_defaults(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "weather"
    workspace.mkdir()
    monkeypatch.chdir(tmp_path)
    (workspace / "response.json").write_text(
        json.dumps({"sensor": {"temperature": 21.5}}),
        encoding="utf-8",
    )

    assert main(["rules", "weather"]) == 0
    assert main(["build", "weather", "--name-separator", ".", "--prefix", "lab"]) == 0
    first = (workspace / "VI--lab.xml").read_text(encoding="utf-8")

    assert main(["build", "weather"]) == 0
    second = (workspace / "VI--lab.xml").read_text(encoding="utf-8")

    assert first == second


def test_cli_fetch_after_local_build_uses_real_source_url(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "weather"
    workspace.mkdir()
    monkeypatch.chdir(tmp_path)
    (workspace / "response.json").write_text(
        json.dumps({"sensor": {"temperature": 21.5}}),
        encoding="utf-8",
    )

    assert main(["rules", "weather"]) == 0
    assert main(["build", "weather"]) == 0

    fetched_url = "https://api.example.invalid/current"
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda url, timeout=30: _FakeResponse('{"sensor":{"temperature":22.0}}'),
    )
    assert main(["fetch", "weather", "--url", fetched_url]) == 0
    assert main(["build", "weather"]) == 0

    manifest = json.loads((workspace / "vih.json").read_text(encoding="utf-8"))
    xml = (workspace / "VI.xml").read_text(encoding="utf-8")
    assert manifest["source"]["url"] == fetched_url
    assert manifest["build"]["address_url"] is None
    assert f'Address="{fetched_url}"' in xml


def test_cli_invalid_rules_returns_error(tmp_path: Path, monkeypatch, caplog) -> None:
    workspace = tmp_path / "broken"
    workspace.mkdir()
    monkeypatch.chdir(tmp_path)
    (workspace / "response.json").write_text(
        '{"sensor":{"temperature":21.5}}',
        encoding="utf-8",
    )
    (workspace / "rules.json").write_text("{not-json", encoding="utf-8")

    caplog.set_level("ERROR")
    assert main(["build", "broken"]) == 2
    assert "rules file is not valid JSON" in caplog.text


def test_cli_invalid_response_returns_error(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    workspace = tmp_path / "broken"
    workspace.mkdir()
    monkeypatch.chdir(tmp_path)
    (workspace / "response.json").write_text("not json and not xml", encoding="utf-8")

    caplog.set_level("ERROR")
    assert main(["rules", "broken"]) == 2
    assert "response is not valid JSON or XML" in caplog.text


def test_cli_invalid_manifest_returns_error(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    workspace = tmp_path / "broken"
    workspace.mkdir()
    monkeypatch.chdir(tmp_path)
    (workspace / "vih.json").write_text("{not-json", encoding="utf-8")

    caplog.set_level("ERROR")
    assert main(["build", "broken"]) == 2
    assert "manifest is not valid JSON" in caplog.text
