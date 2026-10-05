'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');

const { HealthStore } = require('../src/health-store');

const reachable = { state: 'reachable', checkedAt: '2026-10-04T00:00:00.000Z', toolCount: 2 };

test('HealthStore starts each service as unchecked', () => {
  const health = new HealthStore({ probe: async () => reachable });

  assert.deepEqual(health.get('demo'), { state: 'unchecked' });
});

test('HealthStore stores a reachable result for only the checked service', async () => {
  const health = new HealthStore({ probe: async () => reachable });

  const result = await health.check('demo', { name: 'demo', disabled: false });

  assert.deepEqual(result, reachable);
  assert.deepEqual(health.get('demo'), reachable);
  assert.deepEqual(health.get('other'), { state: 'unchecked' });
});

test('HealthStore stores failed probe results without throwing', async () => {
  const failed = { state: 'failed', checkedAt: '2026-10-04T00:01:00.000Z', message: 'offline' };
  const health = new HealthStore({ probe: async () => failed });

  assert.deepEqual(await health.check('demo', { name: 'demo', disabled: false }), failed);
});

test('HealthStore reports disabled over an older successful result', async () => {
  const health = new HealthStore({ probe: async () => reachable });
  await health.check('demo', { name: 'demo', disabled: false });

  const result = await health.check('demo', { name: 'demo', disabled: true });

  assert.equal(result.state, 'disabled');
  assert.ok(result.checkedAt);
  assert.deepEqual(health.get('demo'), result);
});
