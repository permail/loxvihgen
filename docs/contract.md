# Contract

Stable invariants for `loxvihgen`:

- The primary input is a local response snapshot file, not a live endpoint.
- Supported input formats are JSON and XML.
- The generator emits one Virtual HTTP command for each numeric leaf value.
- Command titles are derived from response paths plus an optional prefix.
- Rules match by dot-separated suffix path, with the longest matching suffix
  taking precedence.
- If a rule unit starts with `<`, it is treated as a full Loxone format string.
- The CLI is workspace-directory based:
  `response.*`, `rules.json`, `vih.json`, and `VI*.xml` live inside the
  selected working directory.
- Successful `rules` and `build` runs update `vih.json` so reruns can reuse
  the current workspace defaults.
- Generated XML is deterministic for the same input snapshot, rules, and build
  options.
- Example directories in this repo are intended to be publishable snapshots and
  must stay redacted.

Non-contractual details that may evolve:

- exact metadata embedded in generated XML comments
- logging wording
- contributor tooling and CI shape
