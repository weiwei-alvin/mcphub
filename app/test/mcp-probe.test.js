'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const { probeService } = require('../src/mcp-probe');

const SERVICE = { name: 'demo', type: 'stdio', command: process.execPath, args: [] };

function scriptedProbe({ connect, listTools }) {
  const events = [];
  const transport = {
    close: async () => { events.push('transport.close'); },
  };
  class FakeClient {
    async connect(value) {
      assert.equal(value, transport);
      events.push('connect');
      return connect?.();
    }

    async listTools() {
      events.push('listTools');
      return listTools?.();
    }

    async close() {
      events.push('client.close');
    }
  }
  return { events, transportFactory: () => transport, ClientClass: FakeClient };
}

test('probeService reports reachable only after initialize and tools/list succeed', async () => {
  const scripted = scriptedProbe({ listTools: async () => ({ tools: [{ name: 'demo_tool' }] }) });

  const result = await probeService(SERVICE, { ...scripted, timeoutMs: 100 });

  assert.equal(result.state, 'reachable');
  assert.equal(result.toolCount, 1);
  assert.match(result.checkedAt, /Z$/);
  assert.deepEqual(scripted.events, ['connect', 'listTools', 'client.close', 'transport.close']);
});

test('probeService reports initialize failure and still closes the transport', async () => {
  const scripted = scriptedProbe({ connect: async () => { throw new Error('handshake failed'); } });

  const result = await probeService(SERVICE, { ...scripted, timeoutMs: 100 });

  assert.equal(result.state, 'failed');
  assert.match(result.message, /handshake failed/);
  assert.deepEqual(scripted.events, ['connect', 'client.close', 'transport.close']);
});

test('probeService reports tools/list failure and does not claim health', async () => {
  const scripted = scriptedProbe({ listTools: async () => { throw new Error('list failed'); } });

  const result = await probeService(SERVICE, { ...scripted, timeoutMs: 100 });

  assert.equal(result.state, 'failed');
  assert.match(result.message, /list failed/);
  assert.deepEqual(scripted.events, ['connect', 'listTools', 'client.close', 'transport.close']);
});

test('probeService bounds a hanging initialize and still closes resources', async () => {
  const scripted = scriptedProbe({ connect: () => new Promise(() => {}) });

  const result = await probeService(SERVICE, { ...scripted, timeoutMs: 20 });

  assert.equal(result.state, 'failed');
  assert.match(result.message, /逾時/);
  assert.deepEqual(scripted.events, ['connect', 'client.close', 'transport.close']);
});
