# fancli

[![PyPI version](https://img.shields.io/pypi/v/fancli.svg)](https://pypi.org/project/fancli/)
[![Python versions](https://img.shields.io/pypi/pyversions/fancli.svg)](https://pypi.org/project/fancli/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/Affan-sajid/fancli/blob/main/LICENSE)

Terminal CLI for smart fans. It refreshes and caches an access token, reads device state, and sends commands (power, speed, timer, lights, and more). **Atomberg** is supported today via the [Atomberg IoT developer API](https://developer.atomberg-iot.com); more vendors may be added later.

**Repository:** [github.com/Affan-sajid/fancli](https://github.com/Affan-sajid/fancli)

## Requirements

- Python 3.9+

## Install

### From PyPI

```bash
pip install fancli
```

CLI only, isolated from your default Python environment (recommended):

```bash
pipx install fancli
```

That installs the `fancli` command on your `PATH`. With plain `pip`, prefer a virtual environment or `pip install --user` and ensure your user scripts directory is on `PATH`.

### From source (development)

From a clone of this repository:

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

You should then have the `fancli` command on your `PATH`.

## Quick start

1. Run interactive setup (credentials, device list, save `DEVICE_ID`):

   ```bash
   fancli setup
   ```

2. Check status:

   ```bash
   fancli status
   ```

3. Send a command:

   ```bash
   fancli set power true
   fancli set speed 3
   ```

4. Key/value reference for `set`:

   ```bash
   fancli set --help
   ```

   Or: **`fancli set -h`**

Run **`fancli`** or **`fancli help`** for the full user guide (same text as the bundled `help.txt`).

## Environment

Configure via a `.env` file (project directory, current working directory, or after setup `~/.config/fancli/.env`) or your shell. **Do not commit** `.env` or paste real tokens into issues—use placeholders when asking for help.

Variables are **names only** below; get real values from the vendor developer portal and `fancli setup`.

| Variable | Required | Description |
|----------|----------|-------------|
| `REFRESH_TOKEN` | Yes | OAuth refresh token from the developer portal |
| `API_KEY` | Yes | API key (`x-api-key` header) |
| `DEVICE_ID` | For `status` / `set` | Target device UUID |

Optional:

| Variable | Description |
|----------|-------------|
| `API_URL` | API base URL (default: `https://api.developer.atomberg-iot.com`) |
| `FANCLI_COMPANY` | Vendor name (e.g. `atomberg`); set by `fancli setup` |
| `FANCLI_TOKEN_FILE` | Override path for cached access token JSON (default: `~/.config/fancli/token.json`) |

Access tokens are cached for up to 23 hours; fancli refreshes when the cache is stale or the API returns 401.

## Commands (summary)

| Command | Purpose |
|---------|---------|
| `fancli` / `fancli help` | Full user guide |
| `fancli setup` | Interactive wizard: vendor, credentials, list devices, save selection |
| `fancli status` | Device state (`--json` for raw JSON) |
| `fancli set <key> <value>` | Send a command; **`fancli set --help`** / **`-h`** for the key/value reference (Quick start) |

## Troubleshooting

- **`REFRESH_TOKEN is not set`** — Run `fancli setup` or set variables in `.env` or your environment.
- **HTTP 401** — fancli tries to refresh the token once; verify refresh token and API key if it keeps failing.
- **`help file not found`** — Reinstall the package or run from a checkout with `fancli/help.txt` present.
