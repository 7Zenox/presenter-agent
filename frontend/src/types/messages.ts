/** TypeScript types for WebSocket messages */

// Client → Server messages
export interface ClientConfig {
  type: "CLIENT_CONFIG";
  topic: string;
  voice?: string;
  lang?: string;
}

export interface ClientAudio {
  type: "CLIENT_AUDIO";
  encoding?: string;
  sampleRate?: number;
  data: string; // base64 encoded audio
}

export interface ClientInterrupt {
  type: "CLIENT_INTERRUPT";
}

export interface ClientControl {
  type: "CLIENT_CONTROL";
  command: "NEXT_SLIDE" | "PREV_SLIDE" | "GOTO_SLIDE" | "END_SESSION";
  index?: number;
}

export interface ClientText {
  type: "CLIENT_TEXT";
  text: string;
}

export interface ClientUploadPPT {
  type: "CLIENT_UPLOAD_PPT";
  filename: string;
  data: string; // base64 encoded PowerPoint file
  topic?: string;
}

// Server → Client messages
export interface ServerReady {
  type: "SERVER_READY";
  sessionId: string;
}

export interface ServerTranscript {
  type: "SERVER_TRANSCRIPT";
  role: "user" | "assistant";
  text: string;
  final: boolean;
}

export interface ServerAudio {
  type: "SERVER_AUDIO";
  data: string; // base64 encoded audio
  sequence: number;
}

export interface ServerSlideEvent {
  type: "SERVER_SLIDE_EVENT";
  event: "SLIDE_NEXT" | "SLIDE_PREV" | "SLIDE_JUMP" | "SLIDE_RESTORE";
  index: number;
}

export interface ServerState {
  type: "SERVER_STATE";
  currentSlideIndex: number;
  primarySlideIndex: number;
  slideCursor: number;
}

export interface ServerEnd {
  type: "SERVER_END";
  reason: string;
}

export interface ServerError {
  type: "SERVER_ERROR";
  message: string;
}

export interface ServerSlides {
  type: "SERVER_SLIDES";
  slides: Array<{
    id: number;
    title: string;
    bullets: string[];
  }>;
}

export interface ServerInterrupt {
  type: "SERVER_INTERRUPT";
}

export type ClientMessage = ClientConfig | ClientUploadPPT | ClientAudio | ClientInterrupt | ClientControl | ClientText;
export type ServerMessage = ServerReady | ServerTranscript | ServerAudio | ServerSlideEvent | ServerState | ServerEnd | ServerError | ServerSlides | ServerInterrupt;

