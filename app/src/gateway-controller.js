'use strict';

const { spawn } = require('node:child_process');

/**
 * Shells out to the 1mcp CLI's own supervisor (--background/--stop/--status),
 * which already owns PID-file identity and readiness probing. This wrapper's
 * only job is the part the CLI does not do itself: impose a hard deadline,
 * because --background/--restart block forever (no error, no exit) when the
 * target port is already taken by something else (verified against the real
 * binary: a stuck "runtime starting..." loop past 100s with no EADDRINUSE
 * ever surfacing to the CLI's exit code).
 */
function runOneMcp(entry, configDir, args, { timeoutMs } = {}) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [entry, '--config-dir', configDir, ...args], {
      windowsHide: true,
    });
    let stdout = '';
    let stderr = '';
    let timedOut = false;
    const timer = timeoutMs
      ? setTimeout(() => {
          timedOut = true;
          child.kill();
        }, timeoutMs)
      : null;
    child.stdout.on('data', (chunk) => { stdout += chunk; });
    child.stderr.on('data', (chunk) => { stderr += chunk; });
    child.on('close', (code) => {
      if (timer) clearTimeout(timer);
      resolve({ code, stdout, stderr, timedOut });
    });
    child.on('error', (err) => {
      if (timer) clearTimeout(timer);
      resolve({ code: null, stdout, stderr: String(err), timedOut: false });
    });
  });
}

// Exit codes observed from the real @1mcp/agent 0.38.2 CLI (--status):
// 0 = running (readiness line distinguishes ready vs transiently not-ready),
// 3 = not running, 4 = starting / not ready yet.
function parseStatus({ code, stdout, stderr }) {
  const text = stdout + stderr;
  const pidMatch = /Runtime PID:\s*(\d+)/.exec(text) || /PID:\s*(\d+)/.exec(text);
  const pid = pidMatch ? Number(pidMatch[1]) : null;

  if (code === 3) return { state: 'stopped', pid: null, detail: text };
  if (code === 4) return { state: 'starting', pid, detail: text };
  if (code === 0) {
    const ready = /Readiness \(\/health\/ready\):\s*ready/.test(text);
    return { state: ready ? 'running' : 'starting', pid, detail: text };
  }
  return { state: 'unknown', pid, detail: text };
}

function lastLine(text) {
  return (text || '').trim().split('\n').filter(Boolean).pop() || '未知錯誤';
}

class GatewayController {
  constructor({
    oneMcpEntry,
    configDir,
    host,
    port,
    startTimeoutMs = 30_000,
    stopTimeoutMs = 15_000,
    statusTimeoutMs = 15_000, // observed: first spawn after a fresh npm install can take ~10s (AV scan on new files)
    run = runOneMcp,
  }) {
    if (!oneMcpEntry) throw new Error('oneMcpEntry is required');
    if (!configDir) throw new Error('configDir is required');
    if (!host || !port) throw new Error('host and port are required');
    this.entry = oneMcpEntry;
    this.configDir = configDir;
    this.host = host;
    this.port = port;
    this.startTimeoutMs = startTimeoutMs;
    this.stopTimeoutMs = stopTimeoutMs;
    this.statusTimeoutMs = statusTimeoutMs;
    this._run = run;
  }

  async status() {
    const result = await this._run(this.entry, this.configDir, ['--status'], { timeoutMs: this.statusTimeoutMs });
    if (result.timedOut) return { state: 'unknown', pid: null, detail: '狀態查詢逾時' };
    return parseStatus(result);
  }

  async start() {
    const current = await this.status();
    if (current.state === 'running') return current;

    const result = await this._run(
      this.entry,
      this.configDir,
      ['--background', '--host', this.host, '--port', String(this.port)],
      { timeoutMs: this.startTimeoutMs },
    );

    if (result.timedOut) {
      // The CLI call is stuck; don't leave a half-started supervisor behind.
      await this._run(this.entry, this.configDir, ['--stop'], { timeoutMs: this.stopTimeoutMs });
      return {
        state: 'error',
        message: `啟動逾時（超過 ${Math.round(this.startTimeoutMs / 1000)} 秒）：連接埠 ${this.port} 可能已被其他程序占用，或 Gateway 無回應`,
      };
    }
    if (result.code !== 0) {
      return { state: 'error', message: '啟動失敗：' + lastLine(result.stderr || result.stdout) };
    }
    // Deliberately re-check via --status (the /health/ready probe) rather than
    // trusting --background's own "Servers: X/Y ready" stdout tally: that tally
    // did not track the two real downstream connections in manual testing
    // (printed 0/0 with both configured and actually serving), so treating it
    // as a readiness signal would risk reporting "running" before tools are
    // truly callable.
    const after = await this.status();
    if (after.state !== 'running') {
      return { state: 'error', message: '啟動指令已送出，但狀態未確認為運作中，請檢查日誌後再試' };
    }
    return after;
  }

  async stop() {
    const current = await this.status();
    if (current.state === 'stopped') return current;

    const result = await this._run(this.entry, this.configDir, ['--stop'], { timeoutMs: this.stopTimeoutMs });
    if (result.timedOut) {
      return {
        state: 'error',
        message: `停止逾時（超過 ${Math.round(this.stopTimeoutMs / 1000)} 秒），未能確認是否已停止，不回報已停止`,
      };
    }
    const after = await this.status();
    if (after.state !== 'stopped') {
      return { state: 'error', message: '停止指令已送出，但偵測到程序仍在運作，請人工確認後再試' };
    }
    return after;
  }

  async restart() {
    const stopped = await this.stop();
    if (stopped.state === 'error') return stopped;
    return this.start();
  }
}

module.exports = { GatewayController, parseStatus, runOneMcp };
