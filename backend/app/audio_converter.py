"""Audio format conversion utilities."""
import io
import subprocess
import sys
from collections import defaultdict

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False
    print("[AudioConverter] Warning: pydub not available. Will use ffmpeg directly.")

# Buffer for WebM chunks per session (MediaRecorder sends partial chunks)
_webm_buffers = defaultdict(bytes)

def webm_to_pcm(webm_data: bytes, sample_rate: int = 16000, session_id: str = None) -> bytes:
    """
    Convert WebM audio to PCM format.
    
    MediaRecorder sends partial WebM chunks that can't be decoded individually.
    We buffer chunks until we have enough data to decode.
    
    Args:
        webm_data: WebM audio bytes (can be partial chunks from MediaRecorder)
        sample_rate: Target sample rate (default 16000 for Live API)
        session_id: Optional session ID for buffering (if None, uses single buffer)
    
    Returns:
        PCM audio bytes (16-bit, mono, little-endian), or empty bytes if chunk is partial
    """
    if len(webm_data) == 0:
        return b""
    
    # Buffer chunks per session
    buffer_key = session_id if session_id else "default"
    _webm_buffers[buffer_key] += webm_data
    
    # Try to decode buffered data
    buffered_data = _webm_buffers[buffer_key]
    
    # Minimum size to attempt decoding (WebM needs headers)
    MIN_WEBM_SIZE = 1000  # ~1KB minimum for WebM header
    
    if len(buffered_data) < MIN_WEBM_SIZE:
        # Not enough data yet - buffer and return empty
        return b""
    
    # Try using ffmpeg directly
    try:
        ffmpeg_cmd = [
            "ffmpeg",
            "-f", "webm",           # Input format
            "-i", "pipe:0",         # Read from stdin
            "-f", "s16le",          # Output: signed 16-bit little-endian PCM
            "-ar", str(sample_rate), # Sample rate
            "-ac", "1",             # Mono
            "-loglevel", "error",   # Suppress verbose output
            "-"                     # Output to stdout
        ]
        
        process = subprocess.Popen(
            ffmpeg_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        stdout, stderr = process.communicate(input=buffered_data, timeout=5)
        
        if process.returncode == 0:
            # Success! Clear buffer and return PCM
            _webm_buffers[buffer_key] = b""
            return stdout
        else:
            # Decoding failed - might need more data
            stderr_str = stderr.decode('utf-8', errors='ignore')
            if "EBML header parsing failed" in stderr_str or "Invalid data" in stderr_str:
                # Still not enough data - keep buffering
                # But limit buffer size to prevent memory issues
                if len(buffered_data) > 50000:  # 50KB max buffer
                    print(f"[AudioConverter] ⚠️ Buffer too large ({len(buffered_data)} bytes), clearing")
                    _webm_buffers[buffer_key] = b""
                return b""
            else:
                # Other error - clear buffer and try next chunk
                print(f"[AudioConverter] ⚠️ ffmpeg error: {stderr_str[:200]}")
                _webm_buffers[buffer_key] = b""
                return b""
                
    except subprocess.TimeoutExpired:
        print(f"[AudioConverter] ⚠️ ffmpeg timeout - clearing buffer")
        _webm_buffers[buffer_key] = b""
        return b""
    except FileNotFoundError:
        print(f"[AudioConverter] ⚠️ ffmpeg not found, trying pydub fallback")
    except Exception as e:
        print(f"[AudioConverter] ⚠️ ffmpeg error: {e}")
        _webm_buffers[buffer_key] = b""
        return b""
    
    # Fallback to pydub (may fail on partial chunks)
    if PYDUB_AVAILABLE:
        try:
            audio = AudioSegment.from_file(io.BytesIO(buffered_data), format="webm")
            if audio.channels > 1:
                audio = audio.set_channels(1)
            if audio.frame_rate != sample_rate:
                audio = audio.set_frame_rate(sample_rate)
            pcm_data = audio.raw_data
            _webm_buffers[buffer_key] = b""  # Clear buffer on success
            return pcm_data
        except Exception as e:
            # pydub also failed - might need more data
            if len(buffered_data) > 50000:
                _webm_buffers[buffer_key] = b""
            return b""
    else:
        return b""

