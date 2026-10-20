"use strict";

const {app, BrowserWindow, dialog, session} = require("electron");
const {spawn} = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

const port = 43187;
const url = `http://127.0.0.1:${port}/`;
const origin = new URL(url).origin;
let window = null;
let sidecar = null;
let log = null;

function locale() {
  const file = app.isPackaged
    ? path.join(process.resourcesPath, "sidecar", "en.json")
    : path.join(__dirname, "sidecar", "web", "en.json");
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function sidecarCommand() {
  if (app.isPackaged) {
    return {
      executable: path.join(process.resourcesPath, "sidecar", process.platform === "win32" ? "scribe-translate-server.exe" : "scribe-translate-server"),
      args: ["--port", String(port)],
      cwd: path.join(process.resourcesPath, "sidecar")
    };
  }
  const executable = path.join(__dirname, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
  return {executable, args: [path.join(__dirname, "sidecar", "server.py"), "--port", String(port)], cwd: path.join(__dirname, "sidecar")};
}

function startSidecar() {
  const command = sidecarCommand();
  if (!fs.existsSync(command.executable)) throw new Error("sidecar_missing");
  const logDir = app.getPath("logs");
  fs.mkdirSync(logDir, {recursive: true});
  log = fs.createWriteStream(path.join(logDir, "scribe-translate.log"), {flags: "a"});
  sidecar = spawn(command.executable, command.args, {
    cwd: command.cwd,
    env: {...process.env, PYTHONUNBUFFERED: "1"},
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"]
  });
  sidecar.stdout.pipe(log, {end: false});
  sidecar.stderr.pipe(log, {end: false});
}

function waitForSidecar(attempts = 600) {
  return new Promise((resolve, reject) => {
    const check = () => {
      const request = http.get(`${url}api/status`, {timeout: 500}, (response) => {
        let body = "";
        response.on("data", (chunk) => { body += chunk; });
        response.on("end", () => {
          try {
            const status = JSON.parse(body);
            if (status.app === "scribe-translate") return resolve();
          } catch {}
          if (--attempts > 0) return setTimeout(check, 200);
          reject(new Error("wrong_local_service"));
        });
      });
      request.on("timeout", () => request.destroy());
      request.on("error", () => {
        if (--attempts > 0) return setTimeout(check, 200);
        reject(new Error("sidecar_timeout"));
      });
    };
    check();
  });
}

async function createWindow() {
  window = new BrowserWindow({
    width: 1180,
    height: 780,
    minWidth: 760,
    minHeight: 560,
    show: false,
    backgroundColor: "#090b10",
    webPreferences: {contextIsolation: true, nodeIntegration: false, sandbox: true}
  });
  await window.loadURL(url);
  window.once("ready-to-show", () => window.show());
  window.on("closed", () => { window = null; });
}

const hasLock = app.requestSingleInstanceLock();
if (!hasLock) app.quit();
else {
  app.on("second-instance", () => {
    if (window) {
      if (window.isMinimized()) window.restore();
      window.focus();
    }
  });

  app.whenReady().then(async () => {
    session.defaultSession.setPermissionCheckHandler((_contents, permission, requestingOrigin) =>
      permission === "media" && requestingOrigin === origin
    );
    session.defaultSession.setPermissionRequestHandler((contents, permission, callback) =>
      callback(permission === "media" && new URL(contents.getURL()).origin === origin)
    );
    try {
      startSidecar();
      await waitForSidecar();
      await createWindow();
    } catch (error) {
      if (log) log.write(`${error.stack || error}\n`);
      const messages = locale().errors;
      dialog.showErrorBox(messages.appStartTitle, messages.appStartBody);
      app.quit();
    }
  });
}

app.on("window-all-closed", () => app.quit());
app.on("before-quit", () => {
  if (sidecar && !sidecar.killed) sidecar.kill();
  if (log) log.end();
});
