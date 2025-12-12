export class AudioManager {
  private audioContext: AudioContext | null = null;
  private workletNode: AudioWorkletNode | null = null;
  public ws: WebSocket | null = null;
  private isRecording: boolean = false;
  private isStarting: boolean = false;
  private nextStartTime: number = 0;
  private stream: MediaStream | null = null;
  private reconnectAttempts: number = 0;
  private maxReconnectAttempts: number = 5;
  private reconnectTimeout: number | null = null;
  private shouldReconnect: boolean = true;
  private activeAudioSources: AudioBufferSourceNode[] = []; // Track active audio sources for interruption

  private onSlideChanged?: (slide: any, total: number) => void;

  constructor(
    private onTranscript: (text: string, role: string) => void,
    options?: { onSlideChanged?: (slide: any, total: number) => void }
  ) {
    this.onSlideChanged = options?.onSlideChanged;
  }

  async connect(): Promise<void> {
    return new Promise((resolve) => {
      this.ws = new WebSocket('ws://localhost:8000/ws');

      this.ws.onopen = () => {
        // Only reset reconnect attempts if connection stays open for a bit
        // Don't reset immediately to avoid reconnection loop
        setTimeout(() => {
          if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.reconnectAttempts = 0;
          }
        }, 2000); // Reset after 2 seconds of stable connection
        resolve();
      };

      this.ws.onerror = (error) => {
        console.error('[AudioManager] WebSocket error:', error);
        // Don't reject immediately - let onclose handle reconnection
      };

      this.ws.onmessage = async (event) => {
        try {
          const data = JSON.parse(event.data);
          // console.log('[AudioManager] Received message type:', data.type); // Verbose

          switch (data.type) {
            case 'audio':
              await this.playAudio(data.data);
              break;

            case 'text':
              this.onTranscript(data.text, data.role);
              break;

            case 'interrupted':
              this.clearAudioQueue();
              break;

            case 'response.started':
              // Could emit event for UI to show "speaking" indicator
              break;

            case 'response.done':
              // Could emit event for UI to hide "speaking" indicator
              break;

            case 'speech_started':
              // Clear audio queue when user starts speaking (interruption)
              this.clearAudioQueue();
              break;

            case 'speech_stopped':
              // Could emit event for UI to hide "listening" indicator
              break;

            case 'error':
              console.error('[AudioManager] Error from backend:', data.error);
              break;

            case 'response.created':
              break;

            case 'output_audio_buffer.started':
              break;

            case 'output_audio_buffer.speech_started':
              break;

            case 'output_audio_buffer.speech_stopped':
              break;

            case 'output_audio_buffer.interrupted':
              this.clearAudioQueue();
              break;

            case 'input_audio_buffer.committed':
              break;

            case 'slide_changed':
              if (this.onSlideChanged && data.slide) {
                // Ensure slide has index field
                const slideWithIndex = {
                  ...data.slide,
                  index: data.slide_index !== undefined ? data.slide_index : (data.slide.index || 0)
                };
                this.onSlideChanged(slideWithIndex, data.total_slides || 0);
              } else {
                console.warn('[AudioManager] slide_changed event missing slide data or callback');
              }
              break;

            default:
              // Unknown message types are handled silently
              break;
          }
        } catch (e) {
          console.error('[AudioManager] Error processing message:', e);
        }
      };

      this.ws.onclose = () => {
        // Clear the WebSocket reference
        this.ws = null;

        // Only stop recording if we're actually recording, not if we're still starting up
        if (this.isRecording && !this.isStarting) {
          // If we were recording, try to reconnect
          if (this.shouldReconnect && this.reconnectAttempts < this.maxReconnectAttempts) {
            this.attemptReconnect();
          } else {
            this.stopRecording();
          }
        } else if (this.isStarting) {
          // Don't clean up audioContext during startup disconnect
          // Just mark that we're disconnected and let startRecording handle it
          this.isStarting = false;
          // Only clean up stream if we have one, but keep audioContext
          if (this.stream) {
            this.stream.getTracks().forEach(track => track.stop());
            this.stream = null;
          }
          // Don't nullify audioContext - startRecording might still need it
          // Try to reconnect
          if (this.shouldReconnect && this.reconnectAttempts < this.maxReconnectAttempts) {
            this.attemptReconnect();
          }
        } else {
          // Not recording and not starting - try to reconnect
          if (this.shouldReconnect && this.reconnectAttempts < this.maxReconnectAttempts) {
            this.attemptReconnect();
          }
        }
      };
    });
  }

  private attemptReconnect() {
    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
    }

    this.reconnectAttempts++;
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts - 1), 10000); // Exponential backoff, max 10s

    this.reconnectTimeout = window.setTimeout(async () => {
      try {
        await this.connect();
        // If we have audio setup but lost connection, we're good now
        // If we don't have audio setup yet, startRecording will be called separately
      } catch (e) {
        console.error('[AudioManager] Reconnection failed:', e);
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
          this.attemptReconnect();
        } else {
          console.error('[AudioManager] Max reconnection attempts reached');
        }
      }
    }, delay);
  }

  public analyser: AnalyserNode | null = null; // Public so App can access it

  async startRecording() {
    if (this.isRecording) {
      console.warn('[AudioManager] Already recording');
      return;
    }

    this.isStarting = true;

    try {
      this.audioContext = new AudioContext({ sampleRate: 24000 });
    } catch (e) {
      console.warn('[AudioManager] Could not set sample rate to 24000, falling back to default', e);
      this.audioContext = new AudioContext();
    }

    // Create Analyser
    this.analyser = this.audioContext.createAnalyser();
    this.analyser.fftSize = 256; // 128 data points
    this.analyser.smoothingTimeConstant = 0.8;

    try {
      await this.audioContext.audioWorklet.addModule('/audio-processor.js');
    } catch (e) {
      console.error('[AudioManager] Failed to load audio worklet:', e);
      this.isStarting = false;
      throw e;
    }

    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch (e) {
      console.error('[AudioManager] Failed to get user media:', e);
      // Cleanup context if media fails
      if (this.audioContext) {
        await this.audioContext.close();
        this.audioContext = null;
      }
      this.isStarting = false;
      throw e;
    }

    // Check if audioContext was closed/nullified during async operations
    if (!this.audioContext || this.audioContext.state === 'closed') {
      console.warn('[AudioManager] AudioContext was closed during startup, recreating...');
      try {
        this.audioContext = new AudioContext({ sampleRate: 24000 });
        // Re-create analyser
        this.analyser = this.audioContext.createAnalyser();
        this.analyser.fftSize = 256;
      } catch (e) {
        console.warn('[AudioManager] Could not recreate AudioContext, falling back to default', e);
        this.audioContext = new AudioContext();
        this.analyser = this.audioContext.createAnalyser();
        this.analyser.fftSize = 256;
      }
    }

    if (!this.audioContext) {
      this.isStarting = false;
      throw new Error("AudioContext is null after getUserMedia");
    }

    const source = this.audioContext.createMediaStreamSource(this.stream);

    this.workletNode = new AudioWorkletNode(this.audioContext, 'audio-processor');

    this.workletNode.port.onmessage = (event) => {
      const { type, data } = event.data;

      if (type === 'log') {
        // Audio processor logs are handled silently
        return;
      }

      if (type === 'audio') {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
          // Convert Float32 to Int16
          const float32Data = data;
          const int16Data = this.float32ToInt16(float32Data);

          // Base64 encode
          const base64Data = this.arrayBufferToBase64(int16Data.buffer);

          try {
            this.ws.send(JSON.stringify({
              type: 'audio',
              data: base64Data
            }));
          } catch (e) {
            console.warn('[AudioManager] Failed to send audio chunk:', e);
          }
        } else {
          console.warn('[AudioManager] WebSocket not open, dropping audio chunk');
        }
      }
    };

    source.connect(this.workletNode);
    // Do not connect worklet to destination to avoid self-echo
    // this.workletNode.connect(this.audioContext.destination); 

    this.isRecording = true;
    this.isStarting = false; // Mark startup as complete

    // Ensure context is running (sometimes needed if created before gesture?)
    if (this.audioContext.state === 'suspended') {
      await this.audioContext.resume();
    }
  }

  stopRecording() {
    this.isStarting = false; // Clear startup flag
    this.shouldReconnect = false; // Stop reconnection attempts

    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.stream) {
      this.stream.getTracks().forEach(track => track.stop());
      this.stream = null;
    }

    if (this.workletNode) {
      this.workletNode.disconnect();
      this.workletNode = null;
    }

    if (this.audioContext) {
      // Don't nullify audioContext immediately if we want to reuse it, 
      // but for full stop we close it.
      // However, if stopRecording is called during startup failure cleanup, 
      // we need to be careful.
      if (this.audioContext.state !== 'closed') {
        this.audioContext.close();
      }
      this.audioContext = null;
      this.analyser = null;
    }

    this.isRecording = false;

    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  private float32ToInt16(float32Array: Float32Array): Int16Array {
    const int16Array = new Int16Array(float32Array.length);
    for (let i = 0; i < float32Array.length; i++) {
      const s = Math.max(-1, Math.min(1, float32Array[i]));
      int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return int16Array;
  }

  private arrayBufferToBase64(buffer: ArrayBuffer): string {
    let binary = '';
    const bytes = new Uint8Array(buffer);
    const len = bytes.byteLength;
    for (let i = 0; i < len; i++) {
      binary += String.fromCharCode(bytes[i]);
    }
    return window.btoa(binary);
  }

  private base64ToArrayBuffer(base64: string): ArrayBuffer {
    const binary_string = window.atob(base64);
    const len = binary_string.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {
      bytes[i] = binary_string.charCodeAt(i);
    }
    return bytes.buffer;
  }

  private async playAudio(base64Data: string) {
    if (!this.audioContext) {
      // If audio context is missing, we can't play.
      // It might be possible to re-initialize here, but usually it means we are stopped.
      return;
    }

    try {
      const arrayBuffer = this.base64ToArrayBuffer(base64Data);
      const int16Array = new Int16Array(arrayBuffer);
      const float32Array = new Float32Array(int16Array.length);

      for (let i = 0; i < int16Array.length; i++) {
        float32Array[i] = int16Array[i] / 32768.0;
      }

      // Check if context is valid before creating buffer
      if (this.audioContext.state === 'closed') return;

      const audioBuffer = this.audioContext.createBuffer(1, float32Array.length, 24000);
      audioBuffer.getChannelData(0).set(float32Array);

      const source = this.audioContext.createBufferSource();
      source.buffer = audioBuffer;

      // Connect to analyser if available, otherwise direct to destination
      if (this.analyser) {
        source.connect(this.analyser);
        this.analyser.connect(this.audioContext.destination);
      } else {
        source.connect(this.audioContext.destination);
      }

      // Track this source so we can stop it if interrupted
      this.activeAudioSources.push(source);

      // Clean up source when it finishes playing
      source.onended = () => {
        const index = this.activeAudioSources.indexOf(source);
        if (index > -1) {
          this.activeAudioSources.splice(index, 1);
        }
      };

      const currentTime = this.audioContext.currentTime;
      if (this.nextStartTime < currentTime) {
        this.nextStartTime = currentTime;
      }

      source.start(this.nextStartTime);
      this.nextStartTime += audioBuffer.duration;
    } catch (e) {
      console.error("[AudioManager] Error playing audio chunk:", e);
    }
  }

  private clearAudioQueue() {
    // Stop all currently playing audio sources
    const sourcesToStop = [...this.activeAudioSources]; // Copy array to avoid modification during iteration
    sourcesToStop.forEach((source) => {
      try {
        source.stop(); // Stop the source immediately (throws if already stopped/finished)
        source.disconnect(); // Disconnect from audio context
      } catch (e) {
        // Source may have already finished, been stopped, or not started yet
        // This is expected and fine - just continue
      }
    });

    // Clear the array
    this.activeAudioSources = [];

    // Reset timing for next audio
    if (this.audioContext) {
      this.nextStartTime = this.audioContext.currentTime;
    }
  }
}
