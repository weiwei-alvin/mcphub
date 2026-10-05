'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const { readLog } = require('../src/log-reader');

function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mcp-hub-log-'));
  const log = path.join(root, 'gateway.log');
  return { root, log };
}

test('readLog returns a bounded redacted snapshot without changing the source', () => {
  const { root, log } = fixture();
  const original = 'INFO started\nAuthorization: Bearer real-secret\npassword=real-password\n';
  fs.writeFileSync(log, original);

  const result = readLog({ filePath: log, boundary: root, maxBytes: 1024 });

  assert.equal(result.state, 'available');
  assert.match(result.text, /INFO started/);
  assert.match(result.text, /Authorization: \[已遮蔽\]/);
  assert.doesNotMatch(result.text, /real-secret|real-password/);
  assert.equal(fs.readFileSync(log, 'utf8'), original);
  fs.rmSync(root, { recursive: true, force: true });
});

test('readLog reports missing and out-of-bound files explicitly', () => {
  const { root, log } = fixture();
  const outside = path.join(path.dirname(root), 'outside-gateway.log');
  fs.writeFileSync(outside, 'outside');

  const missing = readLog({ filePath: log, boundary: root });
  const escaped = readLog({ filePath: outside, boundary: root });

  assert.equal(missing.state, 'missing');
  assert.equal(escaped.state, 'unreadable');
  assert.match(escaped.message, /範圍|路徑/);
  fs.rmSync(root, { recursive: true, force: true });
  fs.rmSync(outside, { force: true });
});

test('readLog truncates by bytes and rejects a symlink escaping the boundary', () => {
  const { root, log } = fixture();
  const outside = path.join(path.dirname(root), 'outside-secret.log');
  const link = path.join(root, 'gateway-link.log');
  fs.writeFileSync(log, '0123456789');
  fs.writeFileSync(outside, 'do not expose');
  try {
    fs.symlinkSync(outside, link);
  } catch (error) {
    fs.rmSync(root, { recursive: true, force: true });
    fs.rmSync(outside, { force: true });
    if (error.code === 'EPERM') return;
    throw error;
  }

  const bounded = readLog({ filePath: log, boundary: root, maxBytes: 4 });
  const escaped = readLog({ filePath: link, boundary: root });

  assert.equal(bounded.state, 'available');
  assert.equal(bounded.text, '0123\n[後續內容已截斷]');
  assert.equal(escaped.state, 'unreadable');
  fs.rmSync(root, { recursive: true, force: true });
  fs.rmSync(outside, { force: true });
});
