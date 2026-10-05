'use strict';

const { Client: DefaultClient } = require('@modelcontextprotocol/sdk/client/index.js');
const { StdioClientTransport } = require('@modelcontextprotocol/sdk/client/stdio.js');
const { StreamableHTTPClientTransport } = require('@modelcontextprotocol/sdk/client/streamableHttp.js');

function defaultTransportFactory(service) {
  if (service.type === 'stdio') {
    return new StdioClientTransport({
      command: service.command,
      args: service.args || [],
      stderr: 'pipe',
    });
  }
  if (service.type === 'streamableHttp') {
    return new StreamableHTTPClientTransport(new URL(service.url), {
      reconnectionOptions: {
        initialReconnectionDelay: 10,
        maxReconnectionDelay: 10,
        reconnectionDelayGrowFactor: 1,
        maxRetries: 0,
      },
    });
  }
  throw new Error('不支援的 MCP 傳輸類型');
}

function withTimeout(operation, timeoutMs) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`MCP 連線檢查逾時（${timeoutMs} 毫秒）`)), timeoutMs);
    Promise.resolve(operation).then(resolve, reject).finally(() => clearTimeout(timer));
  });
}

function safeMessage(error) {
  const raw = error instanceof Error ? error.message : String(error);
  return raw
    .replace(/(token|password|authorization|api[_-]?key)\s*[:=]\s*[^\s,;]+/gi, '$1=[已遮蔽]')
    .slice(0, 500);
}

async function closeQuietly(value) {
  if (!value || typeof value.close !== 'function') return;
  try {
    await value.close();
  } catch {
    // Cleanup must not turn a health failure into a process-level error.
  }
}

async function probeService(service, {
  timeoutMs = 8_000,
  ClientClass = DefaultClient,
  transportFactory = defaultTransportFactory,
} = {}) {
  const checkedAt = new Date().toISOString();
  let transport;
  let client;
  try {
    transport = transportFactory(service);
    client = new ClientClass({ name: 'mcp-hub-health-check', version: '1.0.0' });
    await withTimeout(client.connect(transport), timeoutMs);
    const listed = await withTimeout(client.listTools(), timeoutMs);
    if (!listed || !Array.isArray(listed.tools)) {
      throw new Error('MCP tools/list 回應格式不正確');
    }
    return { state: 'reachable', checkedAt, toolCount: listed.tools.length };
  } catch (error) {
    return { state: 'failed', checkedAt, message: safeMessage(error) };
  } finally {
    await closeQuietly(client);
    await closeQuietly(transport);
  }
}

module.exports = { probeService, defaultTransportFactory, safeMessage };
