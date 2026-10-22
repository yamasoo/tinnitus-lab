# 耳鳴工作台 Android 版

手機網頁版「耳鳴頻段工作台」的 Android App，用 Capacitor 包裝。功能與網頁版相同，另外多了：

- 處理好的音樂**直接存成 WAV** 到手機的「文件 › 耳鳴工作台」資料夾，可以用任何音樂播放器在螢幕關閉時聆聽，也可以按「分享」傳到其他 App
- 設定檔可以直接存成 `.json`
- 聆聽、測試時保持螢幕不休眠
- 不需要網路就能使用

處理核心 `src/dsp.js` 和電腦版 `tinnitus_dsp.py` 是同一套算法，設定檔格式（`tinnitus-profile/1`）互通。

---

## 方法一：在自己的 Windows 電腦上建置

### 需要先安裝（只要一次）

1. **Node.js 22 LTS**：<https://nodejs.org>
2. **Android Studio**：<https://developer.android.com/studio>
   安裝後**打開一次**，照著首次設定精靈完成（會自動下載 Android SDK）。
   Android Studio 內建建置需要的 JDK 21，不用另外安裝 Java。

### 建置

在這個資料夾裡雙擊 **`build_apk.bat`**。

腳本會自動找到 Android Studio 的 JDK 和 SDK，依序安裝套件、準備網頁內容、同步到 Android 專案，最後用 Gradle 建置。第一次會下載 Gradle 和相關套件，大約需要 5–10 分鐘；之後只要 1 分鐘左右。

完成後，資料夾裡會出現 **`TinnitusLab-debug.apk`**。

> 如果失敗，把視窗裡的錯誤訊息複製下來就能排查。

**關於 Java 版本**：建置需要 **JDK 21–24**。腳本會自動在常見位置尋找；如果你的電腦只有 Java 25 這類較新的版本（錯誤訊息會出現 `Unsupported class file major version 69`），腳本會詢問是否用 winget 自動安裝 Temurin JDK 21。用 Android Studio 開啟專案時，也請到「Settings › Build, Execution, Deployment › Build Tools › Gradle › Gradle JDK」選擇 JDK 21。

### 也可以用 Android Studio 開啟

先執行一次 `build_apk.bat`（或 `npm install` 再 `npm run sync`），然後在 Android Studio 選「Open」開啟 `android` 資料夾，手機用 USB 連接並開啟「USB 偵錯」，按 ▶ 就能直接安裝到手機上。

---

## 方法二：用 GitHub 自動建置（電腦不用裝 Android Studio）

1. 在 GitHub 建立一個新的 repository（建議設為私人），把這個資料夾的內容推上去（`.gitignore` 已經排除了不需要的檔案）。
2. 推到 `main` 分支後，GitHub Actions 會自動建置（設定在 `.github/workflows/build-apk.yml`）。也可以到 Actions 頁面手動按「Run workflow」。
3. 建置完成後，在該次執行頁面最下方的 Artifacts 下載 **TinnitusLab-debug**，解壓縮就是 APK。

### 第一次使用前：設定簽章金鑰

Android 只允許**同一把金鑰簽署**的 APK 互相覆蓋更新。GitHub 每次建置都在新機器上，如果不設定，會用隨機的新金鑰，手機就會拒絕安裝更新。
設定方式是把你電腦上的偵錯金鑰存成 GitHub 的 Secret（只需要做一次）：

1. 在 PowerShell 執行，金鑰內容會複製到剪貼簿：
   ```
   [Convert]::ToBase64String([IO.File]::ReadAllBytes("$env:USERPROFILE\.android\debug.keystore")) | Set-Clipboard
   ```
2. 到 repo 的 **Settings › Secrets and variables › Actions › New repository secret**
   - Name：`DEBUG_KEYSTORE_BASE64`
   - Secret：貼上剪貼簿內容
3. 回到 Actions 重新執行建置。

這樣 GitHub 和你電腦本機建置的 APK 簽章相同，可以互相覆蓋更新，App 裡的資料也會保留。
這把是偵錯金鑰，自己安裝使用沒問題；如果要上架 Google Play，需要另外建立正式金鑰。

---

## 安裝到手機

1. 把 APK 傳到手機（USB、雲端硬碟、LINE 傳給自己都可以）。
2. 在手機上點開 APK。第一次會要求允許「安裝不明應用程式」，允許你用來開啟 APK 的那個 App（例如檔案管理員）即可。
3. 安裝完成後，桌面會出現「耳鳴工作台」。

這是**偵錯版（debug）APK**，用 Android 內建的偵錯金鑰簽署，自己安裝使用沒有問題。如果之後要上架 Google Play，需要另外建立正式簽署金鑰。

---

## 修改內容後重新建置

- 介面和功能都在 **`src/tinnitus.html`**，處理核心在 **`src/dsp.js`**。這兩個檔案和 claude.ai 上的網頁版是同一份。
- 改完後再執行一次 `build_apk.bat` 就好。`scripts/prepare-www.js` 會自動把它包成 App 用的 `www/index.html`。
- 每次要發新版給手機更新時，記得把 `android/app/build.gradle` 裡的 `versionCode` 加 1（例如 1 → 2），`versionName` 也可以一起改。

---

## 已知限制

- **即時聆聽**在 App 切到背景或螢幕關閉後可能會停止。這需要 Android 的前景服務才能可靠做到，這一版沒有加入。想長時間聆聽，請用「輸出處理好的音檔」存成 WAV，再用手機的音樂播放器聽。
- 輸出的 WAV 統一為 44.1 kHz、16-bit，3 分鐘的歌大約 30 MB。
- 存檔位置是「文件 › 耳鳴工作台」。Android 10 以下第一次存檔時會詢問儲存權限；Android 11 以上不需要任何權限。
- 聽力篩檢沒有經過校準，只能當作參考。單側聽力變差、搏動性耳鳴或突然聽力下降，請直接就醫。

---

## 專案結構

```
src/tinnitus.html        介面與功能（與網頁版共用）
src/dsp.js               處理核心（與電腦版 tinnitus_dsp.py 對應）
scripts/prepare-www.js   產生 www/index.html
android/                 Android 原生專案（Capacitor 產生）
build_apk.bat            Windows 一鍵建置
.github/workflows/       GitHub 自動建置
capacitor.config.json    App 名稱與 ID（com.mayasoo.tinnituslab）
```
