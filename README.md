# TACC HPC MCP Server

Connect [Claude Code](https://claude.ai/claude-code) directly to your project on TACC Lonestar6.
Once set up, Claude can check job status, read log files, cancel jobs, pull code, and run commands
on TACC — without you ever leaving your editor.

```
You: "Check if my pipeline jobs are still running"
Claude: [calls job_status] → shows live squeue output

You: "The coloc step failed — show me the last 50 lines of that log"
Claude: [calls read_log(step="07_coloc", tail_lines=50)] → shows the error

You: "Cancel jobs 3210160 and 3210161"
Claude: [calls cancel_jobs("3210160 3210161")] → done
```

---

## How it works

The MCP server runs **locally on your Mac**. It connects to TACC using a persistent SSH
ControlMaster session — you authenticate once with your password and 2FA token, and every
tool call reuses that connection silently for up to 4 hours.

```
Claude Code  ──MCP──▶  server.py (local)  ──SSH ControlMaster──▶  TACC Lonestar6
```

No credentials are stored. No data goes to any third party. It's just `ssh` under the hood.

---

## Prerequisites

- **Mac or Linux** with Python 3.9+ (the setup script handles the rest)
- **TACC account** with SSH access to Lonestar6 (`ls6.tacc.utexas.edu`)
- **Claude Code** installed (`npm install -g @anthropic-ai/claude-code`)
- **Your project cloned on TACC** — the server points to a specific directory

---

## Installation

### 1. Clone this repo

```bash
git clone https://github.com/YOUR_LAB/tacc-mcp.git
cd tacc-mcp
```

### 2. Run the setup wizard

```bash
python3 setup.py
```

The wizard will ask for:
- Your TACC username and hostname (default: `ls6.tacc.utexas.edu`)
- An SSH alias (default: `tacc` — used as `ssh tacc`)
- The absolute path to your project on TACC, e.g.:
  `/work/07880/jsmith/lonestar/my-project`
- The subfolder where your pipeline writes run logs (default: `logs/runs`)

It will:
1. Add a `ControlMaster` SSH block to `~/.ssh/config`
2. Write `~/.tacc_mcp.json` (your local config — never committed to git)
3. Install `uv` (if not present) and Python 3.12 + the `mcp` package
4. Print the `.claude/settings.json` snippet you need to add

### 3. Add to your project's `.claude/settings.json`

The setup wizard prints this snippet — copy it into `.claude/settings.json` in
**your analysis project** (not this repo):

```json
{
  "mcpServers": {
    "tacc-hpc": {
      "command": "/Users/YOU/.local/bin/uv",
      "args": [
        "run",
        "--python", "3.12",
        "--with", "mcp",
        "/path/to/tacc-mcp/server.py"
      ]
    }
  }
}
```

> **Tip:** The paths in the snippet are absolute. Each lab member gets their own
> snippet pointing to wherever they cloned this repo on their Mac.

### 4. Open your daily SSH session

Before using Claude Code, open one authenticated session to TACC:

```bash
ssh tacc
# Enter: TACC password + 6-digit authenticator code
```

This session stays open for **4 hours** (configurable in `~/.ssh/config`).
You don't need to keep the terminal open — the connection is backgrounded.

### 5. Restart Claude Code

Restart Claude Code in your project directory. You should see `tacc-hpc` listed
in the MCP servers panel (bottom-left in the VS Code extension, or via `/mcp` in the CLI).

---

## Available tools

| Tool | Description |
|---|---|
| `check_connection` | Verify the SSH session is alive |
| `job_status` | Live `squeue` — all pending/running jobs |
| `pipeline_status` | Manifest × squeue cross-reference — which step is where |
| `cancel_jobs` | `scancel` by job ID(s) |
| `list_runs` | Show all pipeline run directories, newest first |
| `list_logs` | List log files in a run directory |
| `read_log` | Tail a log by step name or full path |
| `git_pull` | Pull latest code on TACC |
| `git_status` | Git status + recent commits on TACC |
| `disk_usage` | Quota + df for `$WORK` and `$SCRATCH` |
| `run_command` | Run any shell command on TACC |

### Example prompts

```
"Are my pipeline jobs still running?"
"Show me the last 100 lines of the LDSC log"
"The coloc step failed — what's the error?"
"Cancel all my pending jobs"
"Git pull on TACC then tell me what changed"
"How much disk space do I have left on scratch?"
"List all my pipeline runs"
"Run: cat /work/.../results/agent1/ldsc_rg_matrix.csv"
```

---

## Configuration reference

`~/.tacc_mcp.json` is written by `setup.py`. You can also edit it directly:

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
| `logs_subdir` | No | Log directory relative to `project_dir` (default: `logs/runs`) |

---

## Troubleshooting

### "Not connected to TACC"

Your ControlMaster session has expired or was never opened. Fix:

```bash
ssh tacc
```

### "Config file not found"

Run `setup.py` first, or manually create `~/.tacc_mcp.json` (see Configuration reference).

### MCP server doesn't appear in Claude Code

1. Check `.claude/settings.json` is in your **project** directory (not home)
2. Verify the `command` path (`uv`) and `server.py` path are correct
3. Restart Claude Code

### Test the server manually

```bash
cd tacc-mcp
~/.local/bin/uv run --python 3.12 --with mcp python3 server.py
# Should start without errors (Ctrl+C to stop)
```

### ControlMaster keeps timing out

Increase `ControlPersist` in `~/.ssh/config`:

```
Host tacc
    ControlPersist 8h   # was 4h
```

---

## Security notes

- `~/.tacc_mcp.json` contains your TACC username and project path — treat it like any
  other config file. It does **not** contain passwords or tokens.
- No credentials are passed through the MCP server. All auth happens via the SSH
  ControlMaster session you open yourself.
- `run_command` lets Claude run arbitrary commands on TACC login nodes. It will only
  do what you ask it to — Claude Code always shows you tool calls before executing.

---

## Project structure

```
tacc-mcp/
├── server.py        — MCP server (reads ~/.tacc_mcp.json)
├── setup.py         — interactive setup wizard
├── requirements.txt — Python dependencies
└── README.md        — this file
```

---

## Adapting to other HPC systems

`server.py` only uses standard `ssh` and `squeue`/`scancel` — it works on any
SLURM cluster, not just TACC. Change `tacc_host` in your config to point at a
different machine. The only TACC-specific assumption is `ls6.tacc.utexas.edu` as
the default hostname in `setup.py`, which you can override.

---

## Contributing

PRs welcome. Useful additions:
- `submit_job` — submit a specific SLURM script
- `tail_live` — stream a log file in real time
- Support for multiple HPC systems in one config
