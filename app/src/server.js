'use strict';

const path = require('node:path');
const Fastify = require('fastify');
const fastifyStatic = require('@fastify/static');
const { loadConfig } = require('./config');
const { GatewayController } = require('./gateway-controller');
const { ConfigStore, ValidationError } = require('./config-store');

function buildServer(config, { store = new ConfigStore({ configDir: config.gateway.configDir }) } = {}) {
  const fastify = Fastify({ logger: false });
  const gateway = new GatewayController(config.gateway);

  fastify.register(fastifyStatic, {
    root: path.join(__dirname, '..', 'public'),
    index: 'index.html',
  });

  fastify.get('/api/gateway/status', async () => gateway.status());
  fastify.post('/api/gateway/start', async () => gateway.start());
  fastify.post('/api/gateway/stop', async () => gateway.stop());
  fastify.post('/api/gateway/restart', async () => gateway.restart());

  // The draft is what the page renders. It falls back to the effective config
  // when nothing has been edited, so a fresh install shows an empty list rather
  // than an error.
  fastify.get('/api/services', async () => ({
    services: store.list(),
    pendingChanges: store.hasDraftChanges(),
    hasRecoverableConfig: store.hasLastGood(),
  }));

  fastify.post('/api/services', async (request, reply) => {
    try {
      const service = store.addService(request.body || {});
      return reply.code(201).send({ service, services: store.list() });
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
      return reply.send({ service, services: store.list() });
    } catch (error) {
      if (error instanceof ValidationError) {
        return reply.code(400).send({ error: 'validation', field: error.field, message: error.message });
      }
      throw error;
    }
  });

  // 409 rather than 200 for every non-applied outcome: a failed apply is not a
  // successful request, and the client must not treat a 2xx as "applied".
  fastify.post('/api/config/apply', async (request, reply) => {
    const outcome = await store.apply({ restart: () => gateway.restart() });
    return reply.code(outcome.state === 'applied' ? 200 : 409).send({
      ...outcome,
      services: store.list(),
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
