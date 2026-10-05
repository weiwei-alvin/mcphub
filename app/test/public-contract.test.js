'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const publicDir = path.join(__dirname, '..', 'public');
const html = fs.readFileSync(path.join(publicDir, 'index.html'), 'utf8');
const appJs = fs.readFileSync(path.join(publicDir, 'app.js'), 'utf8');

test('service UI exposes lifecycle actions and draft mutation endpoints', () => {
  assert.match(html, /已設定的 MCP Server/);
  assert.match(appJs, /編輯/);
  assert.match(appJs, /停用/);
  assert.match(appJs, /啟用/);
  assert.match(appJs, /['"]PATCH['"]/);
  assert.match(appJs, /['"]DELETE['"]/);
  assert.match(appJs, /api\/services\//);
});

test('service UI exposes per-service health and timestamp contract', () => {
  assert.match(html, /連線狀態/);
  assert.match(appJs, /測試連線/);
  assert.match(appJs, /可連線/);
  assert.match(appJs, /連線失敗/);
  assert.match(appJs, /time/);
  assert.match(appJs, /\/check/);
});

test('service UI exposes a read-only log panel contract', () => {
  assert.match(html, /查看日誌/);
  assert.match(appJs, /role/);
  assert.match(appJs, /\/api\/gateway\/logs/);
});
