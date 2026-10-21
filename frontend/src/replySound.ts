/** A short local chime. Unlock on a normal user gesture for browser autoplay rules. */
export class ReplySound {
  private context: AudioContext | null = null;
  private pending = false;
  private disposed = false;
  private lastPlayed = -Infinity;

  constructor(private createContext = () => new AudioContext()) {}

  unlock() {
    if (this.disposed) return;
    try {
      this.context ??= this.createContext();
      if (this.context.state === "closed") return;
      if (this.context.state === "running") this.flush();
      else
        void this.context
          .resume()
          .then(() => this.flush())
          .catch(() => undefined);
    } catch {
      // Unsupported or blocked audio must never interfere with the visual alert.
    }
  }

  play() {
    if (this.disposed) return;
    this.pending = true;
    if (this.context) this.unlock();
  }

  /** Native alerts use the device sound if browser audio is not already unlocked. */
  playIfReady(): boolean {
    if (this.disposed || this.context?.state !== "running") return false;
    this.pending = true;
    return this.flush();
  }

  cancelPending() {
    this.pending = false;
  }

  resume() {
    if (this.context) this.unlock();
  }

  private flush(): boolean {
    const context = this.context;
    if (this.disposed || !this.pending || context?.state !== "running")
      return false;
    this.pending = false;
    const at = context.currentTime;
    // Several simultaneous completions produce one gentle chime, not a burst.
    if (at - this.lastPlayed < 0.8) return true;
    try {
      [660, 880].forEach((frequency, index) => {
        const tone = context.createOscillator(),
          gain = context.createGain();
        const start = at + index * 0.16;
        tone.type = "sine";
        tone.frequency.value = frequency;
        gain.gain.setValueAtTime(0, start);
        gain.gain.linearRampToValueAtTime(0.12, start + 0.015);
        gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.32);
        tone.connect(gain);
        gain.connect(context.destination);
        tone.onended = () => {
          tone.disconnect();
          gain.disconnect();
        };
        tone.start(start);
        tone.stop(start + 0.34);
      });
      this.lastPlayed = at;
      return true;
    } catch {
      // An audio device disappearing is not a chat failure.
      return false;
    }
  }

  dispose() {
    this.disposed = true;
    this.pending = false;
    if (this.context) void this.context.close().catch(() => undefined);
    this.context = null;
  }
}

/** Ignore expired requests so a suspended tab cannot sound again after the OS alert. */
export function playNotificationSound(
  data: unknown,
  userId: string,
  sound: ReplySound | null,
  enabled: boolean,
): boolean {
  if (!data || typeof data !== "object") return false;
  const request = data as Record<string, unknown>;
  if (
    !enabled ||
    request.type !== "duka-notification-sound" ||
    request.userId !== userId ||
    typeof request.messageId !== "string" ||
    !/^[a-zA-Z0-9_-]{1,128}$/.test(request.messageId) ||
    typeof request.expiresAt !== "number" ||
    !Number.isFinite(request.expiresAt) ||
    request.expiresAt <= Date.now() ||
    request.expiresAt > Date.now() + 1000
  )
    return false;
  return sound?.playIfReady() ?? false;
}
