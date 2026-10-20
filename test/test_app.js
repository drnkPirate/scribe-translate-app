"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function element() {
  return {
    value: "", textContent: "", className: "", dataset: {}, disabled: false, hidden: false,
    children: [], files: [], options: [], parent: null,
    addEventListener() {}, setAttribute() {}, connect() {}, disconnect() {},
    replaceChildren() { this.options = []; this.children = []; },
    append(...children) { for (const child of children) child.parent = this; this.children.push(...children); this.options.push(...children); },
    prepend(...children) { for (const child of children) child.parent = this; this.children.unshift(...children); },
    remove() { if (this.parent) this.parent.children = this.parent.children.filter((child) => child !== this); },
    querySelector(selector) { return this.children.find((child) => `.${child.className}` === selector) || null; }
  };
}

const elements = new Map();
const requests = [];
const sandbox = {
  console, setTimeout, clearTimeout, performance, AbortController,
  navigator: {mediaDevices: {enumerateDevices: async () => []}},
  document: {
    getElementById(id) { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); },
    createElement() { return element(); }, querySelectorAll() { return []; }
  },
  fetch: async (url, options) => {
    requests.push({url, options});
    return {ok: true, status: 200, json: async () => ({french: "Bonjour", dutch: "Goeiedag", duration_s: 1})};
  },
  addEventListener() {}
};
sandbox.globalThis = sandbox;

const root = path.join(__dirname, "..", "sidecar", "web");
const source = fs.readFileSync(path.join(root, "app.js"), "utf8").replace("void initialize();", "") + `
globalThis.app = {
  makeSegmenter, encodeWav, enqueue, idle, resetCaptions, setState,
  configure(value, phase, isReady) { messages = value; modelPhase = phase; ready = isReady; },
  state() { return {source, queued: queue.length, current: currentItem}; }
};`;
vm.runInNewContext(source, sandbox, {filename: "app.js"});

async function run() {
  const locale = JSON.parse(fs.readFileSync(path.join(root, "en.json"), "utf8"));
  sandbox.app.configure(locale, "models_missing", false);
  sandbox.app.setState("modelsMissing");
  assert.equal(elements.get("model-setup").hidden, false);
  assert.equal(elements.get("download").disabled, false);

  const snapshots = [];
  const segmenter = sandbox.app.makeSegmenter(16_000, (snapshot) => snapshots.push(snapshot), 0.75);
  for (let index = 0; index < 8; index++) segmenter.push(new Float32Array(1_600).fill(0.004));
  assert.deepEqual([snapshots[0].utteranceId, snapshots[0].revision, snapshots[0].final], [0, 1, false]);
  for (let index = 0; index < 7; index++) segmenter.push(new Float32Array(1_600));
  assert.equal(snapshots.at(-1).final, true);

  sandbox.app.configure(locale, "ready", true);
  sandbox.app.setState("ready");
  assert.equal(elements.get("model-setup").hidden, true);
  sandbox.app.enqueue({samples: new Float32Array(16_000).fill(0.004), sampleRate: 16_000, utteranceId: 0, revision: 1, final: true}, 0);
  await sandbox.app.idle();
  assert.equal(requests[0].url, "/api/caption");
  assert.equal(elements.get("captions").children[0].children[0].textContent, "Bonjour");
  assert.equal(elements.get("captions").children[0].children[1].textContent, "Goeiedag");

  sandbox.app.resetCaptions();
  assert.equal(elements.get("captions").children.length, 1);
  assert.equal(elements.get("captions").children[0].textContent, "Dutch transcription and French translation will appear here.");

  const wav = new DataView(sandbox.app.encodeWav(new Float32Array([0, 0.5, -0.5]), 16_000));
  assert.equal(wav.getUint32(24, true), 16_000);
  assert.equal(wav.getUint32(40, true), 6);
  assert.match(fs.readFileSync(path.join(root, "index.html"), "utf8"), /id="download"/);
}

run().then(() => process.stdout.write("browser self-check passed\n"));
