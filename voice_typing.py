import time
import os
import sys
import tempfile
import wave
import traceback
import array
import pyaudio
import threading
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

# --- Set cache and FFmpeg paths ---
if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
    cache_dir = os.path.join(base_path, 'indic_asr_cache')
    if os.path.exists(cache_dir):
        os.environ['HF_HUB_CACHE'] = cache_dir
        log_error(f"Using bundled ASR cache: {cache_dir}")
    else:
        log_error(f"Warning: Bundled ASR cache not found at {cache_dir}")

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
    traceback.print_exc(file=open(os.path.join(os.path.expanduser('~'), 'sahaj_voice_error.log'), 'a'))
except Exception as e:
    ASR_IMPORT_ERROR = str(e)
    log_error(f"Voice typing: Unexpected import error - {e}")
    traceback.print_exc(file=open(os.path.join(os.path.expanduser('~'), 'sahaj_voice_error.log'), 'a'))


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
            # Compute RMS (root mean square) as a rough volume indicator
            try:
                # Convert bytes to int16 samples
                import array
                samples = array.array('h', in_data)
                if samples:
                    rms = (sum(s*s for s in samples) / len(samples)) ** 0.5
                    raw = rms / 32767.0
                    # Multiply by 3 to make quiet speech more visible, cap at 1.0
                    boosted = min(raw * 8.0, 1.0)
                    normalized = boosted ** 0.5
                    self.level_update.emit(normalized)
            except Exception:
                pass
        return (in_data, pyaudio.paContinue)

    def stop(self):
        self._stop_requested = True


class VoiceTypingWorker(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, audio_filepath, timeout_seconds=30):
        super().__init__()
        self.audio_filepath = audio_filepath
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

            # Force offline mode
            os.environ['HF_HUB_OFFLINE'] = '1'

            # Suppress stdout/stderr to avoid progress bar crashes in frozen app
            devnull = open(os.devnull, 'w')
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            sys.stdout = devnull
            sys.stderr = devnull

            try:
                log_error("Initializing IndicTranscriber...")
                transcriber = IndicTranscriber()
                log_error("IndicTranscriber initialized.")
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr
                devnull.close()

            # Chunk and transcribe
            CHUNK_SECONDS = 12
            OVERLAP_SECONDS = 0.5   # reduced overlap
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
                # Deduplicate: remove chunks that are very similar to the previous one
                deduped = []
                prev = ""
                for chunk in full_text:
                    if prev:
                        # Compare similarity
                        import difflib
                        ratio = difflib.SequenceMatcher(None, prev, chunk).ratio()
                        if ratio > 0.7:  # if more than 70% similar, skip
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
            self.error.emit(f"An error occurred during voice typing.\n\nError: {str(e)}\n\nPlease check the log file:\n{os.path.join(os.path.expanduser('~'), 'sahaj_voice_error.log')}")
        finally:
            # Always delete the main audio file
            try:
                if os.path.exists(self.audio_filepath):
                    os.remove(self.audio_filepath)
                    log_error(f"Deleted main audio file: {self.audio_filepath}")
            except Exception as e:
                log_error(f"Failed to delete main audio file: {e}")
