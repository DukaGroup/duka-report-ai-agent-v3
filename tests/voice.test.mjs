import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from '../frontend/node_modules/typescript/lib/typescript.js';

// Use the project's compiler so tests also work on Node builds without native TS support.
const source = await readFile(new URL('../frontend/src/voice.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText;
const { VoiceRecorder, speak } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

function environment(getUserMedia) {
  globalThis.window = { isSecureContext: true, MediaRecorder: true };
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { mediaDevices: { getUserMedia } } });
  globalThis.MediaRecorder = class {
    static isTypeSupported() { return true; }
    constructor(stream, options) { this.mimeType = options.mimeType; this.state = 'inactive'; }
    start() { this.state = 'recording'; }
    stop() { this.state = 'inactive'; this.ondataavailable({ data: new Blob(['audio']) }); this.onstop(); }
  };
}

test('ending voice while microphone permission is pending releases the eventual stream', async () => {
  let resolve, released = false, received = false;
  environment(() => new Promise(r => { resolve = r; }));
  const recorder = new VoiceRecorder();
  const pending = recorder.start(() => { received = true; }, false);
  recorder.stop(true);
  resolve({ getTracks: () => [{ stop() { released = true; } }] });
  assert.equal(await pending, false);
  assert.equal(released, true);
  assert.equal(received, false);
  assert.equal(recorder.recorder, null);
});

test('finishing a recording releases microphone tracks and passes audio for transcription', async () => {
  let released = false, received;
  environment(async () => ({ getTracks: () => [{ stop() { released = true; } }] }));
  const recorder = new VoiceRecorder();
  assert.equal(await recorder.start(blob => { received = blob; }, false), true);
  recorder.stop();
  assert.equal(released, true);
  assert.equal(received.size, 5);
  assert.equal(recorder.timer, null);
  assert.equal(recorder.stream, null);
});

test('discarding a recording never submits it for transcription', async () => {
  let received = false;
  environment(async () => ({ getTracks: () => [{ stop() {} }] }));
  const recorder = new VoiceRecorder();
  await recorder.start(() => { received = true; }, false);
  recorder.stop(true);
  assert.equal(received, false);
});

test('spoken replies default to English and select an English device voice', () => {
  let spoken, finished = false;
  const voice = { lang: 'en-US', name: 'English fixture' };
  globalThis.SpeechSynthesisUtterance = class { constructor(text) { this.text = text; } };
  globalThis.window = { speechSynthesis: { cancel() {}, getVoices: () => [voice], speak(value) { spoken = value; } } };
  speak('Hello', () => { finished = true; });
  assert.equal(spoken.lang, 'en-US');
  assert.equal(spoken.voice, voice);
  spoken.onend();
  assert.equal(finished, true);
});
