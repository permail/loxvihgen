# Changelog

## Unreleased

- tighten package metadata and contributor setup around `pyproject.toml`
- standardize local and CI workflow on `uv` with a tracked lockfile
- add a checked `mypy` pass for the typed package surface
- fail clearly on malformed manifests instead of silently resetting to defaults
- fail clearly on malformed rules files and malformed response snapshots
- stop persisting placeholder XML addresses as workspace defaults
- switch the CLI from stem-based files to workspace directories with fixed file
  names (`response.*`, `rules.json`, `vih.json`, `VI*.xml`)
- remove build-timestamp churn from generated XML comments
- fix XML integer precision handling during command generation
- add CLI and rule-precedence regression tests
- reshape the repo docs around product scope, operating model, and reference
- redact and refresh publishable examples
