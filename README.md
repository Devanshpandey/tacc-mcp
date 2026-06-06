# TACC HPC MCP Server

Connect [Claude Code](https://claude.ai/claude-code) directly to your project on TACC Lonestar6 (or any SLURM cluster).
Once set up, Claude can check job status, read logs, browse files, cancel jobs, and run commands on TACC — without you ever leaving your editor.

```
You: "Are my pipeline jobs still running?"
Claude: [calls job_status] → live squeue output

You: "The coloc step failed — show me the last 50 lines of that log"
Claude: [calls read_log(step="07_coloc", tail_lines=50)] → shows the error

You: "Did the phenotype prep finish? Check the outputs."
Claude: [calls check_outputs(agent=1)] → ✓ pheno_quantitative.txt 34M, ✗ MISSING: regenie/step1/
```

---

## How it works

The MCP server runs **locally on your Mac**. It connects to TACC over a persistent SSH ControlMaster session — you authenticate once with your password + 2FA token, and every Claude tool call reuses that connection silently for up to 4 hours.

```
Claude Code  ──MCP──▶  server.py (local)  ──SSH ControlMaster──▶  TACC Lonestar6
```

No credentials are stored. No data goes to any third party. It's just `ssh` under the hood.

---

## Prerequisites

- **Mac or Linux** with Python 3.10+
- **TACC account** with SSH access to Lonestar6 (`ls6.tacc.utexas.edu`)
- **Claude Code CLI** installed — `npm install -g @anthropic-ai/claude-code`
- **Your project cloned on TACC** — the server points to a specific directory

---

## Installation

### 1. Clone this repo

```bash
git clone https://github.com/Devanshpandey/tacc-mcp.git
cd tacc-mcp
```

### 2. Create a dedicated Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install mcp
```

Or with `uv` (faster):

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python mcp
```

### 3. Run the setup wizard

```bash
python3 setup.py
```

The wizard asks for:
- Your TACC username and hostname (default: `ls6.tacc.utexas.edu`)
- A short SSH alias (default: `tacc` — used as `ssh tacc`)
- The absolute path to your project on TACC, e.g. `/work/07880/jsmith/lonestar/my-project`
- The subfolder where your pipeline writes run logs (default: `logs/runs`)

It will:
1. Add a `ControlMaster` SSH block to `~/.ssh/config`
2. Write `~/.tacc_mcp.json` (your local config — never committed to git)

### 4. Register the MCP server with Claude Code

```bash
claude mcp add tacc-hpc \
  /path/to/tacc-mcp/.venv/bin/python \
  /path/to/tacc-mcp/server.py
```

Replace `/path/to/tacc-mcp` with wherever you cloned this repo, e.g.:

```bash
claude mcp add tacc-hpc \
  /Users/jsmith/tools/tacc-mcp/.venv/bin/python \
  /Users/jsmith/tools/tacc-mcp/server.py
```

> **Important:** use `claude mcp add`, not a manual `settings.json` edit.
> Claude Code stores MCP config in `~/.claude.json` scoped to your project directory,
> and `claude mcp add` writes to exactly the right place.

Verify it's connected:

```bash
claude mcp list
# tacc-hpc: ... — ✓ Connected
```

### 5. Open your daily SSH session

Before using any TACC tool in Claude, authenticate once:

```bash
ssh tacc
# Enter: TACC password + 6-digit authenticator code
```

The connection stays open for **4 hours** (configurable in `~/.ssh/config`). You don't need to keep the terminal window open — the ControlMaster runs in the background.

### 6. Start Claude Code and call `get_started()`

Open Claude Code in your project directory. The `tacc-hpc` tools are now available.
Ask Claude to call `get_started()` for a live status check and full tool tour:

```
"Call get_started() on the TACC MCP"
```

---

## Available tools (20 total)

### Connection
| Tool | Description |
|---|---|
| `get_started()` | Interactive tutorial — status check, tool reference, common workflows, troubleshooting |
| `check_connection()` | Verify SSH ControlMaster is alive; shows hostname, user, load |

### SLURM Job Management
| Tool | Description |
|---|---|
| `job_status()` | Live `squeue` — all pending/running jobs with state and wait reason |
| `job_history(days=3)` | `sacct` — recently completed, failed, or cancelled jobs |
| `job_details(job_id)` | Full SLURM metadata for one job (work dir, resources, exit code) |
| `cancel_jobs("id1 id2")` | `scancel` one or more jobs by ID |

### Pipeline Management
| Tool | Description |
|---|---|
| `pipeline_status()` | Cross-reference `manifest.tsv` with live queue — which step is where |
| `list_runs()` | List all pipeline run directories, newest first |
| `run_pipeline(script, args)` | Submit a `run_all.sh` or step script via nohup |
| `check_outputs(agent)` | Verify expected output files exist for each pipeline agent (1–4) |

### Files & Logs
| Tool | Description |
|---|---|
| `list_dir(path)` | `ls -lh` any remote directory |
| `read_file(path, head_lines, tail_lines)` | Read any text file on TACC — logs, CSVs, scripts |
| `list_logs(run_id)` | List log files for a pipeline run |
| `read_log(step, tail_lines, stream)` | Tail a SLURM log by step name prefix or full path |
| `grep_file(pattern, path)` | Search a remote file with context lines |

### System & Git
| Tool | Description |
|---|---|
| `disk_usage()` | Quota + `df` for `$HOME`, `$WORK`, `$SCRATCH` + project dir sizes |
| `node_load()` | Login node CPU/memory snapshot |
| `git_status()` | Git status + 5 recent commits in the project on TACC |
| `git_pull()` | Pull latest code on TACC (run after pushing from your Mac) |
| `run_command(cmd)` | Run any shell command on TACC (escape hatch) |

---

## Example prompts

```
"Are my jobs still running?"
"What happened to the phenotype prep job — did it succeed?"
"Show me the last 100 lines of the LDSC log"
"Check all agent 1 output files"
"Cancel jobs 3210160 and 3210161"
"Git pull on TACC then tell me what changed"
"How much disk space do I have left on scratch?"
"List all pipeline runs"
"Read the regenie step1 log — did it finish?"
"Is there an error in any of the GWAS logs?"
```

---

## Configuration reference

`~/.tacc_mcp.json` is written by `setup.py`. You can also create/edit it directly:

```json
{
  "tacc_host":   "tacc",
  "tacc_user":   "jsmith",
  "project_dir": "/work/07880/jsmith/lonestar/my-project",
  "logs_subdir": "logs/runs"
}
```

| Key | Required | Description |
|---|---|---|
| `tacc_host` | Yes | SSH alias from `~/.ssh/config` |
| `tacc_user` | Yes | Your TACC username |
| `project_dir` | Yes | Absolute path to project root on TACC |
| `logs_subdir` | No | Log subdirectory relative to `project_dir` (default: `logs/runs`) |

---

## Troubleshooting

### Tools don't appear in Claude Code after setup

The most common cause: MCP config was written to `settings.json` instead of `~/.claude.json`.
Always use `claude mcp add` (not manual edits) and restart Claude Code afterward.

Verify registration:
```bash
claude mcp list
```

If the server shows an error, test it directly:
```bash
/path/to/tacc-mcp/.venv/bin/python /path/to/tacc-mcp/server.py
# Should start silently waiting for input (Ctrl+C to stop)
```

### "Not connected to TACC" / SSH timeout

Your ControlMaster session has expired. Open a new one:
```bash
ssh tacc
```

### "Config file not found"

Run `setup.py`, or create `~/.tacc_mcp.json` manually (see Configuration reference above).

### ControlMaster session expires too quickly

Increase `ControlPersist` in `~/.ssh/config`:
```
Host tacc
    ControlPersist 8h
```

---

## How MCP registration works (for the curious)

Claude Code stores per-project MCP server config in `~/.claude.json` under a `projects` key.
`claude mcp add` writes to the correct location automatically for whichever directory you run it from.

The wrong approaches (which look right but don't work):
- `~/.claude/settings.json` — read by the CLI for other settings, not MCP servers
- `.claude/settings.json` (project-level) — not picked up in all Claude Code environments

The right approach:
```bash
cd /your/project
claude mcp add tacc-hpc /path/to/.venv/bin/python /path/to/server.py
```

---

## Security notes

- `~/.tacc_mcp.json` contains your TACC username and project path — treat it like any other config file. It does **not** contain passwords or tokens.
- No credentials pass through the MCP server. All auth happens via the SSH ControlMaster session you open yourself.
- `run_command` lets Claude run arbitrary shell commands on TACC login nodes. Claude Code always shows you tool calls before executing — you stay in control.

---

## Project structure

```
tacc-mcp/
├── server.py        — MCP server (20 tools, reads ~/.tacc_mcp.json)
├── setup.py         — interactive setup wizard
├── requirements.txt — Python dependencies (mcp)
└── README.md        — this file
```

---

## Adapting to other HPC systems

`server.py` uses standard POSIX `ssh`, `squeue`, and `scancel` — it works on any SLURM cluster, not just TACC. Point `tacc_host` in your config to a different machine. The only TACC-specific assumption is the default hostname in `setup.py`, which you can override during setup.

---

## Contributing

PRs welcome. The server is a single file — easy to extend. Ideas:
- `watch_job(job_id)` — poll until a job reaches a terminal state
- `submit_job(script)` — `sbatch` with output capture
- Multi-cluster config (e.g. Frontera + Lonestar6 in one server)
