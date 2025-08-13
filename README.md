# LoxVIHGen

Generate Loxone Virtual HTTP (VIH) template XML from JSON/XML responses.

- Input: JSON or XML sample (auto-detected)
- Output: Loxone VirtualInHttp XML with one command per numeric leaf
- Features: project-centric subcommands, rules (unit/format overrides), manifest, multi-prefix builds
 
## Use Case
Convert JSON or XML API responses into [Loxone](https://www.loxone.com/) VirtualInHttp commands.
This tool extracts all numeric leaves and emits an XML template that can be
imported into a Loxone project, allowing quick integration of third‑party
services.

## Usage

### CLI
```text
loxvihgen fetch  PROJECT [-u URL]
loxvihgen rules  PROJECT [--force]
loxvihgen build  PROJECT [--title TITLE] [--prefix P ...] [--name-separator SEP] [--polling-time S] [--address-url URL] [--output OUT]
loxvihgen all    PROJECT -u URL
```

- Files per `PROJECT`:
  - Response: `PROJECT.response.json` / `.xml`
  - Rules: `PROJECT.rules.json`
  - Manifest: `PROJECT.vih.json`
  - Output: `VI_PROJECT.xml` (or per-prefix: `VI_PROJECT--<prefix>.xml`)

### Typical workflow
1. Fetch + initialize (or download the response yourself):
   ```bash
   loxvihgen all weather -u 'https://api.openweathermap.org/data/3.0/onecall?units=metric&lang=en&lat=48&lon=14&appid=YOUR_KEY'
   ```
2. Generate/edit rules:
   ```bash
   loxvihgen rules weather
   # edit weather.rules.json
   ```
3. Build XML:
   ```bash
   loxvihgen build weather --name-separator '.' --prefix plug1 --title 'Shelly'
   ```

### Rules format (`project.rules.json`)
```json
{ 
  "overrides": [
    { "pattern": "temp", "unit": "°C" },
    { "pattern": "temp.min", "unit": "°C" },
    { "pattern": "hourly.wind_speed", "unit": "m/s" },
    { "pattern": "aenergy.total", "unit": "<v.3> kWh" }
  ]
}
```
- Dot-separated suffix paths; `[]` optional.
- Longest suffix match wins.
- If `unit` starts with `<`, it is used as the **entire** Loxone format string.

### Examples
See the [`examples/`](examples) folder:
- `examples/openweather/` – One Call API response + rules + manifest
- `examples/shelly_plug/` – Shelly Plug sample + rules + manifest

## Install
```bash
pip install .
# or: pipx install git+https://github.com/you/loxvihgen.git
```

## Contributing
PRs welcome. Please:
- Open an issue for discussion before large changes
- Add tests under `tests/`
- Run `pytest`
- Respect GPL-3.0-only license

## License
GPL-3.0-only. See `LICENSE`.
