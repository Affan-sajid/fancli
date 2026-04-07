#!/usr/bin/env python3
"""CLI for smart fan control (currently Atomberg): token cache, status, commands."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import textwrap
import warnings

# urllib3 warns on LibreSSL (macOS system Python) when imported; filter before requests.
warnings.filterwarnings(
    "ignore",
    message=r"urllib3 v2 only supports OpenSSL 1\.1\.1\+.*",
)
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Tuple

import requests
from dotenv import load_dotenv, set_key

from fancli import __version__

TOKEN_MAX_AGE = timedelta(hours=23)
DEFAULT_API_URL = "https://api.developer.atomberg-iot.com"

# (Command title, Description, JSON, Accepted values, Comments)
SET_COMMAND_REFERENCE_ROWS: list[tuple[str, str, str, str, str]] = [
    (
        "Power",
        "Turn the fan ON or OFF",
        '{"power":val}',
        "true, false",
        "",
    ),
    (
        "Speed Absolute",
        "Set the speed of the fan to an absolute value",
        '{"speed":val}',
        "1,2,3,4,5,6",
        "",
    ),
    (
        "Speed Relative",
        "Increase/decrease speed of the fan",
        '{"speedDelta":val}',
        "1,2,3,4,5,-1,-2,-3,-4,-5",
        "",
    ),
    (
        "Sleep mode",
        "Enable or disable sleep mode",
        '{"sleep":val}',
        "true, false",
        "",
    ),
    (
        "Timer",
        "Set timer",
        '{"timer":val}',
        "0,1,2,3,4",
        "0: Turn off timer\n"
        "1: Set timer for 1 hours\n"
        "2: Set timer for 2 hours\n"
        "3: Set timer for 3 hours\n"
        "4: Set timer for 6 hours",
    ),
    (
        "Lights ON/OFF",
        "Turn the light ON or OFF",
        '{"led":val}',
        "true, false",
        "For Aris Starlight, it will set the fan light at the last known color or "
        "brightness values",
    ),
    (
        "Brightness Absolute",
        "Set the brightness of the fan to an absolute value",
        '{"brightness":val}',
        "10 to 100",
        "Percentage brightness",
    ),
    (
        "Brightness Delta",
        "Increase/decrease brightness of the fan",
        '{"brightnessDelta":val}',
        "-90 to +90",
        "Percentage brightness",
    ),
    (
        "Color",
        "Change the color of the light",
        '{"light_mode":val}',
        '"warm","cool","daylight"',
        "",
    ),
]


def _find_dotenv() -> Optional[Path]:
    cwd = Path.cwd()
    pkg_dir = Path(__file__).resolve().parent
    repo_root = pkg_dir.parent
    for base in (cwd, repo_root, pkg_dir):
        candidate = base / ".env"
        if candidate.is_file():
            return candidate
    fallback = Path.home() / ".config" / "fancli" / ".env"
    if fallback.is_file():
        return fallback
    return None


def help_file_path() -> Path:
    return Path(__file__).resolve().parent / "help.txt"


def run_help() -> None:
    path = help_file_path()
    if not path.is_file():
        raise SystemExit(f"help file not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise SystemExit(f"cannot read help file: {e}") from e
    print(text.rstrip() + "\n")


def load_config() -> dict[str, str]:
    dotenv_path = _find_dotenv()
    if dotenv_path is not None:
        load_dotenv(dotenv_path)
    else:
        load_dotenv()
    refresh = os.environ.get("REFRESH_TOKEN", "").strip()
    device_id = os.environ.get("DEVICE_ID", "").strip()
    api_key = os.environ.get("API_KEY", "").strip()
    raw_url = os.environ.get("API_URL", "").strip()
    company = os.environ.get("FANCLI_COMPANY", "").strip()
    return {
        "refresh_token": refresh,
        "device_id": device_id,
        "api_key": api_key,
        "api_url": normalize_api_url(raw_url),
        "company": company,
    }


def normalize_api_url(raw: str) -> str:
    if not raw:
        return DEFAULT_API_URL
    raw = raw.rstrip("/")
    if not raw.startswith(("http://", "https://")):
        raw = f"https://{raw}"
    return raw


def token_file_path() -> Path:
    override = os.environ.get("FANCLI_TOKEN_FILE", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "fancli" / "token.json"


def read_token_cache(path: Path) -> Tuple[Optional[str], Optional[datetime]]:
    if not path.is_file():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    token = data.get("access_token")
    if not isinstance(token, str) or not token:
        return None, None
    raw_ts = data.get("obtained_at")
    if not isinstance(raw_ts, str):
        return None, None
    try:
        # ISO 8601 from datetime.isoformat()
        obtained = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
        if obtained.tzinfo is None:
            obtained = obtained.replace(tzinfo=timezone.utc)
    except ValueError:
        return None, None
    return token, obtained


def write_token_cache(path: Path, access_token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    payload = {
        "access_token": access_token,
        "obtained_at": now.isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def token_is_fresh(obtained_at: Optional[datetime]) -> bool:
    if obtained_at is None:
        return False
    now = datetime.now(timezone.utc)
    return now - obtained_at < TOKEN_MAX_AGE


def fetch_access_token(
    session: requests.Session,
    base_url: str,
    refresh_token: str,
    api_key: str,
) -> str:
    url = f"{base_url}/v1/get_access_token"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {refresh_token}",
        "x-api-key": api_key,
    }
    r = session.get(url, headers=headers, timeout=30)
    if r.status_code != 200:
        snippet = (r.text or "")[:500]
        raise SystemExit(
            f"get_access_token failed: HTTP {r.status_code}\n{snippet}"
        )
    try:
        data = r.json()
    except json.JSONDecodeError as e:
        raise SystemExit(f"get_access_token: invalid JSON: {e}") from e
    msg = data.get("message")
    if isinstance(msg, dict):
        token = msg.get("access_token")
    else:
        token = None
    if not isinstance(token, str) or not token:
        raise SystemExit(
            "get_access_token: missing message.access_token in response"
        )
    return token


def get_valid_access_token(
    session: requests.Session,
    cfg: dict[str, str],
    cache_path: Path,
    force_refresh: bool = False,
) -> str:
    if not cfg["refresh_token"]:
        raise SystemExit("REFRESH_TOKEN is not set in the environment.")
    if not cfg["api_key"]:
        raise SystemExit("API_KEY is not set in the environment.")

    cached, obtained = read_token_cache(cache_path)
    if not force_refresh and cached and token_is_fresh(obtained):
        return cached

    token = fetch_access_token(
        session,
        cfg["api_url"],
        cfg["refresh_token"],
        cfg["api_key"],
    )
    write_token_cache(cache_path, token)
    return token


def api_headers(access_token: str, api_key: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}",
        "x-api-key": api_key,
    }


def get_device_state(
    session: requests.Session,
    base_url: str,
    device_id: str,
    access_token: str,
    api_key: str,
) -> requests.Response:
    url = f"{base_url}/v1/get_device_state"
    params = {"device_id": device_id}
    return session.get(
        url,
        params=params,
        headers=api_headers(access_token, api_key),
        timeout=30,
    )


def get_list_of_devices(
    session: requests.Session,
    base_url: str,
    access_token: str,
    api_key: str,
) -> requests.Response:
    url = f"{base_url}/v1/get_list_of_devices"
    return session.get(
        url,
        headers=api_headers(access_token, api_key),
        timeout=30,
    )


def send_command(
    session: requests.Session,
    base_url: str,
    device_id: str,
    command: dict[str, Any],
    access_token: str,
    api_key: str,
) -> requests.Response:
    url = f"{base_url}/v1/send_command"
    body = {"device_id": device_id, "command": command}
    headers = {
        **api_headers(access_token, api_key),
        "Content-Type": "application/json",
    }
    return session.post(
        url,
        headers=headers,
        json=body,
        timeout=30,
    )


def _term_width() -> int:
    try:
        w = shutil.get_terminal_size().columns
    except OSError:
        w = 80
    return max(40, w)


def _format_labeled_field(label: str, content: str) -> list[str]:
    """One labeled field; wraps to terminal width. Multi-line content uses a hanging block."""
    if not content.strip():
        return []
    indent = "  "
    hang = "    "
    tw = _term_width()
    if "\n" in content:
        lines = [f"{indent}{label}:"]
        avail = max(20, tw - len(hang) - 1)
        for raw in content.strip().split("\n"):
            ln = raw.strip()
            if not ln:
                continue
            wrapped = textwrap.wrap(
                ln,
                width=avail,
                break_long_words=True,
                break_on_hyphens=False,
            )
            for wline in wrapped or [ln]:
                lines.append(hang + wline)
        return lines

    prefix = f"{indent}{label}: "
    avail = max(16, tw - len(prefix))
    wrapped = textwrap.wrap(
        content.strip(),
        width=avail,
        break_long_words=True,
        break_on_hyphens=False,
    )
    if not wrapped:
        return []
    lines = [prefix + wrapped[0]]
    pad = " " * len(prefix)
    for wline in wrapped[1:]:
        lines.append(pad + wline)
    return lines


def _format_command_reference_block(
    title: str,
    desc: str,
    json_snippet: str,
    accepted: str,
    comments: str,
) -> list[str]:
    out: list[str] = [title]
    out.extend(_format_labeled_field("Description", desc))
    out.extend(_format_labeled_field("JSON", json_snippet))
    out.extend(_format_labeled_field("Accepted", accepted))
    if comments.strip():
        out.extend(_format_labeled_field("Comments", comments))
    return out


def get_set_command_reference_text() -> str:
    """Readable reference for `fancli set` (narrow blocks, wraps to terminal width)."""
    parts: list[str] = [
        "Values are parsed as JSON first, then int, float, or plain text.",
        "",
    ]
    for i, row in enumerate(SET_COMMAND_REFERENCE_ROWS):
        cmd, desc, jsn, acc, com = row
        parts.extend(_format_command_reference_block(cmd, desc, jsn, acc, com))
        if i < len(SET_COMMAND_REFERENCE_ROWS) - 1:
            parts.extend(["", "-" * min(40, _term_width()), ""])
    return "\n".join(parts)


def print_set_command_help() -> None:
    """Full reference when `fancli set --help`, `fancli set -h`, `fancli set`, or `fancli set help`."""
    print("Primary: fancli set --help  (or fancli set -h)")
    print("Shortcut: fancli set  with no arguments, or: fancli set help")
    print()
    print("Usage: fancli set <key> <value>")
    print()
    print(get_set_command_reference_text())


def parse_value(raw: str) -> Any:
    s = raw.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return raw


def _format_epoch_utc(epoch: Any) -> str:
    if not isinstance(epoch, (int, float)):
        return str(epoch)
    try:
        dt = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except (OSError, ValueError, OverflowError):
        return str(epoch)


def _print_status_pretty(data: dict[str, Any]) -> None:
    """Print get_device_state JSON in a readable layout when structure matches."""
    status = data.get("status")
    msg = data.get("message")
    if status != "Success" or not isinstance(msg, dict):
        print(json.dumps(data, indent=2))
        return

    ds = msg.get("device_state")
    if not isinstance(ds, list):
        print(json.dumps(data, indent=2))
        return

    lines: list[str] = ["Device status", ""]

    if not ds:
        lines.append("  (no devices in response)")
        print("\n".join(lines))
        return

    for i, dev in enumerate(ds):
        if not isinstance(dev, dict):
            continue
        if i > 0:
            lines.append("-" * min(40, _term_width()))
            lines.append("")

        did = dev.get("device_id")
        lines.append(f"  {did}" if did is not None else "  (unknown device)")
        lines.extend(
            _format_labeled_field(
                "Power", "on" if dev.get("power") else "off"
            )
        )
        spd = dev.get("last_recorded_speed")
        if spd is not None:
            lines.extend(_format_labeled_field("Speed", str(spd)))
        lines.extend(
            _format_labeled_field(
                "Sleep mode", "on" if dev.get("sleep_mode") else "off"
            )
        )
        lines.extend(
            _format_labeled_field("LED", "on" if dev.get("led") else "off")
        )
        lines.extend(
            _format_labeled_field(
                "Online", "yes" if dev.get("is_online") else "no"
            )
        )
        th = dev.get("timer_hours")
        if th is not None:
            lines.extend(_format_labeled_field("Timer", f"{th} h"))
        te = dev.get("timer_time_elapsed_mins")
        if te is not None:
            lines.extend(_format_labeled_field("Timer elapsed", f"{te} min"))
        ts = dev.get("ts_epoch_seconds")
        if ts is not None:
            lines.extend(_format_labeled_field("Last update", _format_epoch_utc(ts)))

    print("\n".join(lines))


def run_status(cfg: dict[str, str], cache_path: Path, json_output: bool = False) -> None:
    if not cfg["device_id"]:
        raise SystemExit("DEVICE_ID is not set in the environment.")

    session = requests.Session()
    access = get_valid_access_token(session, cfg, cache_path)

    def do_get(tok: str) -> requests.Response:
        return get_device_state(
            session,
            cfg["api_url"],
            cfg["device_id"],
            tok,
            cfg["api_key"],
        )

    r = do_get(access)
    if r.status_code == 401:
        access = get_valid_access_token(session, cfg, cache_path, force_refresh=True)
        r = do_get(access)

    if r.status_code != 200:
        snippet = (r.text or "")[:500]
        raise SystemExit(f"get_device_state failed: HTTP {r.status_code}\n{snippet}")

    try:
        data = r.json()
    except json.JSONDecodeError as e:
        raise SystemExit(f"get_device_state: invalid JSON: {e}") from e
    if json_output:
        print(json.dumps(data, indent=2))
    elif isinstance(data, dict):
        _print_status_pretty(data)
    else:
        print(json.dumps(data, indent=2))


def run_set(cfg: dict[str, str], cache_path: Path, key: str, value_raw: str) -> None:
    if not cfg["device_id"]:
        raise SystemExit("DEVICE_ID is not set in the environment.")

    value = parse_value(value_raw)
    command = {key: value}

    session = requests.Session()
    access = get_valid_access_token(session, cfg, cache_path)

    def do_post(tok: str) -> requests.Response:
        return send_command(
            session,
            cfg["api_url"],
            cfg["device_id"],
            command,
            tok,
            cfg["api_key"],
        )

    r = do_post(access)
    if r.status_code == 401:
        access = get_valid_access_token(session, cfg, cache_path, force_refresh=True)
        r = do_post(access)

    if r.status_code != 200:
        snippet = (r.text or "")[:500]
        raise SystemExit(f"send_command failed: HTTP {r.status_code}\n{snippet}")

    try:
        data = r.json()
    except json.JSONDecodeError as e:
        raise SystemExit(f"send_command: invalid JSON: {e}") from e
    print(json.dumps(data, indent=2))


# (slug or None, label, selectable) — extend when adding vendors.
SETUP_VENDOR_CHOICES: list[tuple[Optional[str], str, bool]] = [
    ("atomberg", "Atomberg", True),
    (
        None,
        "Other vendors — coming soon (not available for setup yet)",
        False,
    ),
]


def dotenv_write_path() -> Path:
    """Prefer an existing .env from the usual search path; otherwise ~/.config/fancli/.env."""
    existing = _find_dotenv()
    if existing is not None:
        return existing
    return Path.home() / ".config" / "fancli" / ".env"


def _mask_secret(s: str) -> str:
    if not s:
        return ""
    tail = s[-4:] if len(s) > 4 else s
    return "****" + tail


def _prompt_secret(
    label: str,
    existing: str,
    *,
    stdin_tty: bool,
) -> str:
    if existing:
        print(
            f"{label} (leave blank to keep {_mask_secret(existing)}): ",
            end="",
            flush=True,
        )
    else:
        print(f"{label}: ", end="", flush=True)
    if stdin_tty:
        # Keep credentials visible while typing in setup.
        line = input("")
    else:
        line = sys.stdin.readline().rstrip("\n")
    out = line.strip()
    if not out and existing:
        return existing
    if not out:
        raise SystemExit(f"{label} is required.")
    return out


def _choose_company(cfg: dict[str, str]) -> str:
    print("Select company (vendor):")
    for i, (_slug, label, _sel) in enumerate(SETUP_VENDOR_CHOICES, start=1):
        print(f"  {i}) {label}")
    cur = (cfg.get("company") or "").lower()
    if cur:
        print(f"  Current saved vendor: {cur!r}")
    print()
    print(
        "More integrations are planned. To contribute a new vendor integration, "
        "open an issue or pull request on the fancli repository (see your source "
        "checkout or where you installed the package from)."
    )
    print()
    n = len(SETUP_VENDOR_CHOICES)
    while True:
        raw = input(f"Enter choice [1–{n}] (default 1): ").strip() or "1"
        try:
            idx = int(raw)
        except ValueError:
            raise SystemExit(f"Invalid choice. Enter a number from 1 to {n}.")
        if idx < 1 or idx > n:
            raise SystemExit(f"Choice out of range. Enter a number from 1 to {n}.")
        slug, _label, selectable = SETUP_VENDOR_CHOICES[idx - 1]
        if selectable and slug:
            return slug
        print()
        print(
            "Other vendors are not available yet. Additional integrations are "
            "coming soon."
        )
        print(
            "If you want to add support for another brand, contribute to fancli "
            "(project README or repository where you obtained the source)."
        )
        print()


def _write_env_keys(path: Path, keys: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.touch()
    for k, v in keys.items():
        set_key(str(path), k, v)


def _print_devices_json(data: dict[str, Any]) -> None:
    print(json.dumps(data, indent=2))


def run_setup(cfg: dict[str, str], cache_path: Path) -> None:
    stdin_tty = sys.stdin.isatty()
    if not stdin_tty:
        raise SystemExit("fancli setup requires an interactive terminal.")

    company = _choose_company(cfg)
    if company != "atomberg":
        raise SystemExit("Only Atomberg is supported for now.")

    api_key = _prompt_secret("API key", cfg.get("api_key") or "", stdin_tty=stdin_tty)
    refresh = _prompt_secret(
        "Refresh token",
        cfg.get("refresh_token") or "",
        stdin_tty=stdin_tty,
    )

    work = {
        **cfg,
        "api_key": api_key,
        "refresh_token": refresh,
        "api_url": cfg["api_url"],
    }

    session = requests.Session()
    print("Refreshing access token…", flush=True)
    access = get_valid_access_token(session, work, cache_path, force_refresh=True)

    print("Fetching devices…", flush=True)

    def do_list(tok: str) -> requests.Response:
        return get_list_of_devices(session, work["api_url"], tok, api_key)

    r = do_list(access)
    if r.status_code == 401:
        access = get_valid_access_token(session, work, cache_path, force_refresh=True)
        r = do_list(access)

    if r.status_code != 200:
        snippet = (r.text or "")[:500]
        raise SystemExit(f"get_list_of_devices failed: HTTP {r.status_code}\n{snippet}")

    try:
        data = r.json()
    except json.JSONDecodeError as e:
        raise SystemExit(f"get_list_of_devices: invalid JSON: {e}") from e

    if not isinstance(data, dict):
        raise SystemExit("Unexpected response shape from get_list_of_devices.")

    _print_devices_json(data)

    msg = data.get("message")
    devices: list[Any] = []
    if isinstance(msg, dict):
        raw_list = msg.get("devices_list")
        if isinstance(raw_list, list):
            devices = raw_list

    if not devices:
        raise SystemExit(
            "No devices in devices_list. Fix credentials or developer mode, then retry."
        )

    print()
    print("Select a device:")
    for i, dev in enumerate(devices, start=1):
        if isinstance(dev, dict):
            did = dev.get("device_id", "?")
            name = dev.get("name", "")
            room = dev.get("room", "")
            model = dev.get("model", "")
            line = f"  {i}) {name or did}"
            bits = [b for b in (room, model) if b]
            if bits:
                line += " — " + " | ".join(str(b) for b in bits)
            line += f" [device_id={did}]"
            print(line)
        else:
            print(f"  {i}) {dev!r}")

    print()
    choice_raw = input(
        f"Enter device number (1–{len(devices)}), or q to quit: "
    ).strip()
    if choice_raw.lower() == "q":
        raise SystemExit("Aborted.")
    try:
        pick = int(choice_raw)
    except ValueError:
        raise SystemExit("Invalid number.")
    if pick < 1 or pick > len(devices):
        raise SystemExit("Choice out of range.")

    chosen = devices[pick - 1]
    if not isinstance(chosen, dict) or not chosen.get("device_id"):
        raise SystemExit("Selected entry has no device_id.")
    device_id = str(chosen["device_id"]).strip()
    if not device_id:
        raise SystemExit("Empty device_id.")

    out_path = dotenv_write_path()
    _write_env_keys(
        out_path,
        {
            "API_KEY": api_key,
            "REFRESH_TOKEN": refresh,
            "DEVICE_ID": device_id,
            "FANCLI_COMPANY": "atomberg",
        },
    )
    print()
    print(f"Saved API_KEY, REFRESH_TOKEN, DEVICE_ID, and FANCLI_COMPANY to {out_path}")
    print(f"Selected device_id: {device_id}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="fancli",
        description="Control your smart fan from the terminal (Atomberg supported today).",
        epilog="With no subcommand, prints the full user guide (same as `fancli help`).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Print installed fancli version and exit",
    )
    sub = parser.add_subparsers(dest="command", required=False)

    sub.add_parser("help", help="Show the full user guide (from help.txt)")

    sub.add_parser(
        "setup",
        help="Interactive setup: vendor, API key & refresh token, list devices, save DEVICE_ID",
    )

    status_p = sub.add_parser("status", help="Print device state (get_device_state)")
    status_p.add_argument(
        "--json",
        action="store_true",
        dest="status_json",
        help="Print raw JSON (default is human-readable)",
    )

    set_p = sub.add_parser(
        "set",
        help="Send a command with a single key/value (send_command)",
        description=(
            "Send POST /v1/send_command with one key/value. "
            "The key/value reference below is the same as "
            "`fancli set` with no arguments or `fancli set help`."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=get_set_command_reference_text(),
    )
    set_p.add_argument(
        "key",
        nargs="?",
        default=None,
        help="Command key (e.g. timer, power, speed)",
    )
    set_p.add_argument(
        "value",
        nargs="?",
        default=None,
        help="Value (number, true/false, or JSON literal)",
    )

    args = parser.parse_args()
    cfg = load_config()
    cache_path = token_file_path()

    try:
        if args.command is None or args.command == "help":
            run_help()
        elif args.command == "status":
            run_status(cfg, cache_path, json_output=getattr(args, "status_json", False))
        elif args.command == "set":
            if args.key == "help" and args.value is None:
                print_set_command_help()
                return
            if args.key is None and args.value is None:
                print_set_command_help()
                return
            if args.key is None or args.value is None:
                print_set_command_help()
                raise SystemExit(
                    "error: both key and value are required (see the command list above)."
                )
            run_set(cfg, cache_path, args.key, args.value)
        elif args.command == "setup":
            run_setup(cfg, cache_path)
        else:
            parser.print_help()
            sys.exit(1)
    except requests.RequestException as e:
        raise SystemExit(f"network error: {e}") from e


if __name__ == "__main__":
    main()
