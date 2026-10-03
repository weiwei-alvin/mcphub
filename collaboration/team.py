"""Bounded OpenCode team runs. No credentials are read or stored by this script."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    "coder": "openrouter/poolside/laguna-s-2.1:free",
    "reviewer": "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",
    "tester": "openrouter/qwen/qwen3.8-27b:free",
}


def parse_events(output):
    events, invalid = [], 0
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            invalid += 1
            continue
        if not isinstance(event, dict) or ("part" in event and not isinstance(event["part"], dict)):
            invalid += 1
            continue
        events.append(event)
    texts = [e["part"]["text"] for e in events if e.get("type") == "text"
             and isinstance(e.get("part", {}).get("text"), str) and e["part"]["text"].strip()]
    errors = sum(e.get("type") == "error" for e in events)
    calls = [e.get("part", {}) for e in events if e.get("type") == "tool_use"]
    tool_errors = sum(not isinstance(p.get("state"), dict) or p["state"].get("status") != "completed" for p in calls)
    return texts, errors, [p.get("tool") for p in calls], tool_errors, invalid


def invoke(role, directory, prompt, timeout=180):
    """One fresh session per role; no automatic paid fallback or shell tools."""
    directory = directory.resolve()
    directory.relative_to(ROOT / "collaboration" / "runs")
    if not directory.is_dir() or not 1 <= timeout <= 600:
        raise ValueError("Existing run directory and timeout of 1..600 seconds required")
    exe = shutil.which("opencode")
    if not exe:
        raise RuntimeError("OpenCode executable unavailable")
    permissions = {
        "*": "deny", "read": {"*": "allow", "*.env": "deny", "*.env.*": "deny"},
        "glob": "allow", "grep": "deny",
        "external_directory": "deny", "bash": "deny", "task": "deny",
        "skill": "deny", "doom_loop": "deny",
        "edit": "deny", "write": "deny", "patch": "deny",
    }
    config = {
        "$schema": "https://opencode.ai/config.json",
        "model": MODELS[role], "small_model": MODELS[role], "share": "disabled",
        "permission": permissions,
        "mcp": {"google-workspace": {"enabled": False}, "notion": {"enabled": False}},
        "agent": {"team-worker": {
            "description": "Isolated MCP Hub collaboration trial worker",
            "mode": "primary", "model": MODELS[role], "steps": 8,
            "permission": permissions,
            "prompt": "You are a delegated read-only worker, not the session coordinator. Codex owns observer and handoff procedures. Read only the supplied non-confidential task packet. Return proposed code/tests as fenced text or a review with concrete counterexamples. Codex alone applies proposals and runs tests. Do not access external directories, secrets, services or skills. Do not run shell commands or write any file. Never claim tests were executed. Do not change tickets or declare product acceptance. If a tool is denied, stop and report the denial without retrying through other tools.",
        }},
    }
    env = os.environ.copy()
    env.update({"OPENCODE_CONFIG_CONTENT": json.dumps(config),
                "OPENCODE_DISABLE_AUTOUPDATE": "true", "OPENCODE_DISABLE_LSP_DOWNLOAD": "true",
                "OPENCODE_DISABLE_PRUNE": "true", "OPENCODE_AUTO_SHARE": "false"})
    args = [exe, "run", "--pure", "--agent", "team-worker", "--model", MODELS[role],
            "--dir", str(directory), "--format", "json", "--title", "MCP Hub team: " + role,
            "Task packet directory: " + directory.as_posix() + ". Use absolute file paths. " + prompt]
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    log = directory / (role + ".jsonl")
    errlog = directory / (role + ".stderr.txt")
    artifacts = [directory / (role + suffix) for suffix in (".jsonl", ".stderr.txt", ".report.json", ".response.md")]
    if any(p.exists() for p in artifacts):
        raise RuntimeError("Run already exists; use a fresh directory to preserve evidence")
    code, cleanup_confirmed, failure = 1, True, None
    # File handles avoid communicate() waiting forever on a launcher descendant's pipes.
    with log.open("x", encoding="utf-8") as out, errlog.open("x", encoding="utf-8") as err:
        process = None
        try:
            process = subprocess.Popen(args, cwd=directory, env=env, stdout=out, stderr=err)
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            code = 124
            cleanup_confirmed = False
            try:
                if os.name == "nt":
                    cleanup = subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
                    cleanup_confirmed = cleanup.returncode == 0
                else:
                    process.kill()
                process.wait(timeout=15)
                if os.name != "nt":
                    cleanup_confirmed = True
            except (OSError, subprocess.SubprocessError) as exc:
                failure = type(exc).__name__
        except (OSError, subprocess.SubprocessError) as exc:
            failure = type(exc).__name__
    output = log.read_text(encoding="utf-8", errors="replace")
    texts, errors, tool_calls, tool_errors, invalid = parse_events(output)
    status = "RESPONSE_RECEIVED" if code == 0 and texts and not (errors or tool_errors or invalid or failure) else "FAILED"
    if not cleanup_confirmed:
        status = "CLEANUP_FAILED"
    report = {"role": role, "model": MODELS[role], "started": started,
              "exit_code": code, "event_errors": errors, "tool_calls": tool_calls,
              "tool_errors": tool_errors, "invalid_events": invalid, "failure": failure,
              "cleanup_confirmed": cleanup_confirmed,
              "has_text": bool(texts), "status": status, "acceptance": "UNVERIFIED"}
    (directory / (role + ".report.json")).write_text(json.dumps(report, indent=2), encoding="utf-8")
    (directory / (role + ".response.md")).write_text("\n\n".join(texts), encoding="utf-8")
    print(json.dumps(report))
    return 0 if report["status"] == "RESPONSE_RECEIVED" else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=MODELS)
    parser.add_argument("--run", required=True, help="Existing isolated directory beneath collaboration/runs")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    return invoke(args.role, Path(args.run), args.prompt, args.timeout)


if __name__ == "__main__":
    sys.exit(main())
