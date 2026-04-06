# Changelog

All notable changes to **fancli** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] — 2026-04-07

### Added

- Initial public release on [PyPI](https://pypi.org/project/fancli/).
- Terminal CLI for smart fans via the **Atomberg IoT developer API** (token refresh, cached access token, device status, commands).
- **`fancli setup`** — interactive wizard: vendor, credentials, list devices, save `DEVICE_ID`.
- **`fancli status`** — read device state (optional `--json`).
- **`fancli set <key> <value>`** — send commands (power, speed, timer, lights, etc.); `fancli set --help` for key/value reference.
- **`fancli` / `fancli help`** — bundled user guide (`help.txt`).
- Configuration via **`.env`** or environment (see README): `REFRESH_TOKEN`, `API_KEY`, `DEVICE_ID`, optional `API_URL`, `FANCLI_*`.
- **Python 3.9+**; dependencies: `requests`, `python-dotenv`.
- **MIT** license; metadata and project URLs in `pyproject.toml`.

[0.1.0]: https://github.com/Affan-sajid/fancli/releases/tag/v0.1.0
