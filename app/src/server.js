'use strict';

const path = require('node:path');
const Fastify = require('fastify');
const fastifyStatic = require('@fastify/static');
const { loadConfig } = require('./config');
const { GatewayController } = require('./gateway-controller');
const { ConfigStore, ValidationError } = require('./config-store');
const { HealthStore } = require('./health-store');
const { readLog } = require('./log-reader');

function buildServer(config, {
  store = new ConfigStore({ configDir: config.gateway.configDir }),
  health = new HealthStore(),
} = {}) {
  const fastify = Fastify({ logger: false });
  const gateway = new GatewayController(config.gateway);

  function serviceRows() {
    return store.list().map((service) => ({
      ...service,
      health: health.get(service.name, service),
    }));
  }

  fastify.register(fastifyStatic, {
    root: path.join(__dirname, '..', 'public'),
    index: 'index.html',
  });

  fastify.get('/api/gateway/status', async () => gateway.status());
  fastify.post('/api/gateway/start', async () => gateway.start());
  fastify.post('/api/gateway/stop', async () => gateway.stop());
  fastify.post('/api/gateway/restart', async () => gateway.restart());

  fastify.get('/api/gateway/logs', async (request, reply) => {
    const result = readLog({
      filePath: config.gateway.logFile,
      boundary: config.gateway.configDir,
    });
    if (result.state === 'missing') return reply.code(404).send(result);
    if (result.state !== 'available') return reply.code(500).send(result);
    return reply.send(result);
  });

  // The draft is what the page renders. It falls back to the effective config
  // when nothing has been edited, so a fresh install shows an empty list rather
  // than an error.
  fastify.get('/api/services', async () => ({
    services: serviceRows(),
    pendingChanges: store.hasDraftChanges(),
    hasRecoverableConfig: store.hasLastGood(),
  }));

  fastify.post('/api/services', async (request, reply) => {
    try {
      const service = store.addService(request.body || {});
      return reply.code(201).send({ service, services: serviceRows() });
    } catch (error) {
      if (error instanceof ValidationError) {
        return reply.code(400).send({ error: 'validation', field: error.field, message: error.message });
      }
      throw error;
    }
  });

  fastify.put('/api/services/:name', async (request, reply) => {
    try {
      const service = store.updateService(request.params.name, request.body || {});
      return reply.send({ service, services: serviceRows() });
    } catch (error) {
      if (error instanceof ValidationError) {
        return reply.code(400).send({ error: 'validation', field: error.field, message: error.message });
      }
      throw error;
    }
  });

  fastify.patch('/api/services/:name', async (request, reply) => {
    try {
      const service = store.disableService(request.params.name, request.body?.disabled);
      return reply.send({ service, services: serviceRows() });
    } catch (error) {
      if (error instanceof ValidationError) {
        return reply.code(400).send({ error: 'validation', field: error.field, message: error.message });
      }
      throw error;
    }
  });

  fastify.delete('/api/services/:name', async (request, reply) => {
    try {
      store.deleteService(request.params.name);
      health.forget(request.params.name);
      return reply.send({ services: serviceRows() });
    } catch (error) {
      if (error instanceof ValidationError) {
        return reply.code(400).send({ error: 'validation', field: error.field, message: error.message });
      }
      throw error;
    }
  });

  fastify.post('/api/services/:name/check', async (request, reply) => {
    const service = store.list().find((item) => item.name === request.params.name);
    if (!service) {
      return reply.code(404).send({ error: 'not_found', message: '服務不存在，無法測試連線' });
    }
    const result = await health.check(service.name, service);
    return reply.send({ service, health: result });
  });

  // 409 rather than 200 for every non-applied outcome: a failed apply is not a
  // successful request, and the client must not treat a 2xx as "applied".
  fastify.post('/api/config/apply', async (request, reply) => {
    const outcome = await store.apply({ restart: () => gateway.restart() });
    return reply.code(outcome.state === 'applied' ? 200 : 409).send({
      ...outcome,
      services: serviceRows(),
    });
  });

  return fastify;
}

async function main() {
  const config = loadConfig();
  const fastify = buildServer(config);
  await fastify.listen({ host: config.hub.host, port: config.hub.port });
  console.log(`MCP Hub listening on http://${config.hub.host}:${config.hub.port}`);
}

if (require.main === module) {
  main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}

module.exports = { buildServer };
