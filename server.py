#!/usr/bin/env python3
"""
TACC HPC MCP Server
Connects Claude Code to TACC Lonestar6 (or any SLURM HPC) via SSH ControlMaster.

Configuration is read from ~/.tacc_mcp.json (written by setup.py).
Required fields:
  tacc_host    — SSH alias from ~/.ssh/config  (e.g. "tacc")
  tacc_user    — your TACC username            (e.g. "jsmith")
  project_dir  — absolute path to project on TACC
                 (e.g. "/work/12345/jsmith/my-project")

Optional fields:
  logs_subdir  — subfolder under project_dir for run logs  (default: "logs/runs")
  scratch_dir  — scratch path for large intermediates       (default: auto-detected)

First time? Call:  get_started()
"""

import subprocess
import json
import textwrap
from pathlib import Path
from mcp.server.fastmcp import FastMCP

# ── Config — loaded lazily so the server never crashes at startup ───────────

CONFIG_PATH = Path.home() / ".tacc_mcp.json"
_CFG: dict | None = None


def _cfg() -> dict | None:
    global _CFG
    if _CFG is not None:
        return _CFG
    if not CONFIG_PATH.exists():
        return None
    try:
        with open(CONFIG_PATH) as f:
            _CFG = json.load(f)
        return _CFG
    except Exception:
        return None


def _require_cfg() -> tuple[dict | None, str]:
    """Return (config, error_message). error_message is empty string on success."""
    cfg = _cfg()
    if cfg is None:
        return None, (
            "No config found at ~/.tacc_mcp.json.\n"
            "Run setup once:  python3 /path/to/tacc-mcp/setup.py\n"
            "Or call get_started() for a step-by-step guide."
        )
    for key in ("tacc_host", "tacc_user", "project_dir"):
        if not cfg.get(key):
            return None, f"Config is missing required key '{key}' in {CONFIG_PATH}."
    return cfg, ""


def _host() -> str:
    cfg, _ = _require_cfg()
    return cfg["tacc_host"] if cfg else ""

def _user() -> str:
    cfg, _ = _require_cfg()
    return cfg["tacc_user"] if cfg else ""

def _project() -> str:
    cfg, _ = _require_cfg()
    return cfg["project_dir"].rstrip("/") if cfg else ""

def _logs_dir() -> str:
    cfg, _ = _require_cfg()
    if not cfg:
        return ""
    sub = cfg.get("logs_subdir", "logs/runs")
    return f"{_project()}/{sub}"


mcp = FastMCP("tacc-hpc")


# ── SSH helper ──────────────────────────────────────────────────────────────

_SSH_HINT = (
    "SSH ControlMaster is not active.\n"
    "Fix: open a terminal and run:  ssh {host}\n"
    "You only need to authenticate once — the connection stays open for 4 hours."
)


def _ssh(cmd: str, timeout: int = 60) -> dict:
    """Run a shell command on TACC via ControlMaster SSH."""
    host = _host()
    if not host:
        return {"stdout": "", "stderr": "No TACC host configured.", "returncode": -1, "ok": False}
    try:
        result = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", host, cmd],
            capture_output=True, text=True, timeout=timeout,
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
            "stderr": _SSH_HINT.format(host=host),
            "returncode": -1, "ok": False,
        }
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "returncode": -1, "ok": False}


def _fmt(r: dict, fallback: str = "(no output)") -> str:
    out = r["stdout"].strip()
    err = r["stderr"].strip()
    if r["ok"]:
        return out or fallback
    hint = _SSH_HINT.format(host=_host()) if "BatchMode" in err or "Permission denied" in err else ""
    msg = f"ERROR (exit {r['returncode']}): {err or out}"
    return f"{msg}\n\n{hint}".strip()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — GETTING STARTED
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def get_started() -> str:
    """
    Interactive tutorial for first-time users of the TACC HPC MCP server.

    Explains what this MCP server does, how to configure it, how to open the
    required SSH session, and gives a quick tour of all available tools.
    Call this if you are new to the server or something is not working.
    """
    cfg, err = _require_cfg()
    config_status = "✓  Config found" if cfg else f"✗  Config missing ({CONFIG_PATH})"
    ssh_ok = _ssh("echo OK").get("ok", False) if cfg else False
    ssh_status = "✓  SSH ControlMaster is live" if ssh_ok else f"✗  SSH not connected — run: ssh {cfg['tacc_host'] if cfg else '<alias>'}"

    return textwrap.dedent(f"""
    ╔══════════════════════════════════════════════════════════════════╗
    ║           TACC HPC MCP Server — Getting Started Guide           ║
    ╚══════════════════════════════════════════════════════════════════╝

    This MCP server lets Claude Code talk to TACC Lonestar6 directly —
    check jobs, read logs, browse files, submit scripts — without you
    having to open a terminal and SSH in yourself.

    ── CURRENT STATUS ──────────────────────────────────────────────────
      {config_status}
      {ssh_status}

    ── STEP 1: ONE-TIME SETUP (if config is missing) ───────────────────
      Run the interactive wizard in your terminal:

        python3 /path/to/tacc-mcp/setup.py

      It will ask for:
        • TACC hostname  (default: ls6.tacc.utexas.edu)
        • Your TACC username
        • A short SSH alias (e.g. "tacc")
        • Your project path on TACC (e.g. /work/12345/user/my-project)

      Then it writes ~/.tacc_mcp.json and patches ~/.ssh/config.

    ── STEP 2: OPEN AN SSH SESSION EACH DAY ────────────────────────────
      Before using any tool, authenticate once:

        ssh tacc          ← enter password + 6-digit TACC token

      The ControlMaster keeps it alive for 4 hours automatically.
      You only need to do this once per session, not before every command.

    ── STEP 3: VERIFY IT WORKS ─────────────────────────────────────────
      Call:  check_connection()
      Expected output:  "Connected to TACC: login1.ls6..."

    ── TOOL QUICK REFERENCE ────────────────────────────────────────────

      CONNECTION & STATUS
        check_connection()         — verify SSH is live
        get_started()              — this guide

      SLURM JOBS
        job_status()               — current queue (pending + running)
        job_history(days=3)        — recently completed/failed jobs
        job_details(job_id)        — full info for one job
        cancel_jobs("id1 id2")     — scancel jobs by ID

      PIPELINE
        pipeline_status()          — cross-ref manifest with live queue
        list_runs()                — show all pipeline run timestamps
        run_pipeline(script)       — submit a run_all.sh or step script
        check_outputs(agent)       — verify expected output files exist

      FILES & LOGS
        list_dir(path)             — ls -lh any remote directory
        read_file(path)            — read any remote file (head/tail options)
        read_log(step)             — tail a log from the latest pipeline run
        list_logs()                — list log files for a run
        grep_file(pattern, path)   — search a remote file

      SYSTEM
        disk_usage()               — quota + filesystem usage
        node_load()                — login node CPU/memory snapshot
        git_status()               — git status on TACC
        git_pull()                 — pull latest code on TACC
        run_command(cmd)           — run any shell command (escape hatch)

    ── COMMON WORKFLOWS ────────────────────────────────────────────────

      "Are my jobs running?"
        → job_status()

      "What happened to the phenotype prep job?"
        → job_history(days=3)   then   read_log(step="01_prep")

      "Did the GWAS finish? Are the output files there?"
        → check_outputs(agent=1)

      "I pushed new code — update TACC"
        → git_pull()

      "Something broke — show me the error"
        → read_log(step="<step_name>", tail_lines=200)

    ── TROUBLESHOOTING ─────────────────────────────────────────────────
      Tools return "SSH ControlMaster is not active"
        →  ssh tacc        (open a new terminal, authenticate)

      Tools not appearing in Claude Code at all
        →  Restart Claude Code — MCP servers are loaded at startup.
           If the SSH session was closed when Claude launched, tools
           may have been silently dropped. Re-open SSH first, then restart.

      "No config found"
        →  python3 /path/to/tacc-mcp/setup.py
    """).strip()


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — CONNECTION
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def check_connection() -> str:
    """
    Check whether the SSH ControlMaster session to TACC is alive.
    Also shows hostname, username, and current TACC system load.
    If not connected, prints the exact command needed to open a session.
    """
    cfg, err = _require_cfg()
    if err:
        return err

    r = _ssh("echo OK && hostname && whoami && uptime")
    if r["ok"]:
        return f"Connected to TACC ({cfg['tacc_host']}):\n{r['stdout'].strip()}"
    return (
        f"Not connected to TACC.\n\n"
        f"Open a session with:  ssh {cfg['tacc_host']}\n"
        f"(Enter your TACC password + 6-digit token — stays open 4 hours)\n\n"
        f"SSH error: {r['stderr'].strip()}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — SLURM JOB MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def job_status() -> str:
    """
    Show all SLURM jobs currently in the queue for this user
    (pending and running), with state, elapsed time, and wait reason.
    """
    cfg, err = _require_cfg()
    if err:
        return err

    r = _ssh(
        f"squeue -u {cfg['tacc_user']} "
        "--format='%.10i %.32j %.8T %.10M %.9l %R' "
        "--sort=-V 2>&1"
    )
    output = r["stdout"].strip()
    if not r["ok"]:
        return _fmt(r)
    lines = output.splitlines()
    if len(lines) <= 1:
        return f"No jobs currently in queue for {cfg['tacc_user']}."
    return output


@mcp.tool()
def job_history(days: int = 3) -> str:
    """
    Show recently completed, failed, or cancelled SLURM jobs.
    days: how many days back to search (default 3).
    Useful for diagnosing what happened to a job that is no longer in the queue.
    """
    cfg, err = _require_cfg()
    if err:
        return err

    from datetime import datetime, timedelta
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    r = _ssh(
        f"sacct -u {cfg['tacc_user']} --starttime={since} "
        "--format='JobID%12,JobName%30,State%12,ExitCode,Start,End,Elapsed' "
        "--noheader 2>&1 | grep -v '\\.batch' | grep -v '\\.extern'"
    )
    if not r["ok"]:
        return _fmt(r)
    out = r["stdout"].strip()
    if not out:
        return f"No completed jobs in the last {days} day(s)."
    header = f"{'JobID':>12}  {'JobName':<30}  {'State':<12}  {'ExitCode':<8}  {'Start':<20}  {'End':<20}  Elapsed"
    return f"{header}\n{'-'*120}\n{out}"


@mcp.tool()
def job_details(job_id: str) -> str:
    """
    Show full SLURM details for a specific job ID.
    Includes working directory, script path, stdout/stderr paths, resource usage.
    Useful for tracking down log files for a specific job.
    job_id: numeric SLURM job ID (e.g. "3210174")
    """
    cfg, err = _require_cfg()
    if err:
        return err

    r = _ssh(
        f"sacct -j {job_id} "
        "--format='JobID,JobName,State,ExitCode,Submit,Start,End,Elapsed,"
        "AllocCPUS,ReqMem,MaxRSS,WorkDir' --parsable2 2>&1"
    )
    return _fmt(r)


@mcp.tool()
def cancel_jobs(job_ids: str) -> str:
    """
    Cancel one or more SLURM jobs by ID.
    job_ids: space-separated list of job IDs, e.g. "3210158 3210159 3210160".
    Array jobs can be cancelled with their base ID, e.g. "3210160" cancels all 3210160_*.
    """
    cfg, err = _require_cfg()
    if err:
        return err

    ids = job_ids.strip()
    if not ids:
        return "No job IDs provided."
    r = _ssh(f"scancel {ids} 2>&1 && echo 'Cancelled: {ids}'")
    return _fmt(r, f"Cancelled: {ids}")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — PIPELINE MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def pipeline_status(run_id: str = "") -> str:
    """
    Show the status of a pipeline run by cross-referencing the manifest.tsv
    (written at submission) with the live SLURM queue and sacct history.
    run_id: timestamp folder name (e.g. "20260606_080012"). Defaults to most recent run.
    """
    cfg, err = _require_cfg()
    if err:
        return err

    logs_dir = _logs_dir()

    if not run_id:
        find_r = _ssh(f"ls -t {logs_dir}/ 2>/dev/null | head -1")
        if not find_r["ok"] or not find_r["stdout"].strip():
            return f"No pipeline runs found in {logs_dir}/"
        run_id = find_r["stdout"].strip()

    run_dir = f"{logs_dir}/{run_id}"

    manifest_r = _ssh(f"cat {run_dir}/manifest.tsv 2>/dev/null")
    queue_r    = _ssh(
        f"squeue -u {cfg['tacc_user']} --format='%.10i %.8T %.10M' --noheader 2>/dev/null"
    )
    # Also pull sacct for recently finished jobs from this run
    sacct_r = _ssh(
        f"sacct -u {cfg['tacc_user']} --starttime=$(date -d '7 days ago' +%Y-%m-%d 2>/dev/null || date -v-7d +%Y-%m-%d) "
        "--format='JobID,State' --noheader --parsable2 2>/dev/null"
    )

    active: dict[str, tuple[str, str]] = {}
    for line in queue_r["stdout"].splitlines():
        parts = line.split()
        if len(parts) >= 2:
            active[parts[0].strip()] = (parts[1].strip(), parts[2].strip() if len(parts) > 2 else "")

    finished: dict[str, str] = {}
    for line in sacct_r["stdout"].splitlines():
        parts = line.split("|")
        if len(parts) >= 2 and "." not in parts[0]:
            finished[parts[0].strip()] = parts[1].strip()

    lines = [f"Run ID : {run_id}", f"Log dir: {run_dir}", ""]

    if not manifest_r["ok"] or not manifest_r["stdout"].strip():
        lines.append("manifest.tsv not found — jobs may still be initialising.")
        return "\n".join(lines)

    lines.append(f"{'Step':<38} {'Job ID':<14} Status")
    lines.append("-" * 76)

    for row in manifest_r["stdout"].splitlines():
        if row.startswith("step"):
            continue
        parts = row.split("\t")
        if len(parts) < 3:
            continue
        step, _script, jid = parts[0], parts[1], parts[2]
        # Handle array job IDs like 3210176_[1-22]
        base_jid = jid.split("_")[0]
        if jid in active or base_jid in active:
            state, elap = active.get(jid) or active.get(base_jid, ("RUNNING", ""))
            status = f"{state}  (elapsed {elap})" if elap else state
        elif jid in finished or base_jid in finished:
            status = finished.get(jid) or finished.get(base_jid, "COMPLETED")
        else:
            status = "not in queue / completed"
        lines.append(f"{step:<38} {jid:<14} {status}")

    return "\n".join(lines)


@mcp.tool()
def list_runs() -> str:
    """
    List all pipeline run directories in the logs folder, newest first.
    Shows the run ID (timestamp), file count, and the run_all.log summary line.
    """
    cfg, err = _require_cfg()
    if err:
        return err

    logs_dir = _logs_dir()
    r = _ssh(
        f"ls -t {logs_dir}/ 2>/dev/null | head -20 | "
        f"while read d; do "
        f"  nf=$(ls {logs_dir}/$d/ 2>/dev/null | wc -l | tr -d ' '); "
        f"  summary=$(grep -m1 'Submitted\\|ERROR\\|complete' {logs_dir}/$d/run_all.log 2>/dev/null | tail -1 | cut -c1-60); "
        f"  echo \"$d  ($nf files)  $summary\"; "
        f"done"
    )
    if not r["ok"] or not r["stdout"].strip():
        return f"No runs found in {logs_dir}/"
    return f"Pipeline runs in {logs_dir}/\n\n{r['stdout'].strip()}"


@mcp.tool()
def run_pipeline(script: str = "run_all.sh", args: str = "") -> str:
    """
    Submit a pipeline script on TACC as a background nohup job.
    script: path relative to project_dir, or absolute path. Defaults to run_all.sh.
    args:   extra arguments passed to the script (e.g. "--step 3").
    Returns the nohup log path and the process ID so you can track it.
    """
    cfg, err = _require_cfg()
    if err:
        return err

    proj = _project()
    script_path = script if script.startswith("/") else f"{proj}/{script}"
    log_path = f"{proj}/logs/nohup_pipeline_{{}}.log"

    r = _ssh(
        f"cd {proj} && "
        f"ts=$(date +%Y%m%d_%H%M%S) && "
        f"log={proj}/logs/nohup_pipeline_$ts.log && "
        f"nohup bash {script_path} {args} > $log 2>&1 & "
        f"echo \"PID=$! LOG=$log\""
    )
    return _fmt(r)


@mcp.tool()
def check_outputs(agent: int = 1) -> str:
    """
    Check which expected output files exist for a given pipeline agent.
    Reports file size and modification time for each expected output.
    agent: 1 (genetics), 2 (genes), 3 (networks), 4 (subtypes)
    """
    cfg, err = _require_cfg()
    if err:
        return err

    proj = _project()

    expected = {
        1: [
            f"{proj}/results/agent1_genetics/phenotypes/pheno_quantitative.txt",
            f"{proj}/results/agent1_genetics/phenotypes/pheno_binary.txt",
            f"{proj}/results/agent1_genetics/phenotypes/covariates.txt",
            f"{proj}/results/agent1_genetics/phenotypes/regenie_keep.txt",
            f"{proj}/results/agent1_genetics/burden_masks/ukb_wes_anno.txt",
            f"{proj}/results/agent1_genetics/burden_masks/ukb_wes_setlist.txt",
            f"{proj}/results/agent1_genetics/burden_masks/ukb_wes_masks.txt",
            f"{proj}/results/agent1_genetics/regenie/step1/",
            f"{proj}/results/agent1_genetics/gwas/",
            f"{proj}/results/agent1_genetics/ldsc/ldsc_rg_matrix.csv",
            f"{proj}/results/agent1_genetics/coloc/coloc_results.csv",
            f"{proj}/results/agent1_genetics/mr/mr_causal_evidence_table.csv",
            f"{proj}/results/agent1_genetics/finemapping/finemapping_credible_sets.csv",
            f"{proj}/results/agent1_genetics/prs/",
        ],
        2: [
            f"{proj}/results/agent2_genes/ranked_causal_gene_table.csv",
            f"{proj}/results/agent2_genes/gene_evidence_heatmap.png",
        ],
        3: [
            f"{proj}/results/agent3_networks/network_modules.json",
            f"{proj}/results/agent3_networks/pathway_enrichment_table.csv",
            f"{proj}/results/agent3_networks/cad_network_map.html",
        ],
        4: [
            f"{proj}/results/agent4_subtypes/patient_subtype_assignments.csv",
            f"{proj}/results/agent4_subtypes/subtype_prs_profiles.csv",
            f"{proj}/results/agent4_subtypes/subtype_outcome_associations.csv",
        ],
    }

    if agent not in expected:
        return f"Unknown agent {agent}. Choose 1, 2, 3, or 4."

    paths = expected[agent]
    # Build a single command that checks each path
    checks = " ".join(
        f"if [ -e '{p}' ]; then echo \"✓  $(ls -lhd '{p}' | awk '{{print $5, $6, $7, $8, $9}}')\"; "
        f"else echo \"✗  MISSING: {p}\"; fi;"
        for p in paths
    )
    r = _ssh(checks, timeout=30)
    out = r["stdout"].strip() or r["stderr"].strip()
    header = f"Agent {agent} expected outputs ({proj}/results/agent{agent}_*/)\n{'─'*70}\n"
    return header + out


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — FILES & LOGS
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def list_dir(path: str = "") -> str:
    """
    List the contents of a directory on TACC (ls -lh).
    path: absolute path on TACC. Defaults to the project root.
    Useful for browsing results, data, or any remote directory.
    """
    cfg, err = _require_cfg()
    if err:
        return err

    target = path.strip() or _project()
    r = _ssh(f"ls -lhp {target} 2>&1 | head -100")
    return _fmt(r)


@mcp.tool()
def read_file(
    path: str,
    head_lines: int = 0,
    tail_lines: int = 0,
    max_lines: int = 200,
) -> str:
    """
    Read a file on TACC. Works for any text file — logs, CSVs, scripts, configs.

    path:       absolute path on TACC
    head_lines: show first N lines only (0 = disabled)
    tail_lines: show last N lines only (0 = disabled)
    max_lines:  cap output at this many lines when using neither head nor tail (default 200)

    Examples:
      read_file("/work/.../results/ldsc_rg_matrix.csv")
      read_file("/work/.../logs/run_all.log", tail_lines=50)
      read_file("/work/.../scripts/agent1_genetics/run_all.sh", head_lines=80)
    """
    cfg, err = _require_cfg()
    if err:
        return err

    if head_lines > 0:
        cmd = f"head -{head_lines} {path} 2>&1"
    elif tail_lines > 0:
        cmd = f"tail -{tail_lines} {path} 2>&1"
    else:
        cmd = f"head -{max_lines} {path} 2>&1 && wc -l {path} 2>/dev/null | awk '{{print \"\\n[total: \"$1\" lines]\"}}"
    r = _ssh(cmd, timeout=30)
    if not r["ok"]:
        return f"Could not read {path}:\n{r['stderr']}"
    return f"=== {path} ===\n{r['stdout'] or '(empty)'}"


@mcp.tool()
def list_logs(run_id: str = "") -> str:
    """
    List log files for a pipeline run, sorted by modification time.
    run_id: timestamp folder name. Defaults to the most recent run.
    """
    cfg, err = _require_cfg()
    if err:
        return err

    logs_dir = _logs_dir()
    if not run_id:
        find_r = _ssh(f"ls -t {logs_dir}/ 2>/dev/null | head -1")
        if not find_r["ok"] or not find_r["stdout"].strip():
            return f"No runs found in {logs_dir}/"
        run_id = find_r["stdout"].strip()

    run_dir = f"{logs_dir}/{run_id}"
    r = _ssh(f"ls -lht {run_dir}/ 2>&1 | head -80")
    return f"Run: {run_id}\nDir: {run_dir}\n\n{_fmt(r)}"


@mcp.tool()
def read_log(
    step: str = "",
    path: str = "",
    run_id: str = "",
    tail_lines: int = 100,
    stream: str = "both",
) -> str:
    """
    Read (tail) a SLURM log file from TACC.

    step:       name prefix to match (e.g. "01_prep", "cad_gwas", "burden")
    path:       full TACC path — overrides step/run_id lookup
    run_id:     timestamp folder name. Defaults to most recent run.
    tail_lines: lines from the end to return (default 100)
    stream:     "out" (stdout only), "err" (stderr only), "both" (default)

    Examples:
      read_log(step="01_prep")
      read_log(step="cad_gwas_lipids", stream="err")
      read_log(path="/work/.../logs/runs/20260606_080012/burden_masks_3210178_1.out")
    """
    cfg, err = _require_cfg()
    if err:
        return err

    logs_dir = _logs_dir()

    if not path:
        if not run_id:
            find_r = _ssh(f"ls -t {logs_dir}/ 2>/dev/null | head -1")
            if not find_r["ok"] or not find_r["stdout"].strip():
                return "No runs found."
            run_id = find_r["stdout"].strip()

        run_dir = f"{logs_dir}/{run_id}"

        if not step:
            return "Provide 'step' (name prefix) or 'path' (full TACC path)."

        if stream == "err":
            glob = f"{step}*.err"
        elif stream == "out":
            glob = f"{step}*.out"
        else:
            glob = f"{step}*"

        find_r = _ssh(f"ls -t {run_dir}/{glob} 2>/dev/null | head -5")
        if not find_r["ok"] or not find_r["stdout"].strip():
            return f"No log files matching '{step}*' in {run_dir}"

        files = find_r["stdout"].strip().splitlines()
        if len(files) == 1:
            path = files[0]
        else:
            # Multiple files — show all (e.g. array job array tasks)
            parts = []
            for f in files[:5]:
                r2 = _ssh(f"echo '=== {f} ===' && tail -{tail_lines} {f} 2>&1")
                parts.append(r2["stdout"])
            return "\n".join(parts)

    r = _ssh(f"tail -{tail_lines} {path} 2>&1")
    if not r["ok"]:
        return f"Could not read {path}:\n{r['stderr']}"
    return f"=== {path} (last {tail_lines} lines) ===\n{r['stdout'] or '(empty)'}"


@mcp.tool()
def grep_file(pattern: str, path: str, context_lines: int = 2) -> str:
    """
    Search for a pattern in a remote file on TACC (grep).
    pattern:       grep regex pattern (e.g. "ERROR", "COMPLETED", "WARNING")
    path:          absolute path on TACC, or a glob (e.g. "/work/.../logs/*.err")
    context_lines: lines of context before/after each match (default 2)

    Examples:
      grep_file("ERROR", "/work/.../logs/runs/20260606_080012/01_prep*.err")
      grep_file("cases=", "/work/.../results/agent1_genetics/phenotypes/phenotype_summary.txt")
    """
    cfg, err = _require_cfg()
    if err:
        return err

    r = _ssh(f"grep -n -C {context_lines} '{pattern}' {path} 2>&1 | head -200", timeout=30)
    out = r["stdout"].strip()
    if not out:
        return f"No matches for '{pattern}' in {path}"
    return f"Matches for '{pattern}' in {path}:\n\n{out}"


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — SYSTEM & GIT
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def disk_usage() -> str:
    """
    Show filesystem quota and usage on TACC.
    Reports $HOME, $WORK, and $SCRATCH usage and quota.
    Check this before starting a large GWAS or WES analysis.
    """
    cfg, err = _require_cfg()
    if err:
        return err

    r = _ssh(
        "echo '=== Quota ===' && quota -s 2>/dev/null; "
        "echo '' && echo '=== Filesystem ===' && "
        "df -h $HOME $WORK $SCRATCH 2>/dev/null && "
        "echo '' && echo '=== Project dir size ===' && "
        f"du -sh {_project()}/results/ 2>/dev/null && "
        f"du -sh {_project()}/data/ 2>/dev/null"
    )
    return _fmt(r, "Could not retrieve disk usage.")


@mcp.tool()
def node_load() -> str:
    """
    Show current login node CPU and memory usage on TACC.
    Useful to check whether a login node is overloaded before running
    a lightweight interactive command.
    """
    cfg, err = _require_cfg()
    if err:
        return err

    r = _ssh("uptime && echo '' && free -h && echo '' && top -bn1 | head -15")
    return _fmt(r)


@mcp.tool()
def git_status() -> str:
    """Show git status and the 5 most recent commits in the project on TACC."""
    cfg, err = _require_cfg()
    if err:
        return err

    proj = _project()
    r = _ssh(
        f"cd {proj} && "
        "echo '=== git status ===' && git status --short && "
        "echo '' && echo '=== recent commits ===' && "
        "git log --oneline -5 2>&1"
    )
    return _fmt(r)


@mcp.tool()
def git_pull() -> str:
    """
    Pull the latest code from GitHub into the project on TACC.
    Run this after pushing changes from your local machine so TACC has the
    latest scripts before you submit a pipeline job.
    """
    cfg, err = _require_cfg()
    if err:
        return err

    r = _ssh(
        f"cd {_project()} && "
        "git pull origin $(git rev-parse --abbrev-ref HEAD) 2>&1",
        timeout=90,
    )
    return _fmt(r, "Already up to date.")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — ESCAPE HATCH
# ══════════════════════════════════════════════════════════════════════════════

@mcp.tool()
def run_command(command: str, timeout: int = 120) -> str:
    """
    Run any shell command on TACC (login node, non-interactive bash).
    Use for anything not covered by the other tools.
    command: shell command string (avoid interactive programs like vim, top -i)
    timeout: seconds to wait before giving up (default 120)

    Examples:
      run_command("ls -lh /work/07880/devansh/lonestar/cad-genetics/results/")
      run_command("module list")
      run_command("wc -l /work/.../results/agent1_genetics/gwas/*.regenie")
    """
    cfg, err = _require_cfg()
    if err:
        return err

    r = _ssh(command, timeout=timeout)
    out = r["stdout"].strip()
    err_out = r["stderr"].strip()
    result = out
    if err_out:
        result += f"\n[stderr]: {err_out}"
    return result or "(no output)"


if __name__ == "__main__":
    mcp.run()
