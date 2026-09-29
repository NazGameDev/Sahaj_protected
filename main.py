import sys
import os
import html
import time
import json
import re
import requests
import difflib
import unicodedata
import shutil

try:
    import voice_typing
except ImportError as e:
    voice_typing = None
    print(f"Voice typing module not available: {e}")

try:
    import typing_modes
    HAS_TYPING_MODES = True
except ImportError as e:
    typing_modes = None
    HAS_TYPING_MODES = False
    print(f"Typing modes module not available: {e}")

from contextlib import contextmanager

@contextmanager
def suppress_stdout():
    """Temporarily suppress stdout to avoid progressbar errors in frozen app."""
    with open(os.devnull, 'w') as devnull:
        old_stdout = sys.stdout
        sys.stdout = devnull
        try:
            yield
        finally:
            sys.stdout = old_stdout

def setup_default_models():
    """Copy bundled models to the default location ~/.AI4Bharat_Xlit_Models/en2indic."""
    if not getattr(sys, 'frozen', False):
        return  # only needed for bundled app

    # Default location used by XlitEngine
    target_root = os.path.join(os.path.expanduser('~'), '.AI4Bharat_Xlit_Models', 'en2indic')
    target_v1_dir = os.path.join(target_root, 'v1.0')

    # Path to bundled models inside _internal
    bundled_root = os.path.join(sys._MEIPASS, '_internal', 'ai4bharat', 'transliteration', 'transformer', 'models', 'en2indic')
    if not os.path.exists(bundled_root):
        # fallback: try without _internal
        bundled_root = os.path.join(sys._MEIPASS, 'ai4bharat', 'transliteration', 'transformer', 'models', 'en2indic')
        if not os.path.exists(bundled_root):
            print("ERROR: Bundled models not found.")
            return

    # Check if existing models are valid
    required_files = ['model.pt', 'vocab.txt', 'dict.txt']
    is_valid = True
    if os.path.exists(target_v1_dir):
        for f in required_files:
            file_path = os.path.join(target_v1_dir, f)
            if not os.path.exists(file_path) or os.path.getsize(file_path) < 1000:
                is_valid = False
                break
        # also check lang_list.txt
        lang_file = os.path.join(target_root, 'lang_list.txt')
        if not os.path.exists(lang_file) or os.path.getsize(lang_file) < 100:
            is_valid = False
    else:
        is_valid = False

    if is_valid:
        print("Models already present in default location.")
        return

    # Remove old invalid folder
    if os.path.exists(target_v1_dir):
        shutil.rmtree(target_v1_dir)

    # Copy v1.0 folder
    shutil.copytree(os.path.join(bundled_root, 'v1.0'), target_v1_dir, dirs_exist_ok=True)

    # Copy lang_list.txt
    src_lang = os.path.join(bundled_root, 'lang_list.txt')
    if os.path.exists(src_lang):
        shutil.copy2(src_lang, target_root)
        print("Copied lang_list.txt")

    print("Models copied to default location:", target_root)

# --- Set environment variable (optional, but keep it) ---
if getattr(sys, 'frozen', False):
    base_model_dir = os.path.join(sys._MEIPASS, '_internal', 'ai4bharat', 'transliteration', 'transformer', 'models', 'en2indic')
    if os.path.exists(base_model_dir):
        os.environ['AI4BHARAT_XLIT_MODEL_DIR'] = base_model_dir

# --- Now copy models to default location (ensures engine finds them) ---
setup_default_models()

# --- AI4BHARAT XLIT ENGINE IMPORT ---
try:
    from ai4bharat.transliteration import XlitEngine
    HAS_XLIT = True
except ImportError:
    HAS_XLIT = False

# --- 1. DIRECTORY PATHING SETUP ---
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

from PyQt6.QtGui import QFontDatabase
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QTextEdit, QLabel,
                             QInputDialog, QMessageBox, QListWidget, QScrollArea, QMenu, QToolTip, QSplashScreen, QDialog, QLineEdit, QCheckBox, QProgressBar, QPlainTextEdit, QComboBox, QListView)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QMimeData, QPoint, QSettings, QEvent
from PyQt6.QtGui import (QFont, QTextCursor, QTextCharFormat, QSyntaxHighlighter, QColor, QDrag, QPixmap, QMovie, QIcon, QCursor, QAction)
from PyQt6.QtNetwork import QNetworkInformation


def get_user_data_dir():
    """Return a writable folder inside %LOCALAPPDATA% for this app."""
    appdata = os.environ.get('LOCALAPPDATA', os.path.expanduser('~'))
    app_dir = os.path.join(appdata, 'Sahaj_v1_1')
    os.makedirs(app_dir, exist_ok=True)
    return app_dir


def clean_translation(text):
    """Remove HTML tags, unescape, strip, and clean common MyMemory junk."""
    if not text:
        return ""
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    text = text.strip()
    if text.startswith('(') and text.endswith(')'):
        text = text[1:-1].strip()
    text = re.sub(r'^\(\)\s*', '', text)
    text = text.strip()
    return text


def font_family_css(families):
    """Convert a list of family names to a CSS font-family string."""
    quoted = [f'"{f}"' if ' ' in f else f for f in families]
    return ", ".join(quoted) + ", sans-serif"


session = requests.Session()

LIGHT_STYLE = """
QWidget {
    background-color: #F8F9FA;
    font-family: {font_css};
    color: #333333;
}
QLabel#headerText {
    color: #2C3E50;
    padding: 15px 0px 5px 0px;
}
QPlainTextEdit {
    font-family: {font_css};
    background-color: #FFFFFF;
    border: 2px solid #DEE2E6;
    border-radius: 8px;
    padding: 12px;
    selection-background-color: #0D6EFD;
    selection-color: #FFFFFF;
    color: #333333;
}
QPlainTextEdit:focus {
    border: 2px solid #86B7FE;
}
QLineEdit {
    border: 1px solid #CED4DA;
    border-radius: 6px;
    padding: 6px;
    background-color: #FFFFFF;
    color: #333333;
}
QPushButton {
    background-color: #FFFFFF;
    border: 1px solid #CED4DA;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 14px;
    font-weight: 500;
    color: #495057;
}
QPushButton:hover {
    background-color: #E2E6EA;
    border-color: #DAE0E5;
    color: #212529;
}
QPushButton:pressed {
    background-color: #DAE0E5;
}
QPushButton#primaryBtn {
    background-color: #0D6EFD;
    color: #FFFFFF;
    border: none;
}
QPushButton#primaryBtn:hover {
    background-color: #0B5ED7;
}
QPushButton#primaryBtn:pressed {
    background-color: #0A58CA;
}
QPushButton#successBtn {
    background-color: #198754;
    color: #FFFFFF;
    border: none;
    font-weight: bold;
}
QPushButton#successBtn:hover {
    background-color: #157347;
}
QPushButton#successBtn:pressed {
    background-color: #146C43;
}
QPushButton#keepEnBtn {
    background-color: #6C757D;
    color: #FFFFFF;
    border: none;
    font-weight: bold;
}
QPushButton#keepEnBtn:hover {
    background-color: #5A6268;
}
QPushButton#keepEnBtn:pressed {
    background-color: #545B62;
}
QListWidget {
    background-color: #FFFFFF;
    border: 1px solid #CED4DA;
    border-radius: 8px;
    outline: none;
    color: #333333;
    font-family: {font_css};
}
QListWidget::item {
    padding: 10px;
    border-bottom: 1px solid #ADB5BD;
}
QListWidget::item:selected {
    background-color: #E7F1FF;
    color: #0C63E4;
    border-radius: 4px;
}
QListWidget::item:hover:!selected {
    background-color: #F8F9FA;
}
QScrollArea {
    border: none;
    background-color: transparent;
}
QScrollBar:horizontal, QScrollBar:vertical {
    border: none;
    background: #E9ECEF;
    width: 8px;
    height: 8px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal, QScrollBar::handle:vertical {
    background: #ADB5BD;
    border-radius: 4px;
}
QScrollBar::handle:horizontal:hover, QScrollBar::handle:vertical:hover {
    background: #6C757D;
}
QScrollBar::add-line, QScrollBar::sub-line {
    border: none;
    background: none;
}
QLabel#translatedResult {
    font-family: {font_css};
    color: #0D6EFD;
    font-weight: bold;
}
QComboBox {
    background-color: #FFFFFF;
    color: #333333;
    border: 1px solid #CED4DA;
    border-radius: 6px;
    padding: 6px 12px;
    font-weight: bold;
    font-size: 14px;
    min-width: 150px;
}
QComboBox:hover {
    border-color: #86B7FE;
}
QComboBox::drop-down {
    border: none;
    width: 22px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #495057;
    width: 0;
    height: 0;
    margin-right: 8px;
}
QComboBox QAbstractItemView {
    background-color: #FFFFFF;
    color: #333333;
    border: 1px solid #E1E4E8;
    border-radius: 8px;
    outline: 0;
    padding: 6px;
    selection-background-color: transparent;
    selection-color: #0C63E4;
}
QComboBox QAbstractItemView::item {
    padding: 8px 14px;
    border-radius: 5px;
    min-height: 22px;
    font-size: 14px;
    color: #333333;
}
QComboBox QAbstractItemView::item:hover {
    background-color: #F1F3F5;
    color: #0C63E4;
}
QComboBox QAbstractItemView::item:selected {
    background-color: #E7F1FF;
    color: #0C63E4;
}
QMenu {
    background-color: #FFFFFF;
    border: 1px solid #CED4DA;
    border-radius: 6px;
    padding: 4px;
    color: #333333;
    font-family: {font_css};
}
QMenu::item {
    padding: 8px 25px 8px 15px;
    border-radius: 4px;
    font-family: {font_css};
}
QMenu::item:selected {
    background-color: #0D6EFD;
    color: #FFFFFF;
}
QMenu::separator {
    height: 1px;
    background-color: #CED4DA;
    margin: 4px 0px;
}
"""

DARK_STYLE = """
QWidget {
    background-color: #2C2C2C;
    font-family: {font_css};
    color: #E0E0E0;
}
QLabel#headerText {
    color: #EAEAEA;
    padding: 15px 0px 5px 0px;
}
QPlainTextEdit {
    font-family: {font_css};
    background-color: #1E1E1E;
    color: #E0E0E0;
    border: 2px solid #555555;
    border-radius: 8px;
    padding: 12px;
    selection-background-color: #007ACC;
    selection-color: #FFFFFF;
}
QPlainTextEdit:focus {
    border: 2px solid #86B7FE;
}
QLineEdit {
    border: 1px solid #555555;
    border-radius: 6px;
    padding: 6px;
    background-color: #1E1E1E;
    color: #E0E0E0;
}
QTextEdit:focus {
    border: 2px solid #86B7FE;
}
QPushButton {
    background-color: #3C3C3C;
    border: 1px solid #555555;
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 14px;
    font-weight: 500;
    color: #E0E0E0;
}
QPushButton:hover {
    background-color: #505050;
    border-color: #666666;
    color: #FFFFFF;
}
QPushButton:pressed {
    background-color: #404040;
}
QPushButton#primaryBtn {
    background-color: #0D6EFD;
    color: #FFFFFF;
    border: none;
}
QPushButton#primaryBtn:hover {
    background-color: #0B5ED7;
}
QPushButton#primaryBtn:pressed {
    background-color: #0A58CA;
}
QPushButton#successBtn {
    background-color: #198754;
    color: #FFFFFF;
    border: none;
    font-weight: bold;
}
QPushButton#successBtn:hover {
    background-color: #157347;
}
QPushButton#successBtn:pressed {
    background-color: #146C43;
}
QPushButton#keepEnBtn {
    background-color: #6C757D;
    color: #FFFFFF;
    border: none;
    font-weight: bold;
}
QPushButton#keepEnBtn:hover {
    background-color: #5A6268;
}
QPushButton#keepEnBtn:pressed {
    background-color: #545B62;
}
QListWidget {
    background-color: #2C2C2C;
    color: #E0E0E0;
    border: 1px solid #555555;
    border-radius: 8px;
    outline: none;
    font-family: {font_css};
}
QListWidget::item {
    padding: 10px;
    border-bottom: 1px solid #555555;
}
QListWidget::item:selected {
    background-color: #094771;
    color: #FFFFFF;
    border-radius: 4px;
}
QListWidget::item:hover:!selected {
    background-color: #3C3C3C;
}
QScrollArea {
    border: none;
    background-color: transparent;
}
QScrollBar:horizontal, QScrollBar:vertical {
    border: none;
    background: #3C3C3C;
    width: 8px;
    height: 8px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal, QScrollBar::handle:vertical {
    background: #666666;
    border-radius: 4px;
}
QScrollBar::handle:horizontal:hover, QScrollBar::handle:vertical:hover {
    background: #888888;
}
QScrollBar::add-line, QScrollBar::sub-line {
    border: none;
    background: none;
}
QLabel#translatedResult {
    font-family: {font_css};
    color: #86B7FE;
    font-weight: bold;
}
QComboBox {
    background-color: #3C3C3C;
    color: #E0E0E0;
    border: 1px solid #555555;
    border-radius: 6px;
    padding: 6px 12px;
    font-weight: bold;
    font-size: 14px;
    min-width: 150px;
}
QComboBox:hover {
    border-color: #86B7FE;
}
QComboBox::drop-down {
    border: none;
    width: 22px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #E0E0E0;
    width: 0;
    height: 0;
    margin-right: 8px;
}
QComboBox QAbstractItemView {
    background-color: #1E1E1E;
    color: #E0E0E0;
    border: 1px solid #4A4A4A;
    border-radius: 8px;
    outline: 0;
    padding: 6px;
    selection-background-color: transparent;
    selection-color: #86B7FE;
}
QComboBox QAbstractItemView::item {
    padding: 8px 14px;
    border-radius: 5px;
    min-height: 22px;
    font-size: 14px;
    color: #E0E0E0;
}
QComboBox QAbstractItemView::item:hover {
    background-color: #3A3A3A;
    color: #86B7FE;
}
QComboBox QAbstractItemView::item:selected {
    background-color: #094771;
    color: #FFFFFF;
}
QMenu {
    background-color: #2C2C2C;
    border: 1px solid #555555;
    border-radius: 6px;
    padding: 4px;
    color: #E0E0E0;
    font-family: {font_css};
}
QMenu::item {
    padding: 8px 25px 8px 15px;
    border-radius: 4px;
    font-family: {font_css};
}
QMenu::item:selected {
    background-color: #007ACC;
    color: #FFFFFF;
}
QMenu::separator {
    height: 1px;
    background-color: #555555;
    margin: 4px 0px;
}
"""

class DictionarySpellChecker:
    def __init__(self, dict_file="assamese_dictionary.txt"):
        self.words = set()
        if os.path.exists(dict_file):
            with open(dict_file, "r", encoding="utf-8") as f:
                for line in f:
                    word = line.strip()
                    if word and not word.startswith("#"):
                        self.words.add(unicodedata.normalize('NFC', word))
        self.dict_file = dict_file

    def check_text(self, text):
        errors = []
        for match in re.finditer(r'[\u0980-\u09FF\u200C\u200D]+', text):
            raw_word = match.group()
            start = match.start()
            end = match.end()
            word = unicodedata.normalize('NFC', raw_word.strip())
            if word not in self.words:
                suggestions = self.get_suggestions(word)
                if word in suggestions:
                    continue
                errors.append((start, end, suggestions))
        return errors

    def get_suggestions(self, word, max_suggestions=8):
        return difflib.get_close_matches(word, self.words, n=max_suggestions, cutoff=0.6)

    def is_available(self):
        return len(self.words) > 0


# --- UPDATED TRANSLATION WORKER (XLIT ENGINE + GOOGLE FALLBACK) ---
class TranslationWorker(QThread):
    finished = pyqtSignal(list, str)

    def __init__(self, word, xlit_engine=None, mode="google"):
        super().__init__()
        self.word = word
        self.xlit_engine = xlit_engine
        self.mode = mode

    def run(self):
        # Determine which engine to try first
        use_google_first = (self.mode == "google")

        if use_google_first:
            # Try Google first (online)
            try:
                url = f"https://inputtools.google.com/request?text={self.word}&itc=as-t-i0-und&num=10&cp=0&cs=1&ie=utf-8&oe=utf-8&app=demopage"
                response = session.get(url, timeout=3)
                data = response.json()
                if data[0] == "SUCCESS":
                    suggestions = data[1][0][1]
                    self.finished.emit(suggestions, self.word)
                    return
            except Exception:
                pass  # Google failed, fall through to offline

            # Fallback to AI4Bharat if Google fails
            if self.xlit_engine:
                try:
                    res = self.xlit_engine.translit_word(self.word, topk=5)
                    suggestions = []
                    if isinstance(res, dict) and 'as' in res:
                        suggestions = res['as']
                    elif isinstance(res, dict) and len(res) > 0:
                        suggestions = list(res.values())[0]
                    elif isinstance(res, list):
                        suggestions = res
                    if suggestions:
                        self.finished.emit(suggestions, self.word)
                        return
                except Exception as e:
                    print("XlitEngine execution error:", e)

        else:
            # Offline mode: try AI4Bharat first
            if self.xlit_engine:
                try:
                    res = self.xlit_engine.translit_word(self.word, topk=5)
                    suggestions = []
                    if isinstance(res, dict) and 'as' in res:
                        suggestions = res['as']
                    elif isinstance(res, dict) and len(res) > 0:
                        suggestions = list(res.values())[0]
                    elif isinstance(res, list):
                        suggestions = res
                    if suggestions:
                        self.finished.emit(suggestions, self.word)
                        return
                except Exception as e:
                    print("XlitEngine execution error:", e)

            # Fallback to Google (if offline engine fails)
            try:
                url = f"https://inputtools.google.com/request?text={self.word}&itc=as-t-i0-und&num=10&cp=0&cs=1&ie=utf-8&oe=utf-8&app=demopage"
                response = session.get(url, timeout=3)
                data = response.json()
                if data[0] == "SUCCESS":
                    suggestions = data[1][0][1]
                    self.finished.emit(suggestions, self.word)
                    return
            except Exception:
                pass

        # Final fallback: return the word itself
        self.finished.emit([self.word], self.word)


class SpellCheckWorker(QThread):
    results_ready = pyqtSignal(list)

    def __init__(self, text, checker):
        super().__init__()
        self.text = text
        self.checker = checker

    def run(self):
        if not self.checker:
            self.results_ready.emit([])
            return
        self.results_ready.emit(self.checker.check_text(self.text))


class MeaningWorker(QThread):
    meaning_fetched = pyqtSignal(str, str)

    def __init__(self, word):
        super().__init__()
        self.word = word

    def run(self):
        try:
            url = "https://api.mymemory.translated.net/get"
            params = {"q": self.word, "langpair": "as|en"}
            resp = requests.get(url, params=params, timeout=3)
            data = resp.json()
            meaning = ""
            if data.get("responseStatus") == 200:
                meaning = data.get("responseData", {}).get("translatedText", "")
            meaning = clean_translation(meaning)
            self.meaning_fetched.emit(self.word, meaning)
        except Exception:
            self.meaning_fetched.emit(self.word, "")


class EnglishToAssameseWorker(QThread):
    translation_fetched = pyqtSignal(str)

    def __init__(self, text):
        super().__init__()
        self.text = text

    def run(self):
        try:
            url = "https://api.mymemory.translated.net/get"
            params = {"q": self.text, "langpair": "en|as"}
            resp = requests.get(url, params=params, timeout=3)
            data = resp.json()
            translation = ""
            if data.get("responseStatus") == 200:
                translation = data.get("responseData", {}).get("translatedText", "")
            translation = clean_translation(translation)
            self.translation_fetched.emit(translation)
        except Exception:
            self.translation_fetched.emit("Error")


class MeaningPopup(QDialog):
    """
    Small floating card showing the English meaning of Assamese text.
    * Matches app light/dark theme (theme is passed in explicitly).
    * Red circular ✕ button (white cross, fades slightly on hover).
    * Closes on ✕, Escape, or clicking anywhere outside the popup.
    """

    def __init__(self, meaning_text, parent=None, theme="dark"):
        super().__init__(parent)
        self.meaning_text = meaning_text or ""
        self._theme = theme

        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setFixedWidth(340)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(8)

        # ---------- Header row: title (left) + ✕ (right) ----------
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(6)

        header = QLabel("📖 English meaning")
        header_font = QFont()
        header_font.setFamilies(CUSTOM_FONT_FAMILIES)
        header_font.setPointSize(10)
        header_font.setBold(True)
        header.setFont(header_font)
        header_row.addWidget(header)
        header_row.addStretch()

        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("meaningClose")
        self.close_btn.setFixedSize(22, 22)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_btn.setToolTip("Close (Esc)")
        self.close_btn.clicked.connect(self.close)
        header_row.addWidget(self.close_btn)

        layout.addLayout(header_row)

        # ---------- Meaning text ----------
        self.text_label = QLabel(self.meaning_text if self.meaning_text else "No translation found")
        self.text_label.setWordWrap(True)
        self.text_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        body_font = QFont()
        body_font.setFamilies(CUSTOM_FONT_FAMILIES)
        body_font.setPointSize(11)
        self.text_label.setFont(body_font)
        layout.addWidget(self.text_label)

        # ---------- Copy button ----------
        self.copy_btn = QPushButton("📋 Copy meaning")
        self.copy_btn.setObjectName("meaningCopy")
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.clicked.connect(self._on_copy_clicked)
        layout.addWidget(self.copy_btn)

        # ---------- Apply theme ----------
        self._apply_theme()

        # ---------- Install click-outside watcher ----------
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        self.adjustSize()

    # ---------------------------------------------------------
    def _apply_theme(self):
        if self._theme == "dark":
            self.setStyleSheet("""
                MeaningPopup {
                    background-color: #2C2C2C;
                    border: 1px solid #666666;
                    border-radius: 8px;
                }
                QLabel {
                    color: #E0E0E0;
                    background: transparent;
                }
                QPushButton#meaningClose {
                    background-color: #DC3545;
                    color: #FFFFFF;
                    border: none;
                    border-radius: 11px;
                    font-size: 13px;
                    font-weight: bold;
                    padding: 0px;
                }
                QPushButton#meaningClose:hover {
                    background-color: #E4606D;
                }
                QPushButton#meaningClose:pressed {
                    background-color: #BB2D3B;
                }
                QPushButton#meaningCopy {
                    background-color: #0D6EFD;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 6px 12px;
                    font-weight: bold;
                }
                QPushButton#meaningCopy:hover   { background-color: #0B5ED7; }
                QPushButton#meaningCopy:pressed { background-color: #0A58CA; }
            """)
        else:
            self.setStyleSheet("""
                MeaningPopup {
                    background-color: #FFFFFF;
                    border: 1px solid #CED4DA;
                    border-radius: 8px;
                }
                QLabel {
                    color: #333333;
                    background: transparent;
                }
                QPushButton#meaningClose {
                    background-color: #DC3545;
                    color: #FFFFFF;
                    border: none;
                    border-radius: 11px;
                    font-size: 13px;
                    font-weight: bold;
                    padding: 0px;
                }
                QPushButton#meaningClose:hover {
                    background-color: #E4606D;
                }
                QPushButton#meaningClose:pressed {
                    background-color: #BB2D3B;
                }
                QPushButton#meaningCopy {
                    background-color: #0D6EFD;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 6px 12px;
                    font-weight: bold;
                }
                QPushButton#meaningCopy:hover   { background-color: #0B5ED7; }
                QPushButton#meaningCopy:pressed { background-color: #0A58CA; }
            """)

    # ---------------------------------------------------------
    def _on_copy_clicked(self):
        QApplication.clipboard().setText(self.meaning_text or "")
        self.copy_btn.setText("✅ Copied!")
        QTimer.singleShot(800, self.close)

    # ---------------------------------------------------------
    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    # ---------------------------------------------------------
    def eventFilter(self, obj, event):
        """
        Watches ALL app events. If the user presses the mouse outside
        this popup's rectangle, we close it. This gives us reliable
        'click anywhere else to dismiss' behavior.
        """
        if event.type() == QEvent.Type.MouseButtonPress and self.isVisible():
            try:
                global_pos = event.globalPosition().toPoint()
                if not self.geometry().contains(global_pos):
                    self.close()
            except Exception:
                pass
        return super().eventFilter(obj, event)

    # ---------------------------------------------------------
    def closeEvent(self, event):
        # Always remove the app-wide filter so we don't linger.
        app = QApplication.instance()
        if app is not None:
            try:
                app.removeEventFilter(self)
            except Exception:
                pass
        super().closeEvent(event)

    # ---------------------------------------------------------
    def show_at(self, global_pos):
        """Position the popup near a global point, keeping it on screen."""
        screen = QApplication.primaryScreen().availableGeometry()
        w = self.width()
        h = self.height()
        x = global_pos.x()
        y = global_pos.y() + 14
        if x + w > screen.right():
            x = screen.right() - w - 8
        if x < screen.left():
            x = screen.left() + 8
        if y + h > screen.bottom():
            y = global_pos.y() - h - 14
        if y < screen.top():
            y = screen.top() + 8
        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

class PhoneticTextEdit(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        editor_font = QFont()
        editor_font.setFamilies(CUSTOM_FONT_FAMILIES)
        editor_font.setPointSize(17)
        self.setFont(editor_font)
        self.translator = None

        self.suggestion_list = QListWidget(self)
        self.suggestion_list.setWindowFlags(Qt.WindowType.ToolTip)
        self.suggestion_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        sugg_font = QFont()
        sugg_font.setFamilies(CUSTOM_FONT_FAMILIES)
        sugg_font.setPointSize(14)
        self.suggestion_list.setFont(sugg_font)
        self.suggestion_list.hide()
        self.suggestion_list.itemClicked.connect(self.apply_suggestion)
        self.last_word_start = 0
        self.last_word_end = 0

        self.original_punctuation = None
        self.punctuation_pos = -1

    def update_suggestion_font(self):
        editor_size = self.font().pointSize()
        sugg_size = max(8, editor_size - 1)
        sugg_font = QFont()
        sugg_font.setFamilies(CUSTOM_FONT_FAMILIES)
        sugg_font.setPointSize(sugg_size)
        self.suggestion_list.setFont(sugg_font)

    def keyPressEvent(self, event):
        if self.suggestion_list.isVisible():
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                row = self.suggestion_list.currentRow()
                if event.key() == Qt.Key.Key_Down:
                    row = (row + 1) % self.suggestion_list.count()
                else:
                    row = (row - 1) % self.suggestion_list.count()
                self.suggestion_list.setCurrentRow(row)
                return
            elif event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return):
                if self.suggestion_list.currentItem():
                    self.apply_suggestion(self.suggestion_list.currentItem())
                return
            elif event.key() == Qt.Key.Key_Escape:
                self.suggestion_list.hide()
                return
            else:
                text = event.text()
                if text and not text in ".,?!;:'\"()-":
                    self.suggestion_list.hide()

        if event.text() == ".":
            self.insertPlainText(".")
            return

        if event.key() == Qt.Key.Key_Space:
            main_win = self.window()
            if isinstance(main_win, AssameseTypingApp) and not main_win.phonetic_enabled:
                super().keyPressEvent(event)
                return

            pos_before_space = self.textCursor().position()
            super().keyPressEvent(event)
            new_pos = self.textCursor().position()

            if new_pos < 2:
                return
            if new_pos >= 2 and self.toPlainText()[new_pos - 2] == ' ':
                return

            cursor = self.textCursor()
            cursor.setPosition(new_pos - 2)
            cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1)
            char_before_space = cursor.selectedText()

            if char_before_space == ".":
                cursor.setPosition(new_pos - 2)
                cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1)
                cursor.insertText("।")
                char_before_space = "।"
                self.setTextCursor(self.textCursor())
                self.original_punctuation = "."
                self.punctuation_pos = new_pos - 2

            if char_before_space and not char_before_space.isalnum() and not char_before_space.isspace():
                word_end = new_pos - 2
                self.pending_punctuation = char_before_space
            else:
                word_end = new_pos - 1
                self.pending_punctuation = None

            word_start = word_end
            while word_start > 0:
                cursor.setPosition(word_start - 1)
                cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1)
                ch = cursor.selectedText()
                if not ch.isascii() or not (ch.isalpha() or ch.isdigit()):
                    break
                word_start -= 1

            if word_start < word_end:
                word = self.toPlainText()[word_start:word_end]
                if word.isascii():
                    if self.original_punctuation == ".":
                        self.english_punctuation = "."
                    else:
                        self.english_punctuation = self.pending_punctuation

                    self.last_word_start = word_start
                    self.last_word_end = word_end
                    self.fetch_translation(word)

            return
        super().keyPressEvent(event)

    def undo(self):
        super().undo()
        self._move_past_space()

    def redo(self):
        super().redo()
        self._move_past_space()

    def _move_past_space(self):
        cursor = self.textCursor()
        pos = cursor.position()
        doc_len = len(self.toPlainText())
        if pos < doc_len and self.toPlainText()[pos] == ' ':
            cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.MoveAnchor, 1)
            self.setTextCursor(cursor)

        self.last_word_start = 0
        self.last_word_end = 0
        self.pending_punctuation = None
        self.original_punctuation = None
        self.punctuation_pos = -1

    def mousePressEvent(self, event):
        if self.suggestion_list.isVisible():
            self.suggestion_list.hide()
        super().mousePressEvent(event)

    def focusOutEvent(self, event):
        if self.suggestion_list.isVisible():
            cursor_pos = self.suggestion_list.mapFromGlobal(QCursor.pos())
            if not self.suggestion_list.rect().contains(cursor_pos):
                self.suggestion_list.hide()
        super().focusOutEvent(event)

    def wheelEvent(self, event):
        if self.suggestion_list.isVisible():
            local_pos = self.suggestion_list.mapFromGlobal(event.globalPosition().toPoint())
            if not self.suggestion_list.rect().contains(local_pos):
                self.suggestion_list.hide()
        super().wheelEvent(event)

    def fetch_translation(self, word):
        main_win = self.window()
        xlit_engine = getattr(main_win, 'xlit_engine', None)
        # Get the current translation mode from the main window
        mode = getattr(main_win, 'translation_mode', 'google')
        self.translator = TranslationWorker(word, xlit_engine=xlit_engine, mode=mode)
        self.translator.finished.connect(self.handle_translation)
        self.translator.start()

    def handle_translation(self, suggestions, original_word):
        if not suggestions:
            return
        cursor = self.textCursor()
        cursor.setPosition(self.last_word_start)
        cursor.setPosition(self.last_word_end, QTextCursor.MoveMode.KeepAnchor)

        cursor.insertText(suggestions[0])
        self.last_word_end = self.last_word_start + len(suggestions[0])

        display_suggestions = suggestions[:]
        if self.pending_punctuation:
            display_suggestions = [s + self.pending_punctuation for s in suggestions]

        if len(display_suggestions) > 1:
            self.show_suggestions(display_suggestions)

    def show_suggestions(self, suggestions):
        if not self.hasFocus():
            return
        self.update_suggestion_font()
        self.suggestion_list.clear()
        self.suggestion_list.addItems(suggestions)
        self.suggestion_list.setCurrentRow(0)
        item_height = 40
        visible_items = min(len(suggestions), 5)
        popup_width = 220
        popup_height = (item_height * visible_items) + 10
        self.suggestion_list.resize(popup_width, popup_height)

        cursor_rect = self.cursorRect()
        cursor_global_top_left = self.mapToGlobal(cursor_rect.topLeft())
        cursor_global_bottom_left = self.mapToGlobal(cursor_rect.bottomLeft())

        popup_x = cursor_global_bottom_left.x()
        popup_y = cursor_global_bottom_left.y() + 20
        screen_rect = QApplication.primaryScreen().availableGeometry()
        if popup_y + popup_height > screen_rect.bottom():
            popup_y = cursor_global_top_left.y() - popup_height
            if popup_y < screen_rect.top():
                popup_y = screen_rect.top()

        if popup_x + popup_width > screen_rect.right():
            popup_x = screen_rect.right() - popup_width
        if popup_x < screen_rect.left():
            popup_x = screen_rect.left()

        self.suggestion_list.move(popup_x, popup_y)
        self.suggestion_list.show()

    def apply_suggestion(self, item):
        text = item.text()
        if self.pending_punctuation and text.endswith(self.pending_punctuation):
            text = text[:-len(self.pending_punctuation)]
        cursor = self.textCursor()
        cursor.setPosition(self.last_word_start)
        cursor.setPosition(self.last_word_end, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(text)
        self.last_word_end = self.last_word_start + len(text)
        self.suggestion_list.hide()
        self.setFocus()
        self.pending_punctuation = None

    def contextMenuEvent(self, event):
        main_win = self.window()
        is_main_app = isinstance(main_win, AssameseTypingApp)

        # -------- What text should we look up? --------
        cursor = self.textCursor()
        if cursor.hasSelection():
            lookup_text = cursor.selectedText().replace("\u2029", " ").strip()
        else:
            word_cursor = self.cursorForPosition(event.pos())
            word_cursor.select(QTextCursor.SelectionType.WordUnderCursor)
            lookup_text = word_cursor.selectedText().strip()

        has_assamese = bool(re.search(r'[\u0980-\u09FF]', lookup_text))

        # -------- Misspelled word under cursor (only when nothing is selected) --------
        misspelled_word = None
        misspelled_range = None
        misspelled_suggestions = None
        if is_main_app and not cursor.hasSelection():
            text = self.toPlainText()
            pos = self.cursorForPosition(event.pos()).position()
            start = pos
            end = pos
            while start > 0 and re.match(r'[\u0980-\u09FF\u200C\u200D]', text[start - 1]):
                start -= 1
            while end < len(text) and re.match(r'[\u0980-\u09FF\u200C\u200D]', text[end]):
                end += 1
            candidate = text[start:end].strip()
            if candidate and re.search(r'[\u0980-\u09FF]', candidate):
                for err_start, err_end, suggestions in main_win.spell_errors:
                    if start == err_start and end == err_end:
                        misspelled_word = text[start:end]
                        misspelled_range = (start, end)
                        misspelled_suggestions = suggestions
                        break

        # -------- Build the menu --------
        menu = QMenu(self)
        menu_font = QFont()
        menu_font.setFamilies(CUSTOM_FONT_FAMILIES)
        # When spell-check suggestions are going to appear, use a larger
        # font (editor size − 3) so the suggestions are easy to read —
        # this matches the earlier behaviour you liked.
        # For a normal right-click, keep a compact, professional size.
        if misspelled_word and misspelled_range:
            editor_size = self.font().pointSize()
            menu_font.setPointSize(max(10, editor_size - 3))
        else:
            menu_font.setPointSize(10)
        menu.setFont(menu_font)

        # ---- 1) Show meaning (always the FIRST item) ----
        if has_assamese and len(lookup_text) >= 1:
            meaning_action = menu.addAction("📖 Show meaning")
            meaning_action.triggered.connect(
                lambda checked=False, t=lookup_text[:500], p=event.globalPos():
                    self._show_meaning_popup(t, p)
            )
            menu.addSeparator()

        # ---- 2) Spell-check section ----
        if misspelled_word and misspelled_range:
            # NOTE: We deliberately do NOT select the misspelled word
            # here. The selection is applied only when the user actually
            # clicks a suggestion — same behaviour as MS Word.
            all_suggestions = list(misspelled_suggestions) if misspelled_suggestions else []
            user_matches = difflib.get_close_matches(
                misspelled_word,
                main_win.user_dictionary,
                n=5,
                cutoff=0.6,
            )
            for um in user_matches:
                if um not in all_suggestions:
                    all_suggestions.append(um)
            all_suggestions = all_suggestions[:8]

            if all_suggestions:
                for sug in all_suggestions:
                    act = menu.addAction(sug)
                    act.triggered.connect(
                        lambda checked=False, s=sug, rng=misspelled_range:
                            self._replace_word_in_range(rng, s)
                    )
            else:
                menu.addAction("(no suggestions)").setEnabled(False)

            menu.addSeparator()
            ignore_action = menu.addAction("Ignore")
            ignore_action.triggered.connect(
                lambda checked=False, s=misspelled_range[0], e=misspelled_range[1]:
                    main_win.ignore_spelling_error(s, e)
            )
            add_dict_action = menu.addAction("Add to Dictionary")
            add_dict_action.triggered.connect(
                lambda checked=False, w=misspelled_word:
                    main_win.add_to_user_dictionary(w)
            )
            menu.addSeparator()

        # ---- 3) Standard Cut / Copy / Paste / Select All etc. ----
        if not (misspelled_word and misspelled_range):
            std_menu = self.createStandardContextMenu()
            for act in std_menu.actions():
                if act.isSeparator():
                    continue
                menu.addAction(act)

        menu.exec(event.globalPos())

    def replace_word(self, cursor, replacement):
        cursor.insertText(replacement)
        self.setTextCursor(cursor)

    def _replace_word_in_range(self, rng, replacement):
        """Replace the given (start, end) character range with `replacement`."""
        cursor = QTextCursor(self.document())
        cursor.setPosition(rng[0])
        cursor.setPosition(rng[1], QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(replacement)
        self.setTextCursor(cursor)

    def _show_meaning_popup(self, text, global_pos):
        """Fetch meaning via MeaningWorker and show it in a floating card."""

        # Close any previously-open popup
        if getattr(self, "_meaning_popup", None) is not None:
            try:
                self._meaning_popup.close()
                self._meaning_popup.deleteLater()
            except Exception:
                pass
            self._meaning_popup = None

        # Show "Loading…" immediately so the user sees a response
        loading = MeaningPopup("Loading…", parent=self.window(), theme=self._current_theme_name())
        loading.show_at(global_pos)
        self._meaning_popup = loading

        worker = MeaningWorker(text)

        def _on_done(_word, meaning, popup_ref=loading, pos=global_pos):
            # Ignore stale results from an earlier lookup
            if getattr(self, "_meaning_popup", None) is not popup_ref:
                return
            try:
                popup_ref.close()
                popup_ref.deleteLater()
            except Exception:
                pass
            result_text = meaning if meaning else "No translation found"
            new_popup = MeaningPopup(result_text, parent=self.window(), theme=self._current_theme_name())
            new_popup.show_at(pos)
            self._meaning_popup = new_popup

        worker.meaning_fetched.connect(_on_done)

        # Keep a reference so the thread isn't garbage-collected mid-flight
        if not hasattr(self, "_meaning_workers"):
            self._meaning_workers = []
        self._meaning_workers.append(worker)

        def _cleanup():
            try:
                self._meaning_workers.remove(worker)
            except ValueError:
                pass
        worker.finished.connect(_cleanup)
        worker.start()

    def _current_theme_name(self):
        """Return 'dark' or 'light' based on the main window's current theme."""
        w = self.window()
        while w is not None:
            if hasattr(w, "current_theme"):
                return w.current_theme
            w = w.parent()
        return "dark"

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        QToolTip.hideText()

    def leaveEvent(self, event):
        QToolTip.hideText()
        super().leaveEvent(event)

    def clear_all(self):
        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.Document)
        cursor.insertText("")


class DraggableButton(QPushButton):
    def __init__(self, text, index, parent=None):
        super().__init__(text, parent)
        self.index = index
        self.setAcceptDrops(True)
        self.drag_start_pos = QPoint()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if (event.pos() - self.drag_start_pos).manhattanLength() < QApplication.startDragDistance():
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(str(self.index))
        drag.setMimeData(mime)
        pixmap = self.grab()
        drag.setPixmap(pixmap)
        drag.setHotSpot(event.pos())
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event):
        source_index = int(event.mimeData().text())
        target_index = self.index
        if source_index != target_index:
            main_win = self.window()
            helpers = main_win.helpers
            item = helpers.pop(source_index)
            if source_index < target_index:
                target_index -= 1
            helpers.insert(target_index, item)
            main_win.save_helper_buttons()
            main_win.refresh_helper_ui()
        event.acceptProposedAction()


# --- ASYNCHRONOUS BACKEND LOADER WITH XLIT ENGINE ---
class AppLoaderThread(QThread):
    finished_loading = pyqtSignal(object, dict, object)
    error_signal = pyqtSignal(str)   # <--- New signal for errors

    def __init__(self, dictionary_file, dict_path):
        super().__init__()
        self.dictionary_file = dictionary_file
        self.dict_path = dict_path

    def run(self):
        spell_tool = None
        try:
            checker = DictionarySpellChecker(self.dict_path)
            if checker.is_available():
                spell_tool = checker
        except Exception:
            spell_tool = None

        dictionary = {}
        if os.path.exists(self.dictionary_file):
            try:
                with open(self.dictionary_file, "r", encoding="utf-8") as f:
                    dictionary = json.load(f)
            except Exception:
                dictionary = {}

        xlit_engine = None  # <-- Moved outside the if block

        if HAS_XLIT:
            try:
                with suppress_stdout():
                    xlit_engine = XlitEngine("as", beam_width=4, rescore=False)

                # Quick test
                test = xlit_engine.translit_word("test", topk=1)
                if test:
                    print("XlitEngine initialized successfully.")
                else:
                    print("XlitEngine initialized but returned empty test result.")

            except Exception as e:
                import traceback
                error_msg = f"Failed to load the AI transliteration engine.\n\nError: {str(e)}\n\nPlease check if models are properly installed."
                print(error_msg)
                log_path = os.path.join(os.path.expanduser('~'), 'sahaj_error.log')
                with open(log_path, 'w', encoding='utf-8') as f:
                    traceback.print_exc(file=f)
                full_error = traceback.format_exc()
                self.error_signal.emit(f"{error_msg}\n\nFull traceback:\n{full_error}")
                xlit_engine = None

        self.finished_loading.emit(spell_tool, dictionary, xlit_engine)

class ModernComboBox(QComboBox):
    """
    A QComboBox with a fully-styleable, bezel-free popup.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        view = QListView()
        view.setUniformItemSizes(True)
        view.setSpacing(2)
        self.setView(view)

        popup_font = QFont()
        popup_font.setPointSize(11)
        popup_font.setBold(True)
        view.setFont(popup_font)

    def _get_theme(self):
        """Walk up the parent chain to find the app's current_theme."""
        w = self.window()
        while w is not None:
            if hasattr(w, "current_theme"):
                return w.current_theme
            w = w.parent()
        return "dark"

    def showPopup(self):
        super().showPopup()

        container = self.view().window()
        if container is None:
            return

        theme = self._get_theme()
        if theme == "dark":
            bg = "#1E1E1E"
        else:
            bg = "#FFFFFF"

        # Remove the native frame/shadow that paints the dark bezel
        try:
            from PyQt6.QtWidgets import QFrame
            if isinstance(container, QFrame):
                container.setFrameShape(QFrame.Shape.NoFrame)
                container.setFrameShadow(QFrame.Shadow.Plain)
        except Exception:
            pass

        # Paint the container with the theme colour so no gray shows through
        container.setStyleSheet(f"""
            QFrame {{
                border: 0px;
                margin: 0px;
                padding: 0px;
                background-color: {bg};
            }}
        """)
        container.setContentsMargins(0, 0, 0, 0)

class AssameseTypingApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("সহজ-Sahaj v3.0")
        self.resize(1050, 750)
        self.settings = QSettings("NazmulDev", "SahajApp")
        user_data = get_user_data_dir()
        self.autosave_file = os.path.join(user_data, "autosave.txt")
        self.helpers_file = os.path.join(user_data, "helpers.json")
        self.dictionary_file = resource_path("dictionary.json")
        self.user_dict_file = os.path.join(user_data, "user_dictionary.txt")
        self.user_dictionary = self.load_user_dictionary()
        self.current_theme = "dark"
        self.is_online = True
        font_css = font_family_css(CUSTOM_FONT_FAMILIES)
        self.setStyleSheet(DARK_STYLE.replace("{font_css}", font_css))
        self.spell_errors = []
        self.spell_tool = None
        self.xlit_engine = None
        self.spell_worker = None
        self.dictionary = {}
        self.ignored_error_ranges = set()
        self.phonetic_enabled = True
        self.translation_mode = "google"
        self.recording_active = False
        self.recording_worker = None
        self.voice_progress = None
        self.loader_thread = AppLoaderThread(self.dictionary_file, resource_path("assamese_dictionary.txt"))
        self.loader_thread.finished_loading.connect(self.on_backend_loaded)
        self.loader_thread.error_signal.connect(self.show_engine_error)
        self.loader_thread.start()
        self.init_ui()
        self.load_autosave()
        self.load_helper_buttons()
        self.autosave_timer = QTimer()
        self.autosave_timer.timeout.connect(self.save_text)
        self.autosave_timer.start(6000)
        # Use the OS's native network information (no polling, zero traffic)
        if QNetworkInformation.load(QNetworkInformation.Feature.Reachability):
            net_info = QNetworkInformation.instance()
            net_info.reachabilityChanged.connect(self.on_reachability_changed)
            # Set the initial status based on the current state
            self.on_reachability_changed(net_info.reachability())
        else:
            # Fallback for unsupported platforms (very rare)
            print("Warning: QNetworkInformation is not supported on this platform.")
            self.update_network_status(True) # Assume online as a last resort
        self.spell_timer = QTimer()
        self.spell_timer.setSingleShot(True)
        self.spell_timer.timeout.connect(lambda: self.check_spelling())
        self.text_area.textChanged.connect(lambda: self.spell_timer.start(5000))
        self.check_spelling()

        # Autosave debounce timer (save 1 second after typing stops)
        self.autosave_debounce = QTimer()
        self.autosave_debounce.setSingleShot(True)
        self.autosave_debounce.timeout.connect(self.save_text)
        self.text_area.textChanged.connect(lambda: self.autosave_debounce.start(2000))

        # Countdown timer for voice recording
        self.remaining_seconds = 24
        self.countdown_timer = QTimer()
        self.countdown_timer.timeout.connect(self.update_countdown)
        self.countdown_timer.setInterval(1000)  # 1 second
        
    def on_engine_mode_changed(self, index):
        """Handle dropdown selection: engine switch OR typing-mode switch."""
        if index in (0, 1):
            # Translation engine modes
            self.translation_mode = "google" if index == 0 else "offline"
            if HAS_TYPING_MODES and getattr(self, "typing_manager", None):
                self.typing_manager.set_mode("none")
        elif index == 2:
            # Mouse typing
            if HAS_TYPING_MODES and getattr(self, "typing_manager", None):
                self.typing_manager.set_mode("mouse")
        elif index == 3:
            # InScript typing
            if HAS_TYPING_MODES and getattr(self, "typing_manager", None):
                self.typing_manager.set_mode("inscript")

    def on_typing_mode_closed(self):
        """Mouse Typing panel was closed by the user.
        Reset the dropdown to Live AI (online) or Built-In AI (offline)
        WITHOUT re-triggering on_engine_mode_changed.
        """
        target_index = 0 if self.is_online else 1
        self.engine_combo.blockSignals(True)
        self.engine_combo.setCurrentIndex(target_index)
        self.engine_combo.blockSignals(False)
        self.translation_mode = "google" if self.is_online else "offline"

    def start_voice_typing(self):
        if not hasattr(self, 'recording_worker') or self.recording_worker is None:
            try:
                self.voice_btn.setEnabled(False)
                self.voice_btn.setText("⏹️ Recording...")
                self.remaining_seconds = 24
                self.voice_progress.setValue(100)
                self.voice_progress.show()
                self.voice_timer_label.setText("24s")   # reset timer text
                self.voice_timer_label.show()
                self.recording_worker = voice_typing.VoiceRecorderWorker(max_duration=24)
                self.recording_worker.recording_started.connect(self.on_recording_started)
                self.recording_worker.recording_stopped.connect(self.on_recording_stopped)
                self.recording_worker.error.connect(self.on_voice_error)
                self.recording_worker.level_update.connect(self.update_voice_level)  # <-- new
                self.recording_worker.start()
                self.countdown_timer.start()

            except Exception as e:
                import traceback
                error_msg = f"start_voice_typing error: {e}\n{traceback.format_exc()}"
                print(error_msg)
                self.on_voice_error(error_msg)
        else:
            # Stop recording
            if self.recording_worker:
                self.recording_worker.stop()
                self.voice_btn.setEnabled(False)
                self.voice_btn.setText("⏹️ Stopping...")
                self.countdown_timer.stop()

    def on_recording_started(self):
        """Called when recording actually starts."""
        self.voice_btn.setEnabled(True)
        self.voice_btn.setText("⏹️ Stop")

    def on_recording_stopped(self, audio_filepath):
        """Called when recording stops (either by user or timer)."""
        self.countdown_timer.stop()
        self.voice_timer_label.hide()
        self.voice_progress.setValue(100)
        self.voice_progress.hide()  # hide progress bar
        self.voice_btn.setEnabled(False)
        self.voice_btn.setText("⏳ Transcribing...")
        self.recording_worker = None
        
        self.transcriber_thread = voice_typing.VoiceTypingWorker(audio_filepath)
        self.transcriber_thread.finished.connect(self.on_voice_transcribed)
        self.transcriber_thread.error.connect(self.on_voice_error)
        self.transcriber_thread.start()

    def on_voice_transcribed(self, text):
        """Handle successful transcription."""
        self.voice_progress.hide()
        self.voice_progress.setValue(100)  # reset for next time
        if text and text.strip():
            self.text_area.insertPlainText(text + " ")
            self.text_area.setFocus()
            cursor = self.text_area.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self.text_area.setTextCursor(cursor)
        self.voice_btn.setEnabled(True)
        self.voice_btn.setText("🎤 Voice Typing")

    def on_voice_error(self, error_message):
        """Handle transcription errors."""
        self.countdown_timer.stop()
        self.voice_timer_label.hide()
        self.voice_progress.hide()
        self.voice_progress.setValue(100)  # reset for next time
        QMessageBox.critical(self, "Voice Typing Error", error_message)
        self.voice_btn.setEnabled(True)
        self.voice_btn.setText("🎤 Voice Typing")
        self.recording_worker = None

    def update_countdown(self):
        self.remaining_seconds -= 1
        self.voice_timer_label.setText(f"{self.remaining_seconds}s")   # update label
        if self.remaining_seconds <= 0:
            self.countdown_timer.stop()
            self.voice_timer_label.hide()         # hide the label
            self.voice_progress.hide()            # hide the VU meter
            if self.recording_worker:
                self.recording_worker.stop()
                self.voice_btn.setEnabled(False)
                self.voice_btn.setText("⏹️ Stopping...")

    def update_voice_level(self, rms):
        """Update progress bar to show audio level."""
        if self.voice_progress.isVisible():
            # Scale to 0-100 (we want it to bounce like a VU meter)
            value = int(rms * 100)
            self.voice_progress.setValue(value)
        else:
            self.voice_progress.show()
            self.voice_progress.setValue(0)    

    def on_backend_loaded(self, spell_tool, dictionary, xlit_engine):
        self.spell_tool = spell_tool
        self.dictionary = dictionary
        self.xlit_engine = xlit_engine
        if not self.spell_tool:
            QMessageBox.warning(self, "Spell Check Disabled",
                                "Could not load the bundled dictionary.\nSpell checking will be disabled.")
        self.check_spelling()
        
    def show_engine_error(self, message):
        # This runs on the main GUI thread – safe to show popups!
        QMessageBox.critical(self, "AI Engine Error", message)

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setContentsMargins(20, 10, 20, 20)
        layout.setSpacing(15)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addStretch(1)

        self.header_logo = QLabel()
        self.header_logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_path = resource_path("header_logo.png")

        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path)
            scaled_pixmap = pixmap.scaledToHeight(70, Qt.TransformationMode.SmoothTransformation)
            self.header_logo.setPixmap(scaled_pixmap)
        else:
            self.header_logo.setText("সহজ-Sahaj v3.0")
            self.header_logo.setObjectName("headerText")
            self.header_logo.setFont(QFont("Arial", 22, QFont.Weight.Bold))

        header_layout.addWidget(self.header_logo)
        header_layout.addStretch(1)

        right_container = QWidget()
        right_layout = QHBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)
        self.network_status_label = QLabel("🟢 Checking...")
        self.network_status_label.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        self.network_status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        right_layout.addWidget(self.network_status_label)

        self.theme_toggle_btn = QPushButton()
        self.theme_toggle_btn.setCheckable(True)
        self.theme_toggle_btn.setChecked(True)
        self.theme_toggle_btn.setFixedSize(44, 44)
        self.theme_toggle_btn.setFont(QFont("Segoe UI Emoji", 22))
        self.theme_toggle_btn.setText("🌙")
        self.theme_toggle_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: none;
                padding: 0px;
                text-align: center;
            }
            QPushButton:hover {
                background-color: rgba(128, 128, 128, 0.2);
                border-radius: 22px;
            }
        """)
        self.theme_toggle_btn.toggled.connect(self.toggle_theme)
        right_layout.addWidget(self.theme_toggle_btn)
        header_layout.addWidget(right_container)
        layout.addLayout(header_layout)

        toolbar = QHBoxLayout()
        clear_btn = QPushButton("Clear Editor")
        clear_btn.setStyleSheet("""
            QPushButton {
                background-color: #DC3545;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #BB2D3B;
            }
            QPushButton:pressed {
                background-color: #A52834;
            }
        """)
        clear_btn.clicked.connect(self.clear_editor)
        self.copy_btn = QPushButton("Copy to Clipboard")
        self.copy_btn.setObjectName("primaryBtn")
        self.copy_btn.clicked.connect(self.copy_to_clipboard)

        self.phonetic_btn = QPushButton("Phonetic ON")
        self.phonetic_btn.setCheckable(True)
        self.phonetic_btn.setChecked(True)
        self.phonetic_btn.setToolTip("Toggle phonetic conversion when you press space")
        self.phonetic_btn.setStyleSheet("""
            QPushButton {
                background-color: #198754;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:checked {
                background-color: #198754;
            }
            QPushButton:!checked {
                background-color: #DC3545;
            }
            QPushButton:hover {
                opacity: 0.9;
            }
        """)
        self.phonetic_btn.toggled.connect(self.toggle_phonetic)
        
        # --- Mode dropdown: Live AI / Built-In AI / Mouse Typing / InScript Typing ---
        self.engine_combo = ModernComboBox()
        self.engine_combo.setToolTip(
            "Choose the translation engine or a typing mode.\n"
            "• Live AI       – online transliteration (Google)\n"
            "• Built-In AI   – offline AI4Bharat engine\n"
            "• Mouse Typing  – click on-screen Assamese letters\n"
            "• Inscript Typing – type Assamese with the physical keyboard"
        )
        self.engine_combo.addItems(
            ["Live AI", "Built-In AI", "Mouse Typing", "Inscript Typing"]
        )
        if not HAS_TYPING_MODES:
            # Grey out the typing-mode entries if the module couldn't load
            model = self.engine_combo.model()
            for i in (2, 3):
                item = model.item(i)
                if item is not None:
                    item.setEnabled(False)
        self.engine_combo.setCurrentIndex(0)
        self.engine_combo.currentIndexChanged.connect(self.on_engine_mode_changed)

        self.voice_btn = QPushButton("🎤 Voice Typing")
        self.voice_btn.setToolTip("Click to start voice typing in Assamese")
        self.voice_btn.setStyleSheet("""
            QPushButton {
                background-color: #6F42C1;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #5A32A3;
            }
            QPushButton:pressed {
                background-color: #4A2B8A;
            }
        """)
        self.voice_btn.clicked.connect(self.start_voice_typing)

        # Progress bar for voice recording countdown
        self.voice_progress = QProgressBar()
        self.voice_progress.setRange(0, 100)
        self.voice_progress.setValue(100)
        self.voice_progress.setTextVisible(False)
        self.voice_progress.setFixedHeight(6)
        self.voice_progress.setStyleSheet("""
            QProgressBar {
                background-color: #D3D3D3;   /* Light Gray */
                border: none;
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background-color: #008080;   /* Deep Teal */
                border-radius: 3px;
            }
        """)
        self.voice_progress.hide()
        # Timer label for voice recording
        self.voice_timer_label = QLabel("24s")
        self.voice_timer_label.setFixedWidth(35)          # enough space for "24s"
        self.voice_timer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.voice_timer_label.setStyleSheet("color: #fb6300; font-weight: bold; font-size: 13px;")
        self.voice_timer_label.hide()                     # hidden by default
        undo_btn = QPushButton("Undo")
        redo_btn = QPushButton("Redo")
        redo_btn.setToolTip("Redo last undone change (Ctrl+Y)")
        redo_btn.clicked.connect(self.redo_edit)
        undo_btn.setToolTip("Undo last change (Ctrl+Z)")
        undo_btn.clicked.connect(self.undo_edit)

        inc_font_btn = QPushButton("A+")
        inc_font_btn.setToolTip("Increase Editor Font Size")
        inc_font_btn.setStyleSheet("padding: 8px 10px;")
        inc_font_btn.clicked.connect(self.increase_font)

        dec_font_btn = QPushButton("A-")
        dec_font_btn.setToolTip("Decrease Editor Font Size")
        dec_font_btn.setStyleSheet("padding: 8px 10px;")
        dec_font_btn.clicked.connect(self.decrease_font)

        add_helper_btn = QPushButton("+ Add Helper Button")
        add_helper_btn.setObjectName("successBtn")
        add_helper_btn.clicked.connect(self.add_helper_dialog)

        toolbar.addWidget(clear_btn)
        toolbar.addWidget(self.copy_btn)
        toolbar.addWidget(self.phonetic_btn)
        toolbar.addWidget(self.engine_combo)
        toolbar.addWidget(self.voice_btn)
        toolbar.addWidget(self.voice_progress)
        toolbar.addWidget(self.voice_timer_label)
        toolbar.addWidget(undo_btn)
        toolbar.addWidget(redo_btn)
        toolbar.addWidget(inc_font_btn)
        toolbar.addWidget(dec_font_btn)
        toolbar.addStretch()
        toolbar.addWidget(add_helper_btn)
        layout.addLayout(toolbar)

        translation_layout = QHBoxLayout()
        translation_layout.setSpacing(10)

        self.eng_input = QLineEdit()
        self.eng_input.setPlaceholderText("Type an English word to translate...")
        self.eng_input.setFont(QFont("Arial", 11))
        self.eng_input.returnPressed.connect(self.translate_english)

        self.translate_btn = QPushButton("Translate")
        self.translate_btn.clicked.connect(self.translate_english)

        self.translated_result = QLabel("Result: ")
        trans_font = QFont()
        trans_font.setFamilies(CUSTOM_FONT_FAMILIES)
        trans_font.setPointSize(13)
        self.translated_result.setFont(trans_font)
        self.translated_result.setMinimumWidth(150)
        self.translated_result.setObjectName("translatedResult")

        self.add_to_editor_btn = QPushButton("Add to Editor")
        self.add_to_editor_btn.setObjectName("successBtn")
        self.add_to_editor_btn.clicked.connect(self.add_translation_to_editor)
        self.add_to_editor_btn.setEnabled(False)

        translation_layout.addWidget(self.eng_input)
        translation_layout.addWidget(self.translate_btn)
        translation_layout.addWidget(self.translated_result)
        translation_layout.addWidget(self.add_to_editor_btn)
        layout.addLayout(translation_layout)

        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #CED4DA;")
        layout.addWidget(sep)

        helper_label = QLabel("Your helper buttons right below!")
        helper_label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        helper_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        helper_label.setStyleSheet("color: #666; padding: 0px 0px 2px 0px;")
        layout.addWidget(helper_label)

        self.helpers_scroll = QScrollArea()
        self.helpers_scroll.setFixedHeight(60)
        self.helpers_scroll.setWidgetResizable(True)
        self.helpers_container = QWidget()
        self.helpers_layout = QHBoxLayout(self.helpers_container)
        self.helpers_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.helpers_layout.setContentsMargins(0, 0, 0, 0)
        self.helpers_layout.setSpacing(10)
        self.helpers_scroll.setWidget(self.helpers_container)
        layout.addWidget(self.helpers_scroll)

        self.text_area = PhoneticTextEdit()
        saved_font_size = self.settings.value("editor_font_size", 17, type=int)
        font = self.text_area.font()
        font.setPointSize(saved_font_size)
        self.text_area.setFont(font)
        self.text_area.update_suggestion_font()
        layout.addWidget(self.text_area)

        # --- Wire up typing-mode manager (InScript + Mouse Typing) ---
        if HAS_TYPING_MODES:
            self.typing_manager = typing_modes.TypingModeManager(
                self, self.text_area, theme=self.current_theme
            )
            self.typing_manager.mode_closed.connect(self.on_typing_mode_closed)
        else:
            self.typing_manager = None

        footer_layout = QHBoxLayout()
        footer_layout.setSpacing(10)

        dev_label = QLabel(
            "<a href='https://www.facebook.com/nazmul.hussain.319' style='color: #0D6EFD; text-decoration: none;'>App designed & developed by Nazmul Hussain</a>")
        dev_label.setOpenExternalLinks(True)
        dev_label.setFont(QFont("Arial", 10))

        about_btn = QPushButton("ℹ️ About")
        about_btn.setFixedWidth(80)
        about_btn.setToolTip("Learn more about সহজ-Sahaj")
        about_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                border: 1px solid #ADB5BD;
                border-radius: 4px;
                padding: 2px 6px;
                font-size: 9pt;
                color: #495057;
            }
            QPushButton:hover {
                background-color: #E2E6EA;
            }
        """)
        about_btn.clicked.connect(self.show_about_dialog)

        support_btn = QPushButton("❤️ Support")
        support_btn.setFixedWidth(90)
        support_btn.setToolTip("Support the developer via UPI")
        support_btn.setStyleSheet("""
            QPushButton {
                background-color: #DC3545;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 2px 6px;
                font-size: 9pt;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #BB2D3B;
            }
        """)
        support_btn.clicked.connect(self.show_support_dialog)
        footer_layout.addStretch()
        footer_layout.addWidget(dev_label)
        footer_layout.addWidget(about_btn)
        footer_layout.addWidget(support_btn)
        layout.addLayout(footer_layout)

    def toggle_theme(self, checked):
        font_css = font_family_css(CUSTOM_FONT_FAMILIES)
        if checked:
            self.setStyleSheet(DARK_STYLE.replace("{font_css}", font_css))
            self.theme_toggle_btn.setText("🌙")
            self.current_theme = "dark"
        else:
            self.setStyleSheet(LIGHT_STYLE.replace("{font_css}", font_css))
            self.theme_toggle_btn.setText("☀️")
            self.current_theme = "light"

        if getattr(self, "typing_manager", None):
            self.typing_manager.set_theme(self.current_theme)

    def closeEvent(self, event):
        # 1. Flush the editor to disk one last time
        try:
            self.save_text()
        except Exception:
            pass

        # 2. Stop the loader thread if it's still spinning up the AI model
        try:
            if getattr(self, "loader_thread", None) and self.loader_thread.isRunning():
                self.loader_thread.wait(1500)
        except Exception:
            pass

        # 3. Stop the network thread so it doesn't try to touch a dead window
        try:
            if getattr(self, "net_worker", None) and self.net_worker.isRunning():
                self.net_worker.wait(1000)
        except Exception:
            pass

        # 4. Tear down the typing-mode manager (removes the event filter)
        try:
            if getattr(self, "typing_manager", None):
                self.typing_manager.shutdown()
        except Exception:
            pass

        super().closeEvent(event)

    def redo_edit(self):
        self.text_area.redo()
        self.text_area.setFocus()

    def toggle_phonetic(self, checked):
        self.phonetic_enabled = checked
        if checked:
            self.phonetic_btn.setText("Phonetic ON")
        else:
            self.phonetic_btn.setText("Phonetic OFF")
        self.text_area.setFocus()

    def on_reachability_changed(self, reachability):
        """
        Called by the OS whenever the network reachability changes.
        This is the new, event-driven replacement for the polling timer.
        """
        # The Reachability enum has several states. We'll treat
        # 'Online' and 'Unknown' as being online. The OS reports
        # 'Unknown' on some platforms when it can't be certain,
        # but a connection is usually still present.
        is_online = reachability in (
            QNetworkInformation.Reachability.Online,
            QNetworkInformation.Reachability.Unknown,
        )
        self.update_network_status(is_online)

    def update_network_status(self, is_online):
        self.is_online = is_online
        if is_online:
            self.network_status_label.setText("🟢 Online")
            self.network_status_label.setStyleSheet("color: #198754;")
        else:
            self.network_status_label.setText("🔴 Offline")
            self.network_status_label.setStyleSheet("color: #DC3545;")

    def check_spelling(self):
        if not self.spell_tool:
            return
        if self.spell_worker and self.spell_worker.isRunning():
            return

        full_text = self.text_area.toPlainText()
        MAX_CHECK_LEN = 2000
        if len(full_text) > MAX_CHECK_LEN:
            cursor = self.text_area.textCursor()
            pos = cursor.position()
            start = max(0, pos - MAX_CHECK_LEN // 2)
            end = min(len(full_text), pos + MAX_CHECK_LEN // 2)
            text_to_check = full_text[start:end]
        else:
            start = 0
            text_to_check = full_text

        self.spell_worker = SpellCheckWorker(text_to_check, self.spell_tool)
        self.spell_worker.results_ready.connect(lambda errors: self.update_spell_errors(errors, start))
        self.spell_worker.start()

    def update_spell_errors(self, errors, offset=0):
        adjusted_errors = []
        for start, end, suggestions in errors:
            real_start = start + offset
            real_end = end + offset
            if (real_start, real_end) not in self.ignored_error_ranges:
                adjusted_errors.append((real_start, real_end, suggestions))

        final_errors = []
        text = self.text_area.toPlainText()
        for start, end, suggestions in adjusted_errors:
            word = text[start:end]
            if unicodedata.normalize('NFC', word) not in self.user_dictionary:
                final_errors.append((start, end, suggestions))

        self.spell_errors = final_errors

        fmt = QTextCharFormat()
        fmt.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SpellCheckUnderline)
        fmt.setUnderlineColor(QColor("red"))
        extra_selections = []
        for start, end, _ in self.spell_errors:
            sel = QTextEdit.ExtraSelection()
            sel.format = fmt
            sel.cursor = QTextCursor(self.text_area.document())
            sel.cursor.setPosition(start)
            sel.cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            extra_selections.append(sel)
        self.text_area.setExtraSelections(extra_selections)

    def ignore_spelling_error(self, start, end):
        self.ignored_error_ranges.add((start, end))
        self.update_spell_errors(self.spell_errors)

    def clear_editor(self):
        self.text_area.clear_all()

    def undo_edit(self):
        self.text_area.undo()
        self.text_area.setFocus()

    def increase_font(self):
        font = self.text_area.font()
        current_size = font.pointSize()
        if current_size < 46:
            font.setPointSize(current_size + 1)
            self.text_area.setFont(font)
            self.settings.setValue("editor_font_size", current_size + 1)
            self.text_area.update_suggestion_font()

    def decrease_font(self):
        font = self.text_area.font()
        current_size = font.pointSize()
        if current_size > 8:
            font.setPointSize(current_size - 1)
            self.text_area.setFont(font)
            self.settings.setValue("editor_font_size", current_size - 1)
            self.text_area.update_suggestion_font()

    def translate_english(self):
        text = self.eng_input.text().strip()
        if not text:
            return

        self.translated_result.setText("Translating...")
        self.add_to_editor_btn.setEnabled(False)

        self.en_as_worker = EnglishToAssameseWorker(text)
        self.en_as_worker.translation_fetched.connect(self.on_translation_ready)
        self.en_as_worker.start()

    def on_translation_ready(self, translation):
        if translation and translation != "Error":
            self.current_translation = translation
            self.translated_result.setText(f"Result: {translation}")
            self.add_to_editor_btn.setEnabled(True)
        else:
            self.translated_result.setText("Result: Not found")
            self.add_to_editor_btn.setEnabled(False)

    def add_translation_to_editor(self):
        if hasattr(self, 'current_translation') and self.current_translation:
            self.text_area.insertPlainText(self.current_translation + " ")
            self.text_area.setFocus()
            self.eng_input.clear()
            self.translated_result.setText("Result: ")
            self.add_to_editor_btn.setEnabled(False)

    def load_helper_buttons(self):
        self.helpers = [
            {"name": "Bhuktobhugi", "text": "ভুক্তভোগী"},
            {"name": "Asami", "text": "আচামী"},
            {"name": "Gusoria", "text": "গোচৰীয়া"}
        ]
        if os.path.exists(self.helpers_file):
            with open(self.helpers_file, "r", encoding="utf-8") as f:
                self.helpers = json.load(f)
        self.refresh_helper_ui()

    def refresh_helper_ui(self):
        for i in reversed(range(self.helpers_layout.count())):
            widget = self.helpers_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        for index, helper in enumerate(self.helpers):
            btn = DraggableButton(helper["name"], index)
            btn.setToolTip(f"Right-click to delete.\nDrag to reorder.\nInserts: {helper['text']}")
            btn.clicked.connect(lambda checked, text=helper["text"]: self.insert_text(text))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(lambda pos, idx=index: self.remove_helper(idx))
            self.helpers_layout.addWidget(btn)

    def add_helper_dialog(self):
        name, ok1 = QInputDialog.getText(self, "Add Helper", "Button Name (e.g., Victim):")
        if ok1 and name:
            text, ok2 = QInputDialog.getText(self, "Add Helper", f"Assamese Text to insert for '{name}':")
            if ok2 and text:
                self.helpers.append({"name": name, "text": text})
                self.save_helper_buttons()
                self.refresh_helper_ui()

    def remove_helper(self, index):
        reply = QMessageBox.question(self, 'Remove Button', 'Are you sure you want to delete this helper button?',
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.helpers.pop(index)
            self.save_helper_buttons()
            self.refresh_helper_ui()

    def save_helper_buttons(self):
        with open(self.helpers_file, "w", encoding="utf-8") as f:
            json.dump(self.helpers, f, ensure_ascii=False, indent=4)

    def load_user_dictionary(self):
        words = set()
        if os.path.exists(self.user_dict_file):
            try:
                with open(self.user_dict_file, "r", encoding="utf-8") as f:
                    for line in f:
                        w = line.strip()
                        if w:
                            words.add(unicodedata.normalize('NFC', w))
            except Exception:
                pass
        return words

    def save_user_dictionary(self):
        try:
            with open(self.user_dict_file, "w", encoding="utf-8") as f:
                for w in sorted(self.user_dictionary):
                    f.write(w + "\n")
        except Exception:
            pass

    def add_to_user_dictionary(self, word):
        word = unicodedata.normalize('NFC', word.strip())
        if word and word not in self.user_dictionary:
            self.user_dictionary.add(word)
            self.save_user_dictionary()
            self.check_spelling()

    def insert_text(self, text):
        self.text_area.insertPlainText(text + " ")
        self.text_area.setFocus()

    def save_text(self):
        """Save editor text atomically with fsync for power-failure safety."""
        text = self.text_area.toPlainText()
        try:
            temp_file = self.autosave_file + ".tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_file, self.autosave_file)
            try:
                if hasattr(os, "O_DIRECTORY"):
                    dir_fd = os.open(
                        os.path.dirname(self.autosave_file) or ".",
                        os.O_DIRECTORY,
                    )
                    try:
                        os.fsync(dir_fd)
                    finally:
                        os.close(dir_fd)
            except Exception:
                pass
            backup_file = self.autosave_file + ".bak"
            with open(backup_file, "w", encoding="utf-8") as f:
                f.write(text)

        except Exception as e:
            try:
                err_log = os.path.join(get_user_data_dir(), "autosave_error.log")
                with open(err_log, "a", encoding="utf-8") as log:
                    log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {e}\n")
            except Exception:
                pass

    def load_autosave(self):
        candidates = [
            self.autosave_file,
            self.autosave_file + ".tmp",
            self.autosave_file + ".bak",
        ]
        for path in candidates:
            if not os.path.exists(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                if content and content.strip():
                    self.text_area.setPlainText(content)
                    if path != self.autosave_file:
                        QMessageBox.information(
                            self,
                            "Recovery",
                            f"Your previous text was recovered from "
                            f"{os.path.basename(path)}.",
                        )
                    return
            except Exception:
                continue

        # If nothing works, start empty
        self.text_area.setPlainText("")

    def copy_to_clipboard(self):
        clipboard = QApplication.clipboard()
        text = self.text_area.toPlainText()

        success = False
        for attempt in range(3):
            clipboard.clear()
            clipboard.setText(text)
            if clipboard.text() == text:
                success = True
                break
            QThread.msleep(50)

        if not success:
            cursor = self.text_area.textCursor()
            self.text_area.selectAll()
            self.text_area.copy()
            cursor.clearSelection()
            self.text_area.setTextCursor(cursor)
            if clipboard.text() != text:
                QMessageBox.warning(self, "Clipboard Error",
                                    "Could not copy to clipboard. Please try manually (Ctrl+C).")
                return

        original_text = self.copy_btn.text()
        self.copy_btn.setText("Copied ✓")
        QTimer.singleShot(1500, lambda: self.copy_btn.setText(original_text))

    def show_about_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("About সহজ-Sahaj")
        dialog.setFixedSize(550, 500)
        dialog.setStyleSheet(self.styleSheet())

        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("সহজ-Sahaj v3.0 — AI Assamese Typing Tool")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        desc = QLabel(
            "A modern, feature‑rich Assamese typing assistant built for "
            "legal professionals, writers, and anyone who needs to type "
            "in Assamese using English phonetics."
        )
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setFont(QFont("Arial", 10))
        layout.addWidget(desc)

        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #ADB5BD;")
        layout.addWidget(sep)

        features_label = QLabel("✨ <b>Features</b>")
        features_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        layout.addWidget(features_label)

        features_text = QTextEdit()
        features_text.setReadOnly(True)
        features_text.setFont(QFont("Arial", 10))
        features_text.setHtml("""
<ul>
<li>🌐 <b>Offline Transliteration</b> — Powered by AI4Bharat Xlit Engine for full offline execution.</li>
<li>🔤 <b>Phonetic Typing</b> — Type English (e.g., <i>bhuktobhugi</i>) and get instant Assamese output (<i>ভুক্তভোগী</i>).</li>
<li>✅ <b>Spell & Grammar Checking</b> — Misspelled Assamese words are underlined in red; right‑click for suggestions.</li>
<li>✅ <b>English to Assamese Translation</b> — Translate an English word to Assamese and add it to the Editor.</li>
<li>📖 <b>Built‑in Dictionary</b> — Hover over any Assamese word to see its English meaning.</li>
<li>🧩 <b>Draggable Helper Buttons</b> — One‑click insertion of frequently used legal phrases. Add, delete, and reorder.</li>
<li>💾 <b>Autosave</b> — Your work is saved automatically every 4 seconds.</li>
<li>🌗 <b>Light / Dark Theme</b> — Toggle between light and dark modes with one click.</li>
</ul>
        """)
        features_text.setMaximumHeight(280)
        layout.addWidget(features_text)

        credit = QLabel("👨‍💻 Developed by <b>Nazmul Hussain</b>")
        credit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        credit.setFont(QFont("Arial", 10))
        layout.addWidget(credit)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)

        dialog.exec()

    def show_support_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Support the Developer")
        dialog.setFixedSize(400, 480)
        dialog.setStyleSheet(self.styleSheet())

        layout = QVBoxLayout(dialog)
        layout.setSpacing(15)

        title = QLabel("❤️ Support সহজ-Sahaj")
        title.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        msg = QLabel(
            "If this tool helps you in your daily work,\n"
            "please consider a small contribution.\n"
            "Your support keeps the project alive! 🙏"
        )
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setWordWrap(True)
        layout.addWidget(msg)

        qr_path = resource_path("donate_qr.png")
        if os.path.exists(qr_path):
            qr_label = QLabel()
            pixmap = QPixmap(qr_path)
            pixmap = pixmap.scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            qr_label.setPixmap(pixmap)
            qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(qr_label)
        else:
            qr_missing = QLabel("(QR code image not found)\nPlace 'donate_qr.png' in the app folder.")
            qr_missing.setAlignment(Qt.AlignmentFlag.AlignCenter)
            qr_missing.setStyleSheet("color: gray;")
            layout.addWidget(qr_missing)

        upi_layout = QHBoxLayout()
        upi_label = QLabel("UPI ID: hussainnazmul786-2@okicici")
        upi_label.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        upi_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        upi_layout.addStretch()
        upi_layout.addWidget(upi_label)
        upi_layout.addStretch()
        layout.addLayout(upi_layout)
        copy_upi_btn = QPushButton("📋 Copy UPI ID")
        copy_upi_btn.clicked.connect(lambda: QApplication.clipboard().setText("hussainnazmul786-2@okicici"))
        layout.addWidget(copy_upi_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)

        dialog.exec()


def resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    clipboard = QApplication.clipboard()
    clipboard.clear()

    app_icon_path = resource_path("header_icon.png")
    if os.path.exists(app_icon_path):
        app.setWindowIcon(QIcon(app_icon_path))

        available_families = []

        font_path1 = resource_path("Nirmala.ttf")
        font_id1 = QFontDatabase.addApplicationFont(font_path1)
        if font_id1 != -1:
            family1 = QFontDatabase.applicationFontFamilies(font_id1)[0]
            available_families.append(family1)

        font_path2 = resource_path("Banikanta.ttf")
        font_id2 = QFontDatabase.addApplicationFont(font_path2)
        if font_id2 != -1:
            family2 = QFontDatabase.applicationFontFamilies(font_id2)[0]
            if family2 not in available_families:
                available_families.append(family2)

        if not available_families:
            available_families = ["Nirmala UI", "Segoe UI", "Arial"]
        else:
            available_families.extend(["Nirmala UI", "Segoe UI", "Arial"])

        seen = set()
        available_families = [f for f in available_families if not (f in seen or seen.add(f))]
        CUSTOM_FONT_FAMILIES = available_families

        splash_gif_path = resource_path("splash_animation.gif")

        if os.path.exists(splash_gif_path):
            splash = QLabel()
            splash.setWindowFlags(Qt.WindowType.SplashScreen |
                                  Qt.WindowType.WindowStaysOnTopHint |
                                  Qt.WindowType.FramelessWindowHint)
            splash.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            movie = QMovie(splash_gif_path)
            splash.setMovie(movie)
            movie.start()
        else:
            splash_label = QLabel()
            splash_label.setFixedSize(450, 250)
            splash_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            splash_label.setStyleSheet("""
                QLabel {
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #2C3E50, stop:1 #3498DB);
                    color: white;
                    font-family: "Segoe UI";
                    font-size: 26px;
                    font-weight: bold;
                    border-radius: 12px;
                    padding: 20px;
                }
            """)
            splash_label.setText("সহজ-Sahaj-v3.0\n\nLoading, please wait...\n\nDeveloped by Nazmul Hussain")
            splash_pixmap = splash_label.grab()
            splash = QSplashScreen(splash_pixmap, Qt.WindowType.WindowStaysOnTopHint)

        splash.show()
        app.processEvents()
        main_window = AssameseTypingApp()
        app.processEvents()

        def show_main_window():
            import sys
            if sys.platform == "win32":
                import ctypes
                hwnd = int(main_window.winId())
                foreground_hwnd = ctypes.windll.user32.GetForegroundWindow()

                if foreground_hwnd and foreground_hwnd != hwnd:
                    foreground_thread_id = ctypes.windll.user32.GetWindowThreadProcessId(foreground_hwnd, None)
                    current_thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
                    ctypes.windll.user32.AttachThreadInput(current_thread_id, foreground_thread_id, True)
                    ctypes.windll.user32.ShowWindow(hwnd, 5)
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
                    ctypes.windll.user32.AttachThreadInput(current_thread_id, foreground_thread_id, False)

            main_window.show()
            main_window.raise_()
            main_window.activateWindow()
            splash.close()

        QTimer.singleShot(7000, show_main_window)
        sys.exit(app.exec())
