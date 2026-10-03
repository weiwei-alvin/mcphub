'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

function env(name, fallback) {
  const value = process.env[name];
  return value === undefined || value === '' ? fallback : value;
}

// No required setup step: a fresh local install gets a working (empty) gateway
// config the first time the app runs, so "single entry, no terminal typing" (T-002
// AC-1) holds even before any MCP server has been added (T-003).
function ensureGatewayConfigDir(dir) {
  fs.mkdirSync(dir, { recursive: true });
  const mcpJsonPath = path.join(dir, 'mcp.json');
  if (!fs.existsSync(mcpJsonPath)) {
    fs.writeFileSync(mcpJsonPath, JSON.stringify({ mcpServers: {} }, null, 2));
  }
  return dir;
}

function loadConfig() {
  const defaultConfigDir = path.join(os.homedir(), '.mcp-hub', 'gateway-config');
  const configDir = path.resolve(env('GATEWAY_CONFIG_DIR', defaultConfigDir));
  ensureGatewayConfigDir(configDir);
  return {
    hub: {
      host: '127.0.0.1', // admin page is local-only by design; never configurable to 0.0.0.0
      port: Number(env('HUB_PORT', 3100)),
    },
    gateway: {
      host: env('GATEWAY_HOST', '127.0.0.1'),
      port: Number(env('GATEWAY_PORT', 3050)),
      configDir: path.resolve(configDir),
      oneMcpEntry: require.resolve('@1mcp/agent/build/index.js'),
      startTimeoutMs: Number(env('GATEWAY_START_TIMEOUT_MS', 30_000)),
      stopTimeoutMs: Number(env('GATEWAY_STOP_TIMEOUT_MS', 15_000)),
    },
  };
}

module.exports = { loadConfig };
