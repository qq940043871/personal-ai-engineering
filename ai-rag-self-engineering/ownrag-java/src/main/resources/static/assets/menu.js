/* ownrag 控制台 · 总菜单
 *
 * 这是全站导航的单一事实源：要新增 / 改名 / 调整顺序的菜单，只改下面的 NAV 数组。
 * 每个页面加载后由 renderSidebar() 渲染侧边栏，并依据 <body data-page="..."> 自动高亮当前项。
 *
 * 当前菜单（8 项）：
 *   overview  概览      → /ui/overview
 *   ingest    入库      → /ui/ingest
 *   review    解析复核  → /ui/review
 *   chat      问答      → /ui/chat
 *   retrieve  检索调试  → /ui/retrieve
 *   kb        知识库    → /ui/kb
 *   observe   观测      → /ui/observe
 *   plan      14 天路线 → /ui/plan
 */
'use strict';

const NAV = [
  { id: 'overview', icon: '◈', label: '概览' },
  { id: 'ingest',   icon: '↥', label: '入库' },
  { id: 'review',   icon: '✓', label: '解析复核' },
  { id: 'chat',     icon: '✦', label: '问答' },
  { id: 'retrieve', icon: '⌕', label: '检索调试' },
  { id: 'kb',       icon: '▤', label: '知识库' },
  { id: 'observe',  icon: '◎', label: '观测' },
  { id: 'plan',     icon: '☰', label: '14 天路线' },
];

const PAGE = document.body.dataset.page || 'overview';

function renderSidebar() {
  const aside = $('#sidebar');
  if (!aside) return;
  aside.innerHTML = `
    <div class="brand">
      <div class="logo">R</div>
      <div><b>ownrag</b><span>自研 RAG 控制台 · 14 天</span></div>
    </div>
    <nav>${NAV.map(n =>
      `<a href="/ui/${n.id}" class="${n.id === PAGE ? 'on' : ''}"><i>${n.icon}</i>${n.label}</a>`
    ).join('')}</nav>
    <div class="side-foot">
      <div class="flex"><span>学习进度</span><span class="sp"></span><span id="planN">0/14</span></div>
      <div class="progress"><i id="planBar"></i></div>
      <div id="sideEnv" class="tiny mono">…</div>
    </div>`;
}
