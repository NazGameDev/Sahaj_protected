import time
import os
import sys
import tempfile
import wave
import traceback
import array
import pyaudio
import threading
from contextlib import contextmanager
from PyQt6.QtCore import QThread, pyqtSignal, QTimer


# --- Logging helper ---
def log_error(msg):
    log_path = os.path.join(os.path.expanduser('~'), 'sahaj_voice_error.log')
    try:
        if os.path.exists(log_path) and os.path.getsize(log_path) > 1024 * 1024:
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write("")
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(msg + '\n')
    except:
        pass


# --- Locate the bundled ASR cache dir (but DO NOT set HF_HUB_CACHE globally) ---
_ASR_CACHE_DIR = None
if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
    candidate = os.path.join(base_path, 'indic_asr_cache')
    if os.path.exists(candidate):
        _ASR_CACHE_DIR = candidate
        log_error(f"ASR cache located at {candidate}")
    else:
        log_error(f"Warning: Bundled ASR cache not found at {candidate}")

    ffmpeg_dir = os.path.join(base_path, 'ffmpeg_bin')
    if os.path.exists(ffmpeg_dir) and os.listdir(ffmpeg_dir):
        os.environ['PATH'] = ffmpeg_dir + os.pathsep + os.environ.get('PATH', '')
        os.environ['TORCHAUDIO_USE_FFMPEG'] = '1'
        log_error(f"Added FFmpeg to PATH: {ffmpeg_dir}")
    else:
        log_error(f"Warning: FFmpeg not found at {ffmpeg_dir}")


# --- Import ASR ---
HAS_ASR = False
ASR_IMPORT_ERROR = None

try:
    from indic_asr_onnx import IndicTranscriber
    HAS_ASR = True
    log_error("Voice typing: indic_asr_onnx imported successfully.")
except ImportError as e:
    ASR_IMPORT_ERROR = str(e)
    log_error(f"Voice typing: ImportError - {e}")
    try:
        traceback.print_exc(file=open(os.path.join(os.path.expanduser('~'), 'sahaj_voice_error.log'), 'a'))
    except Exception:
        pass
except Exception as e:
    ASR_IMPORT_ERROR = str(e)
    log_error(f"Voice typing: Unexpected import error - {e}")
    try:
        traceback.print_exc(file=open(os.path.join(os.path.expanduser('~'), 'sahaj_voice_error.log'), 'a'))
    except Exception:
        pass


# ==================================================================
# ASR env context — sets HF_HUB_CACHE / HF_HUB_OFFLINE temporarily
# so other libraries (ai4bharat.transliteration, transformers, etc.)
# are NOT affected.
# ==================================================================
@contextmanager
def _asr_env_context():
    prev_cache = os.environ.get('HF_HUB_CACHE')
    prev_offline = os.environ.get('HF_HUB_OFFLINE')

    if _ASR_CACHE_DIR:
        os.environ['HF_HUB_CACHE'] = _ASR_CACHE_DIR
    os.environ['HF_HUB_OFFLINE'] = '1'

    try:
        yield
    finally:
        if prev_cache is None:
            os.environ.pop('HF_HUB_CACHE', None)
        else:
            os.environ['HF_HUB_CACHE'] = prev_cache
        if prev_offline is None:
            os.environ.pop('HF_HUB_OFFLINE', None)
        else:
            os.environ['HF_HUB_OFFLINE'] = prev_offline


# ==================================================================
# Voice Recorder
# ==================================================================
class VoiceRecorderWorker(QThread):
    recording_started = pyqtSignal()
    recording_stopped = pyqtSignal(str)
    error = pyqtSignal(str)
    level_update = pyqtSignal(float)

    def __init__(self, max_duration=24):
        super().__init__()
        self.audio = None
        self.stream = None
        self.frames = []
        self.is_recording = False
        self._stop_requested = False
        self.max_duration = max_duration
        self.start_time = None

    def run(self):
        try:
            self.audio = pyaudio.PyAudio()
            self.frames = []
            self.is_recording = True
            self._stop_requested = False
            self.start_time = time.time()
            self.stream = self.audio.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                frames_per_buffer=1024,
                stream_callback=self._callback
            )
            self.stream.start_stream()
            self.recording_started.emit()
            log_error("Recording started.")

            while not self._stop_requested:
                elapsed = time.time() - self.start_time
                if elapsed >= self.max_duration:
                    log_error(f"Reached max duration ({self.max_duration}s), stopping.")
                    break
                self.msleep(100)

            self.is_recording = False
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()
                self.stream = None
            if self.audio:
                self.audio.terminate()
                self.audio = None

            if self.frames:
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
                temp_filename = temp_file.name
                with wave.open(temp_filename, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(16000)
                    wf.writeframes(b''.join(self.frames))
                log_error(f"Recording saved to {temp_filename}")
                self.recording_stopped.emit(temp_filename)
            else:
                self.error.emit("No audio recorded.")

        except Exception as e:
            error_msg = f"Recording error: {str(e)}\n{traceback.format_exc()}"
            log_error(error_msg)
            self.error.emit(error_msg)

    def _callback(self, in_data, frame_count, time_info, status):
        if self.is_recording:
            self.frames.append(in_data)
            try:
                samples = array.array('h', in_data)
                if samples:
                    rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
                    raw = rms / 32767.0
                    boosted = min(raw * 8.0, 1.0)
                    normalized = boosted ** 0.5
                    self.level_update.emit(normalized)
            except Exception:
                pass
        return (in_data, pyaudio.paContinue)

    def stop(self):
        self._stop_requested = True


# ==================================================================
# Voice Transcriber worker
# ==================================================================
class VoiceTypingWorker(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, audio_filepath, transcriber=None, timeout_seconds=30):
        super().__init__()
        self.audio_filepath = audio_filepath
        self.transcriber = transcriber
        self.timeout_seconds = timeout_seconds

    def run(self):
        try:
            if not HAS_ASR:
                self.error.emit(f"Voice typing is not available.\nImport error: {ASR_IMPORT_ERROR}")
                return

            if not self.audio_filepath or not os.path.exists(self.audio_filepath):
                self.error.emit("Audio file not found.")
                return

            # Validate audio file
            try:
                with wave.open(self.audio_filepath, 'rb') as wf:
                    n_frames = wf.getnframes()
                    if n_frames == 0:
                        self.error.emit("No audio recorded. Please check your microphone and try again.")
                        return
                    if os.path.getsize(self.audio_filepath) < 1000:
                        self.error.emit("Audio file is too small. Please record a longer clip.")
                        return
            except Exception as e:
                log_error(f"Audio file validation error: {e}")
                self.error.emit("Could not read the audio file. Please try again.")
                return

            # Everything ASR-related happens inside this context so the
            # HF_HUB_CACHE / HF_HUB_OFFLINE env vars don't leak out.
            with _asr_env_context():
                if self.transcriber is not None:
                    transcriber = self.transcriber
                    log_error("Using pre-loaded IndicTranscriber (fast path).")
                else:
                    log_error("No pre-loaded transcriber — loading on demand (slow path).")
                    devnull = open(os.devnull, 'w')
                    old_stdout = sys.stdout
                    old_stderr = sys.stderr
                    sys.stdout = devnull
                    sys.stderr = devnull
                    try:
                        transcriber = IndicTranscriber()
                        log_error("IndicTranscriber initialized on demand.")
                    finally:
                        sys.stdout = old_stdout
                        sys.stderr = old_stderr
                        devnull.close()

                CHUNK_SECONDS = 12
                OVERLAP_SECONDS = 0.5
                SAMPLE_RATE = 16000
                CHUNK_SAMPLES = CHUNK_SECONDS * SAMPLE_RATE
                OVERLAP_SAMPLES = OVERLAP_SECONDS * SAMPLE_RATE

                with wave.open(self.audio_filepath, 'rb') as wf:
                    raw_data = wf.readframes(wf.getnframes())

                samples = array.array('h', raw_data)
                total_samples = len(samples)

                full_text = []
                start_sample = 0
                start_time = time.time()

                while start_sample < total_samples:
                    elapsed = time.time() - start_time
                    if elapsed > self.timeout_seconds:
                        log_error(f"Transcription timed out after {elapsed:.1f}s")
                        self.error.emit(
                            f"Transcription is taking too long (over {self.timeout_seconds} seconds).\n\n"
                            "This can happen on slower computers.\n"
                            "Please try:\n"
                            "• Recording a shorter sentence (10‑15 seconds)\n"
                            "• Closing other applications to free up memory\n"
                            "• Restarting the app and trying again"
                        )
                        return

                    end_sample = min(start_sample + CHUNK_SAMPLES, total_samples)
                    start_idx = int(start_sample)
                    end_idx = int(end_sample)
                    chunk_samples = samples[start_idx:end_idx]

                    temp_chunk = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
                    temp_chunk_path = temp_chunk.name
                    temp_chunk.close()

                    try:
                        with wave.open(temp_chunk_path, 'wb') as wf_chunk:
                            wf_chunk.setnchannels(1)
                            wf_chunk.setsampwidth(2)
                            wf_chunk.setframerate(SAMPLE_RATE)
                            wf_chunk.writeframes(chunk_samples.tobytes())

                        chunk_text = transcriber.transcribe_rnnt(temp_chunk_path, "as")
                        if chunk_text and chunk_text.strip():
                            full_text.append(chunk_text.strip())

                    except Exception as e:
                        log_error(f"Chunk transcription error: {e}")
                    finally:
                        for attempt in range(5):
                            try:
                                os.remove(temp_chunk_path)
                                break
                            except PermissionError:
                                time.sleep(0.1 * (attempt + 1))
                            except Exception as e:
                                log_error(f"Failed to delete {temp_chunk_path}: {e}")
                                break

                    start_sample = int(start_sample + (CHUNK_SAMPLES - OVERLAP_SAMPLES))

            if full_text:
                deduped = []
                prev = ""
                for chunk in full_text:
                    if prev:
                        import difflib
                        ratio = difflib.SequenceMatcher(None, prev, chunk).ratio()
                        if ratio > 0.7:
                            continue
                    deduped.append(chunk)
                    prev = chunk
                combined = " ".join(deduped).strip()
                self.finished.emit(combined)
            else:
                self.error.emit("Could not understand the audio. Please try again with clearer speech.")

        except Exception as e:
            error_msg = f"VoiceTypingWorker.run error: {str(e)}\n{traceback.format_exc()}"
            log_error(error_msg)
            self.error.emit(
                f"An error occurred during voice typing.\n\n"
                f"Error: {str(e)}\n\n"
                f"Please check the log file:\n"
                f"{os.path.join(os.path.expanduser('~'), 'sahaj_voice_error.log')}"
            )
        finally:
            try:
                if os.path.exists(self.audio_filepath):
                    os.remove(self.audio_filepath)
                    log_error(f"Deleted main audio file: {self.audio_filepath}")
            except Exception as e:
                log_error(f"Failed to delete main audio file: {e}")


# ==================================================================
# Pre-loader (called once from ASRLoaderThread in main.py)
# ==================================================================
def load_transcriber():
    """
    Load IndicTranscriber once. Env vars are scoped via _asr_env_context,
    so ai4bharat.transliteration and other HF users are unaffected.
    """
    if not HAS_ASR:
        log_error("load_transcriber: HAS_ASR is False — skipping pre-load.")
        return None

    with _asr_env_context():
        devnull = open(os.devnull, 'w')
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = devnull
        sys.stderr = devnull
        try:
            log_error("Pre-loading IndicTranscriber (startup)...")
            transcriber = IndicTranscriber()
            log_error("Pre-loading IndicTranscriber: SUCCESS.")
            # Force lazy init NOW instead of on the user's first recording
            _warm_up_transcriber(transcriber)
            return transcriber
        except Exception as e:
            log_error(f"Pre-loading IndicTranscriber FAILED: {e}")
            return None
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            devnull.close()

def _warm_up_transcriber(transcriber):
    """
    Run one silent inference to force indic_asr_onnx to do its
    lazy initialization at startup, so the user's first recording
    is instant instead of taking 10–30 seconds.
    """
    try:
        # 1 second of silence at 16 kHz mono
        silence = b'\x00\x00' * 16000
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tf:
            temp_path = tf.name
        try:
            with wave.open(temp_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(silence)

            log_error("Running warm-up inference...")
            transcriber.transcribe_rnnt(temp_path, "as")
            log_error("Warm-up inference: SUCCESS.")
        finally:
            try:
                os.remove(temp_path)
            except Exception:
                pass
    except Exception as e:
        log_error(f"Warm-up inference FAILED (non-fatal): {e}")
