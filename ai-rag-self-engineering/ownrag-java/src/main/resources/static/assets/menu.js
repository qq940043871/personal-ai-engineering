/* ownrag 控制台 · 总菜单
 *
 * 这是全站导航的单一事实源：要新增 / 改名 / 调整顺序的菜单，只改下面的 NAV 数组。
 * 每个页面加载后由 renderSidebar() 渲染侧边栏，并依据 <body data-page="..."> 自动高亮当前项。
 *
 * 当前菜单（11 项）：
 *   overview   概览      → /ui/overview
 *   ingest     入库      → /ui/ingest
 *   resources  资源      → /ui/resources（全部已上传文档，向量化在此手动触发）
 *   review     解析复核  → /ui/review
 *   talk       对话      → /ui/talk（产品形态多轮会话，演示用）
 *   chat       问答调试  → /ui/chat
 *   retrieve   检索调试  → /ui/retrieve
 *   kb         知识库    → /ui/kb
 *   evalset    评测集    → /ui/evalset（来源 / 内容 / 好坏，跑检索判定并留证据）
 *   observe    观测      → /ui/observe
 *   plan       14 天路线 → /ui/plan
 *
 * 侧边栏底部另有「账号区」（renderAccount）：登录状态与登出操作在所有页面同一位置，
 * 不随页面跳转丢失——状态本身来自服务端 /auth/me（Cookie 会话），不是前端内存。
 */
'use strict';

const NAV = [
  { id: 'overview',  icon: '◈', label: '概览' },
  { id: 'ingest',    icon: '↥', label: '入库' },
  { id: 'resources', icon: '▦', label: '资源' },
  { id: 'review',    icon: '✓', label: '解析复核' },
  { id: 'talk',      icon: '✧', label: '对话' },
  { id: 'chat',      icon: '✦', label: '问答调试' },
  { id: 'retrieve',  icon: '⌕', label: '检索调试' },
  { id: 'kb',        icon: '▤', label: '知识库' },
  { id: 'evalset',   icon: '⚖', label: '评测集' },
  { id: 'observe',   icon: '◎', label: '观测' },
  { id: 'plan',      icon: '☰', label: '14 天路线' },
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
      <div id="sideUser" class="side-user"><div class="tiny">正在读取登录状态…</div></div>
    </div>`;
  renderAccount();
}

/**
 * 账号区（侧边栏底部）：登录态 + 退出。
 * 数据来自 S.me（app.js boot() 里请求 /auth/me），未拿到时按"未登录"显示——
 * 宁可让已登录用户看到一次登录入口，也不能把"未知"显示成"已登录"。
 */
function renderAccount() {
  const el = $('#sideUser');
  if (!el) return;
  const me = (typeof S !== 'undefined' && S.me) || null;
  if (!me) {
    el.innerHTML = '<div class="tiny">正在读取登录状态…</div>';   // 未知 ≠ 未登录：别先闪一下"未登录"
    return;
  }
  if (me.logged_in) {
    const name = me.display_name || me.username || '已登录';
    el.innerHTML = `
      <div class="who"><i class="dot ok"></i><b title="${esc(name)}">${esc(name)}</b>
        <span class="chip ok tiny">已登录</span></div>
      <div class="tiny">可查询与访问全部文档${me.expires_at ? ' · 会话到期 ' + esc(String(me.expires_at).slice(5, 16)) : ''}</div>
      <button class="btn sm ghost" id="sideLogout">退出登录</button>`;
    const btn = $('#sideLogout');
    if (btn) {
      btn.onclick = async () => {
        if (!(await uiConfirm('退出后只能查看公开文档，需要重新登录才能检索全部。', '退出登录？'))) return;
        try {
          const r = await postJSON('/auth/logout', {});
          toast(r.message || '已退出登录', 'ok');
        } catch (e) {
          toast('退出失败：' + e.message, 'bad');
        }
        // 重新加载而不是本地改状态：让服务端重新裁决每个页面的数据（列表/检索都会变窄）
        setTimeout(() => location.reload(), 320);
      };
    }
    return;
  }
  el.innerHTML = `
    <div class="who"><i class="dot"></i><b>未登录</b><span class="chip warn tiny">仅公开</span></div>
    <div class="tiny">只能查看公开文档；登录后可检索与访问全部文档</div>
    <a class="btn sm primary" href="${esc(loginUrl())}">登录</a>`;
}
