/* LinkAI 前端核心：零构建 Vue3 + 原生 JS/CSS */
(function () {
  const { reactive, computed } = Vue;
  const LK = window.LK = {};

  /* ── 自绘内联 SVG 图标（不依赖任何图标字体）── */
  const P = {
    chat: ['M4 5h16v11H9l-5 4V5z', 'M8 9h8', 'M8 12h5'],
    rooms: ['M4 6h16v12H4z', 'M8 6V4h8v2', 'M9 11h6', 'M9 14h4'],
    me: ['M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8z', 'M4 21c0-4 3.5-6 8-6s8 2 8 6'],
    settings: ['M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z', 'M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1-2 3.4-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5v.2h-4v-.2a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1-2-3.4.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H4.7v-4h.2a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1 2-3.4.1.1a1.6 1.6 0 0 0 1.8.3 1.6 1.6 0 0 0 1-1.5V3.8h4v.2a1.6 1.6 0 0 0 1 1.5 1.6 1.6 0 0 0 1.8-.3l.1-.1 2 3.4-.1.1a1.6 1.6 0 0 0-.3 1.8 1.6 1.6 0 0 0 1.5 1h.2v4h-.2a1.6 1.6 0 0 0-1.5 1z'],
    plus: ['M12 5v14', 'M5 12h14'],
    back: ['M15 18l-6-6 6-6'],
    send: ['M4 12l16-8-6 16-3-6-7-2z', 'M11 14l5-6'],
    stop: ['M7 7h10v10H7z'],
    trash: ['M4 7h16', 'M9 7V5h6v2', 'M6 7l1 13h10l1-13', 'M10 11v6', 'M14 11v6'],
    pin: ['M9 4h6l-1 6 4 3v2H6v-2l4-3-1-6z', 'M12 15v5'],
    search: ['M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14z', 'M16 16l4 4'],
    refresh: ['M20 11a8 8 0 1 0-2 6', 'M20 5v6h-6'],
    check: ['M5 12l4 4 10-10'],
    close: ['M6 6l12 12', 'M18 6L6 18'],
    edit: ['M4 20h4l10-10-4-4L4 16v4z', 'M13 7l4 4'],
    link: ['M10 14a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1', 'M14 10a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1'],
    bolt: ['M13 2L5 14h6l-1 8 8-12h-6l1-8z'],
    shield: ['M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z', 'M9 12l2 2 4-4'],
    users: ['M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z', 'M2 20c0-3.5 3-5.5 7-5.5s7 2 7 5.5', 'M16 5a3.5 3.5 0 0 1 0 7', 'M18 15c2.5.5 4 2.5 4 5'],
    chart: ['M4 20V10', 'M10 20V4', 'M16 20v-7', 'M22 20H2'],
    key: ['M15 8a4 4 0 1 1-3 6.5L9 17.5 7.5 16 5.5 18 4 16.5l2-2L4.5 13 6 11.5 9 14.5A4 4 0 0 1 15 8z'],
    globe: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', 'M3 12h18', 'M12 3c3 3 3 15 0 18', 'M12 3c-3 3-3 15 0 18'],
    moon: ['M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z'],
    sun: ['M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10z', 'M12 2v2', 'M12 20v2', 'M4 12H2', 'M22 12h-2', 'M5 5l1.5 1.5', 'M17.5 17.5L19 19', 'M19 5l-1.5 1.5', 'M6.5 17.5L5 19'],
    logout: ['M10 4H5v16h5', 'M14 8l4 4-4 4', 'M18 12H9'],
    copy: ['M8 8h11v12H8z', 'M5 16H4V4h11v1'],
    share: ['M12 16V4', 'M8 8l4-4 4 4', 'M5 14v5h14v-5'],
    download: ['M12 4v11', 'M8 11l4 4 4-4', 'M5 19h14'],
    star: ['M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1-5.4-2.9-5.4 2.9 1-6.1L3.2 9.5l6.1-.9L12 3z'],
    warn: ['M12 3l9 17H3l9-17z', 'M12 10v4', 'M12 17h.01'],
    robot: ['M6 8h12v10H6z', 'M9 8V5h6v3', 'M9 13h.01', 'M15 13h.01', 'M9 16h6', 'M12 3v2'],
    more: ['M6 12h.01', 'M12 12h.01', 'M18 12h.01'],
    filter: ['M4 6h16', 'M7 12h10', 'M10 18h4'],
    clock: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', 'M12 7v5l3 2'],
    spark: ['M12 3l1.6 5.4L19 10l-5.4 1.6L12 17l-1.6-5.4L5 10l5.4-1.6L12 3z'],
  };
  LK.icons = P;
  LK.iconPaths = (n) => P[n] || P.warn;

  /* ── 全局状态 ── */
  const saved = localStorage.getItem('chatroom-token');
  LK.state = reactive({
    token: saved || null, user: null, theme: localStorage.getItem('lk-theme') || 'light',
    models: [], features: {}, quota: null, loading: false,
    toast: null, drawer: null, confirm: null,
    route: location.hash.slice(1) || '/msgs',
  });
  LK.setTheme = (t) => {
    LK.state.theme = t; localStorage.setItem('lk-theme', t);
    document.documentElement.dataset.theme = t;
  };
  LK.setTheme(LK.state.theme);

  /* ── 路由 ── */
  LK.go = (h) => {
    LK.state.route = String(h).replace(/^#/, '') || '/msgs'; // 同步触发响应式重算
    location.hash = h;
  };
  LK.parseRoute = () => {
    const raw = (LK.state.route || location.hash.slice(1) || '/msgs').split('?')[0];
    const parts = raw.split('/').filter(Boolean);
    return { raw, parts, name: parts[0] || 'msgs', id: parts[1] || null, sub: parts[2] || null };
  };
  window.addEventListener('hashchange', () => { LK.state.route = location.hash.slice(1) || '/msgs'; });

  /* ── 请求封装 ── */
  class ApiError extends Error {
    constructor(code, message, status, detail) { super(message); this.code = code; this.status = status; this.detail = detail; }
  }
  LK.ApiError = ApiError;
  LK.api = async (path, opts = {}) => {
    const headers = Object.assign({}, opts.headers || {});
    if (LK.state.token) headers.Authorization = 'Bearer ' + LK.state.token;
    if (opts.body !== undefined) headers['Content-Type'] = 'application/json';
    if (opts.idem) headers['Idempotency-Key'] = opts.idem;
    const resp = await fetch(path, {
      method: opts.method || 'GET', headers,
      body: opts.body === undefined ? undefined : (opts.form ? opts.body : JSON.stringify(opts.body)),
      signal: opts.signal,
    });
    let payload = null;
    try { payload = await resp.json(); } catch (e) { /* 空响应 */ }
    if (!resp.ok) {
      if (resp.status === 401) { LK.logout(true); }
      throw new ApiError(payload?.code || 'INTERNAL', payload?.message || '请求失败', resp.status, payload?.detail);
    }
    return payload?.data;
  };
  LK.logout = (silent) => {
    LK.state.token = null; LK.state.user = null; localStorage.removeItem('chatroom-token');
    if (!silent) LK.api('/api/auth/logout', { method: 'POST' }).catch(() => {});
    LK.go('#/login');
  };
  LK.idem = () => 'k-' + Date.now() + '-' + Math.random().toString(36).slice(2, 9);

  /* ── SSE 流式 ── */
  LK.stream = async (path, body, onEvent, signal) => {
    const resp = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(LK.state.token ? { Authorization: 'Bearer ' + LK.state.token } : {}) },
      body: JSON.stringify(body), signal,
    });
    if (!resp.ok || !resp.body) {
      let msg = '请求失败'; try { msg = (await resp.json()).message || msg; } catch (e) {}
      onEvent('error', { message: msg }); return;
    }
    const reader = resp.body.getReader(), dec = new TextDecoder();
    let buf = '';
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true }).replace(/\r\n/g, '\n');
      const blocks = buf.split('\n\n'); buf = blocks.pop() || '';
      for (const b of blocks) {
        let ev = 'message', data = '';
        for (const line of b.split('\n')) {
          if (line.startsWith('event:')) ev = line.slice(6).trim();
          else if (line.startsWith('data:')) data += line.slice(5).trim();
        }
        if (!data) continue;
        let j = {}; try { j = JSON.parse(data); } catch (e) { continue; }
        onEvent(ev, j);
      }
    }
  };

  /* ── Toast / 抽屉 / 确认 ── */
  let toastTimer = null;
  LK.toast = (message, action) => {
    clearTimeout(toastTimer);
    LK.state.toast = { message, action: action || null };
    toastTimer = setTimeout(() => { LK.state.toast = null; }, action ? 6000 : 3000);
  };
  LK.openDrawer = (title, component, props) => { LK.state.drawer = { title, component, props: props || {} }; };
  LK.closeDrawer = () => { LK.state.drawer = null; };
  LK.confirm = (message, onYes, title) => { LK.state.confirm = { message, onYes, title: title || '请确认' }; };
  LK.closeConfirm = () => { LK.state.confirm = null; };

  LK.fmtTime = (s) => {
    if (!s) return '';
    const d = new Date(s.replace(' ', 'T') + (s.endsWith('Z') ? '' : 'Z'));
    if (isNaN(d)) return s;
    return d.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  };
  LK.err = (e) => e?.message || String(e);

  /* ── 通用组件 ── */
  LK.components = {
    AppIcon: {
      props: { name: String, size: { type: Number, default: 20 } },
      computed: { paths() { return LK.iconPaths(this.name); } },
      template: `<svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path v-for="(d,i) in paths" :key="i" :d="d"/></svg>`,
    },
    NavBar: {
      props: { title: String, back: { type: String, default: '' } },
      methods: { goBack() { this.back ? LK.go(this.back) : history.back(); } },
      template: `<div class="nav">
        <button class="iconbtn" @click="goBack" aria-label="返回"><AppIcon name="back"/></button>
        <h1 class="ellipsis">{{ title }}</h1><slot name="actions"></slot>
      </div>`,
    },
    TabBar: {
      computed: { r() { return LK.parseRoute().name; } },
      template: `<div class="tabbar">
        <a class="tab" :class="{on:r==='msgs'||r==='chat'}" href="#/msgs"><AppIcon name="chat" :size="22"/><span>消息</span></a>
        <a class="tab" :class="{on:r==='rooms'||r==='room'}" href="#/rooms"><AppIcon name="rooms" :size="22"/><span>房间</span></a>
        <a class="tab" :class="{on:r==='me'||r.startsWith('admin')}" href="#/me"><AppIcon name="me" :size="22"/><span>我的</span></a>
      </div>`,
    },
    Avatar: {
      props: { name: String, size: { type: Number, default: 38 } },
      template: `<div class="avatar" :style="{width:size+'px',height:size+'px',borderRadius:Math.round(size/3)+'px'}">{{ (name||'AI').slice(0,1) }}</div>`,
    },
    Switch: {
      props: { modelValue: Boolean },
      template: `<button class="switch" :class="{on:modelValue}" @click="$emit('update:modelValue',!modelValue)" role="switch"><i></i></button>`,
    },
    ProgressBar: {
      props: { value: Number, max: Number, warn: Boolean },
      computed: { pct() { return this.max > 0 ? Math.min(100, Math.round(this.value / this.max * 100)) : 0; } },
      template: `<div class="progress" :class="{warn:warn}"><i :style="{width:pct+'%'}"></i></div>`,
    },
    EmptyState: {
      props: { text: { type: String, default: '这里空空的' }, icon: { type: String, default: 'chat' } },
      template: `<div style="text-align:center;padding:44px 12px;color:var(--sub)"><AppIcon :name="icon" :size="34"/><p style="margin-top:10px">{{ text }}</p></div>`,
    },
    DrawerHost: {
      computed: { d() { return LK.state.drawer; } },
      template: `<div v-if="d" class="mask" @click.self="LK.closeDrawer()"><div class="drawer">
        <div class="between" style="margin-bottom:12px"><h2 style="margin:0">{{ d.title }}</h2>
          <button class="iconbtn" @click="LK.closeDrawer()"><AppIcon name="close"/></button></div>
        <component :is="d.component" v-bind="d.props" @done="LK.closeDrawer()"/>
      </div></div>`,
    },
    ConfirmHost: {
      computed: { c() { return LK.state.confirm; } },
      methods: { yes() { const f = this.c.onYes; LK.closeConfirm(); f && f(); } },
      template: `<div v-if="c" class="mask" @click.self="LK.closeConfirm()"><div class="drawer" style="max-width:380px">
        <h2>{{ c.title }}</h2><p style="margin-bottom:18px;color:var(--sub)">{{ c.message }}</p>
        <div class="row" style="justify-content:flex-end"><button class="btn" @click="LK.closeConfirm()">取消</button>
        <button class="btn primary" @click="yes">确定</button></div>
      </div></div>`,
    },
    ToastHost: {
      computed: { t() { return LK.state.toast; } },
      template: `<div v-if="t" class="toast">{{ t.message }}<span v-if="t.action" class="act" @click="t.action.fn();LK.state.toast=null">{{ t.action.label }}</span></div>`,
    },
  };
})();
