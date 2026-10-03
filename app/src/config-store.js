'use strict';

const fs = require('node:fs');
const path = require('node:path');

/**
 * Three distinct versions of the configuration, per SPEC "Implementation
 * Decisions": the draft the user is editing, the effective version the Gateway
 * is running, and the last version known to have started successfully. They are
 * kept in separate files so a failure can never leave the interface describing
 * a version that is not actually running.
 *
 *   <configDir>/mcp.json        effective  - read by the Gateway process
 *   <configDir>/hub-draft.json  draft      - the user's unapplied edits
 *   <configDir>/hub-last-good.json          - recoverable predecessor
 *
 * last-good is only ever written after a successful apply, so its absence means
 * "no version has ever started successfully", which is exactly the state US-08
 * requires us to report as "nothing to recover to" rather than inventing a
 * backup.
 */

const TRANSPORTS = ['stdio', 'http'];

// Credential-bearing fields are refused outright (PLAN-6, and US-02's rule that
// V1 accepts no secrets). Rejecting the key is what stops the UI from becoming
// a place to store them, and it keeps anything the Gateway logs out of scope.
const SECRET_KEYS = ['env', 'headers', 'header', 'token', 'apiKey', 'api_key', 'password', 'secret', 'authorization'];

class ValidationError extends Error {
  constructor(field, message) {
    super(message);
    this.name = 'ValidationError';
    this.field = field;
  }
}

function isPlainObject(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

// Deliberately narrower than the Gateway's own tolerance: a service name ends up
// as a JSON key and as a tool-name prefix, so anything that could collide with
// the Gateway's naming or escape a path is refused up front.
const NAME_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;

function validateUrl(value) {
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new ValidationError('url', '服務 URL 格式不正確');
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new ValidationError('url', '服務 URL 只支援 http 或 https');
  }
  if (parsed.username || parsed.password) {
    throw new ValidationError('url', '服務 URL 不得包含帳號或密碼');
  }
  if (parsed.search || parsed.hash) {
    throw new ValidationError('url', '服務 URL 不得包含查詢參數或片段');
  }
  return parsed;
}

function transportOf(transport) {
  // On disk the Gateway spells the Streamable HTTP transport "streamableHttp",
  // while the UI offers the shorter "http". Accept both so the same validator
  // serves form input and stored config.
  if (transport === 'streamableHttp') return 'http';
  return transport;
}

function validateService(input, existingNames = new Set()) {
  if (!isPlainObject(input)) throw new ValidationError('form', '服務資料格式不正確');
  for (const key of Object.keys(input)) {
    if (SECRET_KEYS.some((s) => s.toLowerCase() === key.toLowerCase())) {
      throw new ValidationError(key, `不支援 ${key}：第一版不接受憑證或秘密欄位`);
    }
  }

  const name = typeof input.name === 'string' ? input.name.trim() : '';
  if (!name) throw new ValidationError('name', '服務名稱不可空白');
  if (!NAME_PATTERN.test(name)) {
    throw new ValidationError('name', '服務名稱只可使用英數字、點、底線與連字號，且須以英數字開頭');
  }
  if (existingNames.has(name)) throw new ValidationError('name', `服務名稱 ${name} 已存在`);

  const transport = transportOf(input.transport !== undefined ? input.transport : input.type);
  if (!TRANSPORTS.includes(transport)) {
    throw new ValidationError('transport', '傳輸類型只支援 stdio 或 http');
  }

  const service = { name, transport, disabled: false };

  if (transport === 'stdio') {
    const command = typeof input.command === 'string' ? input.command.trim() : '';
    if (!command) throw new ValidationError('command', '啟動命令不可空白');
    let args;
    if (Array.isArray(input.args)) {
      args = input.args;
    } else if (typeof input.args === 'string' && input.args.trim()) {
      try {
        args = JSON.parse(input.args);
      } catch {
        throw new ValidationError('args', '命令參數必須是 JSON 陣列，例如 ["stdio"]');
      }
    } else {
      args = [];
    }
    if (!Array.isArray(args) || args.some((a) => typeof a !== 'string')) {
      throw new ValidationError('args', '命令參數必須是字串組成的 JSON 陣列');
    }
    // type is what the Gateway reads to pick the transport; the UI label is
    // "http" but the on-disk value has to be the Gateway's own spelling.
    service.type = 'stdio';
    service.command = command;
    service.args = args;
  } else {
    const url = typeof input.url === 'string' ? input.url.trim() : '';
    if (!url) throw new ValidationError('url', '服務 URL 不可空白');
    service.type = 'streamableHttp';
    service.url = validateUrl(url).toString();
  }

  return service;
}

class ConfigStore {
  constructor({ configDir, readFile = fs.readFileSync, writeFile = fs.writeFileSync, rename = fs.renameSync, exists = fs.existsSync }) {
    if (!configDir) throw new Error('configDir is required');
    this.dir = configDir;
    this.effectivePath = path.join(configDir, 'mcp.json');
    this.draftPath = path.join(configDir, 'hub-draft.json');
    this.lastGoodPath = path.join(configDir, 'hub-last-good.json');
    this._readFile = readFile;
    this._writeFile = writeFile;
    this._rename = rename;
    this._exists = exists;
  }

  _readJson(file) {
    if (!this._exists(file)) return null;
    const text = this._readFile(file, 'utf8');
    try {
      const data = JSON.parse(text);
      return isPlainObject(data) ? data : null;
    } catch {
      return null;
    }
  }

  // A temporary file plus rename, so a crash mid-write cannot leave the Gateway
  // reading a truncated config.
  _writeJson(file, data) {
    const tmp = `${file}.tmp`;
    this._writeFile(tmp, `${JSON.stringify(data, null, 2)}\n`, 'utf8');
    this._rename(tmp, file);
  }

  effective() {
    return this._readJson(this.effectivePath) || { mcpServers: {} };
  }

  draft() {
    const saved = this._readJson(this.draftPath);
    if (saved) return saved;
    return this.effective();
  }

  hasDraftChanges() {
    return JSON.stringify(this.draft()) !== JSON.stringify(this.effective());
  }

  hasLastGood() {
    return this._readJson(this.lastGoodPath) !== null;
  }

  list() {
    const servers = this.draft().mcpServers || {};
    return Object.entries(servers).map(([name, service]) => ({ name, ...service }));
  }

  addService(input) {
    const draft = this.draft();
    const servers = { ...(draft.mcpServers || {}) };
    const service = validateService(input, new Set(Object.keys(servers)));
    servers[service.name] = service;
    const next = { ...draft, mcpServers: servers };
    this._writeJson(this.draftPath, next);
    return service;
  }

  // Every stored service is re-validated, not just the one being added, so a
  // hand-edited mcp.json cannot smuggle an invalid or credential-bearing entry
  // into the effective config through the apply path.
  validateDraft() {
    const draft = this.draft();
    const servers = draft.mcpServers || {};
    if (!isPlainObject(servers)) {
      return { valid: false, field: 'form', message: '設定格式不正確' };
    }
    const seen = new Set();
    for (const [name, service] of Object.entries(servers)) {
      // The duplicate-name check is skipped here on purpose: this pass validates
      // what is already stored, and JSON object keys are unique by
      // construction, so seeding `seen` with the key would report every service
      // as a duplicate of itself.
      try {
        validateService({ ...service, name: service.name || name }, new Set());
      } catch (error) {
        if (error instanceof ValidationError) {
          return { valid: false, field: name, message: `服務 ${name}：${error.message}` };
        }
        return { valid: false, field: 'form', message: `服務 ${name}：設定無法驗證` };
      }
      seen.add(name);
    }
    return { valid: true };
  }

  /**
   * Validate, then commit, then restart. On a failed restart the previous
   * effective config is written back and the Gateway restarted again; the
   * returned outcome distinguishes recovered / unrecoverable / nothing-to-recover
   * so the UI never reports a plain success for either failure mode (US-08).
   */
  async apply({ restart }) {
    const validation = this.validateDraft();
    if (!validation.valid) {
      return {
        state: 'error',
        stage: 'validation',
        field: validation.field,
        message: validation.message,
      };
    }

    // Recovery target is last-good, never "whatever was effective before": the
    // effective file may itself be a version that never started (an earlier
    // failed apply, a hand edit), and restoring it would report a recovery that
    // did not happen.
    const lastGood = this._readJson(this.lastGoodPath);
    const canRecover = lastGood !== null;
    this._writeJson(this.effectivePath, this.draft());

    const after = await restart();
    if (after.state === 'running') {
      this._writeJson(this.lastGoodPath, this.draft());
      return { state: 'applied', message: '設定已套用，Gateway 已重新啟動' };
    }

    const failure = `新設定套用後 Gateway 未能啟動：${after.message || after.state}`;

    if (!canRecover) {
      return {
        state: 'error',
        stage: 'apply',
        recovered: false,
        recoverable: false,
        message: `${failure}。沒有可恢復的上一份設定（尚無曾成功啟動的版本），Gateway 目前無法使用`,
      };
    }

    this._writeJson(this.effectivePath, lastGood);
    const recovered = await restart();
    if (recovered.state === 'running') {
      return {
        state: 'error',
        stage: 'recovery',
        recovered: true,
        message: `${failure}。已回復上一份可用設定，Gateway 目前使用的是舊設定，不是剛才的新設定`,
      };
    }

    return {
      state: 'error',
      stage: 'recovery',
      recovered: false,
      message: `${failure}。回復上一份設定也失敗：${recovered.message || recovered.state}。服務目前無法使用`,
    };
  }
}

module.exports = { ConfigStore, ValidationError, validateService, validateUrl, TRANSPORTS, SECRET_KEYS };
