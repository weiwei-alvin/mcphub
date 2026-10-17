'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const { buildServer } = require('../src/server');
const { ConfigStore } = require('../src/config-store');

function setup({ health } = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mcp-hub-server-'));
  fs.writeFileSync(path.join(dir, 'mcp.json'), JSON.stringify({ mcpServers: {} }));
  const store = new ConfigStore({ configDir: dir });
  store.addService({ name: 'demo', transport: 'stdio', command: process.execPath, args: [] });
  const app = buildServer({
    gateway: {
      configDir: dir,
      oneMcpEntry: process.execPath,
      host: '127.0.0.1',
      port: 3050,
    },
  }, { store, health });
  return { dir, app };
}

test('PATCH service disable updates draft and preserves the service row', async (t) => {
  const { dir, app } = setup();
  t.after(async () => {
    await app.close();
    fs.rmSync(dir, { recursive: true, force: true });
  });

  const response = await app.inject({
    method: 'PATCH',
    url: '/api/services/demo',
    payload: { disabled: true },
  });

  assert.equal(response.statusCode, 200);
  const body = response.json();
  assert.equal(body.service.disabled, true);
  assert.equal(body.services[0].name, 'demo');
});

test('DELETE service removes only the draft row until apply', async (t) => {
  const { dir, app } = setup();
  fs.writeFileSync(path.join(dir, 'mcp.json'), JSON.stringify({
    mcpServers: { demo: { type: 'stdio', command: process.execPath, args: [] } },
  }));
  t.after(async () => {
    await app.close();
    fs.rmSync(dir, { recursive: true, force: true });
  });

  const response = await app.inject({ method: 'DELETE', url: '/api/services/demo' });

  assert.equal(response.statusCode, 200);
  assert.deepEqual(response.json().services, []);
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(dir, 'mcp.json'))).mcpServers.demo.command, process.execPath);
});

test('PATCH and DELETE unknown services return a validation error', async (t) => {
  const { dir, app } = setup();
  t.after(async () => {
    await app.close();
    fs.rmSync(dir, { recursive: true, force: true });
  });

  const patch = await app.inject({ method: 'PATCH', url: '/api/services/missing', payload: { disabled: true } });
  const deletion = await app.inject({ method: 'DELETE', url: '/api/services/missing' });

  assert.equal(patch.statusCode, 400);
  assert.equal(deletion.statusCode, 400);
  assert.equal(patch.json().error, 'validation');
  assert.equal(deletion.json().error, 'validation');
});

test('service listing and check route expose per-service health', async (t) => {
  const checked = { state: 'reachable', checkedAt: '2026-10-04T00:00:00.000Z', toolCount: 1 };
  const health = {
    get: () => ({ state: 'unchecked' }),
    check: async () => checked,
    forget: () => {},
  };
  const { dir, app } = setup({ health });
  t.after(async () => {
    await app.close();
    fs.rmSync(dir, { recursive: true, force: true });
  });

  const before = await app.inject({ method: 'GET', url: '/api/services' });
  const check = await app.inject({ method: 'POST', url: '/api/services/demo/check' });

  assert.deepEqual(before.json().services[0].health, { state: 'unchecked' });
  assert.equal(check.statusCode, 200);
  assert.deepEqual(check.json().health, checked);
});

test('Gateway log route returns a read-only bounded snapshot', async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mcp-hub-log-route-'));
  const logFile = path.join(dir, 'gateway.log');
  fs.writeFileSync(logFile, 'known-diagnostic-event\n');
  const store = new ConfigStore({ configDir: dir });
  const app = buildServer({
    gateway: {
      configDir: dir,
      logFile,
      oneMcpEntry: process.execPath,
      host: '127.0.0.1',
      port: 3050,
    },
  }, { store });
  t.after(async () => {
    await app.close();
    fs.rmSync(dir, { recursive: true, force: true });
  });

  const response = await app.inject({ method: 'GET', url: '/api/gateway/logs' });

  assert.equal(response.statusCode, 200);
  assert.equal(response.json().state, 'available');
  assert.match(response.json().text, /known-diagnostic-event/);
});
