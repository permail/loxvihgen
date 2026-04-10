# Positioning

`loxvihgen` exists for one narrow job: take a real JSON or XML response
snapshot and turn its numeric leaf values into a Loxone Virtual HTTP input
template.

## Primary Use Case

The typical user has already captured one real response from a device or API
and wants a first VI HTTP XML template without manually walking the whole
payload field by field.

That usually means:

- bootstrap an integration from one known-good payload
- review the generated commands in Loxone afterwards
- optionally refine units and Loxone format strings before import

The value is speed and structure during the first translation step, not full
automation of the whole integration lifecycle.

That is deliberately smaller than:

- a generic API explorer
- a schema-driven code generator
- a full Loxone project authoring tool

Why this still matters:

- many integrations start from a captured payload, not a maintained schema
- Loxone users often need a first useful XML template quickly
- numeric telemetry is the part that is most valuable to bootstrap reliably

## Intended User

The intended user is a technical Loxone or home-automation integrator who can:

- capture a response snapshot
- recognize which generated values are worth keeping
- edit a small JSON rules file when defaults are not good enough

This is not aimed at non-technical end users looking for a polished desktop
wizard or a turnkey integration marketplace.

Non-goals:

- managing authentication or refresh tokens
- modeling every non-numeric field
- discovering live APIs automatically
- editing an existing Loxone project

The product claim should stay narrow: this tool accelerates the first
translation from response snapshot to Loxone VIH XML. It does not remove the
need to understand the upstream service or review the generated commands.
