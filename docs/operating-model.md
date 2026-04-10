# Operating Model

## Working Directory

`loxvihgen` operates on one working directory per source.

Example:

```text
weather/
  response.json
  rules.json
  vih.json
  VI.xml
```

Running `loxvihgen build weather` from the parent directory reads and writes
those files inside `weather/`.

## First Run From A Local Snapshot

The simplest entry point is a captured file such as:

```text
weather/response.json
```

From there:

1. `loxvihgen rules weather` creates `weather/rules.json` and `weather/vih.json`
2. you optionally edit the rules file
3. `loxvihgen build weather ...` writes one or more `weather/VI*.xml` files

This is the right mode when you already have a snapshot and mainly want a first
usable XML export.

## First Run From A URL

If you want the tool to fetch the snapshot itself:

1. `loxvihgen all weather -u URL`
2. the command fetches the response
3. it creates `weather/rules.json` if missing
4. it builds the XML

This mode is better when the response source is stable enough that reruns are
expected.

## Sources Of Truth

- `response.json` or `response.xml`
  The captured upstream payload that defines the discoverable numeric fields.
- `rules.json`
  User-maintained overrides for units and format strings.
- `vih.json`
  Stored defaults such as prefixes, polling time, separator, title, and an
  optional XML address override.

Generated XML is derived output. It should be reproducible from the snapshot,
rules, and manifest.

When you start from a local snapshot instead of `fetch` or `all`, the manifest
is still created on the first successful `rules` or `build` run. That lets a
one-off workflow grow into a repeatable project later.

## Command Generation

- JSON and XML are auto-detected from the response text.
- Numeric values are discovered by walking the response tree.
- Array indices are preserved in command titles and check strings.
- Decimal precision is inferred from observed values per path signature.
- Rules can replace the unit suffix or the complete Loxone format string.

## Reruns

Healthy reruns should be stable:

- `rules` may create a skeleton if missing and records the current response file
- `build` regenerates the XML and writes the effective build defaults back to
  `vih.json`
- `fetch` refreshes the stored response snapshot
- `all` combines `fetch`, `rules`-if-missing, and `build`

That means an explicit first build such as:

```text
loxvihgen build weather --name-separator "." --prefix owm
```

can be followed later by:

```text
loxvihgen build weather
```

using the saved workspace defaults.

Malformed manifests, malformed rules files, and malformed response snapshots are
treated as clear user errors instead of being silently ignored.

If no real source URL or explicit `--address-url` is known, the generated XML
falls back to `http://...` for that run only. The placeholder is not treated as
a saved project default.

## Public Examples

Files under `examples/` are product-facing documentation artifacts. They should
show realistic shapes while keeping private hosts, API keys, SSIDs, MAC
addresses, and internal network details out of the repo.
