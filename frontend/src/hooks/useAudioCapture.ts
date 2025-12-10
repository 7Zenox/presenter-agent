import { useRef, useState, useCallback } from "react";

// AudioWorklet processor code (converts Float32 to Int16 PCM)
const AUDIO_WORKLET_PROCESSOR = `
class AudioProcessingWorklet extends AudioWorkletProcessor {
  // Send and clear buffer every 2048 samples
  // At 16kHz, this is about 8 times per second
  buffer = new Int16Array(2048);
  bufferWriteIndex = 0;

  constructor() {
    super();
  }

  process(inputs) {
    if (inputs[0] && inputs[0][0]) {
      const channel0 = inputs[0][0]; // Float32Array of samples
      this.processChunk(channel0);
    }
    return true;
  }

  sendAndClearBuffer() {
    this.port.postMessage({
      event: "chunk",
      data: {
        int16arrayBuffer: this.buffer.slice(0, this.bufferWriteIndex).buffer,
      },
    });
    this.bufferWriteIndex = 0;
  }

  processChunk(float32Array) {
    const l = float32Array.length;
    
    for (let i = 0; i < l; i++) {
      // Convert float32 (-1.0 to 1.0) to int16 (-32768 to 32767)
      const int16Value = Math.max(-32768, Math.min(32767, Math.round(float32Array[i] * 32768)));
      this.buffer[this.bufferWriteIndex++] = int16Value;
      
      if (this.bufferWriteIndex >= this.buffer.length) {
        this.sendAndClearBuffer();
      }
    }
  }
}

registerProcessor("audio-recorder-worklet", AudioProcessingWorklet);
`;

// Helper to create AudioContext with proper sample rate
// Based on reference implementation from live-api-web-console
async function createAudioContext(sampleRate: number): Promise<AudioContext> {
  // Wait for user interaction if needed (browser autoplay policy)
  const didInteract = new Promise<void>((resolve) => {
    window.addEventListener("pointerdown", () => resolve(), { once: true });
    window.addEventListener("keydown", () => resolve(), { once: true });
  });

  try {
    // Try to play a silent audio to unlock AudioContext
    const a = new Audio();
    a.src = "data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA";
    await a.play();
  } catch (e) {
    // If autoplay fails, wait for user interaction
    await didInteract;
  }

  // Try to create AudioContext with desired sample rate
  try {
    const ctx = new (window.AudioContext || (window as any).webkitAudioContext)({ sampleRate });
    if (ctx.state === "suspended") {
      await ctx.resume();
    }
    console.log(`[AudioCapture] ✅ Created AudioContext with sample rate: ${ctx.sampleRate}Hz (requested: ${sampleRate}Hz)`);
    return ctx;
  } catch (e) {
    // Fallback: create with default sample rate
    console.warn(`[AudioCapture] ⚠️ Could not create AudioContext with ${sampleRate}Hz, using default sample rate`);
    const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
    if (ctx.state === "suspended") {
      await ctx.resume();
    }
    console.log(`[AudioCapture] ✅ Created AudioContext with default sample rate: ${ctx.sampleRate}Hz`);
    // Note: If sample rate doesn't match, browser will resample automatically
    return ctx;
  }
}

// Helper to create worklet module URL from source code
function createWorkletModuleUrl(workletSrc: string): string {
  // workletSrc already contains the full worklet code including registerProcessor
  const script = new Blob([workletSrc], { type: "application/javascript" });
  return URL.createObjectURL(script);
}

// Convert ArrayBuffer to base64
function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return window.btoa(binary);
}

export function useAudioCapture() {
  const audioContextRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const workletRef = useRef<AudioWorkletNode | null>(null);
  const [isRecording, setIsRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const chunksSentRef = useRef(0);
  const lastChunkTimeRef = useRef(0);

  const startRecording = useCallback(async (onDataAvailable: (data: string) => void) => {
    try {
      // Get microphone stream
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      // Create AudioContext with 16kHz sample rate (required by Live API)
      const sampleRate = 16000;
      const audioContext = await createAudioContext(sampleRate);
      audioContextRef.current = audioContext;

      // Create MediaStreamAudioSourceNode
      const source = audioContext.createMediaStreamSource(stream);
      sourceRef.current = source;

      // Create worklet module URL
      const workletName = "audio-recorder-worklet";
      const workletUrl = createWorkletModuleUrl(AUDIO_WORKLET_PROCESSOR);

      // Load and create AudioWorkletNode
      console.log(`[AudioCapture] 📦 Loading AudioWorklet module...`);
      try {
        await audioContext.audioWorklet.addModule(workletUrl);
        console.log(`[AudioCapture] ✅ AudioWorklet module loaded successfully`);
      } catch (err) {
        console.error(`[AudioCapture] ❌ Failed to load AudioWorklet module:`, err);
        throw new Error(`Failed to load AudioWorklet: ${err instanceof Error ? err.message : String(err)}`);
      }
      
      const worklet = new AudioWorkletNode(audioContext, workletName);
      workletRef.current = worklet;
      console.log(`[AudioCapture] ✅ AudioWorkletNode created`);

      // Handle messages from worklet (PCM16 chunks)
      worklet.port.onmessage = (ev: MessageEvent) => {
        const arrayBuffer = ev.data?.data?.int16arrayBuffer;
        
        if (arrayBuffer && arrayBuffer.byteLength > 0) {
          chunksSentRef.current++;
          const shouldLog = chunksSentRef.current <= 20 || chunksSentRef.current % 10 === 0;

          if (shouldLog) {
            console.log(`[AudioCapture] 📦 Chunk #${chunksSentRef.current}: ${arrayBuffer.byteLength} bytes (PCM16)`);
          }

          // Convert PCM16 ArrayBuffer to base64
          const base64 = arrayBufferToBase64(arrayBuffer);

          const now = Date.now();
          const timeSinceLastChunk = now - lastChunkTimeRef.current;
          lastChunkTimeRef.current = now;

          if (shouldLog) {
            console.log(`[AudioCapture] ✅ Sending chunk #${chunksSentRef.current}: ${arrayBuffer.byteLength} bytes PCM16 → ${base64.length} chars base64, interval: ${timeSinceLastChunk}ms`);
          }

          onDataAvailable(base64);
        }
      };

      // Connect source to worklet
      source.connect(worklet);

      setIsRecording(true);
      setError(null);
      chunksSentRef.current = 0;
      lastChunkTimeRef.current = Date.now();
      console.log("[AudioCapture] Started recording with AudioWorklet (PCM16 @ 16kHz)");
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : "Failed to start recording";
      setError(errorMessage);
      console.error("Error starting audio capture:", err);
      
      // Cleanup on error
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
      }
      if (sourceRef.current) {
        sourceRef.current.disconnect();
        sourceRef.current = null;
      }
      if (workletRef.current) {
        workletRef.current.disconnect();
        workletRef.current = null;
      }
      if (audioContextRef.current) {
        await audioContextRef.current.close();
        audioContextRef.current = null;
      }
    }
  }, []);

  const stopRecording = useCallback(async () => {
    if (sourceRef.current) {
      sourceRef.current.disconnect();
      sourceRef.current = null;
    }
    if (workletRef.current) {
      workletRef.current.disconnect();
      workletRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    if (audioContextRef.current) {
      await audioContextRef.current.close();
      audioContextRef.current = null;
    }
    setIsRecording(false);
    console.log("[AudioCapture] Stopped recording");
  }, []);

  return {
    startRecording,
    stopRecording,
    isRecording,
    error,
  };
}


