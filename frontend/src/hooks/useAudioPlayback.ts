import { useRef, useCallback } from "react";

export function useAudioPlayback() {
  const audioContextRef = useRef<AudioContext | null>(null);
  const audioQueueRef = useRef<AudioBuffer[]>([]);
  const isPlayingRef = useRef(false);
  const currentSourceRef = useRef<AudioBufferSourceNode | null>(null);
  const shouldStopRef = useRef(false);

  const initAudioContext = useCallback(() => {
    if (!audioContextRef.current) {
      audioContextRef.current = new (window.AudioContext || (window as any).webkitAudioContext)();
    }
    return audioContextRef.current;
  }, []);

  const stopPlayback = useCallback(() => {
    console.log("[AudioPlayback] 🛑 Stopping playback immediately");
    
    // Signal playQueue to stop FIRST (before clearing queue)
    shouldStopRef.current = true;
    
    // Stop current playing source IMMEDIATELY
    if (currentSourceRef.current) {
      try {
        console.log("[AudioPlayback] Stopping current audio source");
        currentSourceRef.current.stop(0); // Stop immediately (0 = now)
        currentSourceRef.current.disconnect();
      } catch (e) {
        // Ignore errors if already stopped or not started
        console.log(`[AudioPlayback] Error stopping source (expected if already stopped): ${e}`);
      }
      currentSourceRef.current = null;
    }
    
    // Clear the queue
    const clearedCount = audioQueueRef.current.length;
    audioQueueRef.current = [];
    
    // Mark as not playing
    isPlayingRef.current = false;
    
    if (clearedCount > 0) {
      console.log(`[AudioPlayback] Cleared ${clearedCount} audio buffers from queue`);
    }
    console.log("[AudioPlayback] ✅ Playback stopped");
  }, []);

  const playAudio = useCallback(async (base64Data: string) => {
    try {
      // Check if we should stop before processing
      if (shouldStopRef.current) {
        console.log("[AudioPlayback] Ignoring audio - playback stopped");
        return;
      }
      
      console.log(`[AudioPlayback] Received audio data: ${base64Data.length} chars`);
      const audioContext = initAudioContext();
      
      // Decode base64 to ArrayBuffer
      const binaryString = atob(base64Data);
      const bytes = new Uint8Array(binaryString.length);
      for (let i = 0; i < binaryString.length; i++) {
        bytes[i] = binaryString.charCodeAt(i);
      }

      console.log(`[AudioPlayback] Decoded to ${bytes.length} bytes`);
      
      // Live API sends PCM audio at 24kHz, 16-bit, mono
      // Create buffer manually for PCM format
      const sampleRate = 24000;
      const numChannels = 1;
      const length = bytes.length / 2; // 16-bit = 2 bytes per sample
      
      if (length === 0) {
        console.warn("[AudioPlayback] Empty audio data");
        return;
      }
      
      // Check again after processing (might have been stopped during decode)
      if (shouldStopRef.current) {
        console.log("[AudioPlayback] Ignoring audio - playback stopped during processing");
        return;
      }
      
      const audioBuffer = audioContext.createBuffer(numChannels, length, sampleRate);
      const channelData = audioBuffer.getChannelData(0);
      
      // Convert bytes to float32 samples (-1.0 to 1.0)
      // Handle little-endian 16-bit PCM
      for (let i = 0; i < length; i++) {
        const byte1 = bytes[i * 2];
        const byte2 = bytes[i * 2 + 1];
        // Little-endian signed 16-bit
        let sample = (byte1 | (byte2 << 8));
        if (sample > 32767) sample -= 65536; // Convert to signed
        channelData[i] = sample / 32768.0;
      }
      
      console.log(`[AudioPlayback] Created audio buffer: ${length} samples at ${sampleRate}Hz`);
      
      // Final check before adding to queue
      if (shouldStopRef.current) {
        console.log("[AudioPlayback] Ignoring audio - playback stopped before queueing");
        return;
      }
      
      audioQueueRef.current.push(audioBuffer);

      // Play if not already playing
      if (!isPlayingRef.current) {
        console.log("[AudioPlayback] Starting playback queue");
        shouldStopRef.current = false;
        playQueue();
      }
    } catch (error) {
      console.error("[AudioPlayback] Error playing audio:", error);
    }
  }, [initAudioContext]);

  const playQueue = useCallback(async () => {
    if (isPlayingRef.current || audioQueueRef.current.length === 0) {
      return;
    }

    isPlayingRef.current = true;
    const audioContext = initAudioContext();

    while (audioQueueRef.current.length > 0 && !shouldStopRef.current) {
      // Check before processing each buffer
      if (shouldStopRef.current) {
        console.log("[AudioPlayback] Playback stopped - clearing queue");
        audioQueueRef.current = [];
        break;
      }
      
      const buffer = audioQueueRef.current.shift()!;
      const source = audioContext.createBufferSource();
      source.buffer = buffer;
      source.connect(audioContext.destination);
      
      currentSourceRef.current = source;

      // Create a promise that can be resolved immediately if stopped
      let resolvePromise: () => void;
      const playPromise = new Promise<void>((resolve) => {
        resolvePromise = resolve;
        source.onended = () => {
          currentSourceRef.current = null;
          resolve();
        };
        
        // Check if we should stop before starting
        if (shouldStopRef.current) {
          try {
            source.stop();
          } catch (e) {
            // Ignore if already stopped
          }
          currentSourceRef.current = null;
          resolve();
          return;
        }
        
        source.start();
      });
      
      await playPromise;
      
      // Check if we should stop between chunks
      if (shouldStopRef.current) {
        console.log("[AudioPlayback] Playback interrupted between chunks");
        break;
      }
    }

    isPlayingRef.current = false;
    currentSourceRef.current = null;
    
    // If queue is empty and we're done playing, notify parent that AI stopped
    if (audioQueueRef.current.length === 0) {
      // This will be handled by the parent component tracking aiPlayingRef
    }
  }, [initAudioContext]);

  return {
    playAudio,
    stopPlayback,
  };
}


