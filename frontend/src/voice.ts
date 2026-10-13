export class VoiceRecorder {
  recorder: MediaRecorder | null = null;
  stream: MediaStream | null = null;
  audio: AudioContext | null = null;
  timer: ReturnType<typeof setInterval> | null = null;
  discard = false;
  generation = 0;

  async start(onRecorded: (blob: Blob) => void, detectSilence: boolean) {
    if (!window.isSecureContext)
      throw new Error("Mikrofoni kërkon localhost ose një lidhje HTTPS.");
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder)
      throw new Error(
        "Ky shfletues nuk regjistron audio. Provoni një version të përditësuar të Chrome, Firefox ose Safari.",
      );
    this.discard = false;
    const generation = ++this.generation;
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true },
    });
    if (generation !== this.generation) {
      stream.getTracks().forEach((track) => track.stop());
      return false;
    }
    this.stream = stream;
    const type = [
      "audio/webm;codecs=opus",
      "audio/ogg;codecs=opus",
      "audio/mp4",
    ].find((t) => MediaRecorder.isTypeSupported(t));
    this.recorder = new MediaRecorder(
      this.stream,
      type ? { mimeType: type } : undefined,
    );
    const chunks: BlobPart[] = [];
    this.recorder.ondataavailable = (e) => {
      if (e.data.size) chunks.push(e.data);
    };
    this.recorder.onstop = () => {
      const mime = this.recorder?.mimeType || type || "audio/webm";
      const discard = this.discard;
      this.cleanup();
      if (!discard) onRecorded(new Blob(chunks, { type: mime }));
    };
    this.recorder.start(250);
    const started = Date.now();
    let heardSpeech = false,
      lastSpeech = started;
    if (detectSilence) {
      this.audio = new AudioContext();
      const analyser = this.audio.createAnalyser();
      analyser.fftSize = 1024;
      this.audio.createMediaStreamSource(this.stream).connect(analyser);
      const samples = new Uint8Array(analyser.fftSize);
      this.timer = setInterval(() => {
        analyser.getByteTimeDomainData(samples);
        const rms = Math.sqrt(
          samples.reduce((sum, n) => sum + ((n - 128) / 128) ** 2, 0) /
            samples.length,
        );
        if (rms > 0.025) {
          heardSpeech = true;
          lastSpeech = Date.now();
        }
        if (
          (heardSpeech && Date.now() - lastSpeech > 1500) ||
          Date.now() - started > 60000
        )
          this.stop();
      }, 100);
    } else {
      this.timer = setInterval(() => {
        if (Date.now() - started > 60000) this.stop();
      }, 1000);
    }
    return true;
  }

  stop(discard = false) {
    this.generation += 1;
    this.discard = discard;
    if (this.recorder?.state === "recording") this.recorder.stop();
    else this.cleanup();
  }

  cleanup() {
    if (this.timer) clearInterval(this.timer);
    this.timer = null;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    void this.audio?.close();
    this.audio = null;
    this.recorder = null;
  }
}

export function speak(text: string, onEnd?: () => void, language = "en-US") {
  if (!("speechSynthesis" in window)) {
    onEnd?.();
    return;
  }
  window.speechSynthesis.cancel();
  const plain = text
    .replace(/```[\s\S]*?```/g, "Code is shown in the conversation.")
    .replace(/[#*_`]/g, "");
  const utterance = new SpeechSynthesisUtterance(plain);
  utterance.lang = language;
  const replyVoice = window.speechSynthesis
    .getVoices()
    .find((voice) =>
      voice.lang.toLowerCase().startsWith(language.split("-")[0].toLowerCase()),
    );
  if (replyVoice) utterance.voice = replyVoice;
  utterance.onend = () => onEnd?.();
  utterance.onerror = () => onEnd?.();
  window.speechSynthesis.speak(utterance);
}
