"""Top-panel tray indicator: Claude account usage (5h session % + weekly %).

Primary source: undocumented `GET /api/oauth/usage` endpoint (the same one
the VSCode extension's Account & Usage panel uses) -- gives real account-level
percentages. Falls back to local `ccusage` token counting if that call fails
(expired creds, endpoint removed, rate-limited, offline, no `ccusage`
installed -- fallback then just shows "idle").

ponytail: undocumented endpoint, no SLA, may break on a Claude Code update --
if it starts failing outright, this degrades to the ccusage fallback below.
"""
import fcntl
import glob
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import gi

gi.require_version("AppIndicator3", "0.1")
gi.require_version("Gtk", "3.0")
from gi.repository import AppIndicator3, GLib, Gtk

# Keep this well above 1: the endpoint has no Retry-After header and reportedly
# imposes long (hours-scale) 429 bans on aggressive polling.
REFRESH_SECONDS = 180

CREDENTIALS_PATH = os.path.expanduser("~/.claude/.credentials.json")
LOCK_PATH = "/tmp/claude-usage-indicator.lock"
LAST_REQUEST_PATH = "/tmp/claude-usage-indicator.last-request"
# Restarting the app (quit, relaunch) used to fire an immediate request every
# time on top of the normal REFRESH_SECONDS cycle -- fast repeated restarts
# (e.g. while testing) can trip the endpoint's undocumented rate limit, which
# then bans requests for hours. This file persists the last request time
# across restarts so we can skip the immediate one if it's too soon.
MIN_REQUEST_INTERVAL_SECONDS = REFRESH_SECONDS

# GUI/autostart launches don't inherit an interactive shell's proxy env vars.
# If your network needs a proxy to reach api.anthropic.com, export
# CLAUDE_USAGE_PROXY (or just HTTPS_PROXY, if it's already set system-wide)
# before launching -- this script never guesses or hardcodes one.
_proxy = os.environ.get("CLAUDE_USAGE_PROXY") or os.environ.get("HTTPS_PROXY")
if _proxy:
    os.environ.setdefault("HTTP_PROXY", _proxy)
    os.environ.setdefault("HTTPS_PROXY", _proxy)


def _acquire_single_instance_lock():
    lock_file = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(0)  # already running -- clicking the launcher again just no-ops
    return lock_file  # keep a reference alive for the life of the process


def claude_code_version():
    try:
        out = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=5).stdout
        return out.split()[0]
    except Exception:
        return "unknown"


USER_AGENT = f"claude-code/{claude_code_version()}"


def _seconds_since_last_request():
    try:
        return time.time() - os.path.getmtime(LAST_REQUEST_PATH)
    except OSError:
        return None  # no record yet -- never throttle the very first request


def _mark_request_now():
    open(LAST_REQUEST_PATH, "w").close()
    os.utime(LAST_REQUEST_PATH, None)


def fetch_account_usage():
    """Real account-level 5h/7d percentages, straight from Anthropic's backend."""
    elapsed = _seconds_since_last_request()
    if elapsed is not None and elapsed < MIN_REQUEST_INTERVAL_SECONDS:
        print(f"[account-usage] throttled: last request {elapsed:.0f}s ago, skipping", file=sys.stderr)
        return None

    try:
        with open(CREDENTIALS_PATH) as f:
            token = json.load(f)["claudeAiOauth"]["accessToken"]
    except Exception as e:
        print(f"[account-usage] credentials read failed: {e!r}", file=sys.stderr)
        return None

    req = urllib.request.Request(
        "https://api.anthropic.com/api/oauth/usage",
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": USER_AGENT,
            "anthropic-beta": "oauth-2025-04-20",
        },
    )
    _mark_request_now()  # mark before the call: an in-flight retry still counts as "just asked"
    # ponytail: transient network/proxy blips happen; one quick retry absorbs
    # them instead of waiting a full REFRESH_SECONDS cycle to recover.
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            print(f"[account-usage] HTTP {e.code}: {e.read()[:300]!r}", file=sys.stderr)
            return None  # not transient -- retrying won't help (bad/expired token etc.)
        except Exception as e:
            print(f"[account-usage] request failed (attempt {attempt}): {e!r}", file=sys.stderr)
            if attempt == 1:
                time.sleep(3)
    return None


def find_ccusage_cmd():
    global_bin = shutil.which("ccusage")
    if global_bin:
        return [global_bin]
    cached = glob.glob(os.path.expanduser("~/.npm/_npx/*/node_modules/.bin/ccusage"))
    if cached:
        return [cached[0]]
    return ["npx", "ccusage"]


CCUSAGE_CMD = find_ccusage_cmd()


def fetch_ccusage_fallback():
    try:
        out = subprocess.run(
            CCUSAGE_CMD + ["blocks", "--active", "--json", "--offline"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        blocks = json.loads(out).get("blocks", [])
        return blocks[0] if blocks else None
    except Exception:
        return None


def time_until(iso_ts):
    try:
        target = datetime.fromisoformat(iso_ts)
        delta = target - datetime.now(timezone.utc)
        mins = max(0, int(delta.total_seconds() // 60))
        return f"{mins // 60}h{mins % 60:02d}m"
    except Exception:
        return "?"


def format_from_account(usage):
    five_hour = usage.get("five_hour") or {}
    seven_day = usage.get("seven_day") or {}

    session_pct = five_hour.get("utilization")
    session_left = 100 - session_pct if session_pct is not None else None
    session_reset = time_until(five_hour["resets_at"]) if five_hour.get("resets_at") else "?"

    week_pct = seven_day.get("utilization")
    week_left = 100 - week_pct if week_pct is not None else None
    week_reset = time_until(seven_day["resets_at"]) if seven_day.get("resets_at") else "?"

    if session_left is not None and week_left is not None:
        label = f"\U0001f916 5h:{session_left:.0f}% 7d:{week_left:.0f}%"
    else:
        label = "\U0001f916 ?"
    tooltip = (
        f"5-hour session: {session_left:.0f}% left, resets in {session_reset}\n"
        f"Weekly: {week_left:.0f}% left, resets in {week_reset}"
    )
    return label, tooltip


def format_from_ccusage(block):
    if not block:
        return "Claude: idle", "No active session block (ccusage fallback)"
    tokens = block.get("totalTokens", 0)
    cost = block.get("costUSD", 0.0)
    remaining = block.get("projection", {}).get("remainingMinutes")
    remaining_str = f"{remaining // 60}h{remaining % 60:02d}m" if remaining is not None else "?"
    label = f"\U0001f916 {tokens:,}tok ${cost:.2f} (est.)"
    tooltip = (
        f"[ccusage fallback -- token estimate, not account %]\n"
        f"Tokens used this block: {tokens:,}\n"
        f"Cost: ${cost:.2f}\n"
        f"Block resets in: {remaining_str}"
    )
    return label, tooltip


def refresh(indicator, menu_item_status):
    usage = fetch_account_usage()
    if usage is not None:
        label, tooltip = format_from_account(usage)
    else:
        label, tooltip = format_from_ccusage(fetch_ccusage_fallback())

    indicator.set_label(label, "")
    menu_item_status.set_label(tooltip.replace("\n", "  |  "))
    return True  # keep the GLib timer running


def build_menu():
    menu = Gtk.Menu()

    menu_item_status = Gtk.MenuItem(label="Loading...")
    menu_item_status.set_sensitive(False)
    menu.append(menu_item_status)

    menu.append(Gtk.SeparatorMenuItem())

    quit_item = Gtk.MenuItem(label="Quit")
    quit_item.connect("activate", lambda _: Gtk.main_quit())
    menu.append(quit_item)

    menu.show_all()
    return menu, menu_item_status


def main():
    _lock = _acquire_single_instance_lock()  # noqa: F841 -- kept alive for process lifetime

    indicator = AppIndicator3.Indicator.new(
        "claude-usage-indicator",
        "claude-usage-indicator",
        AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
    )
    indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
    menu, menu_item_status = build_menu()
    indicator.set_menu(menu)

    refresh(indicator, menu_item_status)
    GLib.timeout_add_seconds(REFRESH_SECONDS, refresh, indicator, menu_item_status)
    Gtk.main()


if __name__ == "__main__":
    main()
