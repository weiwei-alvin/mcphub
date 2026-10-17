'use strict';

const fs = require('node:fs');
const path = require('node:path');

function insideBoundary(filePath, boundary) {
  const relative = path.relative(path.resolve(boundary), path.resolve(filePath));
  return relative === '' || (!relative.startsWith('..' + path.sep) && relative !== '..' && !path.isAbsolute(relative));
}

function redact(text) {
  return text.replace(
    /((?:token|password|authorization|api[_-]?key)\s*["']?\s*[:=])[^\r\n]*/gi,
    '$1 [已遮蔽]',
  );
}

function readLog({ filePath, boundary, maxBytes = 64 * 1024, readFile = fs.readFileSync, realpath = fs.realpathSync }) {
  if (!filePath || !boundary || !insideBoundary(filePath, boundary)) {
    return { state: 'unreadable', message: '日誌路徑超出允許範圍' };
  }

  let actualPath;
  try {
    actualPath = realpath(filePath);
  } catch (error) {
    if (error?.code === 'ENOENT') return { state: 'missing', message: '找不到 Gateway 日誌' };
    return { state: 'unreadable', message: 'Gateway 日誌無法讀取' };
  }
  if (!insideBoundary(actualPath, boundary)) {
    return { state: 'unreadable', message: '日誌路徑超出允許範圍' };
  }

  try {
    const bytes = readFile(actualPath);
    const truncated = bytes.length > maxBytes;
    const text = bytes.subarray(0, maxBytes).toString('utf8');
    return {
      state: 'available',
      text: redact(truncated ? `${text}\n[後續內容已截斷]` : text),
    };
  } catch {
    return { state: 'unreadable', message: 'Gateway 日誌無法讀取' };
  }
}

module.exports = { readLog, redact, insideBoundary };
