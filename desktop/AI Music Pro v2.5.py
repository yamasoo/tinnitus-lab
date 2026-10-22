"""
AI Music Pro - Modern Glass Edition
v2.5.0
新增（v2.5）：
  - 耳鳴模式：左右耳各自設定 缺口 / 頻段補強 / 關閉、中心頻率、寬度
  - 耳鳴設定對話框、設定檔匯入匯出（與手機版共用 tinnitus-profile/1 格式）
  - 背景執行緒處理，處理後的版本存在快取，切換時從原本位置接著播
  - 曲目資訊顯示處理報告（頻段衰減、頻段能量不足提醒）
  - 批次匯出耳鳴版本（MP3 / FLAC / WAV）
  - 修正：暫停後再播放會從頭開始的問題
  需要：tinnitus_dsp.py（同資料夾）、scipy、soundfile；建議 pyloudnorm

v2.4.0 新增：
  - 修復 ffmpeg 子行程在打包後 CMD 閃窗問題（run_hidden）
  - 排序功能：名稱 A→Z / Z→A、生成時間 新→舊 / 舊→新、時長 短→長 / 長→短
  - 子目錄一層掃描（可勾選）
  - MP4/M4A 支援（ffmpeg 轉碼播放）
  - 封面圖顯示（內嵌 / 同名圖 / 通用封面 / MP4 抽幀）
  - 封面圖作為歌詞框底圖
  - 全域字色改為深紫色 #7C3AED
"""

import sys
import os
import re
import random
import json
import hashlib
import subprocess
import copy
import numpy as np
from pathlib import Path

import pygame
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QListWidget, QTextEdit,
                             QFileDialog, QLabel, QSlider, QStyle, QLineEdit,
                             QComboBox, QMessageBox, QMenuBar, QMenu, QCheckBox,
                             QDialog, QGroupBox, QFormLayout, QSpinBox, QDoubleSpinBox,
                             QDialogButtonBox, QProgressDialog, QInputDialog)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QSize, QPoint, QThread
from PyQt6.QtGui import (QPixmap, QPalette, QBrush, QColor, QIcon, QAction,
                         QFont, QLinearGradient, QPainter, QPen)
import matplotlib
# ★ 先設定 matplotlib 全域字體，避免 Qt 後端初始化時取到 -1
matplotlib.rcParams['font.size'] = 12
matplotlib.rcParams['axes.titlesize'] = 12
matplotlib.rcParams['axes.labelsize'] = 12
matplotlib.rcParams['xtick.labelsize'] = 12
matplotlib.rcParams['ytick.labelsize'] = 12
matplotlib.rcParams['font.family'] = 'sans-serif'
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

try:
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3
    from mutagen.flac import FLAC
    from mutagen.mp4 import MP4
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

# ──────────────────────────────────────────────
# 全域常數
# ──────────────────────────────────────────────

APP_NAME = "AI Music Pro"
APP_VERSION = "2.5.0"
CONFIG_FILE = "player_config.json"
ICON_FILE = "icon.ico"

MUSIC_EXTENSIONS = ('.mp3', '.wav', '.ogg', '.flac', '.m4a', '.mp4')
NEEDS_CONVERT = ('.mp4', '.m4a')
IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp', '.bmp')

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".ai_music_pro_cache")


# ──────────────────────────────────────────────
# 工具函式
# ──────────────────────────────────────────────

def format_time(seconds: float) -> str:
    seconds = max(0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def get_resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def find_ffmpeg():
    """尋找系統上的 ffmpeg 執行檔"""
    from shutil import which
    p = which("ffmpeg")
    if p:
        return p
    if sys.platform == "win32":
        import glob
        candidates = [
            r"C:\ffmpeg\bin\ffmpeg.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-*\bin\ffmpeg.exe"),
            os.path.expandvars(r"%ProgramFiles%\ffmpeg\bin\ffmpeg.exe"),
        ]
        for c in candidates:
            for hit in glob.glob(c):
                if os.path.exists(hit):
                    return hit
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


# ──────────────────────────────────────────────
# Windows 隱藏子行程 console 視窗
# ──────────────────────────────────────────────
if sys.platform == "win32":
    _CREATE_NO_WINDOW = 0x08000000
    _STARTUPINFO = subprocess.STARTUPINFO()
    _STARTUPINFO.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    _STARTUPINFO.wShowWindow = 0   # SW_HIDE
else:
    _CREATE_NO_WINDOW = 0
    _STARTUPINFO = None


def run_hidden(cmd, timeout=None, **kwargs):
    """呼叫外部行程並隱藏 console 視窗（Windows 有效）"""
    run_kwargs = dict(capture_output=True, **kwargs)
    if timeout is not None:
        run_kwargs["timeout"] = timeout
    if sys.platform == "win32":
        run_kwargs["creationflags"] = _CREATE_NO_WINDOW
        run_kwargs["startupinfo"] = _STARTUPINFO
    return subprocess.run(cmd, **run_kwargs)


# ──────────────────────────────────────────────
# 自訂元件
# ──────────────────────────────────────────────

class ClickableSlider(QSlider):
    """支援直接點擊跳轉的進度條"""
    clicked_pos = pyqtSignal(int)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            x_pos = int(event.position().x())
            val = QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(), x_pos, self.width()
            )
            self.setValue(val)
            self.clicked_pos.emit(val)
        super().mousePressEvent(event)


class SpectrumCanvas(FigureCanvas):
    """模擬頻譜視覺化"""
    def __init__(self, parent=None):
        fig = Figure(figsize=(5, 1.2), facecolor='#121212', dpi=100)
        self.ax = fig.add_subplot(111)
        self.ax.set_facecolor('#121212')
        self.ax.set_ylim(0, 10)
        self.ax.set_xlim(0, 100)
        self.ax.axis('off')
        self.x = np.linspace(0, 100, 60)
        self.y = np.zeros(60)
        self.line, = self.ax.plot(self.x, self.y, linewidth=2.5, alpha=0.8)
        self.line.set_color('#00F0FF')
        super().__init__(fig)
        self.phase = 0

    def update_data(self, is_playing: bool):
        if is_playing:
            self.phase += 0.1
            base = np.random.uniform(0.5, 2, 60)
            wave = np.sin(np.linspace(0, 4*np.pi, 60) + self.phase) * 2
            self.y = base + np.abs(wave) * 2
            self.y = np.clip(self.y, 0.5, 9)
            volume_factor = pygame.mixer.music.get_volume() if pygame.mixer.get_init() else 0.5
            self.y = self.y * (0.5 + volume_factor)
        else:
            self.y = np.zeros(60)
            self.phase = 0
        self.line.set_ydata(self.y)
        self.draw_idle()


class EqualizerWidget(QWidget):
    """簡易等化器視窗"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("等化器")
        self.setWindowFlags(Qt.WindowType.Window)
        self.resize(400, 300)
        layout = QVBoxLayout()
        eq_layout = QHBoxLayout()
        self.sliders = []
        frequencies = ["32Hz", "64Hz", "125Hz", "250Hz", "500Hz",
                       "1kHz", "2kHz", "4kHz", "8kHz", "16kHz"]
        for freq in frequencies:
            slider_container = QVBoxLayout()
            slider = QSlider(Qt.Orientation.Vertical)
            slider.setRange(-12, 12)
            slider.setValue(0)
            slider.setTickPosition(QSlider.TickPosition.TicksRight)
            label = QLabel(freq)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            slider_container.addWidget(slider)
            slider_container.addWidget(label)
            eq_layout.addLayout(slider_container)
            self.sliders.append(slider)
        layout.addLayout(eq_layout)
        reset_btn = QPushButton("重置")
        reset_btn.clicked.connect(self.reset_eq)
        layout.addWidget(reset_btn)
        self.setLayout(layout)

    def reset_eq(self):
        for slider in self.sliders:
            slider.setValue(0)



# ──────────────────────────────────────────────
# 耳鳴模式（v2.5）
# ──────────────────────────────────────────────
try:
    import tinnitus_dsp as tdsp
    import soundfile  # noqa: F401  讀寫音檔
    import scipy.signal  # noqa: F401  濾波
    TINNITUS_AVAILABLE = True
    TINNITUS_IMPORT_ERROR = ""
except Exception as _tin_err:  # noqa: BLE001
    tdsp = None
    TINNITUS_AVAILABLE = False
    TINNITUS_IMPORT_ERROR = str(_tin_err)

TINNITUS_CACHE_DIR = os.path.join(CACHE_DIR, "tinnitus")
EAR_LABELS = {"left": "左耳", "right": "右耳"}
MODE_LABELS = [("off", "關閉"), ("notch", "缺口"), ("boost", "頻段補強")]
MODE_SHORT = {"off": "關", "notch": "缺口", "boost": "補強"}


def tinnitus_install_message():
    return ("耳鳴模式需要額外的套件：\n"
            "    pip install numpy scipy soundfile pyloudnorm\n\n"
            "並把 tinnitus_dsp.py 放在和主程式同一個資料夾。\n\n"
            f"目前的錯誤：{TINNITUS_IMPORT_ERROR}")


def default_tinnitus_profile():
    return tdsp.make_profile(
        left={"mode": "notch", "center_hz": 9500, "width_oct": 1.0},
        right={"mode": "off", "center_hz": 9500, "width_oct": 1.0},
        name="左耳 9.5k 缺口")


def describe_tinnitus_profile(profile):
    parts = []
    for ear in ("left", "right"):
        e = profile["ears"][ear]
        if e["mode"] == "off":
            parts.append(f"{EAR_LABELS[ear]}：關")
        else:
            parts.append(f"{EAR_LABELS[ear]}：{MODE_SHORT[e['mode']]} {e['center_hz']:.0f} Hz")
    return "｜".join(parts)


def tinnitus_cache_paths(src_path, profile):
    """快取檔名包含：原檔路徑、大小、修改時間、設定檔內容。任何一項改變都會重新處理。"""
    try:
        st = os.stat(src_path)
        stamp = f"{st.st_size}:{st.st_mtime_ns}"
    except OSError:
        stamp = ""
    key_src = "|".join([os.path.abspath(src_path), stamp,
                        json.dumps(profile, sort_keys=True, ensure_ascii=False)])
    key = hashlib.md5(key_src.encode("utf-8")).hexdigest()
    return (os.path.join(TINNITUS_CACHE_DIR, key + ".wav"),
            os.path.join(TINNITUS_CACHE_DIR, key + ".txt"))


class TinnitusWorker(QThread):
    """背景處理單首歌，產生耳鳴版快取 WAV（16-bit，pygame 相容性最好）"""
    done = pyqtSignal(int, str, str)    # job_id, 輸出路徑, 報告文字
    failed = pyqtSignal(int, str)       # job_id, 錯誤訊息

    def __init__(self, job_id, src_path, profile, parent=None):
        super().__init__(parent)
        self.job_id = job_id
        self.src_path = src_path
        self.profile = profile

    def run(self):
        try:
            wav, txt = tinnitus_cache_paths(self.src_path, self.profile)
            if os.path.exists(wav) and os.path.getsize(wav) > 0:
                summary = ""
                if os.path.exists(txt):
                    with open(txt, encoding="utf-8") as f:
                        summary = f.read()
                self.done.emit(self.job_id, wav, summary)
                return
            os.makedirs(TINNITUS_CACHE_DIR, exist_ok=True)
            tmp = wav[:-4] + ".part.wav"
            _, rep = tdsp.process_file(self.src_path, self.profile,
                                       out_path=tmp, wav_subtype="PCM_16")
            os.replace(tmp, wav)
            summary = rep.summary()
            with open(txt, "w", encoding="utf-8") as f:
                f.write(summary)
            self.done.emit(self.job_id, wav, summary)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(self.job_id, str(e))


class TinnitusBatchWorker(QThread):
    """批次匯出耳鳴版本"""
    progress = pyqtSignal(int, int, str)          # 第幾首, 總數, 檔名
    finished_all = pyqtSignal(int, int, list, list)  # 成功數, 總數, 錯誤, 頻段能量不足的歌

    def __init__(self, paths, profile, out_dir, fmt, parent=None):
        super().__init__(parent)
        self.paths = list(paths)
        self.profile = profile
        self.out_dir = out_dir
        self.fmt = fmt
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        ok, errors, weak = 0, [], []
        n = len(self.paths)
        for i, src in enumerate(self.paths):
            if self._cancel:
                break
            name = os.path.basename(src)
            self.progress.emit(i, n, name)
            try:
                out = tdsp.default_output_path(src, self.out_dir, self.fmt)
                _, rep = tdsp.process_file(src, self.profile, out_path=out)
                ok += 1
                if any("能量很少" in w for e in rep.ears for w in e.warnings):
                    weak.append(name)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{name}：{e}")
        self.progress.emit(n, n, "")
        self.finished_all.emit(ok, n, errors, weak)


class EarSettingsBox(QGroupBox):
    """單耳設定：模式、中心頻率（數字 + 對數滑桿）、寬度、補強增益"""
    F_MIN, F_MAX = 200, 16000

    def __init__(self, ear, settings, parent=None):
        super().__init__(EAR_LABELS[ear], parent)
        self.ear = ear
        form = QFormLayout(self)

        self.mode = QComboBox()
        for key, label in MODE_LABELS:
            self.mode.addItem(label, key)
        form.addRow("模式", self.mode)

        self.freq = QSpinBox()
        self.freq.setRange(self.F_MIN, self.F_MAX)
        self.freq.setSingleStep(10)
        self.freq.setSuffix(" Hz")
        form.addRow("中心頻率", self.freq)

        self.freq_slider = QSlider(Qt.Orientation.Horizontal)
        self.freq_slider.setRange(0, 1000)
        form.addRow("", self.freq_slider)

        self.width = QComboBox()
        for label, val in (("½ 八度", 0.5), ("1 八度", 1.0), ("1½ 八度", 1.5)):
            self.width.addItem(label, val)
        form.addRow("寬度", self.width)

        self.boost = QDoubleSpinBox()
        self.boost.setRange(0, 12)
        self.boost.setSingleStep(0.5)
        self.boost.setSuffix(" dB")
        form.addRow("補強量", self.boost)

        self.band_label = QLabel()
        self.band_label.setWordWrap(True)
        form.addRow("", self.band_label)

        self.freq.valueChanged.connect(self._freq_changed)
        self.freq_slider.valueChanged.connect(self._slider_changed)
        self.mode.currentIndexChanged.connect(self._refresh)
        self.width.currentIndexChanged.connect(self._refresh)
        self.set_settings(settings)

    def _pos_to_f(self, p):
        return self.F_MIN * (self.F_MAX / self.F_MIN) ** (p / 1000)

    def _f_to_pos(self, f):
        return int(round(1000 * np.log(f / self.F_MIN) / np.log(self.F_MAX / self.F_MIN)))

    def _freq_changed(self, v):
        self.freq_slider.blockSignals(True)
        self.freq_slider.setValue(self._f_to_pos(v))
        self.freq_slider.blockSignals(False)
        self._refresh()

    def _slider_changed(self, p):
        f = int(round(self._pos_to_f(p) / 10) * 10)
        self.freq.blockSignals(True)
        self.freq.setValue(f)
        self.freq.blockSignals(False)
        self._refresh()

    def _refresh(self):
        mode = self.mode.currentData()
        on = mode != "off"
        for w in (self.freq, self.freq_slider, self.width):
            w.setEnabled(on)
        self.boost.setEnabled(mode == "boost")
        if not on:
            self.band_label.setText("這一耳不處理")
            return
        w = self.width.currentData()
        lo = self.freq.value() / 2 ** (w / 2)
        hi = self.freq.value() * 2 ** (w / 2)
        verb = "濾掉" if mode == "notch" else "加強"
        self.band_label.setText(f"{verb}約 {lo:,.0f} – {hi:,.0f} Hz")

    def set_settings(self, d):
        self.mode.setCurrentIndex(max(0, self.mode.findData(d.get("mode", "off"))))
        self.freq.setValue(int(round(d.get("center_hz", 4000))))
        idx = self.width.findData(float(d.get("width_oct", 1.0)))
        if idx < 0:
            self.width.addItem(f"{d['width_oct']} 八度", float(d["width_oct"]))
            idx = self.width.count() - 1
        self.width.setCurrentIndex(idx)
        self.boost.setValue(float(d.get("boost_db", 6.0)))
        self._order = int(d.get("order", 6))
        self._freq_changed(self.freq.value())

    def settings(self):
        return {"mode": self.mode.currentData(), "center_hz": float(self.freq.value()),
                "width_oct": float(self.width.currentData()), "order": self._order,
                "boost_db": float(self.boost.value())}


class TinnitusDialog(QDialog):
    """耳鳴設定對話框"""

    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self.setWindowTitle("耳鳴設定")
        self.setMinimumWidth(620)
        self.setStyleSheet("""
            QDialog { background-color: #1B1B1F; }
            QGroupBox { color: #00F0FF; font-weight: bold; border: 1px solid #444;
                        border-radius: 8px; margin-top: 12px; padding: 10px 8px 8px 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QLabel { color: #DDD; }
            QSpinBox, QDoubleSpinBox { background: rgba(34,34,34,220); border: 1px solid #444;
                        border-radius: 6px; padding: 4px; color: #DDD; }
        """)
        self._profile = tdsp.validate_profile(profile)
        self.result_profile = None
        lay = QVBoxLayout(self)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("設定名稱"))
        self.name_edit = QLineEdit()
        name_row.addWidget(self.name_edit, 1)
        lay.addLayout(name_row)

        ears = QHBoxLayout()
        self.boxes = {e: EarSettingsBox(e, self._profile["ears"][e]) for e in ("left", "right")}
        ears.addWidget(self.boxes["left"])
        ears.addWidget(self.boxes["right"])
        lay.addLayout(ears)

        copy_row = QHBoxLayout()
        b1 = QPushButton("左耳設定 → 右耳")
        b1.clicked.connect(lambda: self.boxes["right"].set_settings(self.boxes["left"].settings()))
        b2 = QPushButton("右耳設定 → 左耳")
        b2.clicked.connect(lambda: self.boxes["left"].set_settings(self.boxes["right"].settings()))
        copy_row.addWidget(b1)
        copy_row.addWidget(b2)
        copy_row.addStretch()
        lay.addLayout(copy_row)

        out_box = QGroupBox("輸出")
        out_form = QFormLayout(out_box)
        self.lufs = QDoubleSpinBox()
        self.lufs.setRange(-30, -14)
        self.lufs.setSingleStep(1)
        self.lufs.setSuffix(" LUFS")
        out_form.addRow("目標響度", self.lufs)
        hint = QLabel("耳鳴模式會把每首歌統一到這個響度，通常會比原音小聲。"
                      "長時間聆聽請保持小音量，比耳鳴稍小或差不多即可。")
        hint.setWordWrap(True)
        out_form.addRow("", hint)
        lay.addWidget(out_box)

        btn_row = QHBoxLayout()
        imp = QPushButton("匯入設定檔…")
        imp.clicked.connect(self._import)
        exp = QPushButton("匯出設定檔…")
        exp.clicked.connect(self._export)
        btn_row.addWidget(imp)
        btn_row.addWidget(exp)
        btn_row.addStretch()
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("確定")
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        btn_row.addWidget(bb)
        lay.addLayout(btn_row)

        self._fill(self._profile)

    def _fill(self, p):
        self.name_edit.setText(p.get("name", ""))
        for e in ("left", "right"):
            self.boxes[e].set_settings(p["ears"][e])
        self.lufs.setValue(p["output"]["target_lufs"])

    def _collect(self):
        p = copy.deepcopy(self._profile)
        p["name"] = self.name_edit.text().strip() or "自訂"
        for e in ("left", "right"):
            p["ears"][e] = self.boxes[e].settings()
        p["output"]["target_lufs"] = float(self.lufs.value())
        return tdsp.validate_profile(p)

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "匯入耳鳴設定檔", "", "耳鳴設定檔 (*.json)")
        if not path:
            return
        try:
            self._profile = tdsp.load_profile(path)
            self._fill(self._profile)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "匯入失敗", f"這個檔案不是可用的耳鳴設定檔：\n{e}")

    def _export(self):
        try:
            p = self._collect()
        except ValueError as e:
            QMessageBox.warning(self, "設定有誤", str(e))
            return
        path, _ = QFileDialog.getSaveFileName(self, "匯出耳鳴設定檔", "tinnitus_profile.json",
                                              "耳鳴設定檔 (*.json)")
        if path:
            try:
                tdsp.save_profile(p, path)
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, "匯出失敗", str(e))

    def accept(self):
        try:
            self.result_profile = self._collect()
        except ValueError as e:
            QMessageBox.warning(self, "設定有誤", str(e))
            return
        super().accept()

# ──────────────────────────────────────────────
# 主應用程式
# ──────────────────────────────────────────────

class AIMusicApp(QMainWindow):
    LOOP_NONE, LOOP_ALL, LOOP_ONE = 0, 1, 2

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION} - Modern Glass Edition")
        self.resize(1200, 900)

        self.setup_app_icon()
        self.setAcceptDrops(True)

        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        except pygame.error as e:
            QMessageBox.warning(self, "初始化錯誤",
                               f"音頻系統初始化失敗：{str(e)}\n"
                               "將使用模擬模式（無聲音）")
            pygame.mixer.init()

        # 狀態變數
        self.current_audio_path = ""
        self._playback_path = ""
        self.current_bg_path = get_resource_path("background.jpg")
        self.is_playing = False
        self.total_length = 0
        self.seek_position = 0
        self.loop_mode = self.LOOP_NONE
        self.shuffle_mode = False
        self.all_tracks = []
        self.filtered_tracks = []
        self.play_history = []
        self.current_playlist_index = -1
        self._cover_cache = {}
        self._duration_cache = {}
        self._ffmpeg_path = None
        self._current_info_bg_pixmap = None
        self._paused = False

        # 耳鳴模式狀態
        self.tinnitus_enabled = False
        self.tinnitus_profile = default_tinnitus_profile() if TINNITUS_AVAILABLE else None
        self._tinnitus_job = 0
        self._tinnitus_busy = False
        self._tinnitus_pending = None      # (續播位置, 是否自動播放)
        self._tinnitus_report = ""
        self._source_playback_path = ""    # 原音（或 MP4 轉出的 WAV）
        self._current_track = None
        self._workers = set()
        self._batch_worker = None

        self.init_ui()
        self.create_menu_bar()
        self.load_config()

        if os.path.exists(self.current_bg_path):
            self._apply_background_logic()

        self.setup_timers()
        self.apply_stylesheet()

    def setup_app_icon(self):
        icon_paths = [
            get_resource_path(ICON_FILE),
            get_resource_path("icon.png"),
            get_resource_path("app.ico"),
            os.path.join(os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else __file__), ICON_FILE)
        ]
        for icon_path in icon_paths:
            if os.path.exists(icon_path):
                icon = QIcon(icon_path)
                if not icon.isNull():
                    self.setWindowIcon(icon)
                    if sys.platform == 'win32':
                        try:
                            import ctypes
                            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_NAME)
                        except:
                            pass
                    break

    def create_menu_bar(self):
        menubar = self.menuBar()

        # 檔案選單
        file_menu = menubar.addMenu("檔案")
        open_action = QAction("開啟音樂目錄", self)
        open_action.triggered.connect(self.select_directory)
        file_menu.addAction(open_action)

        open_files_action = QAction("加入音樂檔案", self)
        open_files_action.triggered.connect(self.select_files)
        file_menu.addAction(open_files_action)
        file_menu.addSeparator()

        save_playlist_action = QAction("儲存播放清單", self)
        save_playlist_action.triggered.connect(self.save_playlist)
        file_menu.addAction(save_playlist_action)

        load_playlist_action = QAction("載入播放清單", self)
        load_playlist_action.triggered.connect(self.load_playlist)
        file_menu.addAction(load_playlist_action)
        file_menu.addSeparator()

        exit_action = QAction("離開", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # 播放選單
        play_menu = menubar.addMenu("播放")
        play_pause_action = QAction("播放/暫停", self)
        play_pause_action.setShortcut("Space")
        play_pause_action.triggered.connect(self.toggle_play)
        play_menu.addAction(play_pause_action)

        prev_action = QAction("上一首", self)
        prev_action.setShortcut("Ctrl+Left")
        prev_action.triggered.connect(self.prev_track)
        play_menu.addAction(prev_action)

        next_action = QAction("下一首", self)
        next_action.setShortcut("Ctrl+Right")
        next_action.triggered.connect(self.next_track)
        play_menu.addAction(next_action)
        play_menu.addSeparator()

        loop_menu = play_menu.addMenu("循環模式")
        self.loop_none_action = QAction("不循環", self)
        self.loop_none_action.setCheckable(True)
        self.loop_none_action.triggered.connect(lambda: self.set_loop_mode(0))
        loop_menu.addAction(self.loop_none_action)

        self.loop_all_action = QAction("清單循環", self)
        self.loop_all_action.setCheckable(True)
        self.loop_all_action.triggered.connect(lambda: self.set_loop_mode(1))
        loop_menu.addAction(self.loop_all_action)

        self.loop_one_action = QAction("單曲循環", self)
        self.loop_one_action.setCheckable(True)
        self.loop_one_action.triggered.connect(lambda: self.set_loop_mode(2))
        loop_menu.addAction(self.loop_one_action)
        play_menu.addSeparator()

        shuffle_action = QAction("隨機播放", self)
        shuffle_action.setCheckable(True)
        shuffle_action.triggered.connect(self.toggle_shuffle_menu)
        play_menu.addAction(shuffle_action)

        # 檢視選單
        view_menu = menubar.addMenu("檢視")
        always_on_top_action = QAction("視窗最上層", self)
        always_on_top_action.setCheckable(True)
        always_on_top_action.triggered.connect(lambda checked:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, checked) or self.show())
        view_menu.addAction(always_on_top_action)
        view_menu.addSeparator()

        show_eq_action = QAction("顯示等化器", self)
        show_eq_action.triggered.connect(self.show_equalizer)
        view_menu.addAction(show_eq_action)

        # 耳鳴選單
        tin_menu = menubar.addMenu("耳鳴")
        self.tinnitus_action = QAction("耳鳴模式", self)
        self.tinnitus_action.setCheckable(True)
        self.tinnitus_action.setShortcut("Ctrl+T")
        self.tinnitus_action.triggered.connect(self.set_tinnitus_enabled)
        tin_menu.addAction(self.tinnitus_action)

        tin_settings = QAction("耳鳴設定…", self)
        tin_settings.setShortcut("Ctrl+Shift+T")
        tin_settings.triggered.connect(self.open_tinnitus_settings)
        tin_menu.addAction(tin_settings)
        tin_menu.addSeparator()

        tin_import = QAction("匯入設定檔…", self)
        tin_import.triggered.connect(self.import_tinnitus_profile)
        tin_menu.addAction(tin_import)
        tin_export = QAction("匯出設定檔…", self)
        tin_export.triggered.connect(self.export_tinnitus_profile)
        tin_menu.addAction(tin_export)
        tin_menu.addSeparator()

        tin_batch = QAction("批次匯出耳鳴版本…", self)
        tin_batch.triggered.connect(self.batch_export_tinnitus)
        tin_menu.addAction(tin_batch)
        tin_clear = QAction("清除耳鳴快取", self)
        tin_clear.triggered.connect(self.clear_tinnitus_cache)
        tin_menu.addAction(tin_clear)

        # 說明選單
        help_menu = menubar.addMenu("說明")
        about_action = QAction("關於", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def setup_timers(self):
        self.viz_timer = QTimer()
        self.viz_timer.timeout.connect(lambda: self.canvas.update_data(self.is_playing))
        self.viz_timer.start(50)

        self.progress_timer = QTimer()
        self.progress_timer.timeout.connect(self.update_progress)
        self.progress_timer.start(200)

        self.end_check_timer = QTimer()
        self.end_check_timer.timeout.connect(self.check_track_end)
        self.end_check_timer.start(500)

    def apply_stylesheet(self):
        self.setStyleSheet("""
            QMainWindow { background-color: transparent; }
            QListWidget, QTextEdit {
                background-color: rgba(25, 25, 25, 200);
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 12px;
                color: #FEE;
                padding: 8px;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid rgba(255, 255, 255, 10);
                border-radius: 6px;
            }
            QListWidget::item:hover { background-color: rgba(255, 255, 255, 20); }
            QListWidget::item:selected {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                           stop:0 #00F0FF, stop:1 #0078D4);
                color: black;
            }
            QPushButton {
                background-color: rgba(45, 45, 45, 220);
                border: 1px solid #444;
                border-radius: 8px;
                padding: 8px 15px;
                color: white;
                font-weight: bold;
                font-size: 12px;
            }
            QPushButton:hover {
                border: 1px solid #00F0FF;
                background-color: rgba(60, 60, 60, 240);
            }
            QPushButton:pressed { background-color: rgba(30, 30, 30, 240); }
            QPushButton:checked {
                background-color: #00F0FF;
                color: #000;
                border: 1px solid #00F0FF;
            }
            QLineEdit, QComboBox {
                background: rgba(34, 34, 34, 220);
                border: 1px solid #444;
                border-radius: 6px;
                padding: 6px;
                color: #DDD;
                font-size: 12px;
            }
            QLineEdit:focus, QComboBox:focus { border: 1px solid #00F0FF; }

            /* 全域 QLabel：深紫色（原本是螢光綠） */
            QLabel { color: #7C3AED; font-size: 12px; }

            QCheckBox {
                color: #DDD;
                font-size: 12px;
                padding: 3px;
                spacing: 6px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 1px solid #666;
                border-radius: 4px;
                background: rgba(40, 40, 40, 220);
            }
            QCheckBox::indicator:checked {
                background: #00F0FF;
                border: 1px solid #00F0FF;
                image: none;
            }
            QCheckBox::indicator:hover { border: 1px solid #00F0FF; }
            QSlider::groove:horizontal {
                border: 1px solid #444;
                height: 6px;
                background: rgba(255, 255, 255, 20);
                margin: 2px 0;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #00F0FF;
                border: 1px solid #00F0FF;
                width: 14px;
                height: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }
            QSlider::handle:horizontal:hover { background: #00FFFF; }
            QSlider::sub-page:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                           stop:0 #00F0FF, stop:1 #0078D4);
                border-radius: 3px;
            }
            QMenuBar {
                background-color: rgba(25, 25, 25, 200);
                color: white;
                border-bottom: 1px solid #444;
            }
            QMenuBar::item { padding: 5px 10px; background: transparent; }
            QMenuBar::item:selected { background-color: #00F0FF; color: black; }
            QMenu {
                background-color: rgba(35, 35, 35, 230);
                color: white;
                border: 1px solid #444;
                padding: 5px;
            }
            QMenu::item { padding: 5px 20px; border-radius: 3px; }
            QMenu::item:selected { background-color: #00F0FF; color: black; }
            QMenu::separator { height: 1px; background: #444; margin: 5px 0; }

            /* QMessageBox 內文字也用深紫，在白色對話框上清晰可讀 */
            QMessageBox QLabel { color: #7C3AED; }
        """)

    def init_ui(self):
        self.main_container = QWidget()
        self.setCentralWidget(self.main_container)
        main_layout = QHBoxLayout(self.main_container)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # ── 左面板 ──
        left_panel = QVBoxLayout()
        left_panel.setSpacing(8)

        title_label = QLabel(f"{APP_NAME}")
        title_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #00F0FF; padding: 5px;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_panel.addWidget(title_label)

        btn_toolbar = QHBoxLayout()
        self.btn_browse = QPushButton("📂 開啟目錄")
        self.btn_browse.clicked.connect(self.select_directory)
        btn_toolbar.addWidget(self.btn_browse)

        self.btn_add_files = QPushButton("➕ 加入檔案")
        self.btn_add_files.clicked.connect(self.select_files)
        btn_toolbar.addWidget(self.btn_add_files)
        left_panel.addLayout(btn_toolbar)

        self.chk_subdir = QCheckBox("📁 掃描子目錄（一層）")
        self.chk_subdir.setToolTip("勾選後，開啟目錄時會連同一層子目錄內的音樂一起匯入")
        left_panel.addWidget(self.chk_subdir)

        # 曲風過濾
        self.genre_combo = QComboBox()
        self.genre_combo.addItem("🎵 全部曲風")
        self.genre_combo.currentTextChanged.connect(self.apply_filter)
        left_panel.addWidget(self.genre_combo)

        # 排序
        sort_layout = QHBoxLayout()
        sort_label = QLabel("排序:")
        sort_label.setStyleSheet("color: #BBB; font-size: 12px;")
        sort_layout.addWidget(sort_label)

        self.sort_combo = QComboBox()
        self.sort_combo.addItem("名稱 A→Z", "name_asc")
        self.sort_combo.addItem("名稱 Z→A", "name_desc")
        self.sort_combo.addItem("生成時間 新→舊", "ctime_new")
        self.sort_combo.addItem("生成時間 舊→新", "ctime_old")
        self.sort_combo.addItem("時長 短→長", "dur_short")
        self.sort_combo.addItem("時長 長→短", "dur_long")
        self.sort_combo.setCurrentIndex(0)
        self.sort_combo.currentIndexChanged.connect(self.apply_filter)
        sort_layout.addWidget(self.sort_combo, 1)
        left_panel.addLayout(sort_layout)

        playlist_label = QLabel("📋 播放清單")
        playlist_label.setStyleSheet("font-weight: bold; color: #00F0FF;")
        left_panel.addWidget(playlist_label)

        self.list_widget = QListWidget()
        self.list_widget.itemClicked.connect(self.load_selected_track)
        self.list_widget.itemDoubleClicked.connect(lambda item: self.toggle_play())
        left_panel.addWidget(self.list_widget)

        self.stats_label = QLabel("總曲目: 0")
        self.stats_label.setStyleSheet("color: #888; font-size: 11px; padding: 2px;")
        left_panel.addWidget(self.stats_label)

        main_layout.addLayout(left_panel, 1)

        # ── 右面板 ──
        right_panel = QVBoxLayout()
        right_panel.setSpacing(2)

        self.canvas = SpectrumCanvas()
        right_panel.addWidget(self.canvas)

        now_playing_layout = QHBoxLayout()
        now_playing_label = QLabel("🎵 現在播放:")
        now_playing_label.setStyleSheet("color: #888;")
        now_playing_layout.addWidget(now_playing_label)

        self.lbl_now_playing = QLabel("— 尚未選取曲目 —")
        self.lbl_now_playing.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_now_playing.setStyleSheet(
            "color: #00F0FF; font-size: 16px; font-weight: bold; "
            "background: rgba(0, 240, 255, 20); border-radius: 8px; padding: 8px;"
        )
        now_playing_layout.addWidget(self.lbl_now_playing, 1)
        right_panel.addLayout(now_playing_layout)

        prog_layout = QHBoxLayout()
        self.lbl_time_now = QLabel("00:00")
        self.lbl_time_now.setStyleSheet("color: #DDD; font-family: monospace; font-size: 14px;")

        self.slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.slider.clicked_pos.connect(self.seek_music)

        self.lbl_time_total = QLabel("00:00")
        self.lbl_time_total.setStyleSheet("color: #DDD; font-family: monospace; font-size: 14px;")

        prog_layout.addWidget(self.lbl_time_now)
        prog_layout.addWidget(self.slider)
        prog_layout.addWidget(self.lbl_time_total)
        right_panel.addLayout(prog_layout)

        info_label = QLabel("📝 曲目資訊")
        info_label.setStyleSheet("font-weight: bold; color: #00F0FF;")
        right_panel.addWidget(info_label)

        info_container = QHBoxLayout()
        info_container.setSpacing(8)

        self.cover_label = QLabel("無封面")
        self.cover_label.setFixedSize(180, 180)
        self.cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover_label.setStyleSheet(
            "background: rgba(0, 0, 0, 140); "
            "border: 1px solid rgba(255, 255, 255, 30); "
            "border-radius: 12px; "
            "color: #888; font-size: 12px;"
        )
        info_container.addWidget(self.cover_label)

        self.info_display = QTextEdit()
        self.info_display.setReadOnly(True)
        self.info_display.setMinimumHeight(180)
        info_container.addWidget(self.info_display, 1)

        right_panel.addLayout(info_container)

        ctrl_layout = QHBoxLayout()

        self.btn_prev = QPushButton("⏮")
        self.btn_prev.setToolTip("上一首")
        self.btn_prev.clicked.connect(self.prev_track)

        self.btn_play = QPushButton("▶")
        self.btn_play.setToolTip("播放/暫停")
        self.btn_play.clicked.connect(self.toggle_play)

        self.btn_next = QPushButton("⏭")
        self.btn_next.setToolTip("下一首")
        self.btn_next.clicked.connect(self.next_track)

        self.btn_stop = QPushButton("⏹")
        self.btn_stop.setToolTip("停止")
        self.btn_stop.clicked.connect(self.stop_music)

        ctrl_layout.addWidget(self.btn_prev)
        ctrl_layout.addWidget(self.btn_play)
        ctrl_layout.addWidget(self.btn_next)
        ctrl_layout.addWidget(self.btn_stop)
        right_panel.addLayout(ctrl_layout)

        extra_layout = QHBoxLayout()

        volume_layout = QHBoxLayout()
        vol_icon = QLabel("🔊")
        vol_icon.setStyleSheet("color: #DDD;")
        volume_layout.addWidget(vol_icon)
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(80)
        self.volume_slider.setToolTip("音量控制")
        self.volume_slider.valueChanged.connect(self.change_volume)
        volume_layout.addWidget(self.volume_slider)
        extra_layout.addLayout(volume_layout)

        extra_layout.addStretch()

        self.btn_loop = QPushButton("🔁 不循環")
        self.btn_loop.setToolTip("切換循環模式")
        self.btn_loop.clicked.connect(self.cycle_loop_mode)
        extra_layout.addWidget(self.btn_loop)

        self.btn_shuffle = QPushButton("🔀 隨機")
        self.btn_shuffle.setCheckable(True)
        self.btn_shuffle.setToolTip("隨機播放")
        self.btn_shuffle.clicked.connect(self.toggle_shuffle)
        extra_layout.addWidget(self.btn_shuffle)

        self.btn_tinnitus = QPushButton("🎧 耳鳴模式")
        self.btn_tinnitus.setCheckable(True)
        self.btn_tinnitus.clicked.connect(self.set_tinnitus_enabled)
        self.btn_tinnitus.setToolTip(
            describe_tinnitus_profile(self.tinnitus_profile) if TINNITUS_AVAILABLE
            else tinnitus_install_message())
        extra_layout.addWidget(self.btn_tinnitus)

        self.btn_bg = QPushButton("🖼️ 背景")
        self.btn_bg.setToolTip("設定背景圖片")
        self.btn_bg.clicked.connect(self.select_background)
        extra_layout.addWidget(self.btn_bg)

        right_panel.addLayout(extra_layout)

        main_layout.addLayout(right_panel, 2)

        self.change_volume(self.volume_slider.value())

    # ── 選單功能 ──

    def show_equalizer(self):
        if not hasattr(self, 'equalizer'):
            self.equalizer = EqualizerWidget(self)
        self.equalizer.show()
        self.equalizer.raise_()

    def show_about(self):
        about_text = f"""
        <h2>{APP_NAME} v{APP_VERSION}</h2>
        <p>現代玻璃風格音樂播放器</p>
        <p>功能特色：</p>
        <ul>
            <li>支援 MP3 / FLAC / WAV / OGG / M4A / MP4</li>
            <li>MP4/M4A 透過 ffmpeg 轉碼播放（無 CMD 閃窗）</li>
            <li>封面圖：內嵌圖 / 同名圖 / 影片抽幀</li>
            <li>封面同步作為歌詞框底圖</li>
            <li>子目錄一層掃描</li>
            <li>六種排序：名稱、生成時間、時長</li>
            <li>耳鳴模式：左右耳獨立的缺口 / 頻段補強、批次匯出</li>
        </ul>
        <p>© 2024 AI Music Pro</p>
        """
        QMessageBox.about(self, "關於", about_text)

    def set_loop_mode(self, mode):
        self.loop_mode = mode
        self._update_loop_btn_text()
        self.loop_none_action.setChecked(mode == 0)
        self.loop_all_action.setChecked(mode == 1)
        self.loop_one_action.setChecked(mode == 2)
        self.save_config()

    def toggle_shuffle_menu(self, checked):
        self.shuffle_mode = checked
        self.btn_shuffle.setChecked(checked)
        self.save_config()

    def select_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "選擇音樂檔案", "",
            "音樂檔案 (*.mp3 *.wav *.ogg *.flac *.m4a *.mp4);;所有檔案 (*.*)"
        )
        if files:
            for file_path in files:
                self._add_track(file_path)
            self._refresh_genre_combo()
            self.apply_filter()
            self.save_config()

    def _add_track(self, file_path):
        txt_path = os.path.splitext(file_path)[0] + '.txt'
        txt_path = txt_path if os.path.exists(txt_path) else None
        self.all_tracks.append({
            'name': os.path.basename(file_path),
            'mp3': file_path,
            'txt': txt_path,
            'genre': self._extract_metadata(txt_path, "Genre"),
            'bpm': self._extract_metadata(txt_path, "BPM"),
            'artist': self._extract_metadata(txt_path, "Artist"),
            'album': self._extract_metadata(txt_path, "Album")
        })

    def save_playlist(self):
        if not self.all_tracks:
            QMessageBox.warning(self, "警告", "沒有曲目可以儲存")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "儲存播放清單", "", "播放清單 (*.json)"
        )
        if path:
            playlist_data = {'tracks': self.all_tracks, 'version': APP_VERSION}
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(playlist_data, f, indent=2, ensure_ascii=False)
                QMessageBox.information(self, "成功", "播放清單已儲存")
            except Exception as e:
                QMessageBox.critical(self, "錯誤", f"儲存失敗：{str(e)}")

    def load_playlist(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "載入播放清單", "", "播放清單 (*.json)"
        )
        if path:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    playlist_data = json.load(f)
                self.all_tracks = playlist_data.get('tracks', [])
                self._refresh_genre_combo()
                self.apply_filter()

                missing_files = []
                for track in self.all_tracks[:]:
                    if not os.path.exists(track['mp3']):
                        missing_files.append(track['name'])
                        self.all_tracks.remove(track)

                if missing_files:
                    QMessageBox.warning(self, "警告",
                                       f"以下檔案不存在，已從清單移除：\n" +
                                       "\n".join(missing_files[:5]))
                self.save_config()
            except Exception as e:
                QMessageBox.critical(self, "錯誤", f"載入失敗：{str(e)}")

    # ── 背景處理 ──

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.current_bg_path:
            self._apply_background_logic()
        if self._current_info_bg_pixmap is not None:
            self._apply_info_background(self._current_info_bg_pixmap)

    def select_background(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "選擇背景圖片", "",
            "圖片 (*.png *.jpg *.jpeg *.webp *.bmp)"
        )
        if path:
            self.current_bg_path = path
            self._apply_background_logic()
            self.save_config()

    def _apply_background_logic(self):
        if not self.current_bg_path or not os.path.exists(self.current_bg_path):
            return
        pixmap = QPixmap(self.current_bg_path)
        if pixmap.isNull():
            return
        scaled = pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation
        )
        x = (scaled.width() - self.width()) // 2
        y = (scaled.height() - self.height()) // 2
        final_pixmap = scaled.copy(x, y, self.width(), self.height())

        overlay = QPixmap(final_pixmap.size())
        overlay.fill(QColor(0, 0, 0, 100))

        painter = QPainter(final_pixmap)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.drawPixmap(0, 0, overlay)
        painter.end()

        palette = self.palette()
        palette.setBrush(QPalette.ColorRole.Window, QBrush(final_pixmap))
        self.setPalette(palette)
        self.setAutoFillBackground(True)

    # ── 設定檔 ──

    def save_config(self):
        config = {
            "music_dir": os.path.dirname(self.all_tracks[0]['mp3']) if self.all_tracks else "",
            "bg_path": self.current_bg_path,
            "volume": self.volume_slider.value(),
            "loop_mode": self.loop_mode,
            "shuffle": self.shuffle_mode,
            "scan_subdir": self.chk_subdir.isChecked(),
            "sort_mode": self.sort_combo.currentData() if hasattr(self, 'sort_combo') else "name_asc",
            "window_size": (self.width(), self.height()),
            "window_pos": (self.x(), self.y()),
            "tinnitus_enabled": self.tinnitus_enabled,
            "tinnitus_profile": self.tinnitus_profile,
        }
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"儲存設定失敗：{e}")

    def load_config(self):
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)

            # 先還原排序，再匯入資料夾（這樣匯入時就套用正確排序）
            if hasattr(self, 'sort_combo') and cfg.get("sort_mode"):
                idx = self.sort_combo.findData(cfg["sort_mode"])
                if idx >= 0:
                    self.sort_combo.blockSignals(True)
                    self.sort_combo.setCurrentIndex(idx)
                    self.sort_combo.blockSignals(False)

            self.chk_subdir.setChecked(cfg.get("scan_subdir", False))

            if cfg.get("music_dir") and os.path.exists(cfg["music_dir"]):
                self.import_folder(cfg["music_dir"])

            if cfg.get("bg_path") and os.path.exists(cfg["bg_path"]):
                self.current_bg_path = cfg["bg_path"]
                self._apply_background_logic()

            self.volume_slider.setValue(cfg.get("volume", 80))
            self.loop_mode = cfg.get("loop_mode", 0)
            self._update_loop_btn_text()

            self.shuffle_mode = cfg.get("shuffle", False)
            self.btn_shuffle.setChecked(self.shuffle_mode)

            if "window_size" in cfg:
                self.resize(*cfg["window_size"])
            if "window_pos" in cfg:
                self.move(*cfg["window_pos"])

            if TINNITUS_AVAILABLE and cfg.get("tinnitus_profile"):
                try:
                    self.tinnitus_profile = tdsp.validate_profile(cfg["tinnitus_profile"])
                except Exception as e:  # noqa: BLE001
                    print(f"耳鳴設定檔無效，改用預設值：{e}")
            self._apply_tinnitus_ui(bool(cfg.get("tinnitus_enabled")) and TINNITUS_AVAILABLE)
        except Exception as e:
            print(f"載入設定失敗：{e}")

    # ── 音樂掃描與 Metadata ──

    def select_directory(self):
        path = QFileDialog.getExistingDirectory(self, "選取音樂資料夾")
        if path:
            self.import_folder(path)
            self.save_config()

    def import_folder(self, path):
        self.all_tracks = []
        scan_subdir = self.chk_subdir.isChecked()

        def scan_dir(dir_path, depth=0):
            try:
                for f in sorted(os.listdir(dir_path)):
                    full_path = os.path.join(dir_path, f)
                    if os.path.isdir(full_path):
                        if scan_subdir and depth < 1:
                            scan_dir(full_path, depth + 1)
                    else:
                        file_lower = f.lower()
                        if any(file_lower.endswith(ext) for ext in MUSIC_EXTENSIONS):
                            self._add_track(full_path)
            except Exception as e:
                print(f"掃描 {dir_path} 失敗：{e}")

        scan_dir(path)
        self._refresh_genre_combo()
        self.apply_filter()

    def _extract_metadata(self, txt_path, key):
        if not txt_path:
            return ""
        try:
            with open(txt_path, encoding='utf-8-sig') as f:
                content = f.read()
            pattern = rf"{key}:\s*(.*)"
            m = re.search(pattern, content, re.IGNORECASE)
            return m.group(1).strip() if m else ""
        except Exception as e:
            print(f"讀取 metadata 失敗 ({txt_path}): {e}")
            return ""

    # ── 排序與過濾 ──

    def _get_cached_duration(self, path):
        """取得（並快取）音訊長度，供時長排序使用"""
        if path in self._duration_cache:
            return self._duration_cache[path]
        dur = self._get_audio_length(path)
        self._duration_cache[path] = dur
        return dur

    def _get_file_ctime(self, path):
        """跨平台取得檔案生成時間（秒）"""
        try:
            if sys.platform == "win32":
                return os.path.getctime(path)   # Windows：建立時間
            return os.path.getmtime(path)       # macOS/Linux：修改時間
        except Exception:
            return 0

    def apply_filter(self):
        # 1) 依曲風篩選
        selected = self.genre_combo.currentText()
        if selected == "🎵 全部曲風":
            tracks = list(self.all_tracks)
        else:
            tracks = [t for t in self.all_tracks
                      if t['genre'].strip() == selected.strip()]

        # 2) 依排序模式排序
        mode = "name_asc"
        if hasattr(self, 'sort_combo'):
            data = self.sort_combo.currentData()
            if data:
                mode = data

        if mode == "name_asc":
            tracks.sort(key=lambda t: t['name'].lower())
        elif mode == "name_desc":
            tracks.sort(key=lambda t: t['name'].lower(), reverse=True)
        elif mode == "ctime_new":
            tracks.sort(key=lambda t: self._get_file_ctime(t['mp3']), reverse=True)
        elif mode == "ctime_old":
            tracks.sort(key=lambda t: self._get_file_ctime(t['mp3']))
        elif mode == "dur_short":
            tracks.sort(key=lambda t: self._get_cached_duration(t['mp3']))
        elif mode == "dur_long":
            tracks.sort(key=lambda t: self._get_cached_duration(t['mp3']), reverse=True)

        self.filtered_tracks = tracks

        # 3) 更新清單
        self.list_widget.clear()
        for t in self.filtered_tracks:
            display_name = t['name']
            if t['genre']:
                display_name += f" [{t['genre']}]"
            self.list_widget.addItem(display_name)

        self.stats_label.setText(f"總曲目: {len(self.filtered_tracks)}")

    def _refresh_genre_combo(self):
        current = self.genre_combo.currentText()
        self.genre_combo.blockSignals(True)
        self.genre_combo.clear()
        self.genre_combo.addItem("🎵 全部曲風")
        genres = sorted(set(t['genre'].strip() for t in self.all_tracks if t['genre'].strip()))
        for g in genres:
            self.genre_combo.addItem(g)
        idx = self.genre_combo.findText(current)
        self.genre_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.genre_combo.blockSignals(False)

    # ── 載入曲目 ──

    def load_selected_track(self, item):
        self._load_track_by_index(self.list_widget.row(item))

    def _load_track_by_index(self, idx: int):
        if 0 <= idx < len(self.filtered_tracks):
            track = self.filtered_tracks[idx]
            self.list_widget.setCurrentRow(idx)
            self.current_audio_path = track['mp3']
            self.current_playlist_index = idx

            self.play_history.append(idx)
            if len(self.play_history) > 50:
                self.play_history.pop(0)

            self._current_track = track
            self._tinnitus_report = ""
            self.lbl_now_playing.setText(f"🎵 {track['name']}")

            self.total_length = self._get_audio_length(track['mp3'])

            self.lbl_time_total.setText(format_time(self.total_length))
            self.slider.setRange(0, max(1, int(self.total_length)))
            self.slider.setValue(0)
            self.seek_position = 0
            self._show_track_info(track)
            self._update_cover(track['mp3'])

            try:
                self._source_playback_path = self._prepare_playback_path(track['mp3'])
            except Exception as e:
                QMessageBox.critical(self, "轉檔失敗", str(e))
                self._source_playback_path = ""
                self._playback_path = ""
                return

            self._route_playback(0.0, autoplay=True)

    # ── 音訊長度 ──

    def _get_audio_length(self, audio_path):
        ext = os.path.splitext(audio_path)[1].lower()
        try:
            if MUTAGEN_AVAILABLE:
                if ext == '.mp3':
                    return MP3(audio_path).info.length
                elif ext in ('.mp4', '.m4a'):
                    return MP4(audio_path).info.length
                elif ext == '.flac':
                    return FLAC(audio_path).info.length
            sound = pygame.mixer.Sound(audio_path)
            return sound.get_length()
        except Exception as e:
            print(f"無法取得音樂長度 ({audio_path})：{e}")
            return 0

    # ── ffmpeg / 播放路徑 ──

    def _get_ffmpeg(self):
        if self._ffmpeg_path is None:
            self._ffmpeg_path = find_ffmpeg() or ""
        return self._ffmpeg_path or None

    def _prepare_playback_path(self, audio_path):
        ext = os.path.splitext(audio_path)[1].lower()
        if ext not in NEEDS_CONVERT:
            return audio_path

        try:
            pygame.mixer.music.load(audio_path)
            pygame.mixer.music.unload()
            return audio_path
        except pygame.error:
            pass

        ffmpeg = self._get_ffmpeg()
        if not ffmpeg:
            raise RuntimeError(
                "找不到 ffmpeg，無法播放 MP4/M4A。\n\n"
                "請安裝 ffmpeg：\n"
                "  1) winget install Gyan.FFmpeg\n"
                "  2) 到 https://www.gyan.dev/ffmpeg/builds/ 下載後把 bin 加入 PATH\n"
                "  3) pip install imageio-ffmpeg"
            )

        os.makedirs(CACHE_DIR, exist_ok=True)
        key = hashlib.md5(os.path.abspath(audio_path).encode("utf-8")).hexdigest()
        temp_wav = os.path.join(CACHE_DIR, key + ".wav")

        if not os.path.exists(temp_wav):
            try:
                run_hidden(
                    [ffmpeg, "-y", "-i", audio_path, "-vn",
                     "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
                     temp_wav],
                    check=True
                )
            except subprocess.CalledProcessError as e:
                err = e.stderr.decode("utf-8", errors="ignore") if e.stderr else ""
                raise RuntimeError(f"ffmpeg 轉檔失敗：\n{err[-400:]}")

        return temp_wav

    # ── 封面 ──

    def _get_embedded_cover_bytes(self, audio_path):
        if not MUTAGEN_AVAILABLE:
            return None
        ext = os.path.splitext(audio_path)[1].lower()
        try:
            if ext == '.mp3':
                tags = ID3(audio_path)
                for tag in tags.values():
                    if tag.FrameID == 'APIC':
                        return tag.data
            elif ext == '.flac':
                flac = FLAC(audio_path)
                if flac.pictures:
                    return flac.pictures[0].data
            elif ext in ('.mp4', '.m4a'):
                mp4 = MP4(audio_path)
                if mp4.tags and 'covr' in mp4.tags:
                    return bytes(mp4.tags['covr'][0])
        except Exception as e:
            print(f"讀取內嵌封面失敗 ({audio_path})：{e}")
        return None

    def _extract_video_frame(self, video_path):
        """MP4 用：用 ffmpeg 從影片中抽一幀作為封面，並快取到磁碟"""
        ffmpeg = self._get_ffmpeg()
        if not ffmpeg:
            return None

        os.makedirs(CACHE_DIR, exist_ok=True)
        key = hashlib.md5(("vframe:" + os.path.abspath(video_path)).encode("utf-8")).hexdigest()
        out_path = os.path.join(CACHE_DIR, key + ".jpg")

        if not os.path.exists(out_path):
            ok = False
            for ss in ("1", "0.5", "0"):
                try:
                    result = run_hidden(
                        [ffmpeg, "-y", "-ss", ss, "-i", video_path,
                         "-frames:v", "1", "-vf", "scale=600:-1",
                         "-q:v", "3", out_path],
                        timeout=25
                    )
                    if (result.returncode == 0 and os.path.exists(out_path)
                            and os.path.getsize(out_path) > 0):
                        ok = True
                        break
                except Exception as e:
                    print(f"抽幀失敗 ss={ss}: {e}")
            if not ok:
                return None

        if os.path.exists(out_path):
            pm = QPixmap(out_path)
            if not pm.isNull():
                return pm
        return None

    def _get_cover_pixmap(self, audio_path):
        if audio_path in self._cover_cache:
            return self._cover_cache[audio_path]

        ext = os.path.splitext(audio_path)[1].lower()
        base, _ = os.path.splitext(audio_path)
        folder = os.path.dirname(audio_path)

        def try_load(path):
            pm = QPixmap(path)
            return pm if not pm.isNull() else None

        result = None

        if ext in ('.mp4', '.m4a'):
            # MP4/M4A：內嵌 → 同名 → 通用 → 抽幀
            data = self._get_embedded_cover_bytes(audio_path)
            if data:
                pm = QPixmap()
                if pm.loadFromData(data):
                    result = pm
            if result is None:
                for ie in IMAGE_EXTENSIONS:
                    pm = try_load(base + ie)
                    if pm:
                        result = pm
                        break
            if result is None:
                for name in ('cover', 'folder', 'album', 'front'):
                    for ie in IMAGE_EXTENSIONS:
                        pm = try_load(os.path.join(folder, name + ie))
                        if pm:
                            result = pm
                            break
                    if result:
                        break
            if result is None and ext == '.mp4':
                result = self._extract_video_frame(audio_path)
        else:
            # MP3/FLAC 等：同名 → 通用 → 內嵌
            for ie in IMAGE_EXTENSIONS:
                pm = try_load(base + ie)
                if pm:
                    result = pm
                    break
            if result is None:
                for name in ('cover', 'folder', 'album', 'front'):
                    for ie in IMAGE_EXTENSIONS:
                        pm = try_load(os.path.join(folder, name + ie))
                        if pm:
                            result = pm
                            break
                    if result:
                        break
            if result is None:
                data = self._get_embedded_cover_bytes(audio_path)
                if data:
                    pm = QPixmap()
                    if pm.loadFromData(data):
                        result = pm

        self._cover_cache[audio_path] = result
        return result

    def _update_cover(self, audio_path):
        pixmap = self._get_cover_pixmap(audio_path)
        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(
                self.cover_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
            self.cover_label.setPixmap(scaled)
            self.cover_label.setText("")
            self._apply_info_background(pixmap)
        else:
            self.cover_label.clear()
            self.cover_label.setText("無封面")
            self._apply_info_background(None)

    # ── 封面作為歌詞框底圖 ──

    def _apply_info_background(self, pixmap):
        """將封面（或 None）套用到 info_display 作為背景"""
        self._current_info_bg_pixmap = pixmap

        if pixmap is None or pixmap.isNull():
            self.info_display.setStyleSheet("""
                QTextEdit {
                    background-color: rgba(25, 25, 25, 200);
                    border: 1px solid rgba(255, 255, 255, 30);
                    border-radius: 12px;
                    color: #FEE;
                    padding: 8px;
                    font-size: 12px;
                }
            """)
            return

        w = max(240, self.info_display.width())
        h = max(180, self.info_display.height())

        scaled = pixmap.scaled(
            w, h,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation
        )
        x = (scaled.width() - w) // 2
        y = (scaled.height() - h) // 2
        cropped = scaled.copy(x, y, w, h)

        # 暗化：疊一層半透明黑色，讓文字清楚
        darkened = QPixmap(cropped.size())
        darkened.fill(QColor(0, 0, 0, 0))
        p = QPainter(darkened)
        p.drawPixmap(0, 0, cropped)
        p.fillRect(darkened.rect(), QColor(0, 0, 0, 150))
        p.end()

        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp_path = os.path.join(CACHE_DIR, "_info_bg.png")
        darkened.save(tmp_path, "PNG")
        url = tmp_path.replace("\\", "/")

        self.info_display.setStyleSheet(f"""
            QTextEdit {{
                background-color: rgba(15, 15, 15, 180);
                background-image: url("{url}");
                background-position: center center;
                background-repeat: no-repeat;
                background-attachment: scroll;
                border: 1px solid rgba(255, 255, 255, 40);
                border-radius: 12px;
                color: #F8F8F8;
                padding: 8px;
                font-size: 12px;
            }}
        """)

    def _show_track_info(self, track):
        info = f"🎵 檔名：{track['name']}\n"
        info += "═" * 40 + "\n"
        if track.get('artist'):
            info += f"👤 演出者：{track['artist']}\n"
        if track.get('album'):
            info += f"💿 專輯：{track['album']}\n"
        info += f"🎸 風格：{track['genre'] or 'N/A'}\n"
        info += f"⏱ BPM：{track['bpm'] or 'N/A'}\n"

        if self.tinnitus_enabled and track is self._current_track:
            if self._tinnitus_busy:
                info += "\n🎧 耳鳴模式：處理中…\n"
            elif self._tinnitus_report:
                info += "\n🎧 耳鳴模式\n" + self._tinnitus_report + "\n"

        if track['txt']:
            try:
                with open(track['txt'], encoding='utf-8-sig') as f:
                    content = f.read()
                if "[Prompt]" in content:
                    if "[Lyrics]" in content:
                        prompt_text = content.split("[Prompt]")[1].split("[Lyrics]")[0].strip()
                    else:
                        prompt_text = content.split("[Prompt]")[1].strip()
                    if prompt_text:
                        info += f"\n💡 Prompt：\n{prompt_text[:500]}\n"
                        if len(prompt_text) > 500:
                            info += "..."
                if "[Lyrics]" in content:
                    lyrics = content.split("[Lyrics]")[1].strip()
                    if lyrics:
                        info += "\n📝 歌詞：\n" + lyrics[:500]
                        if len(lyrics) > 500:
                            info += "..."
            except Exception as e:
                print(f"讀取文字檔失敗 ({track['txt']}): {e}")

        self.info_display.setText(info)

    # ── 播放控制 ──

    def _play_current(self):
        if not self._playback_path:
            return
        try:
            pygame.mixer.music.load(self._playback_path)
            pygame.mixer.music.play()
            self.seek_position = 0
            self._paused = False
            self.is_playing = True
            self.btn_play.setText("⏸")
        except Exception as e:
            QMessageBox.critical(self, "播放錯誤", f"無法播放檔案：{str(e)}")

    def toggle_play(self):
        if not self.current_audio_path:
            return
        if self._tinnitus_busy:
            # 處理中：只改變「處理完要不要自動播放」
            if self._tinnitus_pending:
                pos, autoplay = self._tinnitus_pending
                self._tinnitus_pending = (pos, not autoplay)
                self.btn_play.setText("⏸" if not autoplay else "▶")
            return
        if not self.is_playing:
            # pygame 2.0.1 起暫停時 get_busy() 會回傳 False，所以用自己的旗標判斷
            if self._paused:
                pygame.mixer.music.unpause()
                self._paused = False
            else:
                self._play_current()
            self.is_playing = True
            self.btn_play.setText("⏸")
        else:
            pygame.mixer.music.pause()
            self._paused = True
            self.is_playing = False
            self.btn_play.setText("▶")

    def stop_music(self):
        pygame.mixer.music.stop()
        self.is_playing = False
        self._paused = False
        if self._tinnitus_busy and self._tinnitus_pending:
            self._tinnitus_pending = (0.0, False)
        self.btn_play.setText("▶")
        self.seek_position = 0
        self.slider.setValue(0)
        self.lbl_time_now.setText("00:00")

    def seek_music(self, pos):
        if self._tinnitus_busy and self._tinnitus_pending:
            self._tinnitus_pending = (float(pos), self._tinnitus_pending[1])
            return
        if not self._playback_path:
            return
        self.seek_position = pos
        try:
            pygame.mixer.music.load(self._playback_path)
            pygame.mixer.music.play(start=float(pos))
            self._paused = False
            if not self.is_playing:
                pygame.mixer.music.pause()
                self._paused = True
                self.btn_play.setText("▶")
            else:
                self.btn_play.setText("⏸")
        except Exception as e:
            print(f"seek 失敗：{e}")

    def update_progress(self):
        if self.is_playing and pygame.mixer.music.get_busy():
            raw = pygame.mixer.music.get_pos()
            curr = self.seek_position + (raw / 1000.0) if raw >= 0 else self.seek_position
            if curr <= self.total_length:
                self.slider.blockSignals(True)
                self.slider.setValue(int(curr))
                self.slider.blockSignals(False)
                self.lbl_time_now.setText(format_time(curr))

    def check_track_end(self):
        if self.is_playing and not pygame.mixer.music.get_busy():
            if self.loop_mode == self.LOOP_ONE:
                self.seek_position = 0
                self._play_current()
            else:
                self.next_track()

    def next_track(self):
        if not self.filtered_tracks:
            return
        curr = self.current_playlist_index
        if self.shuffle_mode:
            available = list(range(len(self.filtered_tracks)))
            if len(available) > 1 and curr in available:
                available.remove(curr)
            nxt = random.choice(available) if available else 0
        else:
            nxt = curr + 1
            if nxt >= len(self.filtered_tracks):
                if self.loop_mode == self.LOOP_ALL:
                    nxt = 0
                else:
                    self.stop_music()
                    return
        self._load_track_by_index(nxt)

    def prev_track(self):
        if not self.filtered_tracks:
            return
        curr = self.current_playlist_index
        nxt = curr - 1
        if nxt < 0:
            if self.loop_mode == self.LOOP_ALL:
                nxt = len(self.filtered_tracks) - 1
            else:
                nxt = 0
        self._load_track_by_index(nxt)

    def change_volume(self, val):
        pygame.mixer.music.set_volume(val / 100.0)

    def cycle_loop_mode(self):
        self.loop_mode = (self.loop_mode + 1) % 3
        self._update_loop_btn_text()
        self.loop_none_action.setChecked(self.loop_mode == 0)
        self.loop_all_action.setChecked(self.loop_mode == 1)
        self.loop_one_action.setChecked(self.loop_mode == 2)
        self.save_config()

    def _update_loop_btn_text(self):
        texts = {
            self.LOOP_NONE: "🔁 不循環",
            self.LOOP_ALL: "🔁 清單循環",
            self.LOOP_ONE: "🔂 單曲循環"
        }
        self.btn_loop.setText(texts[self.loop_mode])

    def toggle_shuffle(self):
        self.shuffle_mode = self.btn_shuffle.isChecked()
        self.save_config()

    # ── 耳鳴模式 ──

    def _play_from(self, pos, autoplay):
        """從指定秒數開始播放目前的 _playback_path"""
        if not self._playback_path:
            return
        try:
            pygame.mixer.music.load(self._playback_path)
            if pos and pos > 0.5:
                pygame.mixer.music.play(start=float(pos))
            else:
                pygame.mixer.music.play()
                pos = 0.0
            self.seek_position = pos
            self._paused = False
            if autoplay:
                self.is_playing = True
                self.btn_play.setText("⏸")
            else:
                pygame.mixer.music.pause()
                self._paused = True
                self.is_playing = False
                self.btn_play.setText("▶")
            self.slider.blockSignals(True)
            self.slider.setValue(int(pos))
            self.slider.blockSignals(False)
            self.lbl_time_now.setText(format_time(pos))
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "播放錯誤", f"無法播放檔案：{str(e)}")

    def _current_position(self):
        if self._tinnitus_busy and self._tinnitus_pending:
            return self._tinnitus_pending[0]
        if self.is_playing:
            raw = pygame.mixer.music.get_pos()
            if raw >= 0:
                return self.seek_position + raw / 1000.0
        return float(self.slider.value())

    def _route_playback(self, pos=0.0, autoplay=True):
        """依耳鳴模式決定播原音或處理後的版本"""
        src = self._source_playback_path
        if not src:
            return
        if self.tinnitus_enabled and TINNITUS_AVAILABLE:
            self._start_tinnitus_job(src, pos, autoplay)
        else:
            self._tinnitus_job += 1          # 讓還在處理中的結果作廢
            self._set_tinnitus_busy(False)
            self._playback_path = src
            self._play_from(pos, autoplay)

    def _start_tinnitus_job(self, src, pos, autoplay):
        self._tinnitus_job += 1
        job = self._tinnitus_job
        try:
            pygame.mixer.music.stop()
        except pygame.error:
            pass
        self.is_playing = False
        self._paused = False
        self._playback_path = ""
        self._tinnitus_pending = (float(pos), bool(autoplay))
        self.btn_play.setText("⏸" if autoplay else "▶")
        self._set_tinnitus_busy(True)
        tdsp.FFMPEG_PATH = self._get_ffmpeg()
        w = TinnitusWorker(job, src, copy.deepcopy(self.tinnitus_profile), self)
        w.done.connect(self._on_tinnitus_done)
        w.failed.connect(self._on_tinnitus_failed)
        w.finished.connect(lambda w=w: self._workers.discard(w))
        w.finished.connect(w.deleteLater)
        self._workers.add(w)
        w.start()

    def _set_tinnitus_busy(self, busy):
        self._tinnitus_busy = busy
        if self._current_track:
            name = self._current_track['name']
            self.lbl_now_playing.setText(f"⏳ 耳鳴處理中… {name}" if busy else f"🎵 {name}")
            self._show_track_info(self._current_track)

    def _on_tinnitus_done(self, job, path, summary):
        if job != self._tinnitus_job:
            return
        pos, autoplay = self._tinnitus_pending or (0.0, True)
        self._tinnitus_pending = None
        self._tinnitus_report = summary
        self._playback_path = path
        self._set_tinnitus_busy(False)
        self._play_from(pos, autoplay)

    def _on_tinnitus_failed(self, job, msg):
        if job != self._tinnitus_job:
            return
        pos, autoplay = self._tinnitus_pending or (0.0, True)
        self._tinnitus_pending = None
        self._tinnitus_report = ""
        self._set_tinnitus_busy(False)
        QMessageBox.warning(self, "耳鳴處理失敗", f"這首歌改用原音播放。\n\n{msg}")
        self._playback_path = self._source_playback_path
        self._play_from(pos, autoplay)

    def _apply_tinnitus_ui(self, on):
        """只更新狀態與按鈕外觀，不重新處理、不存檔"""
        self.tinnitus_enabled = bool(on)
        for w in (self.btn_tinnitus, self.tinnitus_action):
            w.blockSignals(True)
            w.setChecked(self.tinnitus_enabled)
            w.blockSignals(False)
        self.btn_tinnitus.setText("🎧 耳鳴：開" if self.tinnitus_enabled else "🎧 耳鳴模式")
        if TINNITUS_AVAILABLE and self.tinnitus_profile:
            tip = describe_tinnitus_profile(self.tinnitus_profile)
            self.btn_tinnitus.setToolTip(tip)
            self.tinnitus_action.setToolTip(tip)

    def set_tinnitus_enabled(self, on):
        if on and not TINNITUS_AVAILABLE:
            QMessageBox.warning(self, "無法開啟耳鳴模式", tinnitus_install_message())
            on = False
        was_on = self.tinnitus_enabled
        self._apply_tinnitus_ui(on)
        self.save_config()
        if bool(on) == was_on:
            return
        if not on:
            self._tinnitus_report = ""
        self._reprocess_current()

    def _reprocess_current(self):
        """設定改變後，目前這首歌從原本的位置接著播"""
        if not self._source_playback_path:
            if self._current_track:
                self._show_track_info(self._current_track)
            return
        pos = self._current_position()
        if self._tinnitus_busy and self._tinnitus_pending:
            autoplay = self._tinnitus_pending[1]
        else:
            autoplay = self.is_playing
        self._route_playback(pos, autoplay=autoplay)
        if self._current_track:
            self._show_track_info(self._current_track)

    def _set_tinnitus_profile(self, profile):
        changed = profile != self.tinnitus_profile
        self.tinnitus_profile = profile
        self._apply_tinnitus_ui(self.tinnitus_enabled)
        self.save_config()
        if changed and self.tinnitus_enabled:
            self._reprocess_current()

    def open_tinnitus_settings(self):
        if not TINNITUS_AVAILABLE:
            QMessageBox.warning(self, "耳鳴模式無法使用", tinnitus_install_message())
            return
        dlg = TinnitusDialog(self.tinnitus_profile, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_profile:
            self._set_tinnitus_profile(dlg.result_profile)

    def import_tinnitus_profile(self):
        if not TINNITUS_AVAILABLE:
            QMessageBox.warning(self, "耳鳴模式無法使用", tinnitus_install_message())
            return
        path, _ = QFileDialog.getOpenFileName(self, "匯入耳鳴設定檔", "", "耳鳴設定檔 (*.json)")
        if not path:
            return
        try:
            profile = tdsp.load_profile(path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "匯入失敗", f"這個檔案不是可用的耳鳴設定檔：\n{e}")
            return
        self._set_tinnitus_profile(profile)
        QMessageBox.information(self, "已匯入",
                                f"{profile['name']}\n{describe_tinnitus_profile(profile)}")

    def export_tinnitus_profile(self):
        if not TINNITUS_AVAILABLE:
            QMessageBox.warning(self, "耳鳴模式無法使用", tinnitus_install_message())
            return
        path, _ = QFileDialog.getSaveFileName(self, "匯出耳鳴設定檔", "tinnitus_profile.json",
                                              "耳鳴設定檔 (*.json)")
        if path:
            try:
                tdsp.save_profile(self.tinnitus_profile, path)
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, "匯出失敗", str(e))

    def clear_tinnitus_cache(self):
        if not os.path.isdir(TINNITUS_CACHE_DIR):
            QMessageBox.information(self, "清除耳鳴快取", "目前沒有快取檔案。")
            return
        removed, kept, size = 0, 0, 0
        for f in os.listdir(TINNITUS_CACHE_DIR):
            fp = os.path.join(TINNITUS_CACHE_DIR, f)
            if os.path.normcase(fp) == os.path.normcase(self._playback_path or ""):
                kept += 1
                continue
            try:
                size += os.path.getsize(fp)
                os.remove(fp)
                removed += 1
            except OSError:
                kept += 1
        msg = f"已刪除 {removed} 個檔案，釋放約 {size / 1048576:.0f} MB。"
        if kept:
            msg += f"\n有 {kept} 個檔案正在使用中，先保留。"
        QMessageBox.information(self, "清除耳鳴快取", msg)

    def batch_export_tinnitus(self):
        if not TINNITUS_AVAILABLE:
            QMessageBox.warning(self, "耳鳴模式無法使用", tinnitus_install_message())
            return
        if not self.filtered_tracks:
            QMessageBox.information(self, "批次匯出", "播放清單是空的，請先開啟音樂目錄。")
            return
        if self._batch_worker is not None:
            QMessageBox.information(self, "批次匯出", "上一批還在處理中。")
            return
        fmt, ok = QInputDialog.getItem(
            self, "批次匯出耳鳴版本",
            f"將目前清單的 {len(self.filtered_tracks)} 首歌，用這組設定輸出：\n"
            f"{describe_tinnitus_profile(self.tinnitus_profile)}\n\n輸出格式：",
            ["mp3", "flac", "wav"], 0, False)
        if not ok:
            return
        ffmpeg = self._get_ffmpeg()
        if fmt == "mp3" and not ffmpeg:
            QMessageBox.warning(self, "需要 ffmpeg",
                                "輸出 MP3 需要 ffmpeg。請安裝 ffmpeg，或改選 FLAC / WAV。")
            return
        out_dir = QFileDialog.getExistingDirectory(self, "選擇輸出資料夾")
        if not out_dir:
            return
        tdsp.FFMPEG_PATH = ffmpeg
        paths = [t['mp3'] for t in self.filtered_tracks]
        prog = QProgressDialog("準備中…", "取消", 0, len(paths), self)
        prog.setWindowTitle("批次匯出耳鳴版本")
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)
        prog.setValue(0)
        w = TinnitusBatchWorker(paths, copy.deepcopy(self.tinnitus_profile), out_dir, fmt, self)

        def on_progress(i, n, name):
            prog.setValue(i)
            if name:
                prog.setLabelText(f"處理中 {i + 1}/{n}：{name}")

        w.progress.connect(on_progress)
        prog.canceled.connect(w.cancel)
        w.finished_all.connect(
            lambda ok_n, n, errs, weak: self._on_batch_done(prog, out_dir, ok_n, n, errs, weak))
        w.finished.connect(w.deleteLater)
        self._batch_worker = w
        w.start()

    def _on_batch_done(self, prog, out_dir, ok_n, n, errors, weak):
        prog.close()
        self._batch_worker = None
        msg = f"完成 {ok_n}/{n} 首。\n輸出位置：{out_dir}"
        if ok_n + len(errors) < n:
            msg += "\n（已取消，剩下的沒有處理）"
        if weak:
            msg += (f"\n\n以下 {len(weak)} 首在處理頻段內幾乎沒有聲音，效果有限：\n"
                    + "\n".join(weak[:8]) + ("\n…" if len(weak) > 8 else ""))
        if errors:
            msg += f"\n\n失敗 {len(errors)} 首：\n" + "\n".join(errors[:5])
        QMessageBox.information(self, "批次匯出完成", msg)

    # ── 拖放支援 ──

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()

            if path.lower().endswith(IMAGE_EXTENSIONS):
                self.current_bg_path = path
                self._apply_background_logic()
                self.save_config()

            elif path.lower().endswith(MUSIC_EXTENSIONS):
                self._add_track(path)
                self._refresh_genre_combo()
                self.apply_filter()
                self.save_config()

            elif os.path.isdir(path):
                self.import_folder(path)
                self.save_config()

    def closeEvent(self, event):
        self.save_config()
        if self._batch_worker is not None:
            self._batch_worker.cancel()
            self._batch_worker.wait(5000)
        for w in list(self._workers):
            w.wait(5000)
        self.viz_timer.stop()
        self.progress_timer.stop()
        self.end_check_timer.stop()
        pygame.mixer.music.stop()
        pygame.mixer.quit()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("AI Music Pro")

    from PyQt6.QtGui import QFont
    default_font = QFont()
    default_font.setFamily("Microsoft JhengHei UI")   # 微軟正黑體
    default_font.setPointSize(12)
    app.setFont(default_font)

    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_NAME)
        except:
            pass

    window = AIMusicApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()