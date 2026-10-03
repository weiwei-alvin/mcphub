'use strict';

const { spawn, exec } = require('node:child_process');
const path = require('node:path');

const serverPath = path.join(__dirname, '..', 'src', 'server.js');

const child = spawn(process.execPath, [serverPath], {
  detached: true,
  stdio: 'ignore',
  windowsHide: true,
});
child.unref();

const hubPort = process.env.HUB_PORT || 3100;
const url = `http://127.0.0.1:${hubPort}/`;

// Give the server a moment to bind before opening the browser.
setTimeout(() => {
  if (process.platform === 'win32') exec(`start "" "${url}"`);
  else if (process.platform === 'darwin') exec(`open "${url}"`);
  else exec(`xdg-open "${url}"`);
}, 1500);
