'use strict';

const { probeService } = require('./mcp-probe');

class HealthStore {
  constructor({ probe = probeService } = {}) {
    this._probe = probe;
    this._results = new Map();
  }

  get(name, service) {
    const previous = this._results.get(name);
    if (service?.disabled === true) {
      return {
        state: 'disabled',
        checkedAt: previous?.checkedAt || new Date().toISOString(),
        message: '服務已停用',
      };
    }
    return previous || { state: 'unchecked' };
  }

  async check(name, service) {
    if (service.disabled === true) {
      const result = { state: 'disabled', checkedAt: new Date().toISOString(), message: '服務已停用' };
      this._results.set(name, result);
      return result;
    }
    let result;
    try {
      result = await this._probe(service);
    } catch (error) {
      result = {
        state: 'failed',
        checkedAt: new Date().toISOString(),
        message: error instanceof Error ? error.message : String(error),
      };
    }
    this._results.set(name, result);
    return result;
  }

  forget(name) {
    this._results.delete(name);
  }
}

module.exports = { HealthStore };
