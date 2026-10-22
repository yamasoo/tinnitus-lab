# 耳鳴工作台 Android 版

> [!WARNING]
> **這不是醫療器材，也不能診斷或治療耳鳴。**
> 本專案是個人製作的聲音練習與自我觀察工具，未經任何醫療法規審查或臨床驗證。聽力篩檢沒有經過校準，結果不能取代耳鼻喉科的聽力檢查。
> 出現**突然聽力下降、單側耳鳴或聽力變差、跟心跳同步的搏動性耳鳴、眩暈**等情況，請直接就醫，不要先用本工具處理。
> 使用前請先閱讀下方的〈[醫學背景與使用須知](#醫學背景與使用須知)〉。

手機網頁版「耳鳴頻段工作台」的 Android App，用 Capacitor 包裝。功能與網頁版相同，另外多了：

- 處理好的音樂**直接存成 WAV** 到手機的「文件 › 耳鳴工作台」資料夾，可以用任何音樂播放器在螢幕關閉時聆聽，也可以按「分享」傳到其他 App
- 設定檔可以直接存成 `.json`
- 聆聽、測試時保持螢幕不休眠
- 不需要網路就能使用

處理核心 `src/dsp.js` 和電腦版 `tinnitus_dsp.py` 是同一套算法，設定檔格式（`tinnitus-profile/1`）互通。

---

## 醫學背景與使用須知

### 耳鳴是什麼

耳鳴是在沒有外在聲音時，聽到嗡嗡聲、嘶嘶聲或單一音調的感覺。它是一種**症狀，不是一種疾病**，背後可能有許多原因：噪音造成的聽力損傷、老年性聽力退化、耳垢阻塞、中耳炎、某些藥物、顳顎關節問題，少數情況下也可能是血管或神經方面的問題。

目前常見的解釋是：內耳某個頻段受損後，大腦對該頻段的訊號「調高增益」來補償，結果把神經本身的雜訊也放大成聽得到的聲音。這也是為什麼耳鳴的音調常常落在聽力較差的頻段附近，也是本工具「找頻段、針對頻段處理聲音」的出發點。不過這只是目前的主流假說之一，並不代表調整那個頻段的聲音就能消除耳鳴。

### 請先就醫的情況

以下情況請**優先就醫**，不要先用本工具自行處理：

| 情況 | 為什麼需要注意 |
|---|---|
| **突然聽力下降**（幾小時到幾天內），可能伴隨耳悶 | 可能是突發性聽力損失，屬於耳科急症，越早治療效果越好，請**盡快、最好在 72 小時內**看耳鼻喉科 |
| **只有一側**耳鳴，或一側聽力明顯比另一側差 | 需要排除聽神經等較少見的原因，醫師可能會安排進一步檢查 |
| 耳鳴**跟著心跳一下一下**（搏動性耳鳴） | 可能和血管有關，需要醫師評估 |
| 伴隨**眩暈**、走路不穩、臉部麻木或無力 | 可能涉及內耳或神經系統 |
| 耳朵疼痛、流膿、流血，或頭部受傷後出現耳鳴 | 需要檢查耳朵本身是否有感染或外傷 |
| 耳鳴讓你**長期睡不好、焦慮、心情低落** | 耳鳴造成的困擾本身就值得治療，請告訴醫師 |

如果耳鳴讓你非常痛苦，甚至出現傷害自己的念頭，請立刻尋求協助。在台灣可以撥打 **1925 安心專線**（24 小時、免付費），緊急情況請撥 **119**。

### 目前有證據支持的做法

依據美國耳鼻喉頭頸外科醫學會（AAO-HNS）、英國 NICE 及歐洲的耳鳴臨床指引：

- **找出原因**：先由耳鼻喉科做耳朵檢查和標準聽力檢查，排除可以處理的原因。
- **如果有聽力損失，配戴助聽器**：讓大腦重新聽到原本聽不清楚的聲音，常常能同時減輕耳鳴的困擾。
- **認知行為治療（CBT）**：目前證據最強的方法。它的目標不是讓耳鳴消失，而是降低耳鳴帶來的焦慮、失眠與困擾。
- **衛教與放鬆技巧**：了解耳鳴大多不危險，本身就能減輕不少壓力。

**目前不建議**（缺乏證據，部分還可能有副作用）：用藥物、保健食品、草藥、銀杏、褪黑激素或針灸來「治療耳鳴」。

### 本工具的方法有多少證據

- **聲音治療**（背景聲、噪音、音樂）：Cochrane 系統性回顧發現，**沒有證據顯示它比等待觀察、安慰劑或單純衛教更有效**。有些人覺得有幫助，主要是讓耳鳴不那麼突出、比較容易放鬆或入睡。
- **缺口音樂**（TMNMT，本工具的「缺口」模式）：早期小型研究看到耳鳴音量下降，但最新的統合分析發現，它在減輕耳鳴困擾上**沒有顯著優於一般聽音樂**。英國 NICE 的證據回顧則認為客製化的聲音有一些效益，但證據品質有限。
- **頻段補強**（本工具的「補強」模式）：概念上接近助聽器的頻段放大，但用耳機播放音樂和真正驗配的助聽器並不相同，**不能取代助聽器**。

**請把本工具當成「聽音樂的一種方式」，不要期待它能治好耳鳴。** 如果使用幾週後耳鳴變大聲、更困擾，請停止使用。

### 本工具的限制

- **聽力篩檢不是聽力檢查**：手機、耳機、音量設定都沒有校準，顯示的是相對值（dBFS），不是醫療用的聽力閾值（dB HL）。耳機本身的頻率響應、耳塞戴的深淺，都可能在 8–12 kHz 附近造成「假的凹陷」。**10 kHz 以上的結果尤其不可靠。**
- **兩耳差異請先排除耳機因素**：把耳機左右對調再測一次，差異跟著耳朵走才有參考價值，而且仍然需要醫師確認。
- **音調配對的誤差很大**：同一個人每天配出來的頻率可能差很多，也常常差了一個八度（例如 4 kHz 和 8 kHz 搞混）。建議分幾天多配幾次取平均。
- **沒有任何結果代表「正常」或「沒事」**：篩檢沒發現異常，不代表聽力沒有問題。

### 安全聆聽

- 音量**比耳鳴稍小或差不多**就好，**不要用大音量去蓋過耳鳴**。大音量會造成新的噪音傷害，讓耳鳴更嚴重。
- 世界衛生組織（WHO）與國際電信聯盟的安全聆聽標準，以成人每週累積不超過 **80 dB、40 小時**作為參考上限。實際上，能輕鬆和身旁的人對話的音量，通常就在安全範圍內。
- 每次聆聽之間讓耳朵休息；睡前播放請使用定時關閉。
- 使用時如果出現**耳鳴明顯變大、耳朵痛、耳悶或頭暈**，請立即停止，並視情況就醫。
- 兒童、孕婦、正在接受耳科治療的人，請先詢問醫師。

### 參考資料

- Tunkel DE, et al. *Clinical Practice Guideline: Tinnitus.* Otolaryngology–Head and Neck Surgery, 2014（AAO-HNS）
- Cima RFF, et al. *A multidisciplinary European guideline for tinnitus: diagnostics, assessment, and treatment.* HNO, 2019
- National Institute for Health and Care Excellence. *Tinnitus: assessment and management* (NG155), 2020 — <https://www.nice.org.uk/guidance/ng155>
- Sereda M, et al. *Sound therapy (using amplification devices and/or sound generators) for tinnitus.* Cochrane Database of Systematic Reviews, 2018 — <https://www.cochrane.org/CD013094/ENT_sound-therapy-using-amplification-devices-andor-sound-generators-treating-tinnitus>
- *Efficacy of tailor-made notched music training for primary tinnitus: A systematic review and meta-analysis* — <https://iris.unina.it/handle/11588/1005544>
- Tinnitus UK. *Sound therapy* — <https://tinnitus.org.uk/wp-content/uploads/2024/07/Sound-therapy-July-2024.pdf>

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
- 聽力篩檢沒有經過校準，只能當作參考，詳見〈[醫學背景與使用須知](#醫學背景與使用須知)〉。

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

---

## 免責聲明

本專案以「現狀」提供，僅供個人聲音練習與自我觀察使用，**不提供任何醫療建議、診斷或治療**，也不保證任何效果。本專案的任何內容都不能取代合格醫療人員的診斷與治療；使用本工具所做的任何決定與造成的結果，由使用者自行負責。若對自己的聽力或耳鳴有任何疑慮，請諮詢耳鼻喉科醫師或聽力師。
