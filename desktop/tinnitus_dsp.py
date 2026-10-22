# -*- coding: utf-8 -*-
"""
tinnitus_dsp.py — 耳鳴頻段聲音處理核心模組（AI Music Pro 與 Android APK 共用規格）

功能
  * 左右耳各自獨立設定：模式（缺口 notch / 補強 boost / 關閉 off）、中心頻率、寬度
  * 濾波器「設計公式」只用 numpy，逐行對應到 JavaScript（APK 版用 Web Audio IIRFilterNode
    串接同樣的二階段係數），確保電腦版與手機版的頻率響應一致
  * 響度標準化（LUFS）、峰值上限、淡入淡出
  * 處理前後的頻段能量報告，自動提醒「這首歌在該頻段幾乎沒有能量」
  * 批次處理與命令列介面

需求套件：numpy、scipy、soundfile
選用套件：pyloudnorm（精確 LUFS）、matplotlib（頻譜比較圖）、ffmpeg（輸出 MP3）

────────────────────────────────────────────────────────────────────
共用設定檔規格  schema = "tinnitus-profile/1"
────────────────────────────────────────────────────────────────────
{
  "schema": "tinnitus-profile/1",
  "name": "左耳 9.5k 缺口",
  "ears": {
    "left":  {"mode": "notch", "center_hz": 9500, "width_oct": 1.0, "order": 6, "boost_db": 6.0},
    "right": {"mode": "off",   "center_hz": 9500, "width_oct": 1.0, "order": 6, "boost_db": 6.0}
  },
  "output": {"target_lufs": -23.0, "peak_ceiling_db": -1.0, "fade_in_s": 2.0, "fade_out_s": 3.0}
}

  mode       : "notch" | "boost" | "off"
  center_hz  : 中心頻率，200–16000 Hz
  width_oct  : 頻段寬度（八度），0.25–2.0；常用 0.5 或 1.0
  order      : 缺口的 Butterworth 原型階數（每階 = 一個二階段），2–10，預設 6
  boost_db   : 補強模式的增益 dB，0–12，預設 6

濾波規格（兩個平台都要照這個做）
  頻段邊界：lo = fc / 2^(w/2)，hi = fc * 2^(w/2)；hi 上限為 0.475·fs，lo 下限 20 Hz
  notch：Butterworth 帶阻（雙線性轉換，邊界頻率預扭曲），零點在 sqrt(lo·hi) 的預扭曲幾何中心，
         每個二階段單獨把 DC 增益正規化為 1；以單向（因果）方式濾波
  boost：RBJ Audio EQ Cookbook peaking，Q = sqrt(2^w) / (2^w − 1)
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np

SCHEMA = "tinnitus-profile/1"
EARS = ("left", "right")          # 聲道 0 = 左耳，1 = 右耳
MODES = ("notch", "boost", "off")
AUDIO_EXTS = {".wav", ".flac", ".mp3", ".ogg", ".aiff", ".aif", ".m4a"}

DEFAULT_EAR = {"mode": "off", "center_hz": 4000.0, "width_oct": 1.0, "order": 6, "boost_db": 6.0}
DEFAULT_OUTPUT = {"target_lufs": -23.0, "peak_ceiling_db": -1.0, "fade_in_s": 2.0, "fade_out_s": 3.0}


# ════════════════════════════════════════════════════════════════════
# 設定檔
# ════════════════════════════════════════════════════════════════════
def default_profile() -> dict:
    return {"schema": SCHEMA, "name": "未命名",
            "ears": {e: dict(DEFAULT_EAR) for e in EARS},
            "output": dict(DEFAULT_OUTPUT)}


def make_profile(left=None, right=None, name="自訂", **output) -> dict:
    """快速建立設定檔。left / right 傳 dict，例如 {"mode": "notch", "center_hz": 9500}。"""
    p = default_profile()
    p["name"] = name
    if left:
        p["ears"]["left"].update(left)
    if right:
        p["ears"]["right"].update(right)
    p["output"].update(output)
    return validate_profile(p)


def validate_profile(p: dict) -> dict:
    """補齊缺漏欄位、檢查範圍，回傳一份乾淨的新設定檔。不合法的值直接丟出 ValueError。"""
    if not isinstance(p, dict):
        raise ValueError("設定檔必須是 JSON 物件")
    schema = p.get("schema", SCHEMA)
    if schema != SCHEMA:
        raise ValueError(f"不支援的設定檔版本：{schema}（需要 {SCHEMA}）")
    out = default_profile()
    out["name"] = str(p.get("name", out["name"]))
    ears = p.get("ears", {}) or {}
    for e in EARS:
        src = ears.get(e, {}) or {}
        d = out["ears"][e]
        d.update({k: src[k] for k in DEFAULT_EAR if k in src})
        if d["mode"] not in MODES:
            raise ValueError(f"{e}.mode 必須是 {MODES} 其中之一，收到 {d['mode']!r}")
        d["center_hz"] = float(d["center_hz"])
        d["width_oct"] = float(d["width_oct"])
        d["order"] = int(d["order"])
        d["boost_db"] = float(d["boost_db"])
        if not 200 <= d["center_hz"] <= 16000:
            raise ValueError(f"{e}.center_hz 要在 200–16000 Hz 之間，收到 {d['center_hz']}")
        if not 0.25 <= d["width_oct"] <= 2.0:
            raise ValueError(f"{e}.width_oct 要在 0.25–2.0 之間，收到 {d['width_oct']}")
        if not 2 <= d["order"] <= 10:
            raise ValueError(f"{e}.order 要在 2–10 之間，收到 {d['order']}")
        if not 0 <= d["boost_db"] <= 12:
            raise ValueError(f"{e}.boost_db 要在 0–12 dB 之間，收到 {d['boost_db']}")
    o = p.get("output", {}) or {}
    out["output"].update({k: float(o[k]) for k in DEFAULT_OUTPUT if k in o})
    if not -40 <= out["output"]["target_lufs"] <= -10:
        raise ValueError("output.target_lufs 要在 -40 到 -10 之間")
    if not -12 <= out["output"]["peak_ceiling_db"] <= 0:
        raise ValueError("output.peak_ceiling_db 要在 -12 到 0 之間")
    return out


def load_profile(path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return validate_profile(json.load(f))


def save_profile(p: dict, path) -> None:
    p = validate_profile(p)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)


def band_edges(center_hz: float, width_oct: float, fs: float):
    """回傳 (lo, hi, clamped)。hi 超過 0.475·fs 時會被截斷，clamped=True。"""
    lo = center_hz / 2 ** (width_oct / 2)
    hi = center_hz * 2 ** (width_oct / 2)
    hi_max = 0.475 * fs
    clamped = hi > hi_max
    return max(lo, 20.0), min(hi, hi_max), clamped


# ════════════════════════════════════════════════════════════════════
# 濾波器設計（純 numpy，與 JS 版逐行對應）
# 輸出格式與 scipy 的 SOS 相同：每列 [b0, b1, b2, a0(=1), a1, a2]
# ════════════════════════════════════════════════════════════════════
def design_bandstop_sos(fs: float, lo: float, hi: float, order: int) -> np.ndarray:
    """Butterworth 帶阻濾波器。order = 低通原型階數，產生 order 個二階段。"""
    if not 0 < lo < hi < fs / 2:
        raise ValueError(f"頻段不合法：lo={lo:.1f}, hi={hi:.1f}, fs={fs}")
    k2 = 2.0 * fs
    w1 = k2 * math.tan(math.pi * lo / fs)          # 預扭曲
    w2 = k2 * math.tan(math.pi * hi / fs)
    w0 = math.sqrt(w1 * w2)
    bw = w2 - w1

    # 低通原型極點（左半平面）
    n = order
    lp = [complex(math.cos(math.pi * (2 * k + n - 1) / (2 * n)),
                  math.sin(math.pi * (2 * k + n - 1) / (2 * n))) for k in range(1, n + 1)]

    # LP → BS：p s² − bw s + p w0² = 0
    zp = []
    for p in lp:
        disc = complex(bw * bw) - 4 * p * p * w0 * w0
        r = disc ** 0.5
        for s in ((bw + r) / (2 * p), (bw - r) / (2 * p)):
            zp.append((k2 + s) / (k2 - s))        # 雙線性轉換

    # 零點：e^{±jΩ0}
    om0 = 2.0 * math.atan(w0 / k2)
    b = [1.0, -2.0 * math.cos(om0), 1.0]

    # 極點配對成二階段
    upper = [z for z in zp if z.imag > 1e-12]
    real = sorted([z.real for z in zp if abs(z.imag) <= 1e-12])
    sections = []
    for z in upper:
        sections.append([1.0, -2.0 * z.real, abs(z) ** 2])
    for i in range(0, len(real) - 1, 2):
        q1, q2 = real[i], real[i + 1]
        sections.append([1.0, -(q1 + q2), q1 * q2])
    sections.sort(key=lambda a: a[2])               # 半徑小的在前，數值較穩定

    sos = []
    for a in sections:
        g = (a[0] + a[1] + a[2]) / (b[0] + b[1] + b[2])   # 每段 DC 增益 = 1
        sos.append([b[0] * g, b[1] * g, b[2] * g, a[0], a[1], a[2]])
    return np.array(sos, dtype=np.float64)


def design_peaking_sos(fs: float, center_hz: float, width_oct: float, gain_db: float) -> np.ndarray:
    """RBJ Cookbook peaking EQ，單一二階段。"""
    A = 10 ** (gain_db / 40)
    w = 2 * math.pi * center_hz / fs
    q = math.sqrt(2 ** width_oct) / (2 ** width_oct - 1)
    alpha = math.sin(w) / (2 * q)
    c = math.cos(w)
    b = [1 + alpha * A, -2 * c, 1 - alpha * A]
    a = [1 + alpha / A, -2 * c, 1 - alpha / A]
    return np.array([[b[0] / a[0], b[1] / a[0], b[2] / a[0], 1.0, a[1] / a[0], a[2] / a[0]]])


def design_ear(fs: float, ear: dict):
    """依單耳設定產生 SOS。回傳 (sos 或 None, 資訊 dict)。"""
    info = {"mode": ear["mode"], "center_hz": ear["center_hz"], "width_oct": ear["width_oct"]}
    if ear["mode"] == "off":
        return None, info
    lo, hi, clamped = band_edges(ear["center_hz"], ear["width_oct"], fs)
    info.update(band_lo=lo, band_hi=hi, clamped=clamped)
    if ear["mode"] == "notch":
        return design_bandstop_sos(fs, lo, hi, ear["order"]), info
    return design_peaking_sos(fs, ear["center_hz"], ear["width_oct"], ear["boost_db"]), info


def sos_response_db(sos: np.ndarray, fs: float, freqs) -> np.ndarray:
    """計算 SOS 在指定頻率的增益（dB），給驗證與畫圖用。"""
    freqs = np.asarray(freqs, dtype=float)
    z = np.exp(1j * 2 * np.pi * freqs / fs)
    h = np.ones_like(z)
    for b0, b1, b2, a0, a1, a2 in sos:
        h *= (b0 + b1 / z + b2 / z ** 2) / (a0 + a1 / z + a2 / z ** 2)
    return 20 * np.log10(np.maximum(np.abs(h), 1e-12))


# ════════════════════════════════════════════════════════════════════
# 處理
# ════════════════════════════════════════════════════════════════════
@dataclass
class EarReport:
    ear: str
    mode: str
    center_hz: float
    width_oct: float
    band_lo: float = 0.0
    band_hi: float = 0.0
    band_share_db: float = 0.0     # 處理前，頻段能量佔該聲道總能量（dB）
    band_drop_db: float = 0.0      # 處理後整個頻段能量的變化（負值 = 變小，含邊界 −3 dB 區）
    core_drop_db: float = 0.0      # 頻段中央一半寬度內的能量變化（代表缺口實際深度）
    warnings: list = field(default_factory=list)


@dataclass
class Report:
    sample_rate: int
    channels_in: int
    duration_s: float
    ears: list
    input_lufs: float | None = None
    output_lufs: float | None = None
    gain_db: float = 0.0
    peak_limited: bool = False
    loudness_method: str = ""
    warnings: list = field(default_factory=list)

    def to_dict(self):
        return asdict(self)

    def summary(self) -> str:
        lines = [f"取樣率 {self.sample_rate} Hz｜長度 {self.duration_s:.1f} 秒｜輸入 {self.channels_in} 聲道"]
        name = {"left": "左耳", "right": "右耳"}
        mode = {"notch": "缺口", "boost": "補強", "off": "不處理"}
        for e in self.ears:
            if e.mode == "off":
                lines.append(f"  {name[e.ear]}：不處理")
                continue
            lines.append(f"  {name[e.ear]}：{mode[e.mode]} {e.center_hz:.0f} Hz（{e.band_lo:.0f}–{e.band_hi:.0f} Hz）"
                         f"｜頻段佔比 {e.band_share_db:.1f} dB｜整段 {e.band_drop_db:+.1f} dB｜中心區 {e.core_drop_db:+.1f} dB")
            lines += [f"    ⚠ {w}" for w in e.warnings]
        if self.output_lufs is not None:
            lines.append(f"  響度 {self.input_lufs:.1f} → {self.output_lufs:.1f} LUFS（{self.loudness_method}）"
                         + ("｜已降低增益避免削波" if self.peak_limited else ""))
        lines += [f"  ⚠ {w}" for w in self.warnings]
        return "\n".join(lines)


def _sosfilt(sos, x):
    from scipy.signal import sosfilt
    return sosfilt(sos, x)


def _band_energy(x, fs, lo, hi):
    from scipy.signal import welch
    nper = int(min(len(x), 8192))
    f, pxx = welch(x, fs=fs, nperseg=nper)
    df = f[1] - f[0]
    total = np.sum(pxx) * df + 1e-20
    band = np.sum(pxx[(f >= lo) & (f <= hi)]) * df + 1e-20
    return band, total


def _loudness(x, fs):
    """回傳 (LUFS, 方法)。沒有 pyloudnorm 時用 RMS 近似。"""
    try:
        import pyloudnorm as pyln
        if len(x) / fs >= 0.4:
            v = pyln.Meter(fs).integrated_loudness(x)
            if np.isfinite(v):
                return float(v), "pyloudnorm ITU-R BS.1770"
    except ImportError:
        pass
    rms = np.sqrt(np.mean(x ** 2) + 1e-20)
    return float(20 * np.log10(rms) - 0.691), "RMS 近似（建議安裝 pyloudnorm）"


def _fade(n, fs, seconds, out=False):
    m = int(min(n // 2, max(0, seconds) * fs))
    if m <= 1:
        return None, 0
    ramp = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, m))   # 升餘弦
    return (ramp[::-1] if out else ramp), m


def process_array(audio: np.ndarray, sr: int, profile: dict, normalize: bool = True):
    """
    處理一段音訊。
    audio  : (n,) 單聲道或 (n, ch) 多聲道，float
    回傳   : (處理後 float32 陣列 (n, 2 或更多), Report)
    單聲道輸入只要有一耳要處理，就會轉成立體聲，讓左右耳可以不同。
    """
    p = validate_profile(profile)
    x = np.asarray(audio, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    ch_in = x.shape[1]
    active = [e for e in EARS if p["ears"][e]["mode"] != "off"]
    if ch_in == 1 and active:
        x = np.repeat(x, 2, axis=1)
    y = x.copy()

    rep = Report(sample_rate=int(sr), channels_in=ch_in, duration_s=len(x) / sr, ears=[])
    if ch_in > 2:
        rep.warnings.append(f"輸入有 {ch_in} 個聲道，只處理前兩個（左、右）。")

    for idx, e in enumerate(EARS):
        ear = p["ears"][e]
        sos, info = design_ear(sr, ear)
        er = EarReport(ear=e, mode=ear["mode"], center_hz=ear["center_hz"], width_oct=ear["width_oct"])
        if sos is not None:
            er.band_lo, er.band_hi = info["band_lo"], info["band_hi"]
            if info["clamped"]:
                er.warnings.append(f"頻段上緣超過取樣率允許的範圍，已截在 {er.band_hi:.0f} Hz。")
            y[:, idx] = _sosfilt(sos, x[:, idx])
            b0, t0 = _band_energy(x[:, idx], sr, er.band_lo, er.band_hi)
            b1, _ = _band_energy(y[:, idx], sr, er.band_lo, er.band_hi)
            er.band_share_db = 10 * math.log10(b0 / t0)
            er.band_drop_db = 10 * math.log10(b1 / b0)
            q = 2 ** (ear["width_oct"] / 4)
            c_lo, c_hi = max(er.band_lo, ear["center_hz"] / q), min(er.band_hi, ear["center_hz"] * q)
            if c_hi > c_lo:
                cb0, _ = _band_energy(x[:, idx], sr, c_lo, c_hi)
                cb1, _ = _band_energy(y[:, idx], sr, c_lo, c_hi)
                er.core_drop_db = 10 * math.log10(cb1 / cb0)
            if er.band_share_db < -35:
                er.warnings.append(f"這段聲音在處理頻段內的能量很少（佔總能量 {er.band_share_db:.0f} dB），"
                                   "效果有限，建議改用高頻較豐富的音樂或粉紅噪音。")
        rep.ears.append(er)

    if normalize:
        o = p["output"]
        rep.input_lufs, rep.loudness_method = _loudness(y, sr)
        gain = o["target_lufs"] - rep.input_lufs
        y *= 10 ** (gain / 20)
        peak = np.max(np.abs(y)) + 1e-20
        ceiling = 10 ** (o["peak_ceiling_db"] / 20)
        if peak > ceiling:
            y *= ceiling / peak
            gain += 20 * math.log10(ceiling / peak)
            rep.peak_limited = True
        rep.gain_db = gain
        rep.output_lufs, _ = _loudness(y, sr)
        for out, sec in ((False, o["fade_in_s"]), (True, o["fade_out_s"])):
            ramp, m = _fade(len(y), sr, sec, out)
            if ramp is not None:
                if out:
                    y[-m:] *= ramp[:, None]
                else:
                    y[:m] *= ramp[:, None]

    return y.astype(np.float32), rep


# ════════════════════════════════════════════════════════════════════
# 檔案讀寫
# ════════════════════════════════════════════════════════════════════
def _ffmpeg():
    return shutil.which("ffmpeg")


def read_audio(path):
    import soundfile as sf
    try:
        data, sr = sf.read(str(path), always_2d=True)
        return data, sr
    except Exception:
        ff = _ffmpeg()
        if not ff:
            raise RuntimeError(f"讀不到 {path}，而且找不到 ffmpeg 可以轉檔。")
        with tempfile.TemporaryDirectory() as td:
            tmp = os.path.join(td, "in.wav")
            subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(path), tmp], check=True)
            data, sr = sf.read(tmp, always_2d=True)
            return data, sr


def write_audio(path, data, sr, mp3_bitrate="192k"):
    import soundfile as sf
    path = Path(path)
    ext = path.suffix.lower()
    if ext in (".wav", ".flac", ".ogg", ".aiff", ".aif"):
        subtype = "PCM_24" if ext in (".wav", ".aiff", ".aif") else None
        sf.write(str(path), data, sr, subtype=subtype)
        return path
    ff = _ffmpeg()
    if not ff:
        raise RuntimeError(f"輸出 {ext} 需要 ffmpeg，請改用 .wav / .flac 或安裝 ffmpeg。")
    with tempfile.TemporaryDirectory() as td:
        tmp = os.path.join(td, "out.wav")
        sf.write(tmp, data, sr, subtype="PCM_24")
        cmd = [ff, "-y", "-loglevel", "error", "-i", tmp]
        if ext == ".mp3":
            cmd += ["-codec:a", "libmp3lame", "-b:a", mp3_bitrate]
        elif ext == ".m4a":
            cmd += ["-codec:a", "aac", "-b:a", mp3_bitrate]
        subprocess.run(cmd + [str(path)], check=True)
    return path


def default_output_path(in_path, out_dir=None, fmt=None, suffix="_tinnitus"):
    in_path = Path(in_path)
    ext = ("." + fmt.lstrip(".")) if fmt else in_path.suffix
    if ext.lower() not in AUDIO_EXTS:
        ext = ".wav"
    d = Path(out_dir) if out_dir else in_path.parent
    return d / f"{in_path.stem}{suffix}{ext}"


def process_file(in_path, profile, out_path=None, out_dir=None, fmt=None, plot=False):
    """處理單一檔案。回傳 (輸出路徑, Report)。plot=True 時另存一張頻譜比較圖 (.png)。"""
    data, sr = read_audio(in_path)
    y, rep = process_array(data, sr, profile)
    out = Path(out_path) if out_path else default_output_path(in_path, out_dir, fmt)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_audio(out, y, sr)
    if plot:
        try:
            plot_comparison(data, y, sr, profile, out.with_suffix(".png"))
        except ImportError:
            rep.warnings.append("沒有安裝 matplotlib，略過頻譜圖。")
    return out, rep


def iter_audio_files(paths, recursive=False):
    for p in paths:
        p = Path(p)
        if p.is_dir():
            it = p.rglob("*") if recursive else p.glob("*")
            for f in sorted(it):
                if f.is_file() and f.suffix.lower() in AUDIO_EXTS and "_tinnitus" not in f.stem:
                    yield f
        elif p.is_file():
            yield p


def process_batch(paths, profile, out_dir=None, fmt=None, recursive=False, plot=False, log=print):
    """批次處理。回傳 [(輸入, 輸出 或 None, Report 或 錯誤訊息)]。"""
    results = []
    files = list(iter_audio_files(paths, recursive))
    for i, f in enumerate(files, 1):
        try:
            out, rep = process_file(f, profile, out_dir=out_dir, fmt=fmt, plot=plot)
            log(f"[{i}/{len(files)}] {f.name} → {out.name}\n{rep.summary()}")
            results.append((f, out, rep))
        except Exception as ex:  # noqa: BLE001 — 批次中單檔失敗不中斷
            log(f"[{i}/{len(files)}] {f.name} 失敗：{ex}")
            results.append((f, None, str(ex)))
    return results


# ════════════════════════════════════════════════════════════════════
# 頻譜比較圖
# ════════════════════════════════════════════════════════════════════
def plot_comparison(before, after, sr, profile, png_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from scipy.signal import welch
    p = validate_profile(profile)
    b = np.asarray(before, float)
    b = b[:, None] if b.ndim == 1 else b
    if b.shape[1] == 1:
        b = np.repeat(b, 2, axis=1)
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.6), sharey=True)
    for idx, (e, ax) in enumerate(zip(EARS, axes)):
        for sig, lab, a in ((b[:, idx], "before", 0.5), (after[:, idx], "after", 1.0)):
            f, pxx = welch(sig, fs=sr, nperseg=int(min(len(sig), 8192)))
            ax.semilogx(f[1:], 10 * np.log10(pxx[1:] + 1e-20), label=lab, alpha=a, lw=1)
        ear = p["ears"][e]
        if ear["mode"] != "off":
            lo, hi, _ = band_edges(ear["center_hz"], ear["width_oct"], sr)
            ax.axvspan(lo, hi, color="orange", alpha=0.15)
            ax.axvline(ear["center_hz"], color="orange", ls="--", lw=1)
        ax.set_title(f"{'Left' if e == 'left' else 'Right'}: {ear['mode']}"
                     + (f" {ear['center_hz']:.0f} Hz" if ear["mode"] != "off" else ""))
        ax.set_xlim(50, sr / 2)
        ax.set_xlabel("Hz")
        ax.grid(alpha=0.3, which="both")
    axes[0].set_ylabel("dB")
    axes[0].legend(loc="lower left", fontsize=8)
    fig.tight_layout()
    fig.savefig(png_path, dpi=110)
    plt.close(fig)
    return png_path


# ════════════════════════════════════════════════════════════════════
# 生成提示詞輔助：讓 AI 生成的音樂在處理頻段內有足夠能量
# ════════════════════════════════════════════════════════════════════
def suggest_prompt_tags(center_hz: float) -> list:
    """依中心頻率回傳 ACE-Step / YuE 適用的英文風格標籤。"""
    if center_hz >= 6000:
        return ["bright mix", "crisp hi-hats", "shimmering cymbals", "shakers", "airy synth pads",
                "acoustic guitar harmonics", "glockenspiel", "breathy texture"]
    if center_hz >= 2500:
        return ["bright piano", "violin lead", "acoustic guitar strumming", "clear vocals",
                "bell tones", "brass section"]
    if center_hz >= 800:
        return ["warm piano", "cello", "clarinet", "rich mid-range", "nylon guitar"]
    return ["warm bass", "low strings", "soft pads", "upright bass"]


# ════════════════════════════════════════════════════════════════════
# 命令列
# ════════════════════════════════════════════════════════════════════
def _parse_ear(spec: str) -> dict:
    """格式：MODE[:中心頻率[:寬度八度]]，例如 notch:9500:1、boost:4000:0.5、off"""
    parts = spec.split(":")
    d = {"mode": parts[0]}
    if len(parts) > 1 and parts[1]:
        d["center_hz"] = float(parts[1])
    if len(parts) > 2 and parts[2]:
        d["width_oct"] = float(parts[2])
    return d


def main(argv=None):
    ap = argparse.ArgumentParser(description="耳鳴頻段聲音處理（缺口 / 補強，左右耳獨立）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    mk = sub.add_parser("make-profile", help="建立設定檔")
    mk.add_argument("-o", "--out", required=True, help="輸出的 .json 路徑")
    mk.add_argument("--left", default="off", help="左耳：MODE[:Hz[:八度]]，例 notch:9500:1")
    mk.add_argument("--right", default="off", help="右耳：MODE[:Hz[:八度]]")
    mk.add_argument("--name", default="自訂")
    mk.add_argument("--lufs", type=float, default=-23.0)

    pr = sub.add_parser("process", help="處理檔案或資料夾")
    pr.add_argument("inputs", nargs="+", help="音檔或資料夾")
    pr.add_argument("-p", "--profile", help="設定檔 .json")
    pr.add_argument("--left", help="不用設定檔時：左耳 MODE[:Hz[:八度]]")
    pr.add_argument("--right", help="不用設定檔時：右耳 MODE[:Hz[:八度]]")
    pr.add_argument("-o", "--out-dir", help="輸出資料夾（預設與原檔同資料夾）")
    pr.add_argument("-f", "--format", help="輸出格式：wav / flac / mp3（預設同原檔）")
    pr.add_argument("-r", "--recursive", action="store_true", help="包含子資料夾")
    pr.add_argument("--plot", action="store_true", help="另存頻譜比較圖")

    inf = sub.add_parser("info", help="顯示設定檔的頻段")
    inf.add_argument("profile")
    inf.add_argument("--sr", type=int, default=44100)

    a = ap.parse_args(argv)
    if a.cmd == "make-profile":
        p = make_profile(_parse_ear(a.left), _parse_ear(a.right), name=a.name, target_lufs=a.lufs)
        save_profile(p, a.out)
        print(f"已儲存 {a.out}")
        print(json.dumps(p, ensure_ascii=False, indent=2))
    elif a.cmd == "process":
        if a.profile:
            p = load_profile(a.profile)
        elif a.left or a.right:
            p = make_profile(_parse_ear(a.left or "off"), _parse_ear(a.right or "off"))
        else:
            ap.error("請指定 -p 設定檔，或用 --left / --right")
        res = process_batch(a.inputs, p, a.out_dir, a.format, a.recursive, a.plot)
        ok = sum(1 for _, o, _ in res if o)
        print(f"\n完成 {ok}/{len(res)} 個檔案")
        return 0 if ok == len(res) else 1
    elif a.cmd == "info":
        p = load_profile(a.profile)
        for e in EARS:
            ear = p["ears"][e]
            if ear["mode"] == "off":
                print(f"{e}: off")
                continue
            lo, hi, c = band_edges(ear["center_hz"], ear["width_oct"], a.sr)
            print(f"{e}: {ear['mode']} {ear['center_hz']:.0f} Hz  {lo:.0f}–{hi:.0f} Hz" + ("（已截斷）" if c else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
