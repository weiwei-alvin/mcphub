'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { GatewayController, parseStatus } = require('../src/gateway-controller');

const STATUS_RUNNING = {
  code: 0,
  stdout: 'Status: running\nRuntime PID: 448\nReadiness (/health/ready): ready\n',
  stderr: '',
  timedOut: false,
};
const STATUS_STOPPED = { code: 3, stdout: 'Status: not running\n', stderr: '', timedOut: false };
const STATUS_STARTING = { code: 4, stdout: 'Status: starting (not ready)\nPID: 100\n', stderr: '', timedOut: false };

function queueRunner(responses) {
  const calls = [];
  const run = async (entry, configDir, args) => {
    calls.push(args);
    if (responses.length === 0) throw new Error('no scripted response left for ' + args.join(' '));
    const next = responses.shift();
    return typeof next === 'function' ? next(args) : next;
  };
  run.calls = calls;
  return run;
}

function controller(run, overrides = {}) {
  return new GatewayController({
    oneMcpEntry: '/fake/1mcp.js',
    configDir: '/fake/config',
    host: '127.0.0.1',
    port: 3050,
    startTimeoutMs: 1000,
    stopTimeoutMs: 1000,
    statusTimeoutMs: 1000,
    run,
    ...overrides,
  });
}

test('parseStatus: exit 0 + ready => running', () => {
  assert.equal(parseStatus(STATUS_RUNNING).state, 'running');
  assert.equal(parseStatus(STATUS_RUNNING).pid, 448);
});

test('parseStatus: exit 3 => stopped', () => {
  assert.equal(parseStatus(STATUS_STOPPED).state, 'stopped');
});

test('parseStatus: exit 4 => starting', () => {
  assert.equal(parseStatus(STATUS_STARTING).state, 'starting');
});

test('parseStatus: exit 0 without ready readiness => starting, not running', () => {
  const result = parseStatus({ code: 0, stdout: 'Status: running\nReadiness (/health/ready): not ready\n', stderr: '' });
  assert.equal(result.state, 'starting');
});

test('status(): surfaces unknown on timeout instead of guessing', async () => {
  const run = queueRunner([{ code: null, stdout: '', stderr: '', timedOut: true }]);
  const gw = controller(run);
  const result = await gw.status();
  assert.equal(result.state, 'unknown');
});

test('start(): already running short-circuits without touching --background', async () => {
  const run = queueRunner([STATUS_RUNNING]);
  const gw = controller(run);
  const result = await gw.start();
  assert.equal(result.state, 'running');
  assert.equal(run.calls.length, 1);
  assert.deepEqual(run.calls[0], ['--status']);
});

test('start(): happy path calls --background then confirms via --status', async () => {
  const run = queueRunner([
    STATUS_STOPPED,
    { code: 0, stdout: 'Background runtime started.\nPID: 448\n', stderr: '', timedOut: false },
    STATUS_RUNNING,
  ]);
  const gw = controller(run);
  const result = await gw.start();
  assert.equal(result.state, 'running');
  assert.deepEqual(run.calls[1], ['--background', '--host', '127.0.0.1', '--port', '3050']);
});

test('start(): CLI hang (port conflict) times out, force-stops, and reports a clear error', async () => {
  const run = queueRunner([
    STATUS_STOPPED,
    { code: null, stdout: '', stderr: '', timedOut: true }, // --background hangs
    { code: 0, stdout: 'Stopped\n', stderr: '', timedOut: false }, // cleanup --stop
  ]);
  const gw = controller(run);
  const result = await gw.start();
  assert.equal(result.state, 'error');
  assert.match(result.message, /逾時/);
  assert.match(result.message, /連接埠/);
  assert.deepEqual(run.calls[2], ['--stop']);
});

test('start(): --background exits non-zero reports the real error, not a fake PASS', async () => {
  const run = queueRunner([
    STATUS_STOPPED,
    { code: 1, stdout: '', stderr: 'Error: EACCES\nbind failed\n', timedOut: false },
  ]);
  const gw = controller(run);
  const result = await gw.start();
  assert.equal(result.state, 'error');
  assert.match(result.message, /bind failed/);
});

test('start(): command reports success but status disagrees => error, never "running"', async () => {
  const run = queueRunner([
    STATUS_STOPPED,
    { code: 0, stdout: 'Background runtime started.\n', stderr: '', timedOut: false },
    STATUS_STARTING,
  ]);
  const gw = controller(run);
  const result = await gw.start();
  assert.equal(result.state, 'error');
});

test('stop(): already stopped short-circuits without touching --stop', async () => {
  const run = queueRunner([STATUS_STOPPED]);
  const gw = controller(run);
  const result = await gw.stop();
  assert.equal(result.state, 'stopped');
  assert.equal(run.calls.length, 1);
});

test('stop(): happy path calls --stop then confirms via --status', async () => {
  const run = queueRunner([
    STATUS_RUNNING,
    { code: 0, stdout: 'Stopped\n', stderr: '', timedOut: false },
    STATUS_STOPPED,
  ]);
  const gw = controller(run);
  const result = await gw.stop();
  assert.equal(result.state, 'stopped');
});

test('stop(): timeout refuses to claim stopped', async () => {
  const run = queueRunner([
    STATUS_RUNNING,
    { code: null, stdout: '', stderr: '', timedOut: true },
  ]);
  const gw = controller(run);
  const result = await gw.stop();
  assert.equal(result.state, 'error');
  assert.match(result.message, /逾時/);
});

test('stop(): process identity unconfirmed after --stop => error, not stopped', async () => {
  const run = queueRunner([
    STATUS_RUNNING,
    { code: 0, stdout: 'Stopped\n', stderr: '', timedOut: false },
    STATUS_RUNNING, // still running despite --stop claiming success
  ]);
  const gw = controller(run);
  const result = await gw.stop();
  assert.equal(result.state, 'error');
});

test('restart(): stop failure short-circuits and never calls --background', async () => {
  const run = queueRunner([
    STATUS_RUNNING,
    { code: null, stdout: '', stderr: '', timedOut: true }, // --stop hangs
  ]);
  const gw = controller(run);
  const result = await gw.restart();
  assert.equal(result.state, 'error');
  assert.equal(run.calls.length, 2);
});

test('restart(): composes stop then start end to end', async () => {
  const run = queueRunner([
    STATUS_RUNNING, // stop(): current check
    { code: 0, stdout: 'Stopped\n', stderr: '', timedOut: false }, // stop(): --stop
    STATUS_STOPPED, // stop(): confirm
    STATUS_STOPPED, // start(): current check
    { code: 0, stdout: 'Background runtime started.\n', stderr: '', timedOut: false }, // start(): --background
    STATUS_RUNNING, // start(): confirm
  ]);
  const gw = controller(run);
  const result = await gw.restart();
  assert.equal(result.state, 'running');
  assert.equal(run.calls.length, 6);
});
