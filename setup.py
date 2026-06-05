#!/usr/bin/env python3
"""
Interactive setup for the TACC HPC MCP server.
Run once per machine — writes ~/.tacc_mcp.json and patches ~/.ssh/config.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

CONFIG_PATH = Path.home() / ".tacc_mcp.json"
SSH_CONFIG  = Path.home() / ".ssh" / "config"

BANNER = """
╔══════════════════════════════════════════╗
║     TACC HPC MCP Server — Setup         ║
╚══════════════════════════════════════════╝
This wizard will:
  1. Ask for your TACC connection details
  2. Add a ControlMaster SSH alias to ~/.ssh/config
  3. Write ~/.tacc_mcp.json (read by server.py)
  4. Print the Claude Code settings snippet to add

Press Ctrl+C to abort at any time.
"""


def ask(prompt: str, default: str = "") -> str:
    if default:
        val = input(f"  {prompt} [{default}]: ").strip()
        return val or default
    while True:
        val = input(f"  {prompt}: ").strip()
        if val:
            return val
        print("    (required — please enter a value)")


def patch_ssh_config(alias: str, hostname: str, user: str) -> None:
    """Add a ControlMaster Host block to ~/.ssh/config if not already present."""
    SSH_CONFIG.parent.mkdir(mode=0o700, exist_ok=True)
    SSH_CONFIG.touch(mode=0o600, exist_ok=True)

    existing = SSH_CONFIG.read_text()

    # Check if this alias block already exists
    if re.search(rf"^Host\s+{re.escape(alias)}\s*$", existing, re.MULTILINE):
        print(f"  ~/.ssh/config already has a 'Host {alias}' block — skipping.")
        return

    block = (
        f"\nHost {alias}\n"
        f"    HostName {hostname}\n"
        f"    User {user}\n"
        f"    ControlMaster auto\n"
        f"    ControlPath ~/.ssh/cm_%r@%h:%p\n"
        f"    ControlPersist 4h\n"
    )
    with open(SSH_CONFIG, "a") as f:
        f.write(block)
    print(f"  Added 'Host {alias}' block to ~/.ssh/config")


def test_connection(alias: str) -> bool:
    """Try a BatchMode SSH ping to see if ControlMaster is already active."""
    try:
        r = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4",
             alias, "echo OK"],
            capture_output=True, text=True, timeout=8
        )
        return r.returncode == 0 and "OK" in r.stdout
    except Exception:
        return False


def print_claude_settings(server_py: str, uv_path: str) -> None:
    snippet = json.dumps({
        "mcpServers": {
            "tacc-hpc": {
                "command": uv_path,
                "args": [
                    "run",
                    "--python", "3.12",
                    "--with", "mcp",
                    server_py,
                ]
            }
        }
    }, indent=2)
    print()
    print("─" * 60)
    print("Add this to your project's .claude/settings.json")
    print("(create the file if it doesn't exist):")
    print("─" * 60)
    print(snippet)
    print("─" * 60)


def main() -> None:
    print(BANNER)

    # ── Gather info ──────────────────────────────────────────────────────
    print("Step 1 — TACC connection details")
    print()
    hostname = ask("TACC hostname", "ls6.tacc.utexas.edu")
    user     = ask("Your TACC username")
    alias    = ask("SSH alias (short name for this server)", "tacc")

    print()
    print("Step 2 — Project location on TACC")
    print("  (This is the root of your analysis repo on TACC,")
    print("   e.g. /work/12345/jsmith/my-project)")
    print()
    project_dir = ask("Absolute path to project on TACC")
    logs_subdir = ask("Subfolder for run logs (relative to project)", "logs/runs")

    # ── Write SSH config ─────────────────────────────────────────────────
    print()
    print("Step 3 — Patching ~/.ssh/config")
    patch_ssh_config(alias, hostname, user)

    # ── Write ~/.tacc_mcp.json ───────────────────────────────────────────
    config = {
        "tacc_host":   alias,
        "tacc_user":   user,
        "project_dir": project_dir,
        "logs_subdir": logs_subdir,
    }
    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")
    print()
    print(f"  Config written to {CONFIG_PATH}")

    # ── Find uv ─────────────────────────────────────────────────────────
    print()
    print("Step 4 — Locating uv")
    uv_candidates = [
        Path.home() / ".local" / "bin" / "uv",
        Path("/usr/local/bin/uv"),
        Path("/opt/homebrew/bin/uv"),
    ]
    uv_path = None
    for c in uv_candidates:
        if c.exists():
            uv_path = str(c)
            break
    if not uv_path:
        result = subprocess.run(["which", "uv"], capture_output=True, text=True)
        if result.returncode == 0:
            uv_path = result.stdout.strip()

    if not uv_path:
        print("  uv not found — installing it now...")
        subprocess.run(
            "curl -LsSf https://astral.sh/uv/install.sh | sh",
            shell=True, check=True
        )
        uv_path = str(Path.home() / ".local" / "bin" / "uv")

    print(f"  uv found at: {uv_path}")

    # Ensure Python 3.12 and mcp are available
    print("  Installing Python 3.12 and mcp package via uv...")
    subprocess.run(
        [uv_path, "python", "install", "3.12"],
        check=True, capture_output=True
    )
    subprocess.run(
        [uv_path, "run", "--python", "3.12", "--with", "mcp",
         "python3", "-c", "from mcp.server.fastmcp import FastMCP; print('  mcp OK')"],
        check=True
    )

    # ── Print Claude Code settings snippet ───────────────────────────────
    server_py = str(Path(__file__).parent / "server.py")
    print_claude_settings(server_py, uv_path)

    # ── Test SSH ─────────────────────────────────────────────────────────
    print()
    print("Step 5 — Testing SSH connection")
    if test_connection(alias):
        print(f"  SSH to TACC is live (ControlMaster already active).")
    else:
        print(f"  No active session found.")
        print(f"  Open one with:  ssh {alias}")
        print(f"  (Enter your TACC password + 6-digit token — only needed once per 4 hours)")

    print()
    print("Setup complete!")
    print()
    print("Daily usage:")
    print(f"  1. Open a TACC session:  ssh {alias}")
    print( "  2. Open Claude Code in your project directory")
    print( "  3. The tacc-hpc MCP tools are now available")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)
