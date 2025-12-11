import { useState, useEffect, useRef } from 'react'
import { MessageSquare, Loader2 } from 'lucide-react'
import { AudioManager } from './utils/audio-manager'
import './App.css'

interface Message {
  role: 'user' | 'assistant';
  text: string;
}

function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const audioManager = useRef<AudioManager | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  // Use a ref to track mounting to prevent double-initialization in React Strict Mode
  const isMounted = useRef(false);

  useEffect(() => {
    if (isMounted.current) return;
    isMounted.current = true;

    // Auto-start on mount
    const initAudio = async () => {
        // Prevent multiple initializations
        if (audioManager.current) return;

        audioManager.current = new AudioManager((text, role) => {
            setMessages(prev => {
                const lastMsg = prev[prev.length - 1];
                if (lastMsg && lastMsg.role === role) {
                    return [...prev.slice(0, -1), { ...lastMsg, text: lastMsg.text + text }]
                }
                return [...prev, { role: role as 'user' | 'assistant', text }]
            })
        });

        try {
            await audioManager.current.connect();
            await audioManager.current.startRecording();
            setIsConnected(true);
        } catch (e) {
            console.error('Failed to start audio:', e);
            setIsConnected(false);
        }
    };

    initAudio();

    // Cleanup on unmount
    return () => {
      // In development (Strict Mode), effects run twice. 
      // We want to be careful not to destroy the connection if we intend to keep it, 
      // but usually we should cleanup. 
      // However, the issue here is the double mount/unmount cycle in Dev.
      // If we unmount immediately, we kill the socket.
      
      if (audioManager.current) {
        audioManager.current.stopRecording()
        audioManager.current = null;
      }
      setIsConnected(false);
      isMounted.current = false;
    };
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  return (
    <div className="container">
      <header>
        <h1>Voice Agent</h1>
        <div className="status-indicator">
            {isConnected ? (
                <span className="status-badge connected">● Live Listening</span>
            ) : (
                <span className="status-badge disconnected">● Connecting...</span>
            )}
        </div>
      </header>

      <div className="chat-container">
        {messages.length === 0 ? (
          <div className="empty-state">
            {isConnected ? <MessageSquare size={48} /> : <Loader2 size={48} className="spin" />}
            <p>{isConnected ? "Listening... Start speaking!" : "Connecting to server..."}</p>
          </div>
        ) : (
          messages.map((msg, idx) => (
            <div key={idx} className={`message ${msg.role}`}>
              <div className="message-content">
                <strong>{msg.role === 'user' ? 'You' : 'Assistant'}</strong>
                <p>{msg.text}</p>
              </div>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>
      
      {/* Hidden start button overlay for auto-play policy if needed */}
      {!isConnected && (
         <div className="start-overlay" onClick={() => window.location.reload()}>
            <p>Click to start if not connecting automatically</p>
         </div>
      )}
    </div>
  )
}

export default App
