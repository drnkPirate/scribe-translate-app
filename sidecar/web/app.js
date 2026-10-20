"use strict";

const $ = (id) => document.getElementById(id);
const elements = {
  state: $("state"), mode: $("mode"), error: $("error"), captions: $("captions"),
  device: $("device"), start: $("start"), stop: $("stop"), file: $("file"), replay: $("replay"),
  modelSetup: $("model-setup"), download: $("download"), reset: $("reset")
};

let messages;
let ready = false;
let session = 0;
let source = null;
let queue = [];
let sending = false;
let currentItem = null;
let currentController = null;
const cards = new Map();
let stream = null;
let context = null;
let processor = null;
let segmenter = null;
let modelPhase = "models_missing";

const text = (path, values = {}) => {
  let value = path.split(".").reduce((current, key) => current[key], messages);
  for (const [key, replacement] of Object.entries(values)) value = value.replace(`{${key}}`, replacement);
  return value;
};

function setState(name) {
  elements.state.textContent = text(`states.${name}`);
  elements.state.dataset.kind = name === "live" ? "live" : name === "failed" ? "error" : "";
  elements.mode.textContent = text(`modes.${source || "stopped"}`);
  elements.start.disabled = !ready || source !== null;
  elements.stop.disabled = source === null;
  elements.replay.disabled = !ready || source !== null;
  elements.reset.disabled = source !== null;
  elements.download.disabled = ["downloading", "warming", "ready"].includes(modelPhase);
  elements.modelSetup.hidden = modelPhase === "ready";
}

function setError(message = "") {
  elements.error.textContent = message;
}

function showEmpty() {
  if (elements.captions.children.length) return;
  const empty = document.createElement("p");
  empty.className = "empty";
  empty.textContent = text("empty");
  elements.captions.append(empty);
}

function resetCaptions() {
  cards.clear();
  elements.captions.replaceChildren();
  showEmpty();
}

function updateCaption(item, result, queueDelay, modelDelay) {
  if (!item.final && result.translation_pending) return;
  let entry = cards.get(item.utteranceId);
  if (entry && (entry.finalized || item.revision < entry.revision)) return;
  if (!result.french && !result.dutch) {
    if (entry && item.final) {
      entry.finalized = true;
      entry.card.remove();
      showEmpty();
    }
    return;
  }
  if (!entry) {
    const empty = elements.captions.querySelector(".empty");
    if (empty) empty.remove();
    const card = document.createElement("article");
    card.className = "caption";
    const french = document.createElement("p");
    french.className = "french";
    french.lang = "fr";
    const dutch = document.createElement("p");
    dutch.className = "dutch";
    dutch.lang = "nl";
    const meta = document.createElement("div");
    meta.className = "meta";
    card.append(french, dutch, meta);
    elements.captions.prepend(card);
    entry = {card, french, dutch, meta, revision: 0, finalized: false};
    cards.set(item.utteranceId, entry);
  }
  if (result.french) entry.french.textContent = result.french;
  if (result.dutch) entry.dutch.textContent = result.dutch;
  entry.revision = item.revision;
  entry.finalized = item.final;
  entry.card.dataset.final = String(item.final);
  entry.card.dataset.utteranceId = item.utteranceId;
  entry.card.dataset.revision = String(item.revision);
  const preliminary = item.final ? "" : `${text("preliminary")} · `;
  const updateDelay = performance.now() - item.enqueuedAt;
  entry.meta.textContent = `${preliminary}${text("updateDelay", {value: Math.round(updateDelay)})} · ${text("queueDelay", {value: Math.round(queueDelay)})} · ${text("modelDelay", {value: Math.round(modelDelay)})} · ${text("segment", {value: Number(result.duration_s).toFixed(1)})}`;
}

function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const word = (offset, value) => { for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i)); };
  word(0, "RIFF"); view.setUint32(4, 36 + samples.length * 2, true); word(8, "WAVE"); word(12, "fmt ");
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true); view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true); word(36, "data");
  view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) view.setInt16(44 + i * 2, Math.max(-1, Math.min(1, samples[i])) * 32767, true);
  return buffer;
}

function makeSegmenter(sampleRate, onSegment, intervalSeconds = 0.25) {
  // Energy bounds capture; the server applies trained speech detection before recognition.
  const threshold = 0.001;
  const preRollLimit = Math.round(sampleRate * 0.3);
  const partialInterval = Math.round(sampleRate * intervalSeconds);
  const silenceLimit = Math.round(sampleRate * 0.65);
  const maximum = Math.round(sampleRate * 12);
  let parts = [];
  let length = 0;
  let silence = 0;
  let speaking = false;
  let partialProgress = 0;
  let utteranceId = 0;
  let revision = 0;
  let preRoll = new Float32Array(0);

  const emit = (final) => {
    if (!speaking || !length) return false;
    const output = new Float32Array(length);
    let offset = 0;
    for (const part of parts) { output.set(part, offset); offset += part.length; }
    onSegment({samples: output, sampleRate, utteranceId, revision: ++revision, final});
    partialProgress = 0;
    if (final) {
      parts = []; length = 0; silence = 0; speaking = false;
      utteranceId += 1; revision = 0;
    }
    return true;
  };

  return {
    push(input) {
      const samples = new Float32Array(input);
      let energy = 0;
      for (const sample of samples) energy += sample * sample;
      const speech = Math.sqrt(energy / samples.length) >= threshold;
      if (!speaking) {
        const combined = new Float32Array(Math.min(preRollLimit, preRoll.length + samples.length));
        const oldStart = Math.max(0, preRoll.length - (combined.length - samples.length));
        combined.set(preRoll.subarray(oldStart), 0);
        combined.set(samples.subarray(Math.max(0, samples.length - combined.length)), Math.max(0, combined.length - samples.length));
        preRoll = combined;
        if (!speech) return false;
        speaking = true; parts.push(preRoll); length = preRoll.length; partialProgress = samples.length; preRoll = new Float32Array(0);
      } else {
        parts.push(samples); length += samples.length; partialProgress += samples.length;
      }
      silence = speech ? 0 : silence + samples.length;
      if (length >= maximum || silence >= silenceLimit) return emit(true);
      if (partialProgress >= partialInterval) return emit(false);
      return false;
    },
    flush: () => emit(true)
  };
}

async function sendSegment(item) {
  currentController = new AbortController();
  const timeout = setTimeout(() => currentController.abort(), 120_000);
  const startedAt = performance.now();
  try {
    const response = await fetch("/api/caption", {
      method: "POST", headers: {
        "Content-Type": "audio/wav",
        ...(item.final ? {} : {"X-Caption-Partial": "1"})
      },
      body: encodeWav(item.samples, item.sampleRate), signal: currentController.signal
    });
    if (response.status === 429) throw new Error("overload");
    if (!response.ok) throw new Error("processing");
    const result = await response.json();
    if (item.session === session) updateCaption(item, result, startedAt - item.enqueuedAt, performance.now() - startedAt);
  } finally {
    clearTimeout(timeout);
    currentController = null;
  }
}

async function drainQueue() {
  if (sending) return;
  sending = true;
  while (queue.length) {
    const finalIndex = queue.findIndex((item) => item.final);
    const item = queue.splice(finalIndex < 0 ? 0 : finalIndex, 1)[0];
    currentItem = item;
    try {
      await sendSegment(item);
    } catch (error) {
      if (item.session === session && (item.final || error.message !== "overload")) {
        const overloaded = error.message === "overload";
        session += 1;
        const message = overloaded ? text("errors.overload") : text("errors.processing");
        if (source === "stopping") setError(message);
        else await stop(message, false);
        queue = queue.filter((queued) => queued.session !== item.session);
      }
    }
    currentItem = null;
  }
  sending = false;
}

function enqueue(snapshot, activeSession) {
  if (activeSession !== session) return;
  const utteranceId = `${activeSession}:${snapshot.utteranceId}`;
  const item = {...snapshot, utteranceId, session: activeSession, enqueuedAt: performance.now()};
  if (!item.final && ((currentItem?.utteranceId === utteranceId && currentItem.final) || queue.some((queued) => queued.utteranceId === utteranceId && queued.final))) return;
  if (item.final && [currentItem, ...queue].filter((queued) => queued?.session === activeSession && queued.final).length >= 2) {
    session += 1;
    queue = queue.filter((item) => item.session !== activeSession);
    if (currentItem?.session === activeSession) currentController?.abort();
    void stop(text("errors.overload"), false);
    return;
  }
  if (item.final) queue = queue.filter((queued) => queued.utteranceId !== utteranceId || queued.final);
  else {
    const pending = queue.findIndex((queued) => queued.utteranceId === utteranceId && !queued.final);
    if (pending >= 0) queue.splice(pending, 1, item);
    else queue.push(item);
    void drainQueue();
    return;
  }
  queue.push(item);
  void drainQueue();
}

async function listDevices() {
  const devices = await navigator.mediaDevices.enumerateDevices();
  const selected = elements.device.value;
  elements.device.replaceChildren();
  const microphones = devices.filter((device) => device.kind === "audioinput");
  if (!microphones.length) microphones.push({deviceId: "", label: text("defaultDevice")});
  microphones.forEach((device, index) => {
    const option = document.createElement("option");
    option.value = device.deviceId;
    option.textContent = device.label || `${text("microphone")} ${index + 1}`;
    elements.device.append(option);
  });
  if ([...elements.device.options].some((option) => option.value === selected)) elements.device.value = selected;
}

async function start() {
  if (source !== null || !ready) return;
  setError();
  const activeSession = ++session;
  source = "starting";
  setState("starting");
  try {
    const audio = {
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
      ...(elements.device.value ? {deviceId: {exact: elements.device.value}} : {})
    };
    const captured = await navigator.mediaDevices.getUserMedia({audio});
    if (activeSession !== session || source !== "starting") {
      captured.getTracks().forEach((track) => track.stop()); return;
    }
    stream = captured;
    context = new AudioContext();
    const input = context.createMediaStreamSource(stream);
    processor = context.createScriptProcessor(4096, 1, 1);
    segmenter = makeSegmenter(context.sampleRate, (snapshot) => enqueue(snapshot, activeSession));
    processor.onaudioprocess = (event) => segmenter.push(event.inputBuffer.getChannelData(0));
    input.connect(processor);
    processor.connect(context.destination);
    source = "live";
    setState("live");
  } catch {
    if (stream) { stream.getTracks().forEach((track) => track.stop()); stream = null; }
    if (context) { await context.close(); context = null; }
    if (activeSession !== session) return;
    setError(text("errors.permission"));
    source = null;
    setState("stopped");
    return;
  }
  try { await listDevices(); } catch { /* Keep the active default device. */ }
}

async function stop(message = "", flush = true) {
  if (source === null) { if (message) setError(message); return; }
  if (source === "stopping") { if (message) setError(message); return; }
  const stoppedSource = source;
  const stoppedSession = session;
  if (stoppedSource === "starting" || stoppedSource === "replay") {
    session += 1;
    queue = queue.filter((item) => item.session !== stoppedSession);
    if (currentItem?.session === stoppedSession) currentController?.abort();
  }
  source = "stopping";
  setState("stopping");
  const currentSegmenter = segmenter;
  segmenter = null;
  if (processor) { processor.onaudioprocess = null; processor.disconnect(); processor = null; }
  if (stream) { stream.getTracks().forEach((track) => track.stop()); stream = null; }
  if (context) { await context.close(); context = null; }
  if (flush && stoppedSource === "live" && currentSegmenter) currentSegmenter.flush();
  if (flush && (queue.length || sending)) {
    await idle();
  }
  source = null;
  setState("stopped");
  if (message) setError(message);
}

const idle = () => new Promise((resolve) => {
  const check = () => queue.length || currentItem ? setTimeout(check, 25) : resolve();
  check();
});

async function replay() {
  if (source !== null || !ready) return;
  const file = elements.file.files[0];
  if (!file) { setError(text("errors.file")); return; }
  const activeSession = ++session;
  source = "replay";
  setError();
  setState("replay");
  let replayContext = null;
  try {
    replayContext = new AudioContext({sampleRate: 16000});
    const decoded = await replayContext.decodeAudioData(await file.arrayBuffer());
    const channel = decoded.getChannelData(0);
    const replaySegmenter = makeSegmenter(decoded.sampleRate, (snapshot) => enqueue(snapshot, activeSession));
    for (let offset = 0; offset < channel.length && activeSession === session; offset += 4096) {
      const chunk = channel.subarray(offset, offset + 4096);
      await new Promise((resolve) => setTimeout(resolve, chunk.length / decoded.sampleRate * 1000));
      replaySegmenter.push(chunk);
    }
    replaySegmenter.flush();
    await idle();
  } catch {
    if (activeSession === session) setError(text("errors.file"));
  } finally {
    if (replayContext) await replayContext.close();
  }
  if (activeSession === session) { source = null; setState("stopped"); }
}

async function pollStatus() {
  try {
    const response = await fetch("/api/status", {cache: "no-store"});
    const status = await response.json();
    ready = Boolean(status.ready);
    modelPhase = status.phase;
    if (ready) {
      setState("ready");
    }
    else if (status.error) { setState("failed"); setError(text("errors.startup")); }
    else {
      setState(status.phase === "models_missing" ? "modelsMissing" : status.phase === "downloading" ? "downloading" : "warming");
      setTimeout(pollStatus, 700);
    }
  } catch {
    setState("failed");
    setError(text("errors.server"));
    setTimeout(pollStatus, 1500);
  }
}

async function downloadModels() {
  if (modelPhase !== "models_missing" && modelPhase !== "failed") return;
  setError();
  modelPhase = "downloading";
  setState("downloading");
  try {
    const response = await fetch("/api/models/download", {method: "POST"});
    if (!response.ok) throw new Error("download_failed");
    setTimeout(pollStatus, 500);
  } catch {
    modelPhase = "failed";
    setState("failed");
    setError(text("errors.server"));
  }
}

async function initialize() {
  messages = await fetch("/en.json").then((response) => response.json());
  document.querySelectorAll("[data-i18n]").forEach((element) => { element.textContent = text(element.dataset.i18n); });
  elements.captions.setAttribute("aria-label", text("captions"));
  elements.start.addEventListener("click", start);
  elements.stop.addEventListener("click", () => stop());
  elements.replay.addEventListener("click", replay);
  elements.reset.addEventListener("click", resetCaptions);
  elements.download.addEventListener("click", downloadModels);
  showEmpty();
  setState("warming");
  try { await listDevices(); } catch { /* Device labels become available after explicit start. */ }
  await pollStatus();
}

globalThis.addEventListener("beforeunload", () => { void stop("", false); });

void initialize();
