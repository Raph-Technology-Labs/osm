#!/usr/bin/env node
// Fixes a real bug in the old electron-dev npm script:
//   wait-on http-get://localhost:${PORT:-4001} && electron .
// `${PORT:-4001}` is expanded by the SHELL running the npm script, before
// Node/dotenv ever runs -- so it silently polls the wrong port whenever
// PORT isn't already exported in that exact shell session, even though
// frontend/.env sets PORT=5500 and react-scripts/electron.js both pick
// that up correctly via their own dotenv loading. Symptom: `npm run
// electron-dev` prints "Compiled successfully!" on the real port, but
// Electron never launches -- the browser tab react-scripts opens on its
// own is the only thing visible, and window.ipc (Electron's IPC bridge)
// isn't there, so live camera frames never show up.
//
// This script loads .env the same reliable way, then waits on the actual
// configured port before launching Electron -- no shell-export step
// required.
require("dotenv").config();
const { spawn } = require("child_process");
const waitOn = require("wait-on");

const port = process.env.PORT || 4001;
const url = `http-get://localhost:${port}`;

console.log(`[electron-dev] waiting for ${url} ...`);

waitOn({ resources: [url], timeout: 120000 })
  .then(() => {
    console.log(`[electron-dev] dev server up on port ${port} -- launching Electron`);
    const child = spawn("electron", ["."], { stdio: "inherit", shell: true });
    child.on("exit", (code) => process.exit(code ?? 0));
  })
  .catch((err) => {
    console.error(`[electron-dev] gave up waiting for ${url}: ${err.message}`);
    process.exit(1);
  });
