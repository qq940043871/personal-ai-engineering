/* md.js — ownrag-java UI 共享渲染器（零 CDN：KaTeX 已本地内联到 /ui/assets/katex/）
 *
 * 三件事：
 *   1. Markdown → HTML（标题/列表/表格/代码围栏/引用/图片/行内样式），HTML 先转义再变换，防注入
 *   2. 数学公式：先摘出 $$..$$ 与 $..$（连同 \(..\) / \[..\]）做占位保护，
 *      插 DOM 后交给 KaTeX auto-render 排版——避免数学里的 * _ [ ] 被当 Markdown 吃掉
 *   3. 音视频锚点：anchors.t（"mm:ss-mm:ss"）→ 播放器弹层，/source/{docId} 走 Range 流式
 *
 * 用法：
 *   el.innerHTML = Md.render(text, { docId, sourceType });   // resolveImage 依据 docId
 *   Md.typeset(el);                                          // 公式排版（可选，未加载 KaTeX 时静默跳过）
 *   Md.play(docId, '01:20-01:45');                           // 视频弹层
 */
(function () {
  'use strict';

  /* ---------------- 基础工具 ---------------- */
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function fmtTime(sec) {
    sec = Math.max(0, Math.round(sec));
    const m = Math.floor(sec / 60), s = sec % 60;
    return (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
  }

  /** "mm:ss-mm:ss" → [startSec, endSec]；单值也兼容。 */
  function parseT(t) {
    if (!t) return null;
    const parts = String(t).split('-');
    const toSec = (str) => {
      const seg = String(str).trim().split(':').map(Number);
      if (seg.some(isNaN)) return NaN;
      return seg.reduce((acc, v) => acc * 60 + v, 0);
    };
    const a = toSec(parts[0]);
    const b = parts.length > 1 ? toSec(parts[1]) : a + 30;
    if (isNaN(a)) return null;
    return [a, isNaN(b) ? a + 30 : b];
  }

  /* ---------------- 数学占位保护 ---------------- */
  /** 把 $$..$$ / $..$ / \[..\] / \(..\) 摘成占位符，返回 {text, math:[原文]}。 */
  function extractMath(text) {
    const math = [];
    let out = '';
    let i = 0;
    const n = text.length;
    while (i < n) {
      const two = text.slice(i, i + 2);
      if (two === '$$' || two === '\\[') {
        const end = text.indexOf(two === '$$' ? '$$' : '\\]', i + 2);
        const body = end < 0 ? null : text.slice(i + 2, end);
        if (body != null && body.trim()) {
          math.push(two === '$$' ? '$$' + body + '$$' : '\\[' + body + '\\]');
          out += '\u0000M' + (math.length - 1) + '\u0000';
          i = end + 2;
          continue;
        }
      }
      if (text[i] === '$' && text[i + 1] !== '$') {
        // 行内 $..$：找下一个未转义的 $（跳过数字区间如 $100 与 $200 之间的误配太复杂，取最近配对）
        const end = text.indexOf('$', i + 1);
        const body = end > i + 1 ? text.slice(i + 1, end) : null;
        if (body != null && body.trim() && !/^\s/.test(body) && !/\s$/.test(body)) {
          math.push('$' + body + '$');
          out += '\u0000M' + (math.length - 1) + '\u0000';
          i = end + 1;
          continue;
        }
      }
      if (text.slice(i, i + 2) === '\\(') {
        const end = text.indexOf('\\)', i + 2);
        if (end > 0) {
          math.push('\\(' + text.slice(i + 2, end) + '\\)');
          out += '\u0000M' + (math.length - 1) + '\u0000';
          i = end + 2;
          continue;
        }
      }
      out += text[i];
      i += 1;
    }
    return { text: out, math };
  }

  function restoreMath(html, math) {
    return html.replace(/\u0000M(\d+)\u0000/g, (_, idx) => {
      const raw = math[+idx];
      return raw ? '<span class="math-src">' + esc(raw) + '</span>' : '';
    });
  }

  /* ---------------- 代码围栏保护 ---------------- */
  function extractFences(text, state) {
    return text.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, body) => {
      state.fences.push({ lang, body: body.replace(/\n$/, '') });
      return '\u0000F' + (state.fences.length - 1) + '\u0000';
    });
  }

  /* ---------------- 行内变换（输入已转义） ---------------- */
  function inline(text, opts) {
    // 图片：![alt](src) —— 相对路径按 docId 解析到 /media/{docId}/...
    text = text.replace(/!\[([^\]]*)\]\(([^)\s]+)(?:\s+&quot;[^&]*&quot;)?\)/g, (m, alt, src) => {
      const url = opts.resolveImage ? opts.resolveImage(src) : src;
      if (!url) return esc(alt);
      return '<img class="md-img" src="' + esc(url) + '" alt="' + esc(alt) + '" loading="lazy" onclick="Md.zoom(this.src,this.alt)">';
    });
    // 链接 [t](url)
    text = text.replace(/\[([^\]]+)\]\((https?:[^)\s]+|\/[^)\s]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>');
    // 行内代码
    text = text.replace(/`([^`]+)`/g, '<code>$1</code>');
    // 粗体 / 斜体
    text = text.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
    text = text.replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<i>$2</i>');
    return text;
  }

  /* ---------------- 块级结构 ---------------- */
  function blocks(text, opts) {
    const lines = text.split(/\r?\n/);
    const out = [];
    let para = [];
    let list = null;          // 'ul' | 'ol' | null
    let table = null;         // 行缓冲
    let quote = null;

    const flushPara = () => {
      if (para.length) {
        out.push('<p>' + inline(para.join('<br>'), opts) + '</p>');
        para = [];
      }
    };
    const flushList = () => {
      if (list) { out.push('</' + list + '>'); list = null; }
    };
    const flushTable = () => {
      if (table && table.length >= 2) {
        const cells = (row) => row.replace(/^\||\|$/g, '').split('|').map(c => c.trim());
        const head = cells(table[0]);
        // 第二行是分隔行（---）才认成表
        if (/^[\s|:-]+$/.test(table[1])) {
          let html = '<table class="md-table"><thead><tr>'
            + head.map(h => '<th>' + inline(h, opts) + '</th>').join('') + '</tr></thead><tbody>';
          for (let i = 2; i < table.length; i++) {
            html += '<tr>' + cells(table[i]).map(c => '<td>' + inline(c, opts) + '</td>').join('') + '</tr>';
          }
          out.push(html + '</tbody></table>');
          table = null;
          return;
        }
        // 不是表格：按普通段落还回去
        para = table.slice();
        table = null;
        flushPara();
        return;
      }
      if (table && table.length === 1) { para = table.slice(); table = null; flushPara(); }
      else table = null;
    };
    const flushQuote = () => {
      if (quote) { out.push('<blockquote>' + inline(quote.join('<br>'), opts) + '</blockquote>'); quote = null; }
    };
    const flushAll = () => { flushPara(); flushList(); flushTable(); flushQuote(); };

    for (const raw of lines) {
      const line = raw;
      const fence = line.match(/^\u0000F(\d+)\u0000\s*$/);
      if (fence) {
        flushAll();
        const f = opts.state.fences[+fence[1]];
        out.push('<pre class="md-code' + (f.lang ? ' lang-' + esc(f.lang) : '') + '"><code>' + f.body + '</code></pre>');
        continue;
      }
      const h = line.match(/^(#{1,6})\s+(.*)$/);
      if (h) {
        flushAll();
        out.push('<h' + h[1].length + ' class="md-h">' + inline(h[2], opts) + '</h' + h[1].length + '>');
        continue;
      }
      if (/^\s*(---+|\*\*\*+)\s*$/.test(line)) { flushAll(); out.push('<hr class="md-hr">'); continue; }
      const q = line.match(/^&gt;\s?(.*)$/);
      if (q) { flushPara(); flushList(); flushTable(); (quote = quote || []).push(q[1]); continue; }
      const ul = line.match(/^\s*[-*]\s+(.*)$/);
      const ol = line.match(/^\s*\d+[.、)]\s+(.*)$/);
      if (ul || ol) {
        flushPara(); flushTable(); flushQuote();
        const want = ul ? 'ul' : 'ol';
        if (list !== want) { flushList(); out.push('<' + want + ' class="md-list">'); list = want; }
        out.push('<li>' + inline((ul || ol)[1], opts) + '</li>');
        continue;
      }
      if (/^\s*\|.*\|\s*$/.test(line)) {
        flushPara(); flushList(); flushQuote();
        (table = table || []).push(line.trim());
        continue;
      }
      if (line.trim() === '') { flushAll(); continue; }
      flushList(); flushTable(); flushQuote();
      para.push(line);
    }
    flushAll();
    return out.join('\n');
  }

  /* ---------------- 对外主入口 ---------------- */
  /**
   * render(text, opts)
   * opts.docId        —— 相对图片引用解析到 /media/{docId}/...
   * opts.resolveImage —— 自定义解析函数（默认按 docId 规则）
   */
  function render(text, opts) {
    opts = opts || {};
    if (text == null) return '<div class="empty">（空）</div>';
    if (!opts.resolveImage && opts.docId) {
      opts.resolveImage = defaultResolveImage(opts.docId);  // 相对图片引用 → /media/{docId}/...
    }
    text = String(text);
    // MinerU 转义约定：文本里的 \$ 与 \_ 是字面量。还原后 KaTeX 才能把
    // \$E\_k = \frac{1}{2}mv^2\$ 这类被转义包裹的公式正确配对排版
    text = text.replace(/\\([$_])/g, '$1');
    const state = { fences: [] };
    const extracted = extractMath(text);
    let t = extracted.text;
    t = extractFences(t, state);
    t = esc(t);
    opts.state = state;
    // 注意：extractMath 返回 {text, math} 包装对象，占位符还原必须用 math 数组本身
    let html = restoreMath(blocks(t, opts), extracted.math);
    // 围栏占位还原（blocks 已生成 pre，占位符若仍在行内则兜底还原）
    html = html.replace(/\u0000F(\d+)\u0000/g, (_, idx) => {
      const f = state.fences[+idx];
      return f ? '<pre class="md-code"><code>' + f.body + '</code></pre>' : '';
    });
    return html;
  }

  /** 默认图片解析：相对路径 → /media/{docId}/...；http(s)/绝对路径原样。 */
  function defaultResolveImage(docId) {
    return (src) => {
      if (/^(https?:|data:|\/)/i.test(src)) return src;
      if (!docId) return src;
      return '/media/' + encodeURIComponent(docId) + '/' + src.split('/').map(encodeURIComponent).join('/');
    };
  }

  /* ---------------- KaTeX 排版 ---------------- */
  function typeset(el) {
    if (!el || typeof window.renderMathInElement !== 'function') return;
    try {
      window.renderMathInElement(el, {
        delimiters: [
          { left: '$$', right: '$$', display: true },
          { left: '\\[', right: '\\]', display: true },
          { left: '\\(', right: '\\)', display: false },
          { left: '$', right: '$', display: false }
        ],
        ignoredTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'],
        throwOnError: false
      });
    } catch (e) { /* 公式排版失败不阻塞正文展示 */ }
  }

  /* ---------------- 播放器弹层（视频/音频 + 时间锚点） ---------------- */
  function ensureOverlay() {
    let ov = document.getElementById('md-overlay');
    if (ov) return ov;
    ov = document.createElement('div');
    ov.id = 'md-overlay';
    ov.style.cssText = 'position:fixed;inset:0;background:rgba(10,12,16,.86);z-index:999;'
      + 'display:none;align-items:center;justify-content:center;flex-direction:column;gap:10px;';
    ov.addEventListener('click', (e) => { if (e.target === ov) Md.close(); });
    document.body.appendChild(ov);
    return ov;
  }

  /**
   * play(docId, t)：打开播放器弹层。
   * t 形如 "01:20-01:45"（块锚）或 "01:20"（帧/段锚）；起始秒定位，结束秒到点暂停。
   */
  function play(docId, t) {
    const range = parseT(t) || [0, null];
    const isAudio = false; // 形态由浏览器按 source 内容自决（video 元素可播纯音频）
    const ov = ensureOverlay();
    const endAttr = range[1] != null ? '#t=' + range[0] + ',' + range[1] : '#t=' + range[0];
    ov.innerHTML =
      '<div style="color:#cfd8e3;font:12px/1.6 ui-monospace,monospace">'
      + esc(docId) + ' @ ' + esc(t || '00:00') + '</div>'
      + '<video id="md-player" controls autoplay style="max-width:86vw;max-height:72vh;'
      + (isAudio ? 'width:520px;' : '') + 'background:#000;border-radius:8px"'
      + ' src="/source/' + encodeURIComponent(docId) + endAttr + '"></video>'
      + '<div><button class="btn sm" onclick="Md.close()">关闭</button></div>';
    ov.style.display = 'flex';
    if (range[1] != null) {
      const v = ov.querySelector('video');
      const stop = () => { if (v.currentTime >= range[1]) { v.pause(); v.removeEventListener('timeupdate', stop); } };
      v.addEventListener('timeupdate', stop);
    }
  }

  function close() {
    const ov = document.getElementById('md-overlay');
    if (ov) { ov.style.display = 'none'; ov.innerHTML = ''; }
  }

  /** 图片放大弹层。 */
  function zoom(src, alt) {
    const ov = ensureOverlay();
    ov.innerHTML = '<img src="' + esc(src) + '" alt="' + esc(alt || '') + '"'
      + ' style="max-width:92vw;max-height:86vh;border-radius:8px;background:#fff">'
      + '<div><button class="btn sm" onclick="Md.close()">关闭</button></div>';
    ov.style.display = 'flex';
  }

  /** 块锚点播放按钮 HTML（供 kb/chat 页拼装）。 */
  function playBtn(docId, t, label) {
    if (!t || !docId) return '';
    return '<button class="btn sm" onclick="Md.play(\'' + esc(docId) + '\',\'' + esc(t) + '\')" title="回跳源视频">'
      + esc(label || '▶ ' + t) + '</button>';
  }

  /* ---------------- 挂载 ---------------- */
  window.Md = {
    render, esc, typeset, play, close, zoom, playBtn, parseT, fmtTime,
    resolveImage: defaultResolveImage
  };
})();
