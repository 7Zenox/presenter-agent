import { useState, useEffect, useRef, useCallback } from 'react'
import { Upload, Presentation, ChevronLeft, ChevronRight } from 'lucide-react'
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
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const animationRef = useRef<number>()
  const isMounted = useRef(false);

  useEffect(() => {
    if (isMounted.current) return;
    isMounted.current = true;

    const initAudio = async () => {
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
          setCurrentSlide(slide);
          setTotalSlides(total);
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

    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current)
      }
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

  // Visualizer Animation
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    // Set canvas size
    const resizeCanvas = () => {
      canvas.width = 300;
      canvas.height = 300;
    };
    resizeCanvas();
    // window.addEventListener('resize', resizeCanvas);

    const particles: { x: number, y: number, z: number, baseX: number, baseY: number, baseZ: number }[] = [];
    const particleCount = 400;
    const radius = 80;

    // Initialize sphere particles
    for (let i = 0; i < particleCount; i++) {
      const theta = Math.random() * 2 * Math.PI;
      const phi = Math.acos((Math.random() * 2) - 1);
      const x = radius * Math.sin(phi) * Math.cos(theta);
      const y = radius * Math.sin(phi) * Math.sin(theta);
      const z = radius * Math.cos(phi);
      particles.push({ x, y, z, baseX: x, baseY: y, baseZ: z });
    }

    let angle = 0;

    const draw = () => {
      if (!audioManager.current?.analyser) {
        animationRef.current = requestAnimationFrame(draw);
        return;
      }

      const bufferLength = audioManager.current.analyser.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);
      audioManager.current.analyser.getByteFrequencyData(dataArray);

      // Calculate average volume
      let sum = 0;
      for (let i = 0; i < bufferLength; i++) {
        sum += dataArray[i];
      }
      const average = sum / bufferLength;
      const scale = 1 + (average / 256) * 1.5; // Scale factor based on volume

      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // Only rotate/move if there is audio playing (average > 10 is a small threshold for noise)
      if (average > 5) {
        angle += 0.01;
      }

      const centerX = canvas.width / 2;
      const centerY = canvas.height / 2;

      ctx.fillStyle = '#4ade80'; // Greenish particles
      ctx.fillStyle = 'rgba(100, 180, 255, 0.8)'; // Blueish

      particles.forEach(p => {
        // Rotate
        let x = p.baseX;
        let z = p.baseZ;

        // Rotate around Y
        const cos = Math.cos(angle);
        const sin = Math.sin(angle);
        const rx = x * cos - z * sin;
        const rz = x * sin + z * cos;

        // Expand based on audio
        const audioFactor = (average > 5) ? scale : 1;
        const finalX = rx * audioFactor;
        const finalY = p.baseY * audioFactor;
        const finalZ = rz * audioFactor;

        // Project to 2D
        const perspective = 300 / (300 + finalZ);
        const probX = centerX + finalX * perspective;
        const probY = centerY + finalY * perspective;
        const alpha = ((finalZ + radius) / (2 * radius)) * 0.8 + 0.2;

        if (average > 5) {
          ctx.beginPath();
          ctx.arc(probX, probY, 1.5, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(100, 180, 255, ${alpha})`;
          ctx.fill();
        } else {
          // Stop logic: user said "stop when there's no playback". 
          // We can either hide them or show them static. 
          // Let's show them static but faint or just hide. 
          // "create moving pixels... and stop when there's no playback".
          // This implies they should exist but stop moving, or disappear.
          // Let's keep them frozen and faint.
          ctx.beginPath();
          ctx.arc(probX, probY, 1, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(100, 180, 255, ${alpha * 0.3})`;
          ctx.fill();
        }
      });

      animationRef.current = requestAnimationFrame(draw);
    };

    draw();

    return () => {
      // window.removeEventListener('resize', resizeCanvas);
      if (animationRef.current) cancelAnimationFrame(animationRef.current);
    }
  }, []);

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
      // Allow navigation even without slides for dev/testing if needed, but safer with check
      if (!currentSlide && totalSlides === 0) return;

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

      if (result.slides && result.slides.length > 0) {
        setCurrentSlide(result.slides[0]);
        setTotalSlides(result.total_slides);
      }

      const sendStartPresentation = () => {
        if (audioManager.current?.ws?.readyState === WebSocket.OPEN) {
          audioManager.current.ws.send(JSON.stringify({
            type: 'start_presentation'
          }));
          return true;
        }
        return false;
      };

      if (!sendStartPresentation()) {
        let attempts = 0;
        const maxAttempts = 20;

        const checkConnection = setInterval(() => {
          attempts++;
          if (sendStartPresentation()) {
            clearInterval(checkConnection);
          } else if (attempts >= maxAttempts) {
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
    <div className="app-container">
      {/* Background Visuals */}
      <div className="ambient-glow glow-1"></div>
      <div className="ambient-glow glow-2"></div>

      <header className="app-header">
        <div className="logo-section">
          <Presentation className="logo-icon" size={24} />
          <h1>Synthio Presenter</h1>
        </div>

        <div className="header-controls">
          <div className="status-indicator">
            {isConnected ? (
              <span className="status-dot connected" title="Connected"></span>
            ) : (
              <span className="status-dot disconnected" title="Disconnected"></span>
            )}
          </div>

          <input
            ref={fileInputRef}
            type="file"
            accept=".pptx,.ppt"
            onChange={handleFileUpload}
            style={{ display: 'none' }}
          />
          <button
            className="btn-upload"
            onClick={() => fileInputRef.current?.click()}
            disabled={isUploading}
          >
            <Upload size={16} />
            {isUploading ? 'Uploading...' : 'Upload Deck'}
          </button>
        </div>
      </header>

      <main className="main-content">
        <div className="slide-viewer">
          {currentSlide ? (
            <>
              <h2 className="slide-title">{currentSlide.title}</h2>
              <div className="slide-body-content">
                {currentSlide.content.split('\n').map((line, idx) => (
                  line.trim() && <p key={idx}>{line}</p>
                ))}
              </div>
              {/* Navigation Overlays */}
              <button
                className="nav-arrow prev"
                onClick={() => navigateSlide('prev')}
                disabled={currentSlide.index === 0}
              >
                <ChevronLeft size={40} />
              </button>
              <button
                className="nav-arrow next"
                onClick={() => navigateSlide('next')}
                disabled={totalSlides > 0 && currentSlide.index === totalSlides - 1}
              >
                <ChevronRight size={40} />
              </button>
            </>
          ) : (
            <div className="empty-slide-state">
              <p>Upload a presentation to begin</p>
            </div>
          )}
        </div>

        {/* Visualizer Sphere */}
        <div className="visualizer-container">
          <canvas ref={canvasRef} className="visualizer-canvas"></canvas>
        </div>
      </main>

      <div className="active-quote">
        "Say Start presentation"
      </div>

    </div>
  )
}

export default App


