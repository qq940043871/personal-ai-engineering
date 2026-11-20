/* ownrag 控制台 · 共享脚本：工具函数 / API / 全局状态 / 跨页导航 / 启动 */
'use strict';

/* ================= 基础工具 ================= */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = (n) => (typeof n === 'number' ? n.toLocaleString('zh-CN') : n);
const shortId = (s) => (s ? String(s).slice(0, 10) : '');
const shortPath = (p) => p ? p.replace(/^.*[\\/](?=[^\\/]+[\\/][^\\/]+$)/, '…/') : '—';
function toast(msg, kind = '') {
  const t = $('#toast');
  if (!t) return;
  const d = document.createElement('div');
  d.className = kind; d.textContent = msg;
  t.appendChild(d);
  setTimeout(() => d.remove(), 4200);
}
async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  const text = await res.text();
  let data; try { data = text ? JSON.parse(text) : {}; } catch { data = { raw: text }; }
  if (!res.ok) throw new Error((data && (data.detail || data.raw)) || (res.status + ' ' + res.statusText));
  return data;
}
const postJSON = (path, body) => api(path, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
});

/* SSE：POST + ReadableStream 手写解析（EventSource 只支持 GET） */
async function sse(path, body, onEvent, signal) {
  const res = await fetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body), signal
  });
  if (!res.ok) throw new Error(res.status + ' ' + (await res.text()).slice(0, 300));
  const reader = res.body.getReader(), dec = new TextDecoder();
  let buf = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const raw = buf.slice(0, i); buf = buf.slice(i + 2);
      let ev = 'message', data = '';
      for (const line of raw.split('\n')) {
        if (line.startsWith('event:')) ev = line.slice(6).trim();
        else if (line.startsWith('data:')) data += line.slice(5).trim();
      }
      if (!data) continue;
      let obj; try { obj = JSON.parse(data); } catch { obj = { raw: data }; }
      onEvent(ev, obj);
    }
  }
}

/* ================= 全局状态 ================= */
const S = { config: null, health: null, kbs: [], apps: [], poll: null };

/* ================= 14 天路线（侧边栏进度 + plan 页共用） ================= */
const PLAN_KEY = 'ownrag.plan.v1';
const PLAN = [
  { d: 1, t: '起服务，跑通最小闭环', goal: '把"能跑"变成"我看得见每一步"：起服务 → 上传 CSV → 7 个步骤全 ok。',
    todo: ['读 README 的快速开始，用 restart.ps1 起服务', '打开 /ui，确认顶部 LLM / embed / 步骤注册 / kb 几个灯', '上传一份 CSV，展开任务详情，逐个念出步骤名'],
    check: '能按顺序说出 excel_v1 的 7 步，以及每步产出什么。', tab: 'ingest' },
  { d: 2, t: '解析链路 A：PDF 与降级链', goal: '理解"解析失败不是任务失败"：看 MinerU 缺失如何降级到 pymupdf。',
    todo: ['上传一份 PDF，看 trace 里 parse_mineru fail → fallback → pymupdf ok', '对比 parsed 的 metadata.degraded 与 anchors.page', '打开 /admin/chunks 看这块正文里的页码锚点'],
    check: '能解释 fallback 链的三层，以及降级后丢了什么结构信息。', tab: 'ingest' },
  { d: 3, t: '解析链路 B/C：音视频与 Excel', goal: 'Excel 走 staging 表、音视频走时间锚点——两条链路为何不能共用 PDF 的做法。',
    todo: ['上传 xlsx，看 excel_stage 生成的 staging_* 表名与 schema_infer 的列类型', '看 textualize 的 row_card：为什么不是把表格塞进 prompt', '没有 ffmpeg 时上传音频，确认失败进了待办'],
    check: '能说清 row_card 与 aggregate 的分工（数字来自 SQL，不来自向量）。', tab: 'ingest' },
  { d: 4, t: '切分：决定检索天花板', goal: '看懂 chunker 的三条硬规则：标题路径、表格不跨块、块头增强。',
    todo: ['读 ownrag/index/chunker.py 的 split_segments 与 chunk_markdown', '在知识库页查看块首的「文档标题 > 章节路径」', '把 max_tokens 改小重跑一份文档，观察块数变化'],
    check: '能解释为什么"表格永不跨块"，以及 overlap 只在段落间生效的原因。', tab: 'kb' },
  { d: 5, t: '关键词通道：FTS5 + 中文按字切分', goal: '亲眼看到 CJK 不分词的问题，以及字符化兜底的代价。',
    todo: ['在知识库页用 q=报销 与 q=报销口径 分别搜', '对比命中数：为什么更长的词反而更难命中', '读 store.py 的 _fts_cjk，理解"索引与查询两侧必须同函数"'],
    check: '能解释 bm25 分数为什么取负、OR 回退为什么精度会掉。', tab: 'kb' },
  { d: 6, t: '向量通道：装与不装是两种系统', goal: '同一次检索，比较 vector=skipped 与 vector 有命中的差别。',
    todo: ['检索调试页先跑一次（chromadb 未装 / Ollama 未起），记下 channels.vector 与提示', '装 chromadb、拉 bge-m3 后再跑，对比两路命中', '看 metrics 里 embed_version 分布'],
    check: '能说清丢向量通道后，哪类问题最先退化（同义改写、跨表述）。', tab: 'retrieve' },
  { d: 7, t: '混合与 RRF：不比分数只比名次', goal: '手算一次 RRF，理解为什么不需要归一化两路分数。',
    todo: ['检索调试页看两路原始命中与 rrf 值', '挑一个块，按 1/(60+rank) 手算两路贡献并核对', '改 k（代码里 rrf_fuse 的 k）观察名次变化'],
    check: '能解释 RRF 的假设与失效场景（两路都错时无法救回）。', tab: 'retrieve' },
  { d: 8, t: 'rerank：为什么还要第二道排序', goal: '区分 bi-encoder 召回与 cross-encoder 重排的分工。',
    todo: ['检索调试页看 rerank 未启用时的 note 与顺序', '起 bge-reranker 服务并配 OWNRAG_RERANK_URL，再跑同一问题', '对比 rerank_score 与 rrf 的排序差异'],
    check: '能解释 rerank 为什么不能替代召回，以及延迟代价。', tab: 'retrieve' },
  { d: 9, t: 'Prompt 与引用格式', goal: '让模型只依据资料回答，是可验证的约束而不是愿望。',
    todo: ['读 ownrag/configs/prompts/policy_strict_v1.yaml 的四条规则', '问答页问一个资料里没有的问题，看模型是否拒答', '把规则 2 删掉再问，观察闸门二抓什么'],
    check: '能说明为什么"只靠 prompt 约束不够"，闸门必须存在。', tab: 'chat' },
  { d: 10, t: '两道闸门：把模型会错变成规则', goal: '生成前卡候选、生成后卡引用与数字。',
    todo: ['问答页看 gate:post 的 passed/reason/violations', '故意构造"数字无引用"的问题看 violations', '读 generate/gates.py 的 citation_check 三分支'],
    check: '能解释假引用（块9）与数字幻觉分别怎么被抓到。', tab: 'chat' },
  { d: 11, t: '上下文预算：num_ctx 是输入+输出', goal: '看到"超窗先截问题"的风险被显式化。',
    todo: ['设 OWNRAG_NUM_CTX=700、OWNRAG_MAX_NEW_TOKENS=600 重启', '问答页观察 gate:context_budget 的 kept/dropped/truncated', '检索调试页看预算条与 dropped_ids'],
    check: '能写出预算公式，并解释为什么要给输出预留空间。', tab: 'chat' },
  { d: 12, t: '失败归因：10 分钟定位', goal: '任何一次"答案不对"，都能回答：召回了什么、模型看到什么、闸门放过什么。',
    todo: ['制造一次失败（传坏文件 / 断网），从待办点重试', '用 trace_id 在观测页复盘每一步耗时与计数', '对照 qa_log 的 hit_chunks 与 trace 的 counters'],
    check: '能在 10 分钟内给出"错在解析/切分/召回/生成/闸门"的结论与证据。', tab: 'observe' },
  { d: 13, t: '评测：先立分母再谈优化', goal: '没有评测集的调参都是猜——用 20 条问答把命中率变成数字。',
    todo: ['造 data/eval/qa.jsonl（question + expect 关键词）', '跑 scripts/eval_recall.py，记录 hit_rate', '改切分参数再跑，比较两次数字'],
    check: '能解释"命中率提升但答案变差"的可能原因（召回≠正确）。', tab: 'observe' },
  { d: 14, t: '复盘与压测：把工程讲成一张图', goal: '能画出数据流并指出瓶颈，才算真搞明白。',
    todo: ['画一张图：上传→解析→切分→双通道→RRF→rerank→预算→闸门→生成', '用 10 个问题批量跑检索，记录 P50/P95 耗时', '列出 3 个瓶颈与对应 M2 改进项'],
    check: '能对着图讲 5 分钟，且每个环节都有页面证据。', tab: 'plan' }
];
function planState() {
  try { return JSON.parse(localStorage.getItem(PLAN_KEY) || '{}'); } catch { return {}; }
}

/* ================= 跨页导航 ================= */
function goto(page, qs) {
  const seg = page === 'overview' ? 'overview' : page;
  location.href = '/ui/' + seg + (qs ? '?' + qs : '');
}
function openTrace(id) {
  if (!id) return toast('没有 trace_id');
  goto('observe', 'trace=' + encodeURIComponent(id));
}
function openReviewById(id) {
  goto('review', 'doc=' + encodeURIComponent(id));
}

/* ================= 通用渲染 ================= */
function fillSelect(sel, items, value) {
  const el = $(sel); if (!el) return;
  el.innerHTML = items.map(v => `<option value="${esc(v)}"${v === value ? ' selected' : ''}>${esc(v || '（全部）')}</option>`).join('');
}
function renderPills() {
  const h = S.health || {};
  const ollama = h.ollama || {};
  const cb = h.chat_backend || {};
  const eb = h.embed_backend || {};
  // 首灯统一按「生成后端」口径：本地 ollama 与远程 OpenAI 兼容端点（agnes 等）都归 LLM，
  // 不再出现"Ollama 未使用"这种和当前档位无关的告警。
  const ollamaUsed = ollama.used !== false;
  const pills = [
    { t: 'LLM', ok: !!cb.ok,
      d: cb.ok ? (cb.model || cb.provider || '可用')
        : (cb.detail || '不可达') + (cb.provider ? `（${cb.provider}）` : '') },
    { t: 'embed', ok: !eb.breaker_open,
      d: eb.breaker_open ? `熔断 ${eb.retry_in}s` : (ollamaUsed ? 'ollama' : '远程') },
    { t: '步骤注册', ok: !(h.pipeline_missing_steps || []).length, d: (h.steps_registered || []).length + ' 个' },
    { t: 'rerank', ok: !!h.rerank_enabled, d: h.rerank_enabled ? '已配置' : 'RRF 兜底' },
    { t: 'kb', ok: (h.known_kbs || []).length > 0, d: (h.known_kbs || []).join(',') || '未声明' }
  ];
  const pillsEl = $('#pills');
  if (pillsEl) pillsEl.innerHTML = pills.map(p =>
    `<span class="pill" title="${esc(p.d)}"><i class="dot${p.ok === null ? '' : (p.ok ? ' ok' : ' bad')}"></i>${esc(p.t)}<span class="tiny">${esc(p.d)}</span></span>`
  ).join('');
  const sideEnv = $('#sideEnv');
  if (sideEnv) sideEnv.innerHTML = `data: ${esc(shortPath((h.data_dir || '') + ''))}<br>cfg: ${esc(shortPath((h.config_dir || '') + ''))}`;
}
function renderSidebarProgress() {
  const done = PLAN.filter(p => planState()[p.d]).length;
  const n = $('#planN'), bar = $('#planBar');
  if (n) n.textContent = done + '/14';
  if (bar) bar.style.width = (done / 14 * 100) + '%';
}

/* ================= 启动 ================= */
async function boot() {
  renderSidebar();  // 先渲染侧边栏（来自 assets/menu.js），不依赖接口
  try { S.health = await api('/admin/health'); } catch (e) { toast('健康检查失败：' + e.message, 'bad'); }
  try { S.config = await api('/admin/config'); } catch (e) { toast('读取配置失败：' + e.message, 'bad'); }

  const kbs = (S.health && S.health.known_kbs) || [];
  S.kbs = kbs;
  S.apps = Object.keys((S.config && S.config.apps) || {});
  fillSelect('#upKb', kbs, kbs[0]);
  fillSelect('#kbSel', [''].concat(kbs), kbs[0] || '');
  fillSelect('#dhKb', kbs, kbs[0]);
  fillSelect('#retKb', kbs, kbs[0]);
  fillSelect('#chatApp', S.apps, S.apps[0]);
  fillSelect('#retApp', S.apps, S.apps[0]);

  renderPills();
  renderSidebarProgress();
  if (typeof window.pageInit === 'function') window.pageInit();
}

/* 全局：定时刷新健康与待办数 */
setInterval(async () => {
  try { S.health = await api('/admin/health'); renderPills(); } catch {}
}, 20000);
