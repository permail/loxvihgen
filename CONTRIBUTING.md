# Contributing

## Local Setup

```bash
uv python install
uv sync --locked
```

## Checks

```bash
uv run ruff check .
uv run mypy loxvihgen
uv run pytest -q
uv build
```

## Expectations

- Keep the product scope narrow and explicit.
- Update only the docs whose responsibility changed.
- Keep `uv.lock` in sync with `pyproject.toml`.
- Keep examples redacted and publishable.
- Prefer reproducible snapshot-based tests over live network tests.
- Do not add private endpoints, API keys, SSIDs, MAC addresses, or personal
  email addresses to tracked files.
