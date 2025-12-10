import { useState, useEffect, useCallback, useRef } from "react";
import { useLiveSession } from "./hooks/useLiveSession";
import { useAudioCapture } from "./hooks/useAudioCapture";
import { useAudioPlayback } from "./hooks/useAudioPlayback";
import { SlideContainer } from "./components/SlideContainer";
import { ControlPanel } from "./components/ControlPanel";
import type { Slide } from "./types/slide";
import "./App.css";

function App() {
  const { playAudio, stopPlayback } = useAudioPlayback();
  const [slides, setSlides] = useState<Slide[]>([]);
  // Removed: userSpeaking tracking - Live API handles interruptions automatically
  const lastAudioTimeRef = useRef<number>(0);
  const aiPlayingRef = useRef<boolean>(false); // Track if AI is currently playing (for UI only)
  
  // Handle audio received from server
  const handleAudioReceived = useCallback((audioData: string) => {
    // Always play AI audio - Live API will automatically stop when user speaks
    if (!aiPlayingRef.current) {
      console.log("[App] 🔊 AI started playing");
    }
    aiPlayingRef.current = true; // Mark AI as playing
    playAudio(audioData);
  }, [playAudio]);
  
  const { ready, currentSlide, sendJson, error, slides: serverSlides } = useLiveSession(handleAudioReceived, stopPlayback);
  const { startRecording, isRecording } = useAudioCapture();

  // Update slides when server sends them (via SERVER_STATE or other messages)
  useEffect(() => {
    if (serverSlides.length > 0) {
      setSlides(serverSlides);
    }
  }, [serverSlides]);

  // Handle audio data from capture - start recording automatically when ready
  useEffect(() => {
    if (ready && !isRecording) {
      // Reset tracking when starting new recording
      lastAudioTimeRef.current = 0;
      
      // Start recording automatically when session is ready
      startRecording((data) => {
        const now = Date.now();
        
        // DEBUG: Track chunk count
        if (!window._audioChunkCount) window._audioChunkCount = 0;
        window._audioChunkCount++;
        const chunkNum = window._audioChunkCount;
        const shouldLog = chunkNum <= 20 || chunkNum % 10 === 0;
        
        if (shouldLog) {
          console.log(`[App] 📤 Chunk #${chunkNum}: ${data.length} chars base64`);
        }
        
        // Filter out very small chunks (likely silence)
        const isNonSilentAudio = data.length > 200; // Basic silence filter
        
        if (!isNonSilentAudio) {
          if (shouldLog) {
            console.log(`[App] 🔇 Silent chunk: ${data.length} chars (threshold: 200) - skipping`);
          }
          return; // Skip silent chunks
        }
        
        // SIMPLIFIED: Just send all non-silent audio to backend
        // Let Live API's VAD handle speech detection and interruption
        // Don't try to detect speech or interrupt on frontend
        if (shouldLog) {
          console.log(`[App] 📨 Sending CLIENT_AUDIO to backend: ${data.length} chars (Live API will handle VAD)`);
        }
        
        sendJson({
          type: "CLIENT_AUDIO",
          encoding: "linear16",
          sampleRate: 16000,
          data,
        });
        
        lastAudioTimeRef.current = now;
      });
    }
  }, [ready, isRecording, sendJson, startRecording, stopPlayback]);
  
  // Removed: userSpeaking reset logic - Live API handles this automatically

  const handleUploadPPT = async (file: File) => {
    try {
      // Read file as base64
      const reader = new FileReader();
      reader.onload = (e) => {
        const base64Data = (e.target?.result as string).split(",")[1]; // Remove data URL prefix
        
        sendJson({
          type: "CLIENT_UPLOAD_PPT",
          filename: file.name,
          data: base64Data,
          topic: file.name.replace(".pptx", "").replace(".ppt", ""),
        });
        
        // Note: Audio recording will start automatically after server sends SERVER_READY
        // The server will automatically begin presenting after parsing the PPT
      };
      reader.readAsDataURL(file);
    } catch (error) {
      console.error("Error uploading file:", error);
    }
  };

  // All interactions are now voice-controlled - no button handlers needed


  return (
    <div className="app">
      <header className="app-header">
        <h1>Voice Presentation Agent</h1>
        {error && <div className="error-banner">{error}</div>}
      </header>

      <main className="app-main">
        <ControlPanel
          ready={ready}
          onUploadPPT={handleUploadPPT}
          isRecording={isRecording}
        />

        {ready && (
          <div className="presentation-status">
            <p className="status-message">
              🎤 Voice-controlled presentation active. Speak naturally to interact - say "next slide", "previous slide", ask questions, or interrupt anytime.
            </p>
      </div>
        )}

        <SlideContainer slides={slides} currentSlideIndex={currentSlide} />
      </main>
      </div>
  );
}

export default App;
