# TACC HPC MCP Server

> **One-sentence pitch:** Give Claude Code a direct, live connection to your TACC Lonestar6 project so it can check jobs, read logs, browse files, run analyses, interpret results, and submit new jobs — all from natural language, without you ever opening a terminal.

---

## Table of Contents

1. [What this is and why it exists](#1-what-this-is-and-why-it-exists)
2. [How it works under the hood](#2-how-it-works-under-the-hood)
3. [Prerequisites](#3-prerequisites)
4. [Installation — step by step](#4-installation--step-by-step)
5. [Daily usage](#5-daily-usage)
6. [Complete tool reference](#6-complete-tool-reference)
7. [The analysis co-pilot loop](#7-the-analysis-co-pilot-loop)
8. [Example conversations](#8-example-conversations)
9. [Configuration reference](#9-configuration-reference)
10. [Troubleshooting — every failure mode explained](#10-troubleshooting--every-failure-mode-explained)
11. [Security model](#11-security-model)
12. [Adapting to other HPC systems](#12-adapting-to-other-hpc-systems)
13. [Architecture deep-dive](#13-architecture-deep-dive)

---

## 1. What this is and why it exists

### The problem

When you run bioinformatics pipelines on TACC, you constantly context-switch:

- Open a terminal → `ssh tacc` → authenticate (password + 2FA) → `squeue` → copy job ID → find the log file → `tail -f` → read the error → look up what it means → fix the script → push from your Mac → pull on TACC → resubmit → wait → repeat.

Each of those steps is a context switch away from the actual science. And if you want Claude to help you interpret a result, you have to manually copy-paste it into the chat.

### The solution

This MCP server runs **locally on your Mac** and gives Claude Code 25 tools that talk directly to TACC. Claude can now:

- Check your job queue in real time
- Read log files and diagnose errors by itself
- Browse your results directories
- Run quick R/Python analysis snippets on TACC without a SLURM job
- Extract GWAS top hits and interpret them biologically — immediately
- Fetch result files to your Mac so Claude can plot them locally
- Write and submit new analysis jobs based on what it just read

The result is a conversation like:

```
You:    "Did the GWAS finish? Pull the top LDL hits and tell me what they mean."

Claude: [calls check_outputs] → GWAS complete ✓
        [calls gwas_top_hits("LDL_C")] → returns top 50 loci
        [interprets] → "Lead signal at chr1:55M maps to PCSK9 (p=3.1×10⁻²⁴⁰),
                        novel signal at chr11:116M near APOA1/APOC3 cluster,
                        rs7412 (APOE ε2) reaching GWS for first time in this cohort..."
        [calls submit_analysis(manhattan_plot_script)] → job submitted, ID 3210445
```

No terminal. No copy-paste. No context switch.

---

## 2. How it works under the hood

### The MCP protocol

MCP (Model Context Protocol) is an open standard that lets language models call external tools. Claude Code acts as an MCP **client** — it discovers available tools at startup and calls them during conversations. This server acts as an MCP **server** — it registers 25 tools and handles their execution.

Communication happens over **stdio** (standard input/output). Claude Code launches `server.py` as a subprocess, sends JSON-RPC messages to its stdin, and reads responses from its stdout. This is why the server must start fast — Claude Code has a short initialization timeout.

```
Claude Code (client)
    │
    │  JSON-RPC over stdio
    │
    ▼
server.py (MCP server, runs locally on your Mac)
    │
    │  ssh -o BatchMode=yes tacc "command"
    │  (reuses ControlMaster — no re-auth)
    │
    ▼
TACC Lonestar6 login node
    │
    │  squeue, sbatch, cat, find, Rscript, python3...
    │
    ▼
Your project files, SLURM queue, results
```

### SSH ControlMaster

The server never stores your password or tokens. Instead it relies on SSH's **ControlMaster** feature: when you run `ssh tacc` in your terminal, SSH opens an authenticated connection and keeps it alive as a background socket (`~/.ssh/cm_devansh@ls6.tacc.utexas.edu:22`). Every subsequent `ssh tacc ...` command reuses that socket silently — no re-authentication, near-instant connection.

The `ControlPersist 4h` setting (written by `setup.py`) means the socket stays alive for 4 hours after your last use, even if you close the terminal window.

### Lazy config loading

A critical design decision: `~/.tacc_mcp.json` is read **on the first tool call**, not at import time. This means the server starts successfully even if:
- The config file doesn't exist yet
- The SSH session isn't open yet
- TACC is unreachable

Without lazy loading, any of these conditions would crash the server process before it registered any tools — and Claude Code would silently show no TACC tools with no error message.

---

## 3. Prerequisites

| Requirement | Why | How to check |
|---|---|---|
| Mac or Linux | The server uses `ssh`/`scp`/`rsync` from your system | — |
| Python 3.10+ | Runs the server locally | `python3 --version` |
| TACC account | SSH access to `ls6.tacc.utexas.edu` | TACC user portal |
| Claude Code CLI | Registers MCP servers via `claude mcp add` | `npm install -g @anthropic-ai/claude-code` |
| Node.js + npm | Required by Claude Code CLI | `node --version` |
| Your project on TACC | Server points to a specific directory | — |

**Why Claude Code CLI specifically?** Claude Code stores MCP server registrations in `~/.claude.json` scoped per project. The `claude mcp add` command is the only reliable way to write to the right location. Manual edits to `settings.json` files do not work in all Claude environments (see [Troubleshooting](#10-troubleshooting--every-failure-mode-explained)).

---

## 4. Installation — step by step

### Step 1: Clone this repo

```bash
git clone https://github.com/Devanshpandey/tacc-mcp.git
cd tacc-mcp
```

Clone it somewhere permanent on your Mac — the MCP registration points to this path and will break if you move the folder later.

Good locations:
- `~/tools/tacc-mcp/`
- `~/code/tacc-mcp/`
- `~/Downloads/tacc-mcp/` *(fine, but avoid if you periodically clear Downloads)*

### Step 2: Create a dedicated Python environment

The server needs the `mcp` package. Create an isolated environment so it never conflicts with your other Python projects:

```bash
# Option A — with uv (recommended, fastest)
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python mcp

# Option B — with standard venv
python3 -m venv .venv
source .venv/bin/activate
pip install mcp
deactivate
```

This creates `.venv/` inside the repo. The server is then invoked as `.venv/bin/python server.py` — no activation needed, no `uv run` overhead. Startup time is ~1.7 seconds vs ~10+ seconds with `uv run --with mcp`.

**Why not system Python or conda?**
The `mcp` package requires Python 3.10+ and specific dependencies. Using a dedicated `.venv` guarantees a clean, fast, reproducible environment that won't break when you update other packages.

### Step 3: Run the setup wizard

```bash
python3 setup.py
```

The wizard will prompt for:

| Prompt | Example | Notes |
|---|---|---|
| TACC hostname | `ls6.tacc.utexas.edu` | Default — just press Enter |
| Your TACC username | `jsmith` | Your TACC login |
| SSH alias | `tacc` | Short name used as `ssh tacc` |
| Project path on TACC | `/work/07880/jsmith/lonestar/my-project` | Absolute path to your repo on TACC |
| Logs subfolder | `logs/runs` | Where pipeline run logs live |

It writes two things:

**`~/.tacc_mcp.json`** — the server's local config:
```json
{
  "tacc_host":   "tacc",
  "tacc_user":   "jsmith",
  "project_dir": "/work/07880/jsmith/lonestar/my-project",
  "logs_subdir": "logs/runs"
}
```

**`~/.ssh/config`** — adds a ControlMaster block:
```
Host tacc
    HostName ls6.tacc.utexas.edu
    User jsmith
    ControlMaster auto
    ControlPath ~/.ssh/cm_%r@%h:%p
    ControlPersist 4h
```

`ControlMaster auto` means the first `ssh tacc` opens the master connection; subsequent calls reuse it automatically. `ControlPersist 4h` keeps it alive for 4 hours.

### Step 4: Register with Claude Code

```bash
# Run this from your analysis project directory
cd /path/to/your/analysis-project

claude mcp add tacc-hpc \
  /path/to/tacc-mcp/.venv/bin/python \
  /path/to/tacc-mcp/server.py
```

Replace both paths with wherever you cloned the repo. Example:

```bash
cd ~/genomics/cad-analysis

claude mcp add tacc-hpc \
  ~/tools/tacc-mcp/.venv/bin/python \
  ~/tools/tacc-mcp/server.py
```

**What this command does:** It writes to `~/.claude.json` under a `projects` key scoped to your current directory. The entry looks like:

```json
{
  "projects": {
    "/Users/jsmith/genomics/cad-analysis": {
      "mcpServers": {
        "tacc-hpc": {
          "type": "stdio",
          "command": "/Users/jsmith/tools/tacc-mcp/.venv/bin/python",
          "args": ["/Users/jsmith/tools/tacc-mcp/server.py"]
        }
      }
    }
  }
}
```

Verify the server is reachable:

```bash
claude mcp list
# tacc-hpc: /Users/... — ✓ Connected
```

If it shows `✗ Error`, see [Troubleshooting](#10-troubleshooting--every-failure-mode-explained).

### Step 5: Open your daily SSH session

```bash
ssh tacc
# TACC password: ••••••••
# TACC Token: 123456
# (You're in. You can close this terminal window now.)
```

This is the only time you need to authenticate. The ControlMaster socket stays alive for 4 hours. You don't need to keep the terminal open — the connection background-persists.

### Step 6: Start Claude Code and verify

Open Claude Code in your project directory. The tools load automatically at startup. Ask Claude:

```
"Call get_started() on the TACC MCP"
```

Expected output:
```
✓  Config found
✓  SSH ControlMaster is live
```

If you see ✗ on either line, see [Troubleshooting](#10-troubleshooting--every-failure-mode-explained).

---

## 5. Daily usage

### Your daily routine

```bash
# Morning: open one SSH session (30 seconds, once per day)
ssh tacc

# Then work in Claude Code — no more terminal needed
```

### What you stop doing

| Before | After |
|---|---|
| `ssh tacc` → `squeue` → copy job ID | "Check my jobs" |
| `ssh tacc` → `tail -100 logs/step5.err` | "Show me the last 100 lines of the coloc log" |
| `scp tacc:/work/.../results.csv ~/Desktop/` then open R | "Fetch the MR results and interpret them" |
| Write R script → scp to TACC → sbatch → wait → scp plot back | "Plot a Manhattan for LDL-C and interpret the loci" |
| Manually grep for errors across 22 chr log files | "Is there an error in any of the GWAS logs?" |

### When the SSH session expires

Tools will return:
```
SSH ControlMaster is not active.
Fix: open a terminal and run:  ssh tacc
```

Just run `ssh tacc` in any terminal — takes 30 seconds — and continue. To extend the default 4-hour window, edit `~/.ssh/config`:
```
ControlPersist 8h   # or 12h
```

---

## 6. Complete tool reference

All 25 tools, grouped by function. Every tool returns a string that Claude reads and acts on.

---

### 🔌 Connection & Setup

#### `get_started()`
Interactive tutorial. Checks your current config and SSH status, then prints a complete tool reference and common workflow guide. **Call this first if anything seems wrong.**

```
"Call get_started()"
"Something's not working with the TACC tools — run get_started"
```

#### `check_connection()`
Verifies the SSH ControlMaster is live. Returns hostname, username, and current login node load average. If not connected, prints the exact command to fix it.

```
"Is TACC connected?"
"Check the SSH connection"
```

---

### 📋 SLURM Job Management

#### `job_status()`
Runs `squeue -u <user>` and returns all pending and running jobs with state, elapsed time, and wait reason. The wait reason tells you *why* a job is pending:
- `Priority` — waiting in the queue behind higher-priority jobs
- `Dependency` — waiting for another job (specified in `--dependency`) to complete
- `Resources` — waiting for enough nodes to be free
- `QOSMaxJobsPerUserLimit` — you've hit your concurrent job limit

```
"Are my jobs running?"
"What's the queue looking like?"
"Why is job 3210175 still pending?"
```

#### `job_history(days=3)`
Runs `sacct` to show recently completed, failed, or cancelled jobs. Essential when a job disappears from the queue and you don't know what happened to it. `days` controls how far back to look (default 3).

```
"What happened to the phenotype prep job?"
"Show me all failed jobs from the last week"
"Did the burden mask step complete successfully?"
```

#### `job_details(job_id)`
Shows full SLURM accounting data for one specific job: working directory, script path, stdout/stderr paths, allocated CPUs, requested memory, actual peak memory (MaxRSS), and timing. Useful for tracking down log files when you know the job ID but not the log path.

```
"Show me the details for job 3210174"
"Where are the logs for job 3210182?"
```

#### `cancel_jobs(job_ids)`
Runs `scancel` on the given job IDs (space-separated). Works on individual jobs and array jobs.

```
"Cancel jobs 3210160 3210161 3210162"
"Cancel all my pending jobs"  → job_status() first, then cancel_jobs("id1 id2 ...")
"Cancel the GWAS array job 3210176"  → cancels all 3210176_[1-22]
```

---

### 🔄 Pipeline Management

#### `pipeline_status(run_id="")`
Cross-references your pipeline's `manifest.tsv` (written at job submission) with the live SLURM queue and recent `sacct` history. Gives a per-step view of what's done, running, or pending. `run_id` is a timestamp folder name like `20260606_080012` — leave blank to use the most recent run.

```
"What's the pipeline status?"
"Which steps have finished?"
"pipeline_status for run 20260605_110245"
```

#### `list_runs()`
Lists all pipeline run directories under `logs/runs/`, newest first, with file count and a one-line summary from `run_all.log`. Useful for finding the run ID you need for other tools.

```
"List all my pipeline runs"
"What runs do I have?"
```

#### `run_pipeline(script="run_all.sh", args="")`
Submits a pipeline script on TACC as a background nohup process (not SLURM — runs on the login node). Returns the process ID and log path. Use this to kick off `run_all.sh` or a specific step script without SSHing in.

```
"Start the pipeline"
"Run agent2 genes script"
"Submit run_all.sh with --step 3"
```

> ⚠️ Runs on the login node — only for lightweight orchestration scripts. Heavy computation should go through `submit_analysis()`.

#### `check_outputs(agent=1)`
Checks a predefined list of expected output files for each pipeline agent and reports which exist (with file size and date) and which are missing. Agents: 1 (genetics), 2 (genes), 3 (networks), 4 (subtypes).

```
"Check agent 1 outputs"
"Did the GWAS finish? Are all the files there?"
"check_outputs for agent 2"
```

---

### 📁 Files & Logs

#### `list_dir(path="")`
Runs `ls -lhp` on any directory on TACC. Defaults to the project root if no path given. Results are capped at 100 lines.

```
"List the results directory"
"What's in /work/.../results/agent1_genetics/gwas/"
"Show me the data directory"
```

#### `read_file(path, head_lines=0, tail_lines=0, max_lines=200)`
Reads any text file on TACC. Supports head (first N lines), tail (last N lines), or full read capped at `max_lines`. Works for logs, CSVs, R scripts, config files, summary stats — anything text-based.

```
"Read the phenotype summary"
"Show me the first 20 lines of the LDSC log"
"Read the last 50 lines of run_all.log"
"Show me the run_all.sh script"
```

#### `list_logs(run_id="")`
Lists log files for a pipeline run, sorted by modification time. Shows file sizes so you can quickly identify which logs have content vs which are empty (a common sign of a job that didn't actually run).

```
"List logs for the latest run"
"list_logs for run 20260606_080012"
```

#### `read_log(step="", path="", run_id="", tail_lines=100, stream="both")`
Tails a SLURM log file. You can specify the step by name prefix (e.g. `"01_prep"`, `"cad_gwas"`, `"burden"`), and it finds the matching `.out` and/or `.err` file in the latest run directory. `stream` controls whether to show stdout, stderr, or both.

For array jobs (e.g. `cad_gwas_lipids_[1-22]`), it returns the last 5 matching files automatically.

```
"Show me the phenotype prep log"
"Read the regenie step1 log"
"Show errors only from the GWAS run"   → stream="err"
"Read the last 200 lines of the coloc log"
```

#### `grep_file(pattern, path, context_lines=2)`
Runs `grep -n -C N pattern path` on a remote file. Returns matching lines with surrounding context. Useful for finding specific errors, sample counts, or completion messages across large log files.

```
"Is there an ERROR in the LDSC log?"
"Find 'cases=' in the phenotype summary"
"Search for 'Warning' in all GWAS logs"  → path="/work/.../logs/runs/latest/*.err"
```

---

### 🖥️ System & Git

#### `disk_usage()`
Reports quota usage for `$HOME`, and filesystem usage for `$WORK` and `$SCRATCH`. Also shows the size of your project's `results/` and `data/` directories. Run before starting a large GWAS to make sure you have enough space.

```
"How much disk space do I have?"
"Check quota before I start the GWAS"
```

#### `node_load()`
Shows the current login node's CPU and memory usage (`uptime`, `free -h`, `top -bn1`). Useful before running a login-node script to make sure the node isn't overloaded.

```
"Is the login node busy right now?"
"Check node load before running a script"
```

#### `git_status()`
Runs `git status --short` and `git log --oneline -5` in the project directory on TACC. Shows uncommitted changes and recent commits.

```
"What's the git status on TACC?"
"Have there been any recent commits on TACC?"
```

#### `git_pull()`
Runs `git pull origin <current-branch>` in the project directory on TACC. Use this after pushing code changes from your Mac — updates TACC to the latest version before you resubmit jobs.

```
"Pull the latest code on TACC"
"I pushed a bug fix — update TACC"
```

#### `run_command(command, timeout=120)`
Runs any arbitrary shell command on the TACC login node and returns its output. This is the escape hatch for anything not covered by the other tools. Runs in a non-interactive bash session — no interactive programs (vim, top, etc.).

```
"Run: module list"
"Run: wc -l /work/.../results/gwas/*.regenie"
"Check if plink2 is available: which plink2"
"Count variants in the annotation file"
```

---

### 🔬 Analysis Co-Pilot

These five tools close the loop between TACC results and Claude's analytical capabilities.

#### `fetch_file(remote_path, local_path="")`
Copies a single file from TACC to your Mac via `scp` over the existing ControlMaster connection. Defaults to `~/Downloads/tacc_results/<filename>`. After fetching, Claude can read the file directly using its built-in `Read` tool.

```
"Fetch the MR results table"
"Pull the coloc results CSV to my Mac"
"Fetch the genetic correlation matrix"
```

#### `fetch_results(agent=1, local_dir="", dry_run=False)`
Smart batch-fetch of all key lightweight result files for a pipeline agent. Skips raw GWAS summary stats (too large — typically GB per trait) and fetches only analysis outputs: CSVs, summary tables, pre-generated plots. Missing files are reported but don't cause failure.

`dry_run=True` lists what *would* be fetched without downloading anything.

What gets fetched per agent:
- **Agent 1:** phenotype summary, LDSC rg matrix, coloc results, MR table, fine-mapping credible sets, GWAS top hits CSV, any plots
- **Agent 2:** ranked gene table, gene evidence heatmap
- **Agent 3:** pathway enrichment table, network modules JSON, interactive network HTML
- **Agent 4:** patient subtype assignments, PRS profiles, outcome associations

```
"Fetch all agent 1 results"
"What would fetch_results(agent=1) pull?"   → dry_run=True
"Pull the network biology results to my Mac"
```

#### `submit_analysis(script, job_name, time, memory, cpus, partition, email)`
Writes a script file to TACC and submits it via `sbatch`. Claude composes the script based on your results, and this tool handles all the SLURM boilerplate (headers, log paths, account). Returns the job ID and log paths.

This is how Claude moves from *reading* results to *acting* on them — writing and submitting the next analysis step without you touching a terminal.

```
"Plot a Manhattan for LDL-C"           → Claude writes R script → submit_analysis()
"Run LD clumping on these top hits"    → Claude writes plink2 command → submit_analysis()
"Rerun coloc with a lower PP.H4 threshold" → Claude writes updated script → submit_analysis()
```

#### `run_remote_script(script, interpreter="bash", timeout=120)`
Runs a short script directly on the TACC login node (no SLURM queue) and returns the output inline. Use for lightweight operations: data summaries, quick R snippets, file inspection, format checks. For anything that takes >2 minutes or uses significant CPU/memory, use `submit_analysis()` instead.

Supported interpreters: `bash`, `python3`, `Rscript`, `awk`, `perl`.

**Important:** The login node's default Python may have NumPy/pandas conflicts. Specify the full path to your conda environment's Python if needed:
```
interpreter="/work/07880/jsmith/anaconda3/envs/r_env/bin/Rscript"
```

```
"What are the summary statistics for LDL-C in our data?"
"How many genome-wide significant hits are in the GWAS?"
"Quick R: check if the LDSC output file has the right format"
```

#### `gwas_top_hits(phenotype, n=50, pval_threshold=5e-8)`
Extracts the top N GWAS loci for a phenotype directly from REGENIE summary statistics on TACC, filtered by p-value threshold (default genome-wide significance 5×10⁻⁸). Returns the hits inline so Claude can immediately interpret which genes they map to, whether they're novel, and what follow-up analyses to suggest.

Phenotype names must match the REGENIE output filenames in `results/agent1_genetics/gwas/` (e.g. `LDL_C`, `CAD`, `HDL_C`, `TG`, `MACE`, `MI`).

```
"What are the top GWAS hits for LDL-C?"
"Pull the top 100 CAD loci and tell me which are novel"
"Any genome-wide significant hits for Lp(a)?"
```

---

## 7. The analysis co-pilot loop

The five co-pilot tools enable a self-contained research loop where Claude moves from monitoring → reading → interpreting → acting:

```
┌─────────────────────────────────────────────────────────────────┐
│                    ANALYSIS CO-PILOT LOOP                       │
│                                                                  │
│  1. MONITOR          job_status() / check_outputs(agent)        │
│         │                                                        │
│         ▼                                                        │
│  2. EXTRACT          gwas_top_hits() / run_remote_script()      │
│         │            (lightweight — runs on login node)          │
│         ▼                                                        │
│  3. FETCH            fetch_results() / fetch_file()             │
│         │            (pulls files to Mac for Claude to read)     │
│         ▼                                                        │
│  4. INTERPRET        Claude reads CSVs/tables locally           │
│         │            → biological interpretation                 │
│         │            → identifies what to do next               │
│         ▼                                                        │
│  5. ACT              submit_analysis(Claude-written script)     │
│         │            → new job on TACC                          │
│         │                                                        │
│         └──────────────────────────────────────────────────────┐│
│                       loop back to 1                            ││
└─────────────────────────────────────────────────────────────────┘
```

### Example: GWAS → Manhattan → Biology

```
Step 1  check_outputs(agent=1)
        → "GWAS complete: LDL_C.regenie exists (2.1GB)"

Step 2  gwas_top_hits("LDL_C", n=100)
        → returns top 100 loci inline
        → Claude: "Lead signal at PCSK9 (p=3×10⁻²⁴⁰), novel signal
                   at chr11:116M near ANGPTL3, 6 loci not in GLGC 2021..."

Step 3  submit_analysis(manhattan_R_script, job_name="ldl_manhattan")
        → job 3210445 submitted

Step 4  [wait] → job_status() → COMPLETED

Step 5  fetch_file("/work/.../plots/ldl_manhattan.png")
        → Claude reads plot image
        → "The chr1 PCSK9 peak is clean, the chr11 signal shows
            LD structure consistent with two independent signals..."

Step 6  submit_analysis(conditional_analysis_script)
        → follow-up conditional GWAS for chr11 region
```

---

## 8. Example conversations

### "Just check on things"

```
You:    "Quick status check — jobs, outputs, disk"

Claude: [job_status()]      → 7 jobs pending, regenie step1 waiting on Priority
        [check_outputs(1)]  → phenotypes ✓, burden masks ✓, regenie ✗, GWAS ✗
        [disk_usage()]      → WORK 47% used, results/ 1.6GB, data/ 71GB
        → "Regenie step1 is queued (Priority). Once it runs (~2-4h),
            the GWAS array will start automatically. No disk concerns."
```

### "Debug a failed job"

```
You:    "The burden step failed — what happened?"

Claude: [job_history(days=3)]         → burden_masks 3199835_[1-22] FAILED
        [job_details("3199835")]       → WorkDir, log paths
        [read_log(step="burden", stream="err")] → "FileNotFoundError: annotated_chr_1..."
        → "The annotated VCF path was wrong. The script expected
            annotated_chr_1_sites_dbNSFP.vcf.gz but the file is named
            annotated_chr1_sites_dbNSFP.vcf.gz (no underscore after chr).
            Want me to fix the script and resubmit?"
```

### "Interpret results"

```
You:    "LDSC finished — fetch the rg matrix and tell me what's correlated"

Claude: [check_outputs(1)]              → ldsc_rg_matrix.csv ✓
        [fetch_file("ldsc_rg_matrix.csv")]  → pulled to ~/Downloads/tacc_results/
        [reads file locally]
        → "LDL-C × CAD: rg=0.71 (se=0.03) — strong positive correlation,
            consistent with LDL being causal for CAD.
            HDL-C × CAD: rg=-0.42 (se=0.05) — moderate protective correlation,
            weaker than expected given earlier studies, possibly due to
            pleiotropic effects at CETP/LIPC.
            TG × stroke: rg=0.38 (se=0.06) — notable, suggests shared
            inflammatory/coagulation pathways..."
```

### "Run a new sub-analysis"

```
You:    "The chr1 GWAS peak for LDL looks like it might have two signals.
         Run a conditional analysis conditioning on the lead SNP."

Claude: [gwas_top_hits("LDL_C", n=5)]  → lead SNP is rs11206510 at PCSK9
        → writes a REGENIE conditional analysis script
        [submit_analysis(script, job_name="ldl_conditional_chr1", time="4:00:00")]
        → "Submitted job 3210512. It will run REGENIE step2 on chr1 only,
            conditioning on rs11206510. Log at logs/claude_jobs/ldl_conditional_chr1_3210512.out.
            I'll check it when you ask — should take ~45 minutes."
```

---

## 9. Configuration reference

### `~/.tacc_mcp.json`

Written by `setup.py`. All paths and values are used by the server at runtime.

```json
{
  "tacc_host":   "tacc",
  "tacc_user":   "jsmith",
  "project_dir": "/work/07880/jsmith/lonestar/my-project",
  "logs_subdir": "logs/runs"
}
```

| Key | Required | Default | Description |
|---|---|---|---|
| `tacc_host` | ✓ | — | SSH alias from `~/.ssh/config`. Used in every `ssh <host> "cmd"` call. |
| `tacc_user` | ✓ | — | Your TACC username. Used in `squeue -u <user>` and `sacct -u <user>`. |
| `project_dir` | ✓ | — | Absolute path to your project root on TACC. All relative paths resolve from here. |
| `logs_subdir` | | `logs/runs` | Subfolder under `project_dir` where pipeline run log directories live. |

### `~/.ssh/config` block (written by `setup.py`)

```
Host tacc
    HostName ls6.tacc.utexas.edu
    User jsmith
    ControlMaster auto
    ControlPath ~/.ssh/cm_%r@%h:%p
    ControlPersist 4h
```

| Option | Effect |
|---|---|
| `ControlMaster auto` | First connection opens master; subsequent connections reuse it |
| `ControlPath` | Socket file location. `%r`=username, `%h`=hostname, `%p`=port |
| `ControlPersist 4h` | Keep socket alive 4 hours after last use. Set to `8h` or `12h` if you want longer sessions |

### MCP registration (`~/.claude.json`)

Written by `claude mcp add`. Do not edit manually.

```json
{
  "projects": {
    "/Users/jsmith/genomics/my-project": {
      "mcpServers": {
        "tacc-hpc": {
          "type": "stdio",
          "command": "/Users/jsmith/tools/tacc-mcp/.venv/bin/python",
          "args": ["/Users/jsmith/tools/tacc-mcp/server.py"]
        }
      }
    }
  }
}
```

---

## 10. Troubleshooting — every failure mode explained

### ❌ Tools don't appear in Claude Code after restart

**Cause A: MCP registered in wrong config file.**
`~/.claude/settings.json` and `.claude/settings.json` (project-level) are NOT the right place. Claude Code reads MCP servers from `~/.claude.json` (no subdirectory, registered per-project).

Fix:
```bash
cd /your/project
claude mcp add tacc-hpc /path/to/.venv/bin/python /path/to/server.py
claude mcp list   # should show ✓ Connected
```

**Cause B: Server crashes at startup.**
If the server process crashes before registering tools, Claude Code silently shows no tools.

Test the server directly:
```bash
/path/to/tacc-mcp/.venv/bin/python /path/to/tacc-mcp/server.py
# Should start silently, waiting on stdin. Ctrl+C to stop.
# If it prints an error and exits, that's the crash.
```

**Cause C: Python path is wrong.**
The `command` in the MCP registration must point to the `.venv/bin/python` inside the tacc-mcp directory — not system Python, not conda Python.

```bash
# Verify the path exists and runs
/path/to/tacc-mcp/.venv/bin/python --version
```

**Cause D: SSH session was closed when Claude Code started.**
Claude Code initializes all MCP servers at startup. If the SSH ControlMaster is down, the server starts fine (lazy loading), but some Claude environments may time out waiting for the first tool response.

Fix: Open `ssh tacc` before starting Claude Code.

---

### ❌ "SSH ControlMaster is not active"

Your 4-hour session expired, or was never opened.

```bash
ssh tacc   # re-authenticate (30 seconds)
```

To extend the window, edit `~/.ssh/config`:
```
ControlPersist 8h
```

To check if a ControlMaster is currently active:
```bash
ssh -O check tacc
# "Master running (pid=XXXXX)" → active
# "No ControlMaster..." → need to ssh tacc
```

---

### ❌ "No config found at ~/.tacc_mcp.json"

```bash
python3 /path/to/tacc-mcp/setup.py
```

Or create it manually:
```bash
cat > ~/.tacc_mcp.json << 'EOF'
{
  "tacc_host":   "tacc",
  "tacc_user":   "YOUR_USERNAME",
  "project_dir": "/work/XXXXX/YOUR_USERNAME/your-project",
  "logs_subdir": "logs/runs"
}
EOF
```

---

### ❌ `run_remote_script` fails with Python/NumPy errors

The system Python on TACC login nodes may have version conflicts. Find your conda environment's Python:

```bash
# On TACC
find /work/$USER/anaconda3/envs -name "python3" | head -5
find /work/$USER/anaconda3/envs -name "Rscript" | head -5
```

Then pass the full path as `interpreter`:
```
interpreter="/work/07880/jsmith/anaconda3/envs/r_env/bin/Rscript"
```

---

### ❌ `claude mcp list` shows `✗ Error`

Run the full MCP handshake manually to see the actual error:

```bash
printf '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}\n{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}\n{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}\n' | \
  /path/to/tacc-mcp/.venv/bin/python \
  /path/to/tacc-mcp/server.py 2>&1
```

Should return JSON with `"tools": [...]`. If it errors, the output tells you exactly what's wrong.

---

### ❌ `fetch_file` or `fetch_results` times out

`scp` uses the same ControlMaster socket. Verify it's active:
```bash
ssh -O check tacc
```

For very large files (>500MB), use `run_command` to check file size first, then decide whether to fetch or just run analysis on TACC.

---

### ❌ `submit_analysis` job fails immediately (exit code 1, runs for <5 seconds)

Check the job's stderr log:
```bash
# In Claude:
"Read the log for job <job_id>"
→ read_log(path="/work/.../logs/claude_jobs/<jobname>_<id>.err")
```

Common causes:
- Missing `module load` for the tool you're using (e.g. `module load plink2`)
- Wrong file paths in the script (use absolute paths)
- Account mismatch (the server uses your `tacc_user` as the account — override with `partition` if needed)

---

## 11. Security model

### What the server can and cannot access

| Can | Cannot |
|---|---|
| Run any command you ask on TACC login nodes | Access other users' files |
| Read/write files in your TACC project | Submit jobs to queues you don't have access to |
| Submit SLURM jobs under your account | Authenticate to TACC (you do this manually) |
| Copy files to/from your Mac | Store your password or tokens anywhere |

### Credential handling

- Your TACC password and 2FA token **never touch this software**. You enter them directly into `ssh`.
- The SSH ControlMaster socket (`~/.ssh/cm_devansh@ls6.tacc.utexas.edu:22`) is owned by your user, mode 600. Only processes running as you can use it.
- `~/.tacc_mcp.json` contains only your username and project path — no secrets.

### The `run_command` and `submit_analysis` tools

These can execute arbitrary code on TACC under your account. Claude Code always shows you the tool call before executing — you see exactly what command will run and can decline. The tools run with your standard TACC permissions — they cannot escalate privileges or access other users' files.

### Local data privacy

`fetch_file` and `fetch_results` copy files to your local Mac (default: `~/Downloads/tacc_results/`). These files are subject to your usual data governance obligations — UKB data access agreements, IRB protocols, etc. Do not store UKB individual-level data in uncontrolled locations.

---

## 12. Adapting to other HPC systems

The server uses only POSIX-standard tools: `ssh`, `scp`, `rsync`, `squeue`, `sbatch`, `sacct`, `scancel`. It works on **any SLURM cluster**.

### Minimal changes to use a different cluster

1. **`~/.tacc_mcp.json`** — point `tacc_host` to your new cluster's SSH alias
2. **`setup.py`** — change the default hostname from `ls6.tacc.utexas.edu`
3. **`check_outputs()`** in `server.py` — update the expected file paths for your pipeline structure

### Clusters tested / compatible

- TACC Lonestar6 ✓ (primary target)
- TACC Frontera ✓ (change hostname, same SLURM)
- Any SLURM cluster with `squeue`/`sbatch`/`sacct` ✓
- PBS/Torque clusters ✗ (would need `qstat`/`qsub` variants)

---

## 13. Architecture deep-dive

### File structure

```
tacc-mcp/
├── server.py          — MCP server, 25 tools, ~850 lines
│   ├── Section 1      — get_started() tutorial tool
│   ├── Section 2      — check_connection()
│   ├── Section 3      — SLURM: job_status, job_history, job_details, cancel_jobs
│   ├── Section 4      — Pipeline: pipeline_status, list_runs, run_pipeline, check_outputs
│   ├── Section 5      — Files: list_dir, read_file, list_logs, read_log, grep_file
│   ├── Section 6      — System: disk_usage, node_load, git_status, git_pull
│   ├── Section 7      — Escape hatch: run_command
│   └── Section 8      — Co-pilot: fetch_file, fetch_results, submit_analysis,
│                                   run_remote_script, gwas_top_hits
├── setup.py           — interactive setup wizard (~200 lines)
├── requirements.txt   — mcp>=1.0.0
├── .venv/             — dedicated Python environment (created by you, not committed)
└── README.md          — this file
```

### Key design decisions

**Lazy config loading** — `_load_config()` is called on first tool use, not at import. This prevents startup crashes when SSH is down or config is missing.

**Single `_ssh()` helper** — all TACC communication goes through one function that handles timeouts, BatchMode enforcement, and error formatting. Errors always include the fix command (`ssh tacc`).

**Separate `_scp()` and `_rsync()` helpers** — file transfer uses the ControlMaster socket via the `-o ControlPath` flag, reusing the authenticated session.

**No state between calls** — every tool call is stateless. The server holds no connection pool, no cache, no session. This makes it robust to long idle periods and easy to debug.

**FastMCP framework** — tools are registered as Python functions decorated with `@mcp.tool()`. FastMCP handles the JSON-RPC protocol, argument parsing, and stdio transport automatically.

### Adding new tools

```python
@mcp.tool()
def my_new_tool(arg1: str, arg2: int = 10) -> str:
    """
    Docstring is shown to Claude as the tool description.
    Be specific — Claude uses this to decide when to call the tool.

    arg1: description of this argument
    arg2: description, with default (default: 10)
    """
    cfg, err = _require_cfg()
    if err:
        return err

    r = _ssh(f"some command {arg1} | head -{arg2}")
    return _fmt(r)
```

Restart Claude Code after adding tools. No reregistration needed — `claude mcp add` stays valid.

---

## Contributing

PRs welcome. The server is a single self-contained file — easy to extend.

Useful additions that aren't yet implemented:
- `watch_job(job_id)` — poll until a job reaches a terminal state and report outcome
- `multi_cluster` — support multiple HPC systems in one config
- `PBS/Torque` support — `qstat`/`qsub` variants of the SLURM tools
- `transfer_progress` — rsync with live progress for large result directories
- `notebook_analysis` — fetch results and open a pre-populated Jupyter notebook locally
