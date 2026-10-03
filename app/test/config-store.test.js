'use strict';

const assert = require('node:assert/strict');
const path = require('node:path');
const { describe, it } = require('node:test');

const { ConfigStore, ValidationError, validateService } = require('../src/config-store');

const DIR = 'C:/hub';
// path.join, not a literal: on Windows the store builds backslash paths, and a
// hardcoded 'C:/hub/mcp.json' key would never match, silently making every
// fixture read as "file absent".
const effectivePath = path.join(DIR, 'mcp.json');
const draftPath = path.join(DIR, 'hub-draft.json');
const lastGoodPath = path.join(DIR, 'hub-last-good.json');

function fakeFs(initial = {}) {
  const files = { ...initial };
  const writes = [];
  return {
    files,
    writes,
    readFile: (p) => {
      if (!(p in files)) throw Object.assign(new Error('ENOENT'), { code: 'ENOENT' });
      return files[p];
    },
    writeFile: (p, text) => { files[p] = text; writes.push({ path: p, text }); },
    rename: (from, to) => {
      files[to] = files[from];
      delete files[from];
    },
    exists: (p) => p in files,
  };
}

function makeStore(fs, dir = DIR) {
  return new ConfigStore({
    configDir: dir,
    readFile: fs.readFile,
    writeFile: fs.writeFile,
    rename: fs.rename,
    exists: fs.exists,
  });
}

const STDIO = { name: 'demo-stdio', transport: 'stdio', command: 'node', args: '["stdio"]' };
const HTTP = { name: 'demo-http', transport: 'http', url: 'http://127.0.0.1:3051/mcp' };

const running = { state: 'running' };
const failed = (m) => ({ state: 'error', message: m });

describe('validateService', () => {
  it('accepts a stdio service and stores the Gateway spelling', () => {
    const service = validateService(STDIO);
    assert.equal(service.type, 'stdio');
    assert.deepEqual(service.args, ['stdio']);
  });

  it('accepts a streamable HTTP service and stores type streamableHttp', () => {
    const service = validateService(HTTP);
    assert.equal(service.type, 'streamableHttp');
    assert.equal(service.url, 'http://127.0.0.1:3051/mcp');
  });

  it('rejects a blank name', () => {
    assert.throws(() => validateService({ ...STDIO, name: '  ' }), ValidationError);
  });

  it('rejects a name that could escape a path or collide with tool naming', () => {
    for (const bad of ['../evil', 'a/b', 'has space', '-leading', '']) {
      assert.throws(() => validateService({ ...STDIO, name: bad }), ValidationError, `expected reject: ${bad}`);
    }
  });

  it('rejects a duplicate name', () => {
    assert.throws(() => validateService(STDIO, new Set(['demo-stdio'])), ValidationError);
  });

  it('rejects non-JSON command arguments', () => {
    assert.throws(() => validateService({ ...STDIO, args: 'stdio' }), ValidationError);
  });

  it('rejects a URL carrying credentials, a query or a fragment', () => {
    for (const url of ['http://user:pw@127.0.0.1:3051/mcp', 'http://127.0.0.1:3051/mcp?token=x', 'http://127.0.0.1:3051/mcp#f']) {
      assert.throws(() => validateService({ ...HTTP, url }), ValidationError, `expected reject: ${url}`);
    }
  });

  it('rejects a non-HTTP scheme', () => {
    assert.throws(() => validateService({ ...HTTP, url: 'file:///etc/passwd' }), ValidationError);
  });

  it('refuses credential-bearing fields outright (V1 takes no secrets)', () => {
    for (const key of ['env', 'headers', 'apiKey', 'password', 'token']) {
      assert.throws(() => validateService({ ...STDIO, [key]: 'x' }), ValidationError, `expected reject: ${key}`);
    }
  });

  it('rejects a missing command for stdio and a missing URL for http', () => {
    assert.throws(() => validateService({ ...STDIO, command: '  ' }), ValidationError);
    assert.throws(() => validateService({ ...HTTP, url: '' }), ValidationError);
  });
});

describe('ConfigStore draft handling', () => {
  it('addService writes only the draft and leaves the effective config untouched', () => {
    const fs = fakeFs({ [effectivePath]: JSON.stringify({ mcpServers: {} }) });
    const store = makeStore(fs);
    store.addService(STDIO);
    assert.equal(JSON.parse(fs.files[draftPath]).mcpServers['demo-stdio'].type, 'stdio');
    assert.equal(JSON.parse(fs.files[effectivePath]).mcpServers['demo-stdio'], undefined);
  });

  it('a second add accumulates rather than replacing the first', () => {
    const fs = fakeFs({ [effectivePath]: JSON.stringify({ mcpServers: {} }) });
    const store = makeStore(fs);
    store.addService(STDIO);
    store.addService(HTTP);
    assert.deepEqual(Object.keys(JSON.parse(fs.files[draftPath]).mcpServers), ['demo-stdio', 'demo-http']);
  });

  it('an invalid add leaves the draft byte-identical', () => {
    const fs = fakeFs({ [effectivePath]: JSON.stringify({ mcpServers: {} }) });
    const store = makeStore(fs);
    store.addService(STDIO);
    const before = fs.files[draftPath];
    assert.throws(() => store.addService({ ...HTTP, url: 'not-a-url' }), ValidationError);
    assert.equal(fs.files[draftPath], before);
  });

  it('reports pending changes only while the draft differs from the effective config', () => {
    const fs = fakeFs({ [effectivePath]: JSON.stringify({ mcpServers: {} }) });
    const store = makeStore(fs);
    assert.equal(store.hasDraftChanges(), false);
    store.addService(STDIO);
    assert.equal(store.hasDraftChanges(), true);
  });

  it('reads the effective config when no draft file exists yet', () => {
    const fs = fakeFs({ [effectivePath]: JSON.stringify({ mcpServers: { pre: { type: 'stdio' } } }) });
    const store = makeStore(fs);
    assert.deepEqual(store.list().map((s) => s.name), ['pre']);
  });
});

describe('ConfigStore.apply', () => {
  async function storeWithDraft(restarts) {
    const fs = fakeFs({ [effectivePath]: JSON.stringify({ mcpServers: {} }) });
    const store = makeStore(fs);
    store.addService(STDIO);
    return { fs, store, restarts };
  }

  it('a successful apply commits, restarts once, and records the version as recoverable', async () => {
    const calls = [];
    const { fs, store } = await storeWithDraft();
    const outcome = await store.apply({ restart: async () => { calls.push('restart'); return running; } });
    assert.equal(outcome.state, 'applied');
    assert.deepEqual(calls, ['restart']);
    assert.equal(JSON.parse(fs.files[effectivePath]).mcpServers['demo-stdio'].type, 'stdio');
    assert.equal(JSON.parse(fs.files[lastGoodPath]).mcpServers['demo-stdio'].type, 'stdio');
    assert.equal(store.hasLastGood(), true);
  });

  it('a failed restart with nothing to recover reports unrecoverable, not success', async () => {
    const { fs, store } = await storeWithDraft();
    const outcome = await store.apply({ restart: async () => failed('port busy') });
    assert.equal(outcome.state, 'error');
    assert.equal(outcome.recovered, false);
assert.equal(outcome.recoverable, false);
    assert.ok(outcome.message.includes('沒有可恢復的上一份設定'), outcome.message);
    assert.equal(store.hasLastGood(), false);
  });

  it('a failed restart with a recoverable predecessor restores it and says so plainly', async () => {
    const fs = fakeFs({
      [effectivePath]: JSON.stringify({ mcpServers: { 'old-good': { type: 'stdio', command: 'node', args: [] } } }),
      [lastGoodPath]: JSON.stringify({ mcpServers: { 'old-good': { type: 'stdio', command: 'node', args: [] } } }),
    });
    const store = makeStore(fs);
    store.addService(STDIO);
    const states = [failed('bad config'), running];
    const outcome = await store.apply({ restart: async () => states.shift() });
    assert.equal(outcome.state, 'error');
    assert.equal(outcome.recovered, true);
    assert.ok(outcome.message.includes('已回復上一份可用設定'), outcome.message);
    // The new service must be gone from the effective config after recovery.
    assert.equal(JSON.parse(fs.files[effectivePath]).mcpServers['demo-stdio'], undefined);
    assert.ok(JSON.parse(fs.files[effectivePath]).mcpServers['old-good']);
  });

  it('a failed restart AND a failed recovery reports the service as unavailable with both failures', async () => {
    const fs = fakeFs({
      [effectivePath]: JSON.stringify({ mcpServers: { 'old-good': { type: 'stdio', command: 'node', args: [] } } }),
      [lastGoodPath]: JSON.stringify({ mcpServers: { 'old-good': { type: 'stdio', command: 'node', args: [] } } }),
    });
    const store = makeStore(fs);
    store.addService(STDIO);
    const states = [failed('new config broken'), failed('old config also broken')];
    const outcome = await store.apply({ restart: async () => states.shift() });
    assert.equal(outcome.state, 'error');
    assert.equal(outcome.recovered, false);
    assert.ok(outcome.message.includes('服務目前無法使用'), outcome.message);
    assert.match(outcome.message, /new config broken/);
    assert.match(outcome.message, /old config also broken/);
  });

  it('validation failure short-circuits: no write, no restart, effective config intact', async () => {
    const fs = fakeFs({
      [effectivePath]: JSON.stringify({ mcpServers: { 'old-good': { type: 'stdio', command: 'node', args: [] } } }),
    });
    const store = makeStore(fs);
    // Bypass addService to plant an invalid entry, as a hand-edited file would.
    fs.files[draftPath] = JSON.stringify({
      mcpServers: { broken: { type: 'streamableHttp', url: 'file:///etc/passwd' } },
    });
    let restarted = false;
    const outcome = await store.apply({ restart: async () => { restarted = true; return running; } });
    assert.equal(outcome.state, 'error');
    assert.equal(outcome.stage, 'validation');
    assert.equal(restarted, false, 'an invalid config must never reach the Gateway');
    assert.equal(fs.files[effectivePath], JSON.stringify({ mcpServers: { 'old-good': { type: 'stdio', command: 'node', args: [] } } }));
  });

  it('validates stored services too, so a hand-edited credential field blocks the apply', async () => {
    const fs = fakeFs({ [effectivePath]: JSON.stringify({ mcpServers: {} }) });
    fs.files[draftPath] = JSON.stringify({
      mcpServers: { sneaky: { type: 'stdio', command: 'node', args: [], env: { TOKEN: 'x' } } },
    });
    const store = makeStore(fs);
    const outcome = await store.apply({ restart: async () => running });
    assert.equal(outcome.stage, 'validation');
    assert.ok(outcome.message.includes('憑證或秘密欄位'), outcome.message);
  });
});
