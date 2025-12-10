import { useEffect, useRef, useState, useCallback } from "react";
import type { ServerMessage, ClientMessage } from "../types/messages";
import type { Slide } from "../types/slide";

const WS_URL = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws/live";

export function useLiveSession(
  onAudioReceived?: (audioData: string) => void,
  onStopPlayback?: () => void
) {
  const wsRef = useRef<WebSocket | null>(null);
  const [ready, setReady] = useState(false);
  const [currentSlide, setCurrentSlide] = useState(0);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [transcript, setTranscript] = useState<{ role: string; text: string }[]>([]);
  const [slides, setSlides] = useState<Slide[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Load voices when component mounts (needed for some browsers)
    if ("speechSynthesis" in window) {
      window.speechSynthesis.getVoices(); // Trigger voice loading
    }
    
    const ws = new WebSocket(WS_URL);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log("WebSocket connected");
      setError(null);
    };

    ws.onmessage = (event) => {
      try {
        const msg: ServerMessage = JSON.parse(event.data);
        
        // DEBUG: Log all message types
        if (msg.type !== "SERVER_AUDIO") {
          console.log(`[Frontend] 📨 Received ${msg.type} message`);
        }
        
        switch (msg.type) {
          case "SERVER_READY":
            console.log(`[Frontend] ✅ Session ready: ${msg.sessionId}`);
            setReady(true);
            setSessionId(msg.sessionId);
            // Presentation will start automatically - no user action needed
            break;
          
          case "SERVER_SLIDE_EVENT":
            if (
              msg.event === "SLIDE_JUMP" ||
              msg.event === "SLIDE_NEXT" ||
              msg.event === "SLIDE_PREV" ||
              msg.event === "SLIDE_RESTORE"
            ) {
              console.log(`[Frontend] 📊 Slide event: ${msg.event}, index: ${msg.index}`);
              setCurrentSlide(msg.index);
            }
            break;
          
          case "SERVER_STATE":
            console.log(`[Frontend] 📊 State update: slide ${msg.currentSlideIndex}`);
            setCurrentSlide(msg.currentSlideIndex);
            break;
          
          case "SERVER_SLIDES":
            console.log(`[Frontend] 📊 Received ${msg.slides.length} slides`);
            setSlides(msg.slides);
            break;
          
          case "SERVER_TRANSCRIPT":
            console.log(`[Frontend] 📝 Transcript [${msg.role}]: ${msg.text.substring(0, 100)}...`);
            setTranscript((prev) => [...prev, { role: msg.role, text: msg.text }]);
            break;
          
          case "SERVER_AUDIO":
            // Audio will be played by useAudioPlayback hook
            // Store audio data for playback
            if (!window._audioReceivedCount) window._audioReceivedCount = 0;
            window._audioReceivedCount++;
            const shouldLogAudio = window._audioReceivedCount <= 20 || window._audioReceivedCount % 10 === 0;
            
            if (shouldLogAudio) {
              console.log(`[Frontend] 🔊 Received SERVER_AUDIO #${window._audioReceivedCount}: ${msg.data.length} chars base64`);
            }
            
            if (onAudioReceived) {
              onAudioReceived(msg.data);
            } else {
              console.warn("[Frontend] ⚠️ No audio callback registered");
            }
            break;
          
          case "SERVER_INTERRUPT":
            console.log(`[Frontend] 🛑 SERVER_INTERRUPT received - stopping AI playback`);
            // Call the stopPlayback callback if provided
            if (onStopPlayback) {
              onStopPlayback();
            }
            break;
          
          case "SERVER_ERROR":
            console.error(`[Frontend] ❌ Error: ${msg.message}`);
            setError(msg.message);
            break;
          
          case "SERVER_END":
            console.log(`[Frontend] 🏁 Session ended`);
            setReady(false);
            break;
        }
      } catch (e) {
        console.error("[Frontend] ✗ Error parsing WebSocket message:", e);
      }
    };

    ws.onerror = (error) => {
      console.error("WebSocket error:", error);
      setError("WebSocket connection error");
    };

    ws.onclose = () => {
      console.log("WebSocket disconnected");
      setReady(false);
    };

    return () => {
      ws.close();
    };
  }, []);

  const sendJson = useCallback((payload: ClientMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      // DEBUG: Log sent messages (throttle audio messages)
      if (payload.type !== "CLIENT_AUDIO") {
        console.log(`[Frontend] 📤 Sending ${payload.type} message`);
      }
      wsRef.current.send(JSON.stringify(payload));
    } else {
      console.warn(`[Frontend] ⚠️ WebSocket not connected (state: ${wsRef.current?.readyState})`);
    }
  }, []);

  return {
    ready,
    currentSlide,
    sessionId,
    transcript,
    slides,
    error,
    sendJson,
  };
}

