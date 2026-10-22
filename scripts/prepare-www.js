/*
 * 把 src/tinnitus.html 包成 APK 用的 www/index.html，並複製 dsp.js。
 * tinnitus.html 和 claude.ai 上的網頁版是同一份檔案；網頁版的外框（doctype、charset、viewport）
 * 在這裡補上，另外移除 Google Fonts 連結，讓 App 離線時也能立刻開啟（Android 內建思源黑體）。
 */
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..");
const src = path.join(root, "src");
const www = path.join(root, "www");
fs.mkdirSync(www, { recursive: true });

let body = fs.readFileSync(path.join(src, "tinnitus.html"), "utf8");
body = body
  .replace(/<link[^>]+fonts\.(googleapis|gstatic)\.com[^>]*>\s*/g, "")
  .replace(/<meta name="claude:viewport-fit-sides"[^>]*>\s*/, "");

const html = `<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<style>
:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}
body{margin:0;font-size:14px;-webkit-tap-highlight-color:transparent}
img{max-width:100%}
[hidden]{display:none!important}
</style>
</head>
<body>
${body}
</body>
</html>
`;
fs.writeFileSync(path.join(www, "index.html"), html);
fs.copyFileSync(path.join(src, "dsp.js"), path.join(www, "dsp.js"));
console.log("www/ 已更新：index.html、dsp.js");
