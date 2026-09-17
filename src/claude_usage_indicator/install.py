"""`claude-usage-indicator --install` / `--uninstall`.

Deploys the parts pip can't: the app-menu launcher (.desktop), the
autostart-on-login entry, and the tray/launcher icon. Run once after
`pip install claude-usage-indicator`.
"""
import os
import shutil
import subprocess
import sys

from .icon import install_icons

APPLICATIONS_DIR = os.path.expanduser("~/.local/share/applications")
AUTOSTART_DIR = os.path.expanduser("~/.config/autostart")
DESKTOP_NAME = "claude-usage-indicator.desktop"

DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Name=Claude Usage
Comment=Claude account usage tray indicator (5h session / weekly % remaining)
Exec={exec_cmd}
Icon=claude-usage-indicator
Terminal=false
Categories=Utility;
"""

AUTOSTART_ENTRY = DESKTOP_ENTRY + "X-GNOME-Autostart-enabled=true\nNoDisplay=true\n"


def _exec_cmd():
    bin_path = shutil.which("claude-usage-indicator")
    cmd = bin_path or f"{sys.executable} -m claude_usage_indicator.tray"

    # A GUI/autostart launch won't inherit this shell's env vars, so if a
    # proxy is set right now (interactively, where api.anthropic.com is
    # reachable), bake it into Exec= -- otherwise the indicator would need a
    # proxy but never get one, and silently fall back to ccusage every time.
    proxy = os.environ.get("CLAUDE_USAGE_PROXY") or os.environ.get("HTTPS_PROXY")
    if proxy:
        cmd = f"env CLAUDE_USAGE_PROXY={proxy} {cmd}"
    return cmd


def install():
    exec_cmd = _exec_cmd()

    os.makedirs(APPLICATIONS_DIR, exist_ok=True)
    with open(os.path.join(APPLICATIONS_DIR, DESKTOP_NAME), "w") as f:
        f.write(DESKTOP_ENTRY.format(exec_cmd=exec_cmd))

    os.makedirs(AUTOSTART_DIR, exist_ok=True)
    with open(os.path.join(AUTOSTART_DIR, DESKTOP_NAME), "w") as f:
        f.write(AUTOSTART_ENTRY.format(exec_cmd=exec_cmd))

    icon_dir = install_icons()
    subprocess.run(["gtk-update-icon-cache", "-f", "-t", icon_dir], capture_output=True)

    print("Installed:")
    print(f"  - App menu launcher: {APPLICATIONS_DIR}/{DESKTOP_NAME}")
    print(f"  - Autostart on login: {AUTOSTART_DIR}/{DESKTOP_NAME}")
    print(f"  - Icon: {icon_dir}/*/apps/claude-usage-indicator.png")
    print()
    print("Search your app menu for \"Claude Usage\" to launch it now,")
    print("or it will start automatically next time you log in.")
    print()
    if "env CLAUDE_USAGE_PROXY=" in exec_cmd:
        print(f"Detected a proxy in this shell and baked it into the launcher: {exec_cmd}")
        print("Re-run --install if that proxy address ever changes.")
    else:
        print("No proxy detected in this shell. If api.anthropic.com needs one on")
        print("your network, export CLAUDE_USAGE_PROXY=http://host:port before")
        print("re-running --install (a GUI launcher won't otherwise see it).")


def uninstall():
    for d in (APPLICATIONS_DIR, AUTOSTART_DIR):
        path = os.path.join(d, DESKTOP_NAME)
        if os.path.exists(path):
            os.remove(path)
            print(f"Removed {path}")
    print("Note: icons under ~/.local/share/icons/hicolor/*/apps/claude-usage-indicator.png were left in place.")
