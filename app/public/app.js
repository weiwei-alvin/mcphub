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
  let editingName = null;

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

  function clearForm() {
    editingName = null;
    form.elements.name.disabled = false;
    document.getElementById('service-form-legend').textContent = '新增 MCP Server';
    document.getElementById('service-submit').textContent = '新增 MCP Server';
    form.elements.name.value = '';
    form.elements.command.value = '';
    form.elements.args.value = '';
    form.elements.url.value = '';
  }

  function beginEdit(service) {
    editingName = service.name;
    form.elements.name.value = service.name;
    form.elements.name.disabled = true;
    form.elements.transport.value = service.transport === 'streamableHttp' ? 'http' : service.transport;
    form.elements.command.value = service.command || '';
    form.elements.args.value = Array.isArray(service.args) ? JSON.stringify(service.args) : '';
    form.elements.url.value = service.url || '';
    document.getElementById('service-form-legend').textContent = '編輯 MCP Server';
    document.getElementById('service-submit').textContent = '更新 MCP Server';
    toggleTransportFields();
    form.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function renderServices(services) {
    rowsEl.replaceChildren();
    for (const service of services) {
      const row = document.createElement('tr');
      const name = document.createElement('td');
      name.textContent = service.name;
      const transport = document.createElement('td');
      transport.textContent = TRANSPORT_TEXT[service.transport] || service.transport;
      const actions = document.createElement('td');
      const edit = document.createElement('button');
      edit.type = 'button';
      edit.textContent = '編輯';
      edit.addEventListener('click', () => beginEdit(service));
      actions.append(edit);
      row.append(name, transport, actions);
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

  function formPayload() {
    const transport = form.elements.transport.value;
    const payload = { name: form.elements.name.value, transport };
    if (transport === 'stdio') {
      payload.command = form.elements.command.value;
      payload.args = form.elements.args.value;
    } else {
      payload.url = form.elements.url.value;
    }
    return payload;
  }

  async function saveEdit() {
    const name = editingName;
    const response = await fetch('/api/services/' + encodeURIComponent(name), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(formPayload()),
    });
    const data = await response.json();
    if (!response.ok) {
      showFieldError(data.field, data.message || '編輯失敗');
      return false;
    }
    renderServices(data.services || []);
    clearForm();
    await refreshServices();
    return true;
  }

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    clearFieldErrors();

    try {
      if (editingName) {
        await saveEdit();
        return;
      }
      const payload = formPayload();
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
      clearForm();
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
      if (editingName && !(await saveEdit())) {
        applyStatusEl.textContent = '變更未儲存，設定未套用';
        applyStatusEl.dataset.state = 'error';
        return;
      }
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
