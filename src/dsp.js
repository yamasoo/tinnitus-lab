/*
 * dsp.js — 耳鳴頻段處理核心（JavaScript 版）
 *
 * 與 tinnitus_dsp.py 逐行對應，共用設定檔規格 "tinnitus-profile/1"：
 *   - 濾波器設計：Butterworth 帶阻（雙線性、預扭曲）、RBJ peaking
 *   - 濾波執行：二階段 Direct Form II Transposed（與 scipy.signal.sosfilt 相同）
 *   - 響度：ITU-R BS.1770 門限積分響度（與 pyloudnorm 相同的 K 加權與門限）
 *   - 頻段報告：Welch 平均週期圖（Hann、8192 點、50% 重疊，與 scipy.signal.welch 相同）
 * 用在：手機網頁工具（即時播放用 IIRFilterNode、離線處理用 process()），以及之後的 APK。
 *
 * 不依賴任何套件；瀏覽器載入後是 window.TinnitusDSP，Node 下是 module.exports。
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.TinnitusDSP = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const SCHEMA = "tinnitus-profile/1";
  const EARS = ["left", "right"];
  const MODES = ["notch", "boost", "off"];
  const DEFAULT_EAR = { mode: "off", center_hz: 4000, width_oct: 1.0, order: 6, boost_db: 6.0 };
  const DEFAULT_OUTPUT = { target_lufs: -23.0, peak_ceiling_db: -1.0, fade_in_s: 2.0, fade_out_s: 3.0 };
  const EAR_NAME = { left: "左耳", right: "右耳" };
  const MODE_NAME = { notch: "缺口", boost: "補強", off: "不處理" };

  // ═══════════════════════ 設定檔 ═══════════════════════
  function defaultProfile() {
    return {
      schema: SCHEMA, name: "未命名",
      ears: { left: Object.assign({}, DEFAULT_EAR), right: Object.assign({}, DEFAULT_EAR) },
      output: Object.assign({}, DEFAULT_OUTPUT),
    };
  }

  function makeProfile(left, right, name, output) {
    const p = defaultProfile();
    p.name = name || "自訂";
    if (left) Object.assign(p.ears.left, left);
    if (right) Object.assign(p.ears.right, right);
    if (output) Object.assign(p.output, output);
    return validateProfile(p);
  }

  function num(v, field) {
    const n = Number(v);
    if (!Number.isFinite(n)) throw new Error(`${field} 必須是數字，收到 ${JSON.stringify(v)}`);
    return n;
  }

  /** 補齊缺漏欄位、檢查範圍。不合法丟出 Error（訊息與 Python 版相同）。 */
  function validateProfile(p) {
    if (!p || typeof p !== "object" || Array.isArray(p)) throw new Error("設定檔必須是 JSON 物件");
    const schema = p.schema === undefined ? SCHEMA : p.schema;
    if (schema !== SCHEMA) throw new Error(`不支援的設定檔版本：${schema}（需要 ${SCHEMA}）`);
    const out = defaultProfile();
    out.name = String(p.name === undefined ? out.name : p.name);
    const ears = p.ears || {};
    for (const e of EARS) {
      const src = ears[e] || {};
      const d = out.ears[e];
      for (const k of Object.keys(DEFAULT_EAR)) if (k in src) d[k] = src[k];
      if (!MODES.includes(d.mode)) throw new Error(`${e}.mode 必須是 notch / boost / off 其中之一，收到 ${JSON.stringify(d.mode)}`);
      d.center_hz = num(d.center_hz, `${e}.center_hz`);
      d.width_oct = num(d.width_oct, `${e}.width_oct`);
      d.order = Math.trunc(num(d.order, `${e}.order`));
      d.boost_db = num(d.boost_db, `${e}.boost_db`);
      if (!(d.center_hz >= 200 && d.center_hz <= 16000)) throw new Error(`${e}.center_hz 要在 200–16000 Hz 之間，收到 ${d.center_hz}`);
      if (!(d.width_oct >= 0.25 && d.width_oct <= 2.0)) throw new Error(`${e}.width_oct 要在 0.25–2.0 之間，收到 ${d.width_oct}`);
      if (!(d.order >= 2 && d.order <= 10)) throw new Error(`${e}.order 要在 2–10 之間，收到 ${d.order}`);
      if (!(d.boost_db >= 0 && d.boost_db <= 12)) throw new Error(`${e}.boost_db 要在 0–12 dB 之間，收到 ${d.boost_db}`);
    }
    const o = p.output || {};
    for (const k of Object.keys(DEFAULT_OUTPUT)) if (k in o) out.output[k] = num(o[k], `output.${k}`);
    if (!(out.output.target_lufs >= -40 && out.output.target_lufs <= -10)) throw new Error("output.target_lufs 要在 -40 到 -10 之間");
    if (!(out.output.peak_ceiling_db >= -12 && out.output.peak_ceiling_db <= 0)) throw new Error("output.peak_ceiling_db 要在 -12 到 0 之間");
    return out;
  }

  function parseProfile(text) {
    let obj;
    try { obj = JSON.parse(text); } catch (e) { throw new Error("不是有效的 JSON：" + e.message); }
    return validateProfile(obj);
  }

  function describeProfile(p) {
    return EARS.map((e) => {
      const d = p.ears[e];
      return d.mode === "off" ? `${EAR_NAME[e]}：關` : `${EAR_NAME[e]}：${MODE_NAME[d.mode]} ${Math.round(d.center_hz)} Hz`;
    }).join("｜");
  }

  /** 回傳 [lo, hi, clamped] */
  function bandEdges(centerHz, widthOct, fs) {
    const lo = centerHz / Math.pow(2, widthOct / 2);
    const hi = centerHz * Math.pow(2, widthOct / 2);
    const hiMax = 0.475 * fs;
    return [Math.max(lo, 20), Math.min(hi, hiMax), hi > hiMax];
  }

  // ═══════════════════════ 濾波器設計 ═══════════════════════
  // 複數小工具
  const C = {
    add: (a, b) => [a[0] + b[0], a[1] + b[1]],
    sub: (a, b) => [a[0] - b[0], a[1] - b[1]],
    mul: (a, b) => [a[0] * b[0] - a[1] * b[1], a[0] * b[1] + a[1] * b[0]],
    div: (a, b) => { const d = b[0] * b[0] + b[1] * b[1]; return [(a[0] * b[0] + a[1] * b[1]) / d, (a[1] * b[0] - a[0] * b[1]) / d]; },
    sqrt: (a) => { // 主值平方根，與 Python complex ** 0.5 一致
      const r = Math.hypot(a[0], a[1]);
      if (r === 0) return [0, 0];
      const t = Math.atan2(a[1], a[0]) / 2, s = Math.sqrt(r);
      return [s * Math.cos(t), s * Math.sin(t)];
    },
    scale: (a, k) => [a[0] * k, a[1] * k],
    abs: (a) => Math.hypot(a[0], a[1]),
  };

  /** Butterworth 帶阻。order = 低通原型階數 → order 個二階段。每列 [b0,b1,b2,1,a1,a2] */
  function designBandstopSos(fs, lo, hi, order) {
    if (!(lo > 0 && lo < hi && hi < fs / 2)) throw new Error(`頻段不合法：lo=${lo.toFixed(1)}, hi=${hi.toFixed(1)}, fs=${fs}`);
    const k2 = 2 * fs;
    const w1 = k2 * Math.tan(Math.PI * lo / fs);
    const w2 = k2 * Math.tan(Math.PI * hi / fs);
    const w0 = Math.sqrt(w1 * w2);
    const bw = w2 - w1;
    const n = order;
    const zp = [];
    for (let k = 1; k <= n; k++) {
      const ang = Math.PI * (2 * k + n - 1) / (2 * n);
      const p = [Math.cos(ang), Math.sin(ang)];
      // p s² − bw s + p w0² = 0
      const disc = C.sub([bw * bw, 0], C.scale(C.mul(p, p), 4 * w0 * w0));
      const r = C.sqrt(disc);
      const twoP = C.scale(p, 2);
      for (const s of [C.div(C.add([bw, 0], r), twoP), C.div(C.sub([bw, 0], r), twoP)]) {
        zp.push(C.div(C.add([k2, 0], s), C.sub([k2, 0], s)));
      }
    }
    const om0 = 2 * Math.atan(w0 / k2);
    const b = [1, -2 * Math.cos(om0), 1];
    const sections = [];
    for (const z of zp) if (z[1] > 1e-12) sections.push([1, -2 * z[0], C.abs(z) ** 2]);
    const real = zp.filter((z) => Math.abs(z[1]) <= 1e-12).map((z) => z[0]).sort((a, c) => a - c);
    for (let i = 0; i + 1 < real.length; i += 2) sections.push([1, -(real[i] + real[i + 1]), real[i] * real[i + 1]]);
    sections.sort((a, c) => a[2] - c[2]);
    return sections.map((a) => {
      const g = (a[0] + a[1] + a[2]) / (b[0] + b[1] + b[2]);
      return [b[0] * g, b[1] * g, b[2] * g, a[0], a[1], a[2]];
    });
  }

  /** RBJ peaking EQ，單一二階段 */
  function designPeakingSos(fs, centerHz, widthOct, gainDb) {
    const A = Math.pow(10, gainDb / 40);
    const w = 2 * Math.PI * centerHz / fs;
    const q = Math.sqrt(Math.pow(2, widthOct)) / (Math.pow(2, widthOct) - 1);
    const alpha = Math.sin(w) / (2 * q);
    const c = Math.cos(w);
    const b = [1 + alpha * A, -2 * c, 1 - alpha * A];
    const a = [1 + alpha / A, -2 * c, 1 - alpha / A];
    return [[b[0] / a[0], b[1] / a[0], b[2] / a[0], 1, a[1] / a[0], a[2] / a[0]]];
  }

  /** 回傳 { sos: 陣列或 null, lo, hi, clamped } */
  function designEar(fs, ear) {
    if (ear.mode === "off") return { sos: null };
    const [lo, hi, clamped] = bandEdges(ear.center_hz, ear.width_oct, fs);
    const sos = ear.mode === "notch"
      ? designBandstopSos(fs, lo, hi, ear.order)
      : designPeakingSos(fs, ear.center_hz, ear.width_oct, ear.boost_db);
    return { sos, lo, hi, clamped };
  }

  function sosResponseDb(sos, fs, freqs) {
    return freqs.map((f) => {
      const w = 2 * Math.PI * f / fs;
      const z1 = [Math.cos(-w), Math.sin(-w)], z2 = [Math.cos(-2 * w), Math.sin(-2 * w)];
      let h = [1, 0];
      for (const [b0, b1, b2, a0, a1, a2] of sos) {
        const num_ = C.add(C.add([b0, 0], C.scale(z1, b1)), C.scale(z2, b2));
        const den = C.add(C.add([a0, 0], C.scale(z1, a1)), C.scale(z2, a2));
        h = C.mul(h, C.div(num_, den));
      }
      return 20 * Math.log10(Math.max(C.abs(h), 1e-12));
    });
  }

  // ═══════════════════════ 濾波執行 ═══════════════════════
  /** 與 scipy.signal.sosfilt 相同（DF2T、初始狀態 0）。回傳新的 Float64Array。 */
  function sosfilt(sos, x) {
    let y = Float64Array.from(x);
    for (const [b0, b1, b2, , a1, a2] of sos) {
      let z1 = 0, z2 = 0;
      for (let i = 0; i < y.length; i++) {
        const xi = y[i];
        const yi = b0 * xi + z1;
        z1 = b1 * xi - a1 * yi + z2;
        z2 = b2 * xi - a2 * yi;
        y[i] = yi;
      }
    }
    return y;
  }

  /** 與 scipy.signal.lfilter(b, a, x) 相同（單一二階段，a 已正規化） */
  function biquad(b, a, x) {
    return sosfilt([[b[0], b[1], b[2], 1, a[1], a[2]]], x);
  }

  // ═══════════════════════ 頻譜（Welch） ═══════════════════════
  function fftInPlace(re, im) {
    const n = re.length;
    for (let i = 1, j = 0; i < n; i++) {
      let bit = n >> 1;
      for (; j & bit; bit >>= 1) j ^= bit;
      j ^= bit;
      if (i < j) { let t = re[i]; re[i] = re[j]; re[j] = t; t = im[i]; im[i] = im[j]; im[j] = t; }
    }
    for (let len = 2; len <= n; len <<= 1) {
      const ang = -2 * Math.PI / len, wr = Math.cos(ang), wi = Math.sin(ang);
      for (let i = 0; i < n; i += len) {
        let cr = 1, ci = 0;
        for (let j = 0; j < len / 2; j++) {
          const a = i + j, b = a + len / 2;
          const tr = re[b] * cr - im[b] * ci, ti = re[b] * ci + im[b] * cr;
          re[b] = re[a] - tr; im[b] = im[a] - ti; re[a] += tr; im[a] += ti;
          const ncr = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = ncr;
        }
      }
    }
  }

  /**
   * Welch PSD（相對值即可，比例與 scipy 相同）。回傳 { f: Float64Array, p: Float64Array }
   * nperseg = min(len, 8192)；長度不是 2 的冪次時改用離散傅立葉的直接計算（只會發生在很短的片段）。
   */
  function welch(x, fs) {
    const nper = Math.min(x.length, 8192);
    const step = nper - Math.floor(nper / 2);
    const nfreq = Math.floor(nper / 2) + 1;
    const win = new Float64Array(nper);
    for (let i = 0; i < nper; i++) win[i] = 0.5 - 0.5 * Math.cos(2 * Math.PI * i / nper); // 週期 Hann
    const p = new Float64Array(nfreq);
    const pow2 = (nper & (nper - 1)) === 0;
    let segs = 0;
    const re = new Float64Array(nper), im = new Float64Array(nper);
    for (let start = 0; start + nper <= x.length; start += step) {
      let mean = 0;
      for (let i = 0; i < nper; i++) mean += x[start + i];
      mean /= nper;
      for (let i = 0; i < nper; i++) { re[i] = (x[start + i] - mean) * win[i]; im[i] = 0; }
      if (pow2) fftInPlace(re, im);
      else { // 小片段的 DFT 備援
        const r2 = new Float64Array(nper), i2 = new Float64Array(nper);
        for (let k = 0; k < nfreq; k++) for (let t = 0; t < nper; t++) {
          const a = -2 * Math.PI * k * t / nper; r2[k] += re[t] * Math.cos(a); i2[k] += re[t] * Math.sin(a);
        }
        re.set(r2); im.set(i2);
      }
      for (let k = 0; k < nfreq; k++) {
        let v = re[k] * re[k] + im[k] * im[k];
        if (k !== 0 && !(nper % 2 === 0 && k === nfreq - 1)) v *= 2;
        p[k] += v;
      }
      segs++;
    }
    for (let k = 0; k < nfreq; k++) p[k] /= Math.max(1, segs);
    const f = new Float64Array(nfreq);
    for (let k = 0; k < nfreq; k++) f[k] = k * fs / nper;
    return { f, p };
  }

  function bandEnergy(psd, lo, hi) {
    let band = 1e-20, total = 1e-20;
    for (let k = 0; k < psd.f.length; k++) {
      total += psd.p[k];
      if (psd.f[k] >= lo && psd.f[k] <= hi) band += psd.p[k];
    }
    return [band, total];
  }

  // ═══════════════════════ 響度（BS.1770，與 pyloudnorm 相同） ═══════════════════════
  function kWeightingCoeffs(rate) {
    function gen(G, Q, fc, type) {
      const A = Math.pow(10, G / 40), w0 = 2 * Math.PI * (fc / rate), alpha = Math.sin(w0) / (2 * Q);
      const cw = Math.cos(w0), sA = Math.sqrt(A);
      let b, a;
      if (type === "high_shelf") {
        b = [A * ((A + 1) + (A - 1) * cw + 2 * sA * alpha), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - 2 * sA * alpha)];
        a = [(A + 1) - (A - 1) * cw + 2 * sA * alpha, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - 2 * sA * alpha];
      } else {
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2];
        a = [1 + alpha, -2 * cw, 1 - alpha];
      }
      return { b: b.map((v) => v / a[0]), a: a.map((v) => v / a[0]) };
    }
    return [gen(4.0, 1 / Math.sqrt(2), 1500.0, "high_shelf"), gen(0.0, 0.5, 38.0, "high_pass")];
  }

  function integratedLoudness(channels, rate) {
    const G = [1.0, 1.0, 1.0, 1.41, 1.41];
    const Tg = 0.4, step = 0.25, gammaA = -70;
    const filt = kWeightingCoeffs(rate);
    const data = channels.map((ch) => { let y = ch; for (const s of filt) y = biquad(s.b, s.a, y); return y; });
    const nS = channels[0].length;
    const T = nS / rate;
    // Python round() 為銀行家捨入；這裡模擬 np.round
    const raw = (T - Tg) / (Tg * step);
    const fl = Math.floor(raw), frac = raw - fl;
    const rounded = frac > 0.5 ? fl + 1 : frac < 0.5 ? fl : (fl % 2 === 0 ? fl : fl + 1);
    const nBlocks = rounded + 1;
    const z = data.map(() => new Float64Array(nBlocks));
    data.forEach((ch, i) => {
      for (let j = 0; j < nBlocks; j++) {
        const l = Math.trunc(Tg * (j * step) * rate), u = Math.min(Math.trunc(Tg * (j * step + 1) * rate), nS);
        let s = 0;
        for (let k = l; k < u; k++) s += ch[k] * ch[k];
        z[i][j] = s / (Tg * rate);
      }
    });
    const lj = [];
    for (let j = 0; j < nBlocks; j++) {
      let s = 0;
      for (let i = 0; i < data.length; i++) s += G[i] * z[i][j];
      lj.push(-0.691 + 10 * Math.log10(s));
    }
    const meanOver = (idx) => data.map((_, i) => idx.length ? idx.reduce((acc, j) => acc + z[i][j], 0) / idx.length : NaN);
    let J = lj.map((v, j) => (v >= gammaA ? j : -1)).filter((j) => j >= 0);
    let zg = meanOver(J);
    const gammaR = -0.691 + 10 * Math.log10(zg.reduce((acc, v, i) => acc + G[i] * v, 0)) - 10;
    J = lj.map((v, j) => (v > gammaR && v > gammaA ? j : -1)).filter((j) => j >= 0);
    zg = meanOver(J).map((v) => (Number.isNaN(v) ? 0 : v));
    return -0.691 + 10 * Math.log10(zg.reduce((acc, v, i) => acc + G[i] * v, 0));
  }

  function loudness(channels, rate) {
    if (channels[0].length / rate >= 0.4) {
      const v = integratedLoudness(channels, rate);
      if (Number.isFinite(v)) return [v, "ITU-R BS.1770"];
    }
    let s = 0, n = 0;
    for (const ch of channels) { for (let i = 0; i < ch.length; i++) s += ch[i] * ch[i]; n += ch.length; }
    return [20 * Math.log10(Math.sqrt(s / n + 1e-20)) - 0.691, "RMS 近似"];
  }

  // ═══════════════════════ 處理 ═══════════════════════
  /**
   * channels：Float32Array 或 Float64Array 的陣列（每個聲道一個）
   * 回傳 { channels: Float32Array[], report }
   * opts.onProgress(0..1)：選用，長時間處理時回報進度
   */
  function process(channelsIn, sr, profile, opts) {
    opts = opts || {};
    const normalize = opts.normalize !== false;
    const tick = opts.onProgress || (() => {});
    const p = validateProfile(profile);
    let x = channelsIn.map((c) => Float64Array.from(c));
    const chIn = x.length;
    const active = EARS.filter((e) => p.ears[e].mode !== "off");
    if (chIn === 1 && active.length) x = [x[0], Float64Array.from(x[0])];
    const y = x.map((c) => Float64Array.from(c));
    const rep = { sample_rate: sr, channels_in: chIn, duration_s: x[0].length / sr, ears: [], input_lufs: null, output_lufs: null, gain_db: 0, peak_limited: false, loudness_method: "", warnings: [] };
    if (chIn > 2) rep.warnings.push(`輸入有 ${chIn} 個聲道，只處理前兩個（左、右）。`);

    EARS.forEach((e, idx) => {
      const ear = p.ears[e];
      const er = { ear: e, mode: ear.mode, center_hz: ear.center_hz, width_oct: ear.width_oct, band_lo: 0, band_hi: 0, band_share_db: 0, band_drop_db: 0, core_drop_db: 0, warnings: [] };
      const d = designEar(sr, ear);
      if (d.sos && idx < x.length) {
        er.band_lo = d.lo; er.band_hi = d.hi;
        if (d.clamped) er.warnings.push(`頻段上緣超過取樣率允許的範圍，已截在 ${Math.round(er.band_hi)} Hz。`);
        y[idx] = sosfilt(d.sos, x[idx]);
        tick(0.15 + idx * 0.35);
        const p0 = welch(x[idx], sr), p1 = welch(y[idx], sr);
        const [b0, t0] = bandEnergy(p0, er.band_lo, er.band_hi);
        const [b1] = bandEnergy(p1, er.band_lo, er.band_hi);
        er.band_share_db = 10 * Math.log10(b0 / t0);
        er.band_drop_db = 10 * Math.log10(b1 / b0);
        const q = Math.pow(2, ear.width_oct / 4);
        const cLo = Math.max(er.band_lo, ear.center_hz / q), cHi = Math.min(er.band_hi, ear.center_hz * q);
        if (cHi > cLo) {
          const [cb0] = bandEnergy(p0, cLo, cHi), [cb1] = bandEnergy(p1, cLo, cHi);
          er.core_drop_db = 10 * Math.log10(cb1 / cb0);
        }
        if (er.band_share_db < -35) er.warnings.push(`這段聲音在處理頻段內的能量很少（佔總能量 ${Math.round(er.band_share_db)} dB），效果有限，建議改用高頻較豐富的音樂或粉紅噪音。`);
        tick(0.35 + idx * 0.35);
      }
      rep.ears.push(er);
    });

    if (normalize) {
      const o = p.output;
      [rep.input_lufs, rep.loudness_method] = loudness(y, sr);
      let gain = o.target_lufs - rep.input_lufs;
      let k = Math.pow(10, gain / 20);
      let peak = 1e-20;
      for (const c of y) for (let i = 0; i < c.length; i++) { c[i] *= k; const a = Math.abs(c[i]); if (a > peak) peak = a; }
      const ceiling = Math.pow(10, o.peak_ceiling_db / 20);
      if (peak > ceiling) {
        const r = ceiling / peak;
        for (const c of y) for (let i = 0; i < c.length; i++) c[i] *= r;
        gain += 20 * Math.log10(r);
        rep.peak_limited = true;
      }
      rep.gain_db = gain;
      rep.output_lufs = loudness(y, sr)[0];
      const n = y[0].length;
      for (const [out, sec] of [[false, o.fade_in_s], [true, o.fade_out_s]]) {
        const m = Math.trunc(Math.min(Math.floor(n / 2), Math.max(0, sec) * sr));
        if (m <= 1) continue;
        for (let i = 0; i < m; i++) {
          const r = 0.5 - 0.5 * Math.cos(Math.PI * i / (m - 1));      // np.linspace(0, π, m)
          const idx = out ? n - 1 - i : i;                               // 淡出 = 反轉
          for (const c of y) c[idx] *= r;
        }
      }
    }
    tick(1);
    return { channels: y.map((c) => Float32Array.from(c)), report: rep };
  }

  function summary(rep) {
    const L = [`取樣率 ${rep.sample_rate} Hz｜長度 ${rep.duration_s.toFixed(1)} 秒｜輸入 ${rep.channels_in} 聲道`];
    for (const e of rep.ears) {
      if (e.mode === "off") { L.push(`  ${EAR_NAME[e.ear]}：不處理`); continue; }
      L.push(`  ${EAR_NAME[e.ear]}：${MODE_NAME[e.mode]} ${Math.round(e.center_hz)} Hz（${Math.round(e.band_lo)}–${Math.round(e.band_hi)} Hz）｜頻段佔比 ${e.band_share_db.toFixed(1)} dB｜整段 ${sgn(e.band_drop_db)} dB｜中心區 ${sgn(e.core_drop_db)} dB`);
      for (const w of e.warnings) L.push(`    ⚠ ${w}`);
    }
    if (rep.output_lufs !== null) L.push(`  響度 ${rep.input_lufs.toFixed(1)} → ${rep.output_lufs.toFixed(1)} LUFS（${rep.loudness_method}）` + (rep.peak_limited ? "｜已降低增益避免削波" : ""));
    for (const w of rep.warnings) L.push(`  ⚠ ${w}`);
    return L.join("\n");
  }
  function sgn(v) { return (v >= 0 ? "+" : "") + v.toFixed(1); }

  // ═══════════════════════ 檔案輸出 ═══════════════════════
  /** 16-bit PCM WAV */
  function encodeWav16(channels, sr) {
    const nCh = channels.length, n = channels[0].length;
    const buf = new ArrayBuffer(44 + n * nCh * 2);
    const v = new DataView(buf);
    const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
    str(0, "RIFF"); v.setUint32(4, 36 + n * nCh * 2, true); str(8, "WAVE");
    str(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, nCh, true);
    v.setUint32(24, sr, true); v.setUint32(28, sr * nCh * 2, true); v.setUint16(32, nCh * 2, true); v.setUint16(34, 16, true);
    str(36, "data"); v.setUint32(40, n * nCh * 2, true);
    let o = 44;
    for (let i = 0; i < n; i++) for (let c = 0; c < nCh; c++) {
      const s = Math.max(-1, Math.min(1, channels[c][i]));
      v.setInt16(o, s < 0 ? Math.round(s * 32768) : Math.round(s * 32767), true); o += 2;
    }
    return buf;
  }

  let crcTable = null;
  function crc32(u8) {
    if (!crcTable) {
      crcTable = new Uint32Array(256);
      for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; crcTable[n] = c >>> 0; }
    }
    let c = 0xFFFFFFFF;
    for (let i = 0; i < u8.length; i++) c = crcTable[(c ^ u8[i]) & 0xFF] ^ (c >>> 8);
    return (c ^ 0xFFFFFFFF) >>> 0;
  }

  /** 不壓縮的 ZIP（store），用於網頁版只能存 .zip 的情況。files: [{name, data: Uint8Array}] */
  function zipStore(files) {
    const enc = new TextEncoder();
    const parts = [], central = [];
    let offset = 0;
    for (const f of files) {
      const name = enc.encode(f.name), data = f.data instanceof Uint8Array ? f.data : new Uint8Array(f.data);
      const crc = crc32(data);
      const lh = new DataView(new ArrayBuffer(30));
      lh.setUint32(0, 0x04034b50, true); lh.setUint16(4, 20, true); lh.setUint16(6, 0x0800, true); // UTF-8 檔名
      lh.setUint16(8, 0, true); lh.setUint32(14, crc, true); lh.setUint32(18, data.length, true); lh.setUint32(22, data.length, true);
      lh.setUint16(26, name.length, true);
      parts.push(new Uint8Array(lh.buffer), name, data);
      const ch = new DataView(new ArrayBuffer(46));
      ch.setUint32(0, 0x02014b50, true); ch.setUint16(4, 20, true); ch.setUint16(6, 20, true); ch.setUint16(8, 0x0800, true);
      ch.setUint32(16, crc, true); ch.setUint32(20, data.length, true); ch.setUint32(24, data.length, true);
      ch.setUint16(28, name.length, true); ch.setUint32(42, offset, true);
      central.push(new Uint8Array(ch.buffer), name);
      offset += 30 + name.length + data.length;
    }
    const cSize = central.reduce((a, c) => a + c.length, 0);
    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054b50, true); end.setUint16(8, files.length, true); end.setUint16(10, files.length, true);
    end.setUint32(12, cSize, true); end.setUint32(16, offset, true);
    const all = [...parts, ...central, new Uint8Array(end.buffer)];
    if (typeof Blob !== "undefined") return new Blob(all, { type: "application/zip" });
    const outU8 = new Uint8Array(all.reduce((a, c) => a + c.length, 0));
    let pos = 0;
    for (const c of all) { outU8.set(c, pos); pos += c.length; }
    return outU8;
  }

  return {
    SCHEMA, EARS, MODES, DEFAULT_EAR, DEFAULT_OUTPUT,
    defaultProfile, makeProfile, validateProfile, parseProfile, describeProfile, bandEdges,
    designBandstopSos, designPeakingSos, designEar, sosResponseDb,
    sosfilt, welch, integratedLoudness, loudness, process, summary,
    encodeWav16, zipStore, crc32,
  };
});
