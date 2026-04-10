# LoxVIHGen

`loxvihgen` turns a captured JSON or XML response into a Loxone Virtual HTTP
input template.

It is intentionally narrow:

- it works from response snapshots, not live API schemas
- it emits one command per numeric leaf value
- it lets you override units and format strings through a small rules file

This keeps it useful for quickly bootstrapping Loxone integrations from real
payloads without pretending to be a general API client or a full Loxone project
generator.

## When It Helps

Use `loxvihgen` when all you really need is:

- one real JSON or XML response from a device or API
- a first useful Loxone VI HTTP XML file
- a place to tweak units or format strings before importing into Loxone

It is aimed at technical Loxone or home-automation users who are comfortable
capturing a response snapshot and editing a small JSON rules file.

## Setup

```bash
uv python install
uv sync --locked
```

## Fastest Path: Local Snapshot In, XML Out

Assume you want to make one response from a weather API usable in Loxone.

Create one working directory for that source and put the captured snapshot
there:

```text
weather/
  response.json
```

From the parent directory, generate a rules skeleton from the numeric fields:

```bash
uv run loxvihgen rules weather
```

This creates:

- `weather/rules.json`
- `weather/vih.json`

If you want nicer units or custom Loxone format strings, edit
`weather/rules.json`.

Then build the XML:

```bash
uv run loxvihgen build weather --name-separator "." --prefix owm
```

This writes:

- `weather/VI--owm.xml`

Import that XML into Loxone and review the generated commands before treating
it as finished.

## Repeatable Project Mode

If you expect reruns, keep one source per working directory with fixed file
names:

- `response.json` or `response.xml`
- `rules.json`
- `vih.json`
- `VI.xml` or `VI--PREFIX.xml`

Concretely, a repeatable workspace looks like this:

```text
weather/
  response.json or response.xml
  rules.json
  vih.json
  VI.xml or VI--PREFIX.xml
```

`vih.json` stores the reusable workspace defaults. Successful `rules` and
`build` runs update it, so later `build` runs can reuse the same separator,
prefixes, title, polling interval, and address URL.

To fetch a response and initialize the manifest in one go:

```bash
uv run loxvihgen all weather -u 'https://api.example.invalid/current?token=REDACTED'
```

After that, a typical repeat cycle is:

```bash
uv run loxvihgen fetch weather
uv run loxvihgen build weather
```

If you are only doing a one-off conversion from a local snapshot, you do not
need to care much about `vih.json`. It will still be created, but you can
mostly treat it as workspace bookkeeping.

## Examples

See [`examples/README.md`](examples/README.md) for redacted project directories
grouped by use case:

- shortest local-snapshot workflow
- complete single-source build with unit overrides
- rules-based unit and format overrides on a larger payload

## Docs

- [`docs/positioning.md`](docs/positioning.md): scope and why this tool exists
- [`docs/contract.md`](docs/contract.md): stable product invariants
- [`docs/operating-model.md`](docs/operating-model.md): first run, reruns, and file semantics
- [`docs/reference.md`](docs/reference.md): CLI flags, rules syntax, and file layout
- [`CONTRIBUTING.md`](CONTRIBUTING.md): contributor workflow

This repo standardizes on `uv` for local setup, locking, checks, and builds.

## License

GPL-3.0-only. See [`LICENSE`](LICENSE).
