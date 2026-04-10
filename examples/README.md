# Examples

These directories are publishable, redacted project snapshots. They are meant
to answer "what does a real working project directory look like?" without
requiring you to run the tool first.

## Start Here

If you just found the repo, look at these examples in this order:

- `shelly_getstatus/`
  The shortest local-snapshot path. It shows `response.json`, `rules.json`,
  and `vih.json` after a simple `rules` run.
- `shelly_plug/`
  A more complete single-device project. It includes a generated XML file and
  shows how unit overrides and an explicit XML address override look in
  practice.
- `openweathermap.org/`
  A larger API payload with a prefix-based build and a longer rules file.
  Useful once you already understand the basic project shape.

## What To Look For

- `response.json` or `response.xml`
  The captured upstream payload.
- `rules.json`
  The user-maintained rules file. This is where unit suffixes and full Loxone
  format strings are overridden.
- `vih.json`
  The saved workspace defaults used for reruns.
- `VI*.xml`
  Generated output ready to review before importing into Loxone.

## Rules Examples

If you want to see the "bells and whistles" after learning the happy path:

- `shelly_plug/rules.json`
  Shows simple suffix replacements such as `W`, `V`, `Hz`, `A`, and `°C`.
- `shelly_plug/VI.xml`
  Shows the resulting rendered units in the final XML.
- `openweathermap.org/rules.json`
  Shows a larger real-world rules file with repeated temperature, pressure,
  precipitation, and wind overrides.

The repo does not treat these directories as golden integration fixtures. They
are product-facing documentation artifacts and should stay realistic, redacted,
and aligned with the current CLI behavior.
