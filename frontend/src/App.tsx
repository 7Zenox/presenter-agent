import { useState, useEffect, useRef, useCallback } from 'react'
import { MessageSquare, Loader2, Upload, Presentation, ChevronLeft, ChevronRight } from 'lucide-react'
import { AudioManager } from './utils/audio-manager'
import './App.css'

interface Message {
  role: 'user' | 'assistant';
  text: string;
}

interface Slide {
  index: number;
  title: string;
  content: string;
  notes: string;
}

function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const [currentSlide, setCurrentSlide] = useState<Slide | null>(null)
  const [totalSlides, setTotalSlides] = useState<number>(0)
  const [isUploading, setIsUploading] = useState(false)
  const audioManager = useRef<AudioManager | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
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
        }, {
            onSlideChanged: (slide: Slide, total: number) => {
                console.log('[App] Slide changed callback:', slide, total);
                setCurrentSlide(slide);
                setTotalSlides(total);
                // Scroll to slide container when slide changes
                setTimeout(() => {
                    const slideContainer = document.querySelector('.slide-container');
                    if (slideContainer) {
                        slideContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    }
                }, 100);
            }
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

  const navigateSlide = useCallback((action: 'next' | 'prev' | 'jump', slideIndex?: number) => {
    if (!audioManager.current?.ws || audioManager.current.ws.readyState !== WebSocket.OPEN) {
      console.warn('WebSocket not connected');
      return;
    }

    const message: any = {
      type: 'navigate_slide',
      action,
    };

    if (action === 'jump' && slideIndex !== undefined) {
      message.slide_index = slideIndex;
    }

    audioManager.current.ws.send(JSON.stringify(message));
  }, []);

  // Keyboard navigation
  useEffect(() => {
    const handleKeyPress = (event: KeyboardEvent) => {
      if (!currentSlide || totalSlides === 0) return;
      
      if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
        event.preventDefault();
        navigateSlide('prev');
      } else if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
        event.preventDefault();
        navigateSlide('next');
      }
    };

    window.addEventListener('keydown', handleKeyPress);
    return () => window.removeEventListener('keydown', handleKeyPress);
  }, [currentSlide, totalSlides, navigateSlide]);

  const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch('http://localhost:8000/api/upload-presentation', {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        throw new Error('Failed to upload presentation');
      }

      const result = await response.json();
      console.log('Presentation uploaded:', result);
      
      // Set initial slide
      if (result.slides && result.slides.length > 0) {
        setCurrentSlide(result.slides[0]);
        setTotalSlides(result.total_slides);
      }

      // Trigger AI to start presenting automatically
      const sendStartPresentation = () => {
        if (audioManager.current?.ws?.readyState === WebSocket.OPEN) {
          console.log('[App] Sending start_presentation message');
          audioManager.current.ws.send(JSON.stringify({
            type: 'start_presentation'
          }));
          return true;
        }
        return false;
      };

      // Try immediately if connected
      if (!sendStartPresentation()) {
        // If not connected yet, wait for connection then start
        console.log('[App] WebSocket not ready, waiting for connection...');
        let attempts = 0;
        const maxAttempts = 20; // 10 seconds total (20 * 500ms)
        
        const checkConnection = setInterval(() => {
          attempts++;
          if (sendStartPresentation()) {
            console.log('[App] start_presentation sent successfully');
            clearInterval(checkConnection);
          } else if (attempts >= maxAttempts) {
            console.warn('[App] Failed to send start_presentation after', maxAttempts, 'attempts');
            clearInterval(checkConnection);
          }
        }, 500);
      }
    } catch (error) {
      console.error('Error uploading presentation:', error);
      alert('Failed to upload presentation. Please try again.');
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div className="container">
      <header>
        <h1>PowerPoint Presenter Agent</h1>
        <div className="header-actions">
          <input
            ref={fileInputRef}
            type="file"
            accept=".pptx,.ppt"
            onChange={handleFileUpload}
            style={{ display: 'none' }}
          />
          <button
            className="upload-button"
            onClick={() => fileInputRef.current?.click()}
            disabled={isUploading}
          >
            <Upload size={16} />
            {isUploading ? 'Uploading...' : 'Upload PowerPoint'}
          </button>
          <div className="status-indicator">
              {isConnected ? (
                  <span className="status-badge connected">● Live Listening</span>
              ) : (
                  <span className="status-badge disconnected">● Connecting...</span>
              )}
          </div>
        </div>
      </header>

      {currentSlide && (
        <div className="slide-container">
          <div className="slide-header">
            <Presentation size={20} />
            <span>Slide {currentSlide.index + 1} of {totalSlides}</span>
            <div className="slide-navigation">
              <button
                className="nav-button"
                onClick={() => navigateSlide('prev')}
                disabled={currentSlide.index === 0}
                title="Previous slide (← or ↑)"
              >
                <ChevronLeft size={20} />
              </button>
              <button
                className="nav-button"
                onClick={() => navigateSlide('next')}
                disabled={currentSlide.index === totalSlides - 1}
                title="Next slide (→ or ↓)"
              >
                <ChevronRight size={20} />
              </button>
            </div>
          </div>
          <div className="slide-content">
            <h2>{currentSlide.title}</h2>
            <div className="slide-body">
              {currentSlide.content.split('\n').map((line, idx) => (
                line.trim() && <p key={idx}>{line}</p>
              ))}
            </div>
            {currentSlide.notes && (
              <div className="slide-notes">
                <strong>Notes:</strong> {currentSlide.notes}
              </div>
            )}
          </div>
        </div>
      )}

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
