@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"
echo ============================================
echo   耳鳴工作台 APK 建置
echo ============================================

where node >nul 2>nul
if errorlevel 1 (
  echo [錯誤] 找不到 Node.js。請先安裝 Node.js 22 LTS：https://nodejs.org
  goto :fail
)

rem ── JDK：需要 21–24 版（Capacitor 需要 21 以上；Gradle 8.14 不支援 25 以上）──
call :findjdk
if not defined JDK (
  echo.
  echo [需要 JDK 21] 電腦上沒有找到 21–24 版的 JDK。
  if defined JAVA_HOME echo   目前的 JAVA_HOME：!JAVA_HOME!（版本不符合）
  where winget >nul 2>nul
  if errorlevel 1 (
    echo   請到 https://adoptium.net 下載安裝 Temurin JDK 21，再重新執行這個檔案。
    goto :fail
  )
  choice /c YN /m "要現在用 winget 自動安裝 Temurin JDK 21 嗎"
  if errorlevel 2 goto :fail
  winget install -e --id EclipseAdoptium.Temurin.21.JDK --accept-package-agreements --accept-source-agreements
  call :findjdk
  if not defined JDK (
    echo [錯誤] 安裝後仍找不到 JDK 21。請關閉這個視窗，重新執行一次 build_apk.bat。
    goto :fail
  )
)
set "JAVA_HOME=!JDK!"
set "PATH=!JDK!\bin;!PATH!"
echo JDK：!JDK_VER!（!JDK!）

rem ── Android SDK ──
if not defined ANDROID_HOME if defined ANDROID_SDK_ROOT set "ANDROID_HOME=!ANDROID_SDK_ROOT!"
if not defined ANDROID_HOME if exist "%LOCALAPPDATA%\Android\Sdk" set "ANDROID_HOME=%LOCALAPPDATA%\Android\Sdk"
if not defined ANDROID_HOME (
  echo [錯誤] 找不到 Android SDK。請先打開 Android Studio 完成第一次設定（會自動下載 SDK）。
  goto :fail
)
echo SDK：!ANDROID_HOME!
set "SDKP=!ANDROID_HOME:\=/!"
>android\local.properties echo sdk.dir=!SDKP!

echo.
echo [1/4] 安裝套件...
call npm install --no-audit --no-fund || goto :fail
call npx cap telemetry off >nul 2>nul

echo [2/4] 準備網頁內容...
call node scripts\prepare-www.js || goto :fail

echo [3/4] 同步到 Android 專案...
call npx cap sync android || goto :fail

echo [4/4] 建置 APK（第一次會下載 Gradle，需要幾分鐘）...
pushd android
call gradlew.bat --stop >nul 2>nul
call gradlew.bat assembleDebug
set "RC=!errorlevel!"
popd
if not "!RC!"=="0" goto :fail

copy /y "android\app\build\outputs\apk\debug\app-debug.apk" "TinnitusLab-debug.apk" >nul || goto :fail
echo.
echo ============================================
echo   完成：TinnitusLab-debug.apk
echo   把這個檔案傳到手機上安裝即可。
echo ============================================
pause
exit /b 0

:fail
echo.
echo 建置失敗，請把上面的錯誤訊息複製給 Claude。
pause
exit /b 1

rem ────────────────────────────────────────────
rem 依序檢查常見位置，找第一個 21–24 版的 JDK，結果放在 JDK / JDK_VER
:findjdk
set "JDK="
set "JDK_VER="
for /d %%D in ("%ProgramFiles%\Eclipse Adoptium\jdk-21*" "%ProgramFiles%\Microsoft\jdk-21*" "%ProgramFiles%\Java\jdk-21*" "%ProgramFiles%\Zulu\zulu-21*" "%ProgramFiles%\Amazon Corretto\jdk21*") do call :tryjdk "%%~fD"
call :tryjdk "%JAVA_HOME%"
call :tryjdk "%ProgramFiles%\Android\Android Studio\jbr"
call :tryjdk "%LOCALAPPDATA%\Programs\Android Studio\jbr"
for /d %%D in ("%ProgramFiles%\Eclipse Adoptium\jdk-2*" "%ProgramFiles%\Java\jdk-2*" "%ProgramFiles%\Microsoft\jdk-2*") do call :tryjdk "%%~fD"
exit /b 0

:tryjdk
if defined JDK exit /b 0
set "CAND=%~1"
if not defined CAND exit /b 0
if not exist "%CAND%\bin\java.exe" exit /b 0
if not exist "%CAND%\release" exit /b 0
set "VER="
for /f "tokens=2 delims==" %%V in ('findstr /b "JAVA_VERSION=" "%CAND%\release"') do set "VER=%%~V"
if not defined VER exit /b 0
set "MAJ="
for /f "tokens=1 delims=." %%M in ("%VER%") do set "MAJ=%%M"
if not defined MAJ exit /b 0
if %MAJ% GEQ 21 if %MAJ% LEQ 24 (
  set "JDK=%CAND%"
  set "JDK_VER=%VER%"
)
exit /b 0
