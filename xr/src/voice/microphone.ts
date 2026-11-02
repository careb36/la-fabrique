/**
 * The microphone as 16 kHz float frames.
 *
 * An AudioWorklet (its code inlined, so no extra file to serve) collects
 * the browser's 128-sample blocks into frames of 512, resampling when the
 * audio context does not run at 16 kHz, and hands them to the page, which
 * forwards them to the recognizer's worker. Echo cancellation and noise
 * suppression are asked of the browser: in a headset the speaker is next
 * to the microphone.
 */

export const MIC_SAMPLE_RATE = 16_000;
export const MIC_FRAME = 512;

const WORKLET = `
class Frames extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / ${MIC_SAMPLE_RATE};
    this.buffer = new Float32Array(${MIC_FRAME});
    this.filled = 0;
    this.phase = 0;
  }
  process(inputs) {
    const input = inputs[0] && inputs[0][0];
    if (!input) return true;
    if (this.ratio === 1) {
      this.push(input);
    } else {
      // Linear resampling to 16 kHz; enough for a voice detector and Whisper.
      const out = [];
      for (let t = this.phase; t < input.length - 1; t += this.ratio) {
        const i = Math.floor(t);
        out.push(input[i] + (input[i + 1] - input[i]) * (t - i));
      }
      this.phase = (this.phase + out.length * this.ratio) - input.length;
      if (this.phase < 0) this.phase = 0;
      this.push(Float32Array.from(out));
    }
    return true;
  }
  push(samples) {
    let at = 0;
    while (at < samples.length) {
      const n = Math.min(samples.length - at, this.buffer.length - this.filled);
      this.buffer.set(samples.subarray(at, at + n), this.filled);
      this.filled += n;
      at += n;
      if (this.filled === this.buffer.length) {
        this.port.postMessage(this.buffer, [this.buffer.buffer]);
        this.buffer = new Float32Array(${MIC_FRAME});
        this.filled = 0;
      }
    }
  }
}
registerProcessor('voice-frames', Frames);
`;

export type MicrophoneFailure = 'microphone' | 'unsupported';

/** Whether this page can capture the microphone at all. */
export function microphoneSupported(): boolean {
  const n = globalThis.navigator as Navigator | undefined;
  return !!n?.mediaDevices?.getUserMedia && typeof (globalThis as { AudioContext?: unknown }).AudioContext === 'function';
}

/**
 * Open the microphone and hand each 512-sample frame to `onFrame`. Resolves
 * to a function that closes it; rejects with a `MicrophoneFailure`.
 */
export async function openMicrophone(onFrame: (frame: Float32Array) => void): Promise<() => void> {
  if (!microphoneSupported()) throw new Error('unsupported' satisfies MicrophoneFailure);
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
  } catch {
    throw new Error('microphone' satisfies MicrophoneFailure);
  }
  let context: AudioContext;
  try {
    context = new AudioContext({ sampleRate: MIC_SAMPLE_RATE });
  } catch {
    // Some browsers refuse a rate: take theirs and resample in the worklet.
    context = new AudioContext();
  }
  const url = URL.createObjectURL(new Blob([WORKLET], { type: 'application/javascript' }));
  try {
    await context.audioWorklet.addModule(url);
  } finally {
    URL.revokeObjectURL(url);
  }
  const source = context.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(context, 'voice-frames', { numberOfInputs: 1, numberOfOutputs: 0 });
  node.port.onmessage = (e: MessageEvent<Float32Array>) => onFrame(e.data);
  source.connect(node);
  await context.resume();
  return () => {
    node.port.onmessage = null;
    source.disconnect();
    node.disconnect();
    for (const track of stream.getTracks()) track.stop();
    void context.close();
  };
}
