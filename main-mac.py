import os
import sys
import base64
import webbrowser
import threading
import logging
from datetime import datetime
from PIL import ImageGrab
import requests
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QLineEdit, QTextEdit,
    QPushButton, QDialog, QRubberBand
)
from PyQt5.QtCore import Qt, QPoint, QRect, pyqtSignal, QObject
from PyQt5.QtGui import QPainter, QColor, QGuiApplication, QCursor
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Configuration
API_KEY = os.getenv("OPENAI_API_KEY")
if not API_KEY:
    raise RuntimeError("OPENAI_API_KEY not found in environment. Please set it in your .env file.")

TRANSLATION = os.getenv("TRANSLATION", "english")
OCR_MODEL = "gpt-4.1-mini"
TTS_MODEL = "gpt-4o-mini-tts"

# Logging setup
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("app.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Directories
SCREENSHOT_DIR = os.path.join(os.path.expanduser("~"), "Pictures", "Project")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)
SPEECH_DIR = os.path.join(os.path.expanduser("~"), "Pictures", "Speech")
os.makedirs(SPEECH_DIR, exist_ok=True)

class RegionSelector(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Select Region')
        # Frameless, always on top
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        # Remove FullScreen flag to keep transparency
        # Set the dialog geometry to cover the entire screen
        screen = QGuiApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        screen_rect = screen.geometry()
        self.setGeometry(screen_rect)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.origin = QPoint()
        self.rubberBand = QRubberBand(QRubberBand.Rectangle, self)
        self.selection = QRect()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))

    def mousePressEvent(self, event):
        self.origin = event.pos()
        self.rubberBand.setGeometry(QRect(self.origin, event.pos()))
        self.rubberBand.show()

    def mouseMoveEvent(self, event):
        self.rubberBand.setGeometry(QRect(self.origin, event.pos()).normalized())

    def mouseReleaseEvent(self, event):
        self.selection = self.rubberBand.geometry()
        self.rubberBand.hide()
        self.accept()

    def get_selection(self):
        return self.selection.getRect()

class SignalEmitter(QObject):
    capture = pyqtSignal()
    screenshot_last = pyqtSignal()

class App(QWidget):
    def __init__(self):
        super().__init__()
        self.last_path = None
        self.last_bbox = None
        self.signals = SignalEmitter()
        self.signals.capture.connect(self.capture_and_process)
        self.signals.screenshot_last.connect(self.screenshot_last_region)
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle('Screenshot OCR & Translation')
        layout = QVBoxLayout()
        layout.addWidget(QLabel('Last Screenshot:'))
        self.path_box = QLineEdit(); self.path_box.setReadOnly(True); layout.addWidget(self.path_box)
        layout.addWidget(QLabel('Extracted Text:'))
        self.text_box = QTextEdit(); layout.addWidget(self.text_box)
        btn = QPushButton('Capture'); btn.clicked.connect(lambda: self.signals.capture.emit()); layout.addWidget(btn)
        self.setLayout(layout); self.resize(800, 500)

    def capture_and_process(self):
        selector = RegionSelector()
        if selector.exec_() != QDialog.Accepted:
            return
        x, y, w, h = selector.get_selection()
        self.last_bbox = (x, y, x + w, y + h)
        self._capture(self.last_bbox)

    def screenshot_last_region(self):
        if not self.last_bbox:
            logger.warning("No previous region to capture.")
            return
        self._capture(self.last_bbox)

    def _capture(self, bbox):
        try:
            path = os.path.join(SCREENSHOT_DIR, f"{datetime.now():%Y%m%d_%H%M%S}.png")
            ImageGrab.grab(bbox).save(path)
            self.last_path = path
            self.path_box.setText(path)
            logger.info(f"Captured screenshot {path} bbox={bbox}")

            with open(path, 'rb') as f:
                data = base64.b64encode(f.read()).decode()
            messages = [
                {
                    "role": "system",
                    "content": f"""
You are an advanced OCR and translation engine. When given an image, follow these steps in order:

1. **Extract Text**: Use OCR to accurately extract all visible text from the image.
2. **Detect Language**: Identify the language of the extracted text.
3. **Full Sentence Translation**: Translate the entire original sentence into fluent {TRANSLATION}, preserving the context and meaning.
4. **Word-by-Word Breakdown**: For each word in the text, provide:
   - The original word
   - Its meaning in {TRANSLATION}
   - Its part of speech (if identifiable)

Your response must be structured and informative, suitable for someone trying to both understand and learn from the original text.
"""
                },
                {"role": "user", "content": [{"type": "text", "text": ""},
                                             {"type": "image_url", "image_url": {"url": "data:image/png;base64," + data}}]}
            ]
            payload = {"model": OCR_MODEL, "messages": messages}
            headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
            resp = requests.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers)
            resp.raise_for_status()
            self.text_box.setPlainText(resp.json()["choices"][0]["message"]["content"])
        except Exception:
            logger.exception("Error during screenshot and OCR")

if __name__ == '__main__':
    logger.info("Starting application")
    app = QApplication(sys.argv)
    ex = App()
    ex.show()
    sys.exit(app.exec_())