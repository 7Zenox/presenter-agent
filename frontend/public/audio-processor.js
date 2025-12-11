class AudioProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.bufferSize = 2400;
    this.buffer = new Float32Array(this.bufferSize);
    this.bufferIndex = 0;
    this.port.postMessage({ type: 'log', message: 'AudioProcessor initialized' });
  }

  process(inputs, outputs, parameters) {
    const input = inputs[0];
    if (!input || !input.length) return true;
    
    const channelData = input[0];
    
    // Fill buffer
    for (let i = 0; i < channelData.length; i++) {
      this.buffer[this.bufferIndex++] = channelData[i];
      
      // When buffer is full, flush
      if (this.bufferIndex >= this.bufferSize) {
        this.flush();
      }
    }
    
    return true;
  }

  flush() {
    // Clone buffer to send
    const dataToSend = this.buffer.slice(0, this.bufferIndex);
    this.port.postMessage({ type: 'audio', data: dataToSend });
    this.bufferIndex = 0;
  }
}

registerProcessor('audio-processor', AudioProcessor);
