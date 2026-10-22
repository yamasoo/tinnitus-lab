# 耳鳴工作台 電腦版（AI Music Pro v2.5）

> [!WARNING]
> **這不是醫療器材，也不能診斷或治療耳鳴。** 耳鳴模式只是一種聆聽音樂的方式，效果沒有經過證實。
> 突然聽力下降、單側耳鳴、搏動性耳鳴或眩暈請直接就醫。請先閱讀主說明的〈[醫學背景與使用須知](../README.md#醫學背景與使用須知)〉。

`AI Music Pro v2.5.py` 是 PyQt6 音樂播放器，內建耳鳴模式；`tinnitus_dsp.py` 是處理核心，也可以單獨用命令列批次處理。
處理算法、設定檔格式（`tinnitus-profile/1`）都和手機網頁版、Android App 的 `src/dsp.js` 相同，設定檔可以互相匯入。

## 安裝

```
pip install PyQt6 pygame mutagen matplotlib numpy scipy soundfile pyloudnorm
```

輸出 MP3、播放 MP4/M4A 需要 ffmpeg（`winget install Gyan.FFmpeg`）。

兩個檔案放在同一個資料夾，執行：

```
python "AI Music Pro v2.5.py"
```

## 耳鳴模式

- 控制列的「🎧 耳鳴模式」（Ctrl+T）開關；「耳鳴 › 耳鳴設定…」（Ctrl+Shift+T）設定左右耳的模式、中心頻率和寬度
- 處理後的版本存在 `~/.ai_music_pro_cache/tinnitus/`，同一首歌第二次播放直接讀快取
- 「耳鳴 › 批次匯出耳鳴版本…」把目前清單輸出成 MP3 / FLAC / WAV

## 命令列

```
python tinnitus_dsp.py make-profile -o my.json --left notch:9500:1 --right off
python tinnitus_dsp.py process "音樂資料夾" -p my.json -f mp3 --plot
```
