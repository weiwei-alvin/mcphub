'use strict';

(function () {
  const statusEl = document.getElementById('gateway-status');
  const applyStatusEl = document.getElementById('apply-status');
  const applyDetailEl = document.getElementById('apply-detail');
  const draftStatusEl = document.getElementById('draft-status');
  const rowsEl = document.getElementById('service-rows');
  const form = document.getElementById('service-form');

  const gatewayButtons = {
    start: document.getElementById('gateway-start'),
    stop: document.getElementById('gateway-stop'),
    restart: document.getElementById('gateway-restart'),
  };

  const STATE_TEXT = {
    running: 'Gateway 運作中',
    stopped: 'Gateway 已停止',
    starting: 'Gateway 啟動中…',
    unknown: 'Gateway 狀態未知',
  };

  const TRANSPORT_TEXT = { stdio: 'stdio', streamableHttp: 'Streamable HTTP' };
  const FIELD_ERRORS = ['name', 'transport', 'command', 'args', 'url', 'form'];

  function render(result) {
    const text = result.state === 'error'
      ? 'Gateway 發生錯誤：' + result.message
      : (STATE_TEXT[result.state] || STATE_TEXT.unknown);
    statusEl.textContent = text;
    statusEl.dataset.state = result.state;
  }

  function setBusy(busy) {
    Object.values(gatewayButtons).forEach((button) => { button.disabled = busy; });
  }

  async function call(action) {
    setBusy(true);
    try {
      const response = await fetch('/api/gateway/' + action, { method: action === 'status' ? 'GET' : 'POST' });
      const result = await response.json();
      render(result);
    } catch (error) {
      render({ state: 'error', message: '無法連線到 MCP Hub 後端' });
    } finally {
      setBusy(false);
    }
  }

  Object.entries(gatewayButtons).forEach(([action, button]) => {
    button.addEventListener('click', () => call(action));
  });

  function clearFieldErrors() {
    FIELD_ERRORS.forEach((field) => {
      const box = document.getElementById('error-' + field);
      box.textContent = '';
      box.hidden = true;
    });
  }

  function showFieldError(field, message) {
    // A rejected field the form has no input for (e.g. a refused secret key)
    // still has to be visible, so it falls back to the form-level message.
    const box = document.getElementById('error-' + field) || document.getElementById('error-form');
    box.textContent = message;
    box.hidden = false;
  }

  function toggleTransportFields() {
    const isHttp = form.elements.transport.value === 'http';
    document.getElementById('stdio-fields').hidden = isHttp;
    document.getElementById('http-fields').hidden = !isHttp;
  }

  form.elements.transport.addEventListener('change', toggleTransportFields);

  function renderServices(services) {
    rowsEl.replaceChildren();
    for (const service of services) {
      const row = document.createElement('tr');
      const name = document.createElement('td');
      name.textContent = service.name;
      const transport = document.createElement('td');
      transport.textContent = TRANSPORT_TEXT[service.transport] || service.transport;
      row.append(name, transport);
      rowsEl.append(row);
    }
  }

  async function refreshServices() {
    const response = await fetch('/api/services');
    const data = await response.json();
    renderServices(data.services || []);
    if (data.pendingChanges) {
      draftStatusEl.textContent = '有尚未套用的變更';
      draftStatusEl.hidden = false;
    } else {
      draftStatusEl.hidden = true;
    }
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    clearFieldErrors();

    const transport = form.elements.transport.value;
    const payload = { name: form.elements.name.value, transport };
    if (transport === 'stdio') {
      payload.command = form.elements.command.value;
      payload.args = form.elements.args.value;
    } else {
      payload.url = form.elements.url.value;
    }

    try {
      const response = await fetch('/api/services', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await response.json();
      if (!response.ok) {
        showFieldError(data.field, data.message || '新增失敗');
        return;
      }
      renderServices(data.services);
      form.elements.name.value = '';
      form.elements.command.value = '';
      form.elements.args.value = '';
      form.elements.url.value = '';
      await refreshServices();
    } catch (error) {
      applyStatusEl.textContent = '無法連線到 MCP Hub 後端';
      applyStatusEl.dataset.state = 'error';
    }
  });

  document.getElementById('apply-config').addEventListener('click', async () => {
    // US-07 requires the interruption to be stated before the apply happens,
    // not inferred from the result afterwards.
    const confirmed = window.confirm(
      '套用設定會重新啟動 Gateway，正在進行中的工具呼叫可能會中斷。要繼續嗎？'
    );
    if (!confirmed) return;

    applyStatusEl.textContent = '套用中…';
    applyStatusEl.dataset.state = 'applying';
    applyDetailEl.textContent = '';

    try {
      const response = await fetch('/api/config/apply', { method: 'POST' });
      const data = await response.json();
      if (data.state === 'applied') {
        applyStatusEl.textContent = '設定已套用';
        applyStatusEl.dataset.state = 'applied';
      } else {
        // Distinct wording per outcome (US-08): none of these may read as success.
        if (data.recovered === true) {
          applyStatusEl.textContent = '新設定未套用，已回復舊設定';
        } else if (data.stage === 'validation') {
          applyStatusEl.textContent = '設定未套用（驗證失敗）';
        } else {
          applyStatusEl.textContent = '套用失敗，Gateway 目前無法使用';
        }
        applyStatusEl.dataset.state = 'error';
        applyDetailEl.textContent = data.message || '套用失敗';
      }
      renderServices(data.services || []);
      await refreshServices();
      await call('status');
    } catch (error) {
      applyStatusEl.textContent = '無法連線到 MCP Hub 後端';
      applyStatusEl.dataset.state = 'error';
    }
  });

  call('status');
  refreshServices().catch(() => {});
})();
