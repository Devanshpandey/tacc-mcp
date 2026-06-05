#!/usr/bin/env python3
"""
TACC HPC MCP Server
Connects Claude Code to any TACC Lonestar6 project via SSH ControlMaster.

Configuration is read from ~/.tacc_mcp.json (written by setup.py).
Required fields:
  tacc_host    — SSH alias from ~/.ssh/config  (e.g. "tacc")
  tacc_user    — your TACC username            (e.g. "jsmith")
  project_dir  — absolute path to project on TACC
                 (e.g. "/work/12345/jsmith/my-project")

Optional fields:
  logs_subdir  — subfolder under project_dir for run logs
                 (default: "logs/runs")
"""

import subprocess
import os
import json
from pathlib import Path
from mcp.server.fastmcp import FastMCP

# ── Load config ────────────────────────────────────────────────────────────

CONFIG_PATH = Path.home() / ".tacc_mcp.json"

def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Config file not found: {CONFIG_PATH}\n"
            "Run setup.py first:  python3 setup.py"
        )
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    for key in ("tacc_host", "tacc_user", "project_dir"):
        if not cfg.get(key):
            raise ValueError(f"Missing required config key: {key} in {CONFIG_PATH}")
    return cfg

CFG         = _load_config()
TACC_HOST   = CFG["tacc_host"]
TACC_USER   = CFG["tacc_user"]
PROJECT_DIR = CFG["project_dir"].rstrip("/")
LOGS_SUBDIR = CFG.get("logs_subdir", "logs/runs")
LOGS_DIR    = f"{PROJECT_DIR}/{LOGS_SUBDIR}"

mcp = FastMCP("tacc-hpc")


# ── SSH helper ─────────────────────────────────────────────────────────────

def _ssh(cmd: str, timeout: int = 60) -> dict:
    """Run a shell command on TACC via ControlMaster SSH."""
    try:
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
             TACC_HOST, cmd],
            capture_output=True, text=True, timeout=timeout
        )
        return {
            "stdout":     result.stdout,
            "stderr":     result.stderr,
            "returncode": result.returncode,
            "ok":         result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": (
                "SSH timed out — is your ControlMaster session open?\n"
                f"Fix: ssh {TACC_HOST}"
            ),
            "returncode": -1, "ok": False,
        }
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "returncode": -1, "ok": False}


def _fmt(r: dict, fallback: str = "") -> str:
    out = r["stdout"].strip()
    err = r["stderr"].strip()
    if r["ok"]:
        return out or fallback
    return f"ERROR (exit {r['returncode']}): {err or out}"


# ── Tools ──────────────────────────────────────────────────────────────────

@mcp.tool()
def check_connection() -> str:
    """
    Check whether the SSH ControlMaster session to TACC is alive.
    If it is not, print the command to open one.
    """
    r = _ssh("echo OK && hostname && whoami")
    if r["ok"]:
        return f"Connected to TACC:\n{r['stdout'].strip()}"
    return (
        f"Not connected to TACC ({TACC_HOST}).\n"
        f"Open a master session with:  ssh {TACC_HOST}\n"
        f"SSH error: {r['stderr'].strip()}"
    )


@mcp.tool()
def job_status() -> str:
    """
    Show all SLURM jobs currently in the queue for this user
    (pending and running), with state and elapsed time.
    """
    r = _ssh(
        f"squeue -u {TACC_USER} "
        "--format='%.10i %.32j %.8T %.10M %.5D %R' "
        "--sort=-V 2>&1"
    )
    output = r["stdout"].strip()
    if not output or output.startswith("JOBID"):
        lines = output.splitlines()
        if len(lines) <= 1:
            return f"No jobs in queue for {TACC_USER}."
    return output


@mcp.tool()
def cancel_jobs(job_ids: str) -> str:
    """
    Cancel one or more SLURM jobs.
    Provide a space-separated list of numeric job IDs,
    e.g. "3210158 3210159 3210160".
    """
    ids = job_ids.strip()
    if not ids:
        return "No job IDs provided."
    r = _ssh(f"scancel {ids} 2>&1 && echo 'Cancelled: {ids}'")
    return _fmt(r, f"Cancelled: {ids}")


@mcp.tool()
def pipeline_status(run_id: str = "") -> str:
    """
    Show the status of a pipeline run by cross-referencing the
    manifest.tsv (written at job submission) with the live SLURM queue.

    If run_id is empty, uses the most recent run under logs/runs/.
    Each line shows the step name, job ID, and current state.
    """
    if not run_id:
        find_r = _ssh(f"ls -t {LOGS_DIR}/ 2>/dev/null | head -1")
        if not find_r["ok"] or not find_r["stdout"].strip():
            return f"No pipeline runs found in {LOGS_DIR}/"
        run_id = find_r["stdout"].strip()

    run_dir = f"{LOGS_DIR}/{run_id}"

    manifest_r = _ssh(f"cat {run_dir}/manifest.tsv 2>/dev/null")
    queue_r    = _ssh(
        f"squeue -u {TACC_USER} --format='%.10i %.8T %.10M' --noheader 2>/dev/null"
    )

    # Parse live queue into {job_id: (state, elapsed)}
    active: dict[str, tuple[str, str]] = {}
    for line in queue_r["stdout"].splitlines():
        parts = line.split()
        if len(parts) >= 2:
            active[parts[0].strip()] = (
                parts[1].strip(),
                parts[2].strip() if len(parts) > 2 else "",
            )

    lines = [f"Run ID : {run_id}", f"Log dir: {run_dir}", ""]

    if not manifest_r["ok"] or not manifest_r["stdout"].strip():
        lines.append("manifest.tsv not found — jobs may still be starting up.")
        return "\n".join(lines)

    lines.append(f"{'Step':<38} {'Job ID':<12} Status")
    lines.append("-" * 72)
    for row in manifest_r["stdout"].splitlines():
        if row.startswith("step"):
            continue
        parts = row.split("\t")
        if len(parts) < 3:
            continue
        step, _script, jid = parts[0], parts[1], parts[2]
        if jid in active:
            state, elap = active[jid]
            status = f"{state}  (running {elap})" if elap else state
        else:
            status = "done / not in queue"
        lines.append(f"{step:<38} {jid:<12} {status}")

    return "\n".join(lines)


@mcp.tool()
def list_runs() -> str:
    """
    List all pipeline runs in the logs directory, newest first.
    Shows the run ID (timestamp) and number of log files inside.
    """
    r = _ssh(
        f"ls -t {LOGS_DIR}/ 2>/dev/null | head -20 | "
        f"while read d; do echo \"$d  ($(ls {LOGS_DIR}/$d/ 2>/dev/null | wc -l | tr -d ' ') files)\"; done"
    )
    if not r["ok"] or not r["stdout"].strip():
        return f"No runs found in {LOGS_DIR}/"
    return f"Pipeline runs in {LOGS_DIR}/\n\n{r['stdout'].strip()}"


@mcp.tool()
def list_logs(run_id: str = "") -> str:
    """
    List log files for a pipeline run, sorted by size (largest first).
    If run_id is empty, uses the most recent run.
    """
    if not run_id:
        find_r = _ssh(f"ls -t {LOGS_DIR}/ 2>/dev/null | head -1")
        if not find_r["ok"] or not find_r["stdout"].strip():
            return f"No runs found in {LOGS_DIR}/"
        run_id = find_r["stdout"].strip()

    run_dir = f"{LOGS_DIR}/{run_id}"
    r = _ssh(f"ls -lhS {run_dir}/ 2>&1 | head -80")
    return f"Run: {run_id}\nDir: {run_dir}\n\n{_fmt(r)}"


@mcp.tool()
def read_log(
    step: str = "",
    path: str = "",
    run_id: str = "",
    tail_lines: int = 100,
) -> str:
    """
    Read (tail) a log file from TACC.

    Examples:
      read_log(step="06_ldsc_rg")           — most recent run, step prefix match
      read_log(step="07_coloc", run_id="…") — specific run
      read_log(path="/work/…/some.log")     — full path override

    tail_lines: how many lines from the end to return (default 100).
    """
    if not path:
        if not run_id:
            find_r = _ssh(f"ls -t {LOGS_DIR}/ 2>/dev/null | head -1")
            if not find_r["ok"] or not find_r["stdout"].strip():
                return "No runs found."
            run_id = find_r["stdout"].strip()

        run_dir = f"{LOGS_DIR}/{run_id}"

        if step:
            find_r = _ssh(f"ls -t {run_dir}/{step}* 2>/dev/null | head -1")
            if not find_r["ok"] or not find_r["stdout"].strip():
                return f"No log files matching '{step}*' in {run_dir}"
            path = find_r["stdout"].strip()
        else:
            return "Provide 'step' (name prefix) or 'path' (full TACC path)."

    r = _ssh(f"tail -{tail_lines} {path} 2>&1")
    if not r["ok"]:
        return f"Could not read {path}:\n{r['stderr']}"

    return f"=== {path} (last {tail_lines} lines) ===\n{r['stdout'] or '(empty)'}"


@mcp.tool()
def git_pull() -> str:
    """
    Pull the latest code from GitHub on TACC.
    Run this after pushing changes from your local machine.
    """
    r = _ssh(
        f"cd {PROJECT_DIR} && git pull origin $(git rev-parse --abbrev-ref HEAD) 2>&1",
        timeout=90,
    )
    return _fmt(r, "Already up to date.")


@mcp.tool()
def git_status() -> str:
    """Show git status and the 5 most recent commits on TACC."""
    r = _ssh(
        f"cd {PROJECT_DIR} && "
        "echo '=== git status ===' && git status --short && "
        "echo '' && echo '=== recent commits ===' && "
        "git log --oneline -5 2>&1"
    )
    return _fmt(r)


@mcp.tool()
def disk_usage() -> str:
    """
    Show filesystem quota and usage on TACC.
    Reports home, work ($WORK), and scratch ($SCRATCH) usage.
    Useful for checking space before starting a large analysis.
    """
    r = _ssh(
        "echo '=== Quota ===' && quota -s 2>/dev/null; "
        "echo '' && echo '=== Filesystem usage ===' && "
        "df -h $WORK $SCRATCH 2>/dev/null"
    )
    return _fmt(r, "Could not retrieve disk usage.")


@mcp.tool()
def run_command(command: str) -> str:
    """
    Run an arbitrary shell command on TACC (login node, non-interactive bash).
    Use for anything not covered by the other tools — checking files,
    inspecting results, running lightweight scripts, etc.
    """
    r = _ssh(command, timeout=120)
    out = r["stdout"].strip()
    err = r["stderr"].strip()
    result = out
    if err:
        result += f"\n[stderr]: {err}"
    return result or "(no output)"


if __name__ == "__main__":
    mcp.run()
