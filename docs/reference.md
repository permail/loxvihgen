# Reference

## Repo Workflow

The repository standardizes on `uv`.

Common commands:

- `uv python install`: install the pinned local Python version
- `uv sync --locked`: create or update the local `.venv` from `uv.lock`
- `uv run pytest -q`: run the test suite
- `uv run ruff check .`: run lint checks
- `uv run mypy loxvihgen`: run the static type check
- `uv build`: build sdist and wheel
- `uv lock`: refresh `uv.lock` after dependency changes

## Commands

### `loxvihgen fetch WORKSPACE [-u URL]`

Fetches a response via HTTP GET and stores it as:

- `WORKSPACE/response.json`, or
- `WORKSPACE/response.xml`

It also creates or updates `WORKSPACE/vih.json`.

If `-u/--url` is omitted, the command uses the URL stored in the manifest.

### `loxvihgen rules WORKSPACE [--force]`

Reads the response snapshot and creates `WORKSPACE/rules.json`.

It also creates or updates `WORKSPACE/vih.json` so the workspace can be rerun
later, even if you started from a local snapshot instead of `fetch`.

- `--force`: overwrite an existing `rules.json`

### `loxvihgen build WORKSPACE [options]`

Builds one or more XML files from the response snapshot and rules.

The effective build settings are written back to `WORKSPACE/vih.json`, so a
later `build WORKSPACE` run can reuse the same workspace defaults.

If no explicit `--address-url`, saved XML address override, or fetched source
URL is available, the generated XML uses `http://...` as a render-only
placeholder. That placeholder is not stored back as a project default.

Options:

- `--title TITLE`: Virtual HTTP title
- `--prefix PREFIX`: repeatable command-title prefix
- `--name-separator SEP`: separator between title path segments
- `--polling-time SECONDS`: Virtual HTTP polling interval
- `--address-url URL`: address stored in generated XML
- `--output PATH`: explicit output file for single-prefix builds

### `loxvihgen all WORKSPACE -u URL`

Runs:

1. `fetch`
2. `rules` if the rules file does not exist yet
3. `build`

## Common Use Patterns

### One-Off From An Existing Snapshot

```bash
uv run loxvihgen rules weather
uv run loxvihgen build weather --name-separator "." --prefix owm
```

This is the shortest path from one captured payload to one reviewable XML file.

### Repeatable Project With Stored Defaults

```bash
uv run loxvihgen all weather -u 'https://api.example.invalid/current?token=REDACTED'
uv run loxvihgen fetch weather
uv run loxvihgen build weather
```

This is the better mode when you expect to refresh the snapshot and rebuild.

## Error Cases

These cases are treated as normal user-facing errors:

- missing response snapshot
- invalid `vih.json`
- invalid `rules.json`
- response files that are neither valid JSON nor valid XML

## Rules File

Rules use suffix matching on dot-separated path fragments:

```json
{
  "overrides": [
    { "pattern": "temp", "unit": "°C" },
    { "pattern": "aenergy.total", "unit": "<v.3> kWh" }
  ]
}
```

Semantics:

- longest suffix match wins
- `unit: "°C"` becomes `<v> °C` or `<v.N> °C`
- `unit: "<v.3> kWh"` replaces the whole format string

A small practical example:

- generated default: `<v.1>`
- rule: `{ "pattern": "current.temp", "unit": "°C" }`
- result: `<v.1> °C`

Use a full format string when the default decimal precision is wrong or when
the suffix alone is not enough.

## Rules Recipes

Common patterns:

- add a unit suffix without changing inferred decimals
- replace the full format string when decimals or formatting must change
- use a shorter suffix pattern to affect a whole family of fields

Examples:

- `{ "pattern": "temp", "unit": "°C" }`
  Appends `°C` while keeping the inferred `<v>` or `<v.N>` precision.
- `{ "pattern": "aenergy.total", "unit": "<v.3> kWh" }`
  Replaces the full format string to force three decimals.
- `{ "pattern": "wind_speed", "unit": "m/s" }`
  Applies to any path whose suffix ends in `wind_speed`.

See also:

- [`examples/shelly_plug/rules.json`](../examples/shelly_plug/rules.json)
- [`examples/openweathermap.org/rules.json`](../examples/openweathermap.org/rules.json)

## Files

- `response.json` / `response.xml`: input snapshot
- `rules.json`: rules overrides
- `vih.json`: manifest with stored rerun defaults
- `VI.xml`: generated XML without prefixes
- `VI--PREFIX.xml`: generated XML for prefixed builds
