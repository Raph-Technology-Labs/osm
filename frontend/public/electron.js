// Electron main process. Adapted from gcm's frontend/public/electron.js
// ZMQ SUB / IPC bridge, stripped of gcm's Docker-orchestration code since
// dev here runs the backend via plain `uvicorn`, not containers.
const { app, BrowserWindow } = require("electron");
const path = require("path");
const net = require("net");
const zmq = require("zeromq");

// Loads PORT/BACKEND_PORT/ZMQ_PORT from frontend/.env -- doesn't override
// vars already set in the shell/docker environment (e.g. multiple devs
// running concurrently on the same host, each with their own ZMQ_PORT).
require("dotenv").config();

const isDev = !app.isPackaged;
const BACKEND_PORT = parseInt(process.env.BACKEND_PORT || "9001", 10);
const ZMQ_PORT = process.env.ZMQ_PORT || "5558";
const FRONTEND_PORT = process.env.PORT || "4001";

// Backend/ZMQ may be remote (e.g. reached over Tailscale), not just
// localhost -- derive the host from the same REACT_APP_API_URL the
// renderer's axios client uses, instead of assuming 127.0.0.1.
const API_URL = process.env.REACT_APP_API_URL || `http://localhost:${BACKEND_PORT}/api/v1`;
const BACKEND_HOST = new URL(API_URL).hostname;

let mainWindow;
let sock;

function waitForBackend(host, port, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  return new Promise((resolve, reject) => {
    const tryConnect = () => {
      const socket = net.createConnection(port, host);
      socket.once("connect", () => {
        socket.end();
        resolve();
      });
      socket.once("error", () => {
        socket.destroy();
        if (Date.now() > deadline) {
          reject(new Error(`Backend not reachable at ${host}:${port} after ${timeoutMs}ms`));
        } else {
          setTimeout(tryConnect, 500);
        }
      });
    };
    tryConnect();
  });
}

async function connectZmq() {
  sock = new zmq.Subscriber();
  await sock.connect(`tcp://${BACKEND_HOST}:${ZMQ_PORT}`);
  sock.subscribe("");
  console.log(`[electron] ZMQ SUB connected to tcp://${BACKEND_HOST}:${ZMQ_PORT}`);

  for await (const [topic, msg] of sock) {
    const messageType = topic.toString();
    if (!mainWindow) continue;
    if (messageType.startsWith("MessageType.CameraFeed")) {
      // already a base64 data URL string -- no JSON parse needed
      mainWindow.webContents.send(messageType, msg.toString());
    } else {
      try {
        mainWindow.webContents.send(messageType, JSON.parse(msg.toString()));
      } catch (e) {
        console.warn(`[electron] failed to parse message on topic ${messageType}:`, e);
      }
    }
  }
}

function disconnectZmq() {
  if (sock) {
    sock.close();
    sock = null;
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  const startUrl = isDev
    ? `http://localhost:${FRONTEND_PORT}`
    : `file://${path.join(__dirname, "../build/index.html")}`;
  mainWindow.loadURL(startUrl);
}

app.whenReady().then(async () => {
  try {
    await waitForBackend(BACKEND_HOST, BACKEND_PORT, 60000);
  } catch (e) {
    console.error("[electron]", e.message);
  }
  createWindow();
  connectZmq();
});

app.on("window-all-closed", () => {
  disconnectZmq();
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", disconnectZmq);
