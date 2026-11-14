/* 成员端视图（移动优先） */
(function () {
  const LK = window.LK;
  const V = LK.memberViews = {};

  V.LoginView = {
    data() { return { tab: 'login', account: '', password: '', nickname: '', invite: '', busy: false }; },
    methods: {
      async submit() {
        if (this.busy) return; this.busy = true;
        try {
          const url = this.tab === 'login' ? '/api/auth/login' : '/api/auth/register';
          const body = this.tab === 'login'
            ? { account: this.account, password: this.password }
            : { account: this.account, password: this.password, nickname: this.nickname, invite_code: this.invite };
          const d = await LK.api(url, { method: 'POST', body });
          LK.state.token = d.token; localStorage.setItem('chatroom-token', d.token);
          LK.state.user = d.user;
          try { const me = await LK.api('/api/auth/me'); LK.state.models = me.models; LK.state.features = me.features; LK.state.quota = me.quota; } catch (e) {}
          LK.go(d.user.must_change_password ? '#/password' : '#/msgs');
        } catch (e) { LK.toast(LK.err(e)); } finally { this.busy = false; }
      },
    },
    template: `<div class="auth"><div class="auth-box">
      <div class="brand"><div class="logo"><AppIcon name="robot" :size="30"/></div>
        <h1>LinkAI</h1><p class="sub">多房间 AI 聊天平台 · Vue + PHP + MySQL</p></div>
      <div class="tabs"><button :class="{on:tab==='login'}" @click="tab='login'">登录</button>
        <button :class="{on:tab==='register'}" @click="tab='register'">注册</button></div>
      <div class="card">
        <div class="field"><label>手机号 / 邮箱</label><input v-model="account" placeholder="admin@demo.com" autocomplete="username"/></div>
        <div class="field" v-if="tab==='register'"><label>昵称</label><input v-model="nickname" placeholder="怎么称呼你"/></div>
        <div class="field"><label>密码</label><input v-model="password" type="password" placeholder="至少 8 位" autocomplete="current-password" @keyup.enter="submit"/></div>
        <div class="field" v-if="tab==='register'"><label>邀请码</label><input v-model="invite" placeholder="RM-XXXXXX"/></div>
        <button class="btn primary" style="width:100%" :disabled="busy" @click="submit">{{ busy?'请稍候…':(tab==='login'?'登录':'注册并登录') }}</button>
        <p class="sub" style="margin-top:12px;text-align:center">演示账号 admin@demo.com / AdminPass2026</p>
      </div>
    </div></div>`,
  };

  V.PasswordView = {
    data() { return { old: '', fresh: '', again: '', busy: false }; },
    methods: {
      async submit() {
        if (this.fresh !== this.again) return LK.toast('两次输入的新密码不一致');
        if (this.fresh.length < 8) return LK.toast('新密码至少 8 位');
        this.busy = true;
        try {
          const d = await LK.api('/api/auth/password', { method: 'POST', body: { old_password: this.old, new_password: this.fresh } });
          LK.state.token = d.token; localStorage.setItem('chatroom-token', d.token);
          LK.state.user = d.user; LK.toast('密码已更新'); LK.go('#/msgs');
        } catch (e) { LK.toast(LK.err(e)); } finally { this.busy = false; }
      },
    },
    template: `<div><NavBar title="修改密码" back="#/login"/><div class="page page-narrow">
      <div class="card"><p class="sub" style="margin-bottom:14px">首次登录或密码被重置后，需要先修改密码才能继续使用。</p>
        <div class="field"><label>原密码</label><input v-model="old" type="password"/></div>
        <div class="field"><label>新密码</label><input v-model="fresh" type="password"/></div>
        <div class="field"><label>确认新密码</label><input v-model="again" type="password"/></div>
        <button class="btn primary" style="width:100%" :disabled="busy" @click="submit">保存并继续</button>
      </div></div></div>`,
  };

  V.NewConvDrawer = {
    emits: ['done'],
    data() { return { title: '' }; },
    methods: {
      async create() {
        try {
          const d = await LK.api('/api/conversations', { method: 'POST', body: { title: this.title || '新会话' }, idem: LK.idem() });
          this.$emit('done'); LK.go('#/chat/' + d.item.id);
        } catch (e) { LK.toast(LK.err(e)); }
      },
    },
    template: `<div><div class="field"><label>会话标题</label><input v-model="title" placeholder="例如：产品方案讨论" autofocus/></div>
      <button class="btn primary" style="width:100%" @click="create">创建并开始</button></div>`,
  };

  V.MsgsView = {
    data() { return { items: [], q: '', loaded: false }; },
    async mounted() { await this.load(); },
    methods: {
      async load() {
        try { const d = await LK.api('/api/conversations' + (this.q ? '?q=' + encodeURIComponent(this.q) : '')); this.items = d.items; }
        catch (e) { LK.toast(LK.err(e)); } finally { this.loaded = true; }
      },
      async pin(c) { try { await LK.api('/api/conversations/' + c.id, { method: 'PUT', body: { pinned: !c.pinned } }); await this.load(); } catch (e) { LK.toast(LK.err(e)); } },
      del(c) {
        LK.confirm('删除会话「' + c.title + '」？', async () => {
          try {
            await LK.api('/api/conversations/' + c.id, { method: 'DELETE' }); await this.load();
            LK.toast('已删除', { label: '撤销', fn: async () => { await LK.api('/api/conversations/' + c.id + '/undelete', { method: 'POST' }); this.load(); } });
          } catch (e) { LK.toast(LK.err(e)); }
        });
      },
    },
    template: `<div><div class="nav"><h1>消息</h1>
        <button class="iconbtn" @click="LK.openDrawer('新建会话','NewConvDrawer')"><AppIcon name="plus"/></button></div>
      <div class="page">
        <div class="row" style="margin-bottom:12px"><input v-model="q" placeholder="搜索会话" @keyup.enter="load"/>
          <button class="btn sm" @click="load"><AppIcon name="search" :size="16"/></button></div>
        <EmptyState v-if="loaded && !items.length" text="还没有会话，点右上角新建" icon="chat"/>
        <div class="list"><div class="card" v-for="c in items" :key="c.id" @click="LK.go('#/chat/'+c.id)" style="cursor:pointer">
          <div class="between"><div class="row grow"><Avatar :name="c.title"/>
            <div class="grow"><div class="strong ellipsis">{{ c.title }} <span v-if="c.pinned" class="chip">置顶</span></div>
              <div class="sub ellipsis">{{ c.last_content || '暂无消息' }}</div></div></div>
            <button class="iconbtn" @click.stop="pin(c)" :aria-label="'置顶'"><AppIcon name="pin" :size="17"/></button>
            <button class="iconbtn" @click.stop="del(c)" aria-label="删除"><AppIcon name="trash" :size="17"/></button></div>
          <div class="sub" style="margin-top:8px">{{ c.msg_count }} 条 · {{ LK.fmtTime(c.updated_at) }}</div>
        </div></div>
      </div></div>`,
  };

  V.ChatView = {
    props: ['id'],
    data() { return { messages: [], input: '', models: [], modelId: null, generating: false, streamText: '',
      usage: null, abort: null, title: '对话', sending: false }; },
    async mounted() {
      try {
        const me = await LK.api('/api/auth/me'); this.models = me.models; LK.state.models = me.models;
        this.modelId = this.models.find(m => m.is_default)?.id || this.models[0]?.id || null;
        const d = await LK.api('/api/conversations/' + this.id + '/messages'); this.messages = d.items;
        this.scroll();
      } catch (e) { LK.toast(LK.err(e)); }
    },
    updated() { this.$nextTick(() => this.scroll()); },
    methods: {
      scroll() { const el = this.$refs.sc; if (el) el.scrollTop = el.scrollHeight; },
      async send() {
        const text = this.input.trim();
        if (!text || this.generating) return;
        this.input = ''; this.generating = true; this.streamText = ''; this.usage = null;
        this.messages.push({ id: 'tmp-' + Date.now(), role: 'user', content: text, created_at: new Date().toISOString() });
        this.abort = new AbortController();
        try {
          await LK.stream('/api/conversations/' + this.id + '/completions', { content: text, model_id: this.modelId },
            (ev, d) => {
              if (ev === 'delta') this.streamText += d.content || '';
              else if (ev === 'usage') this.usage = d;
              else if (ev === 'error') LK.toast(d.message || '生成失败');
            }, this.abort.signal);
        } catch (e) { if (e.name !== 'AbortError') LK.toast(LK.err(e)); }
        finally {
          this.generating = false; this.streamText = ''; this.abort = null;
          try { const d = await LK.api('/api/conversations/' + this.id + '/messages'); this.messages = d.items; } catch (e) {}
        }
      },
      stop() {
        if (this.abort) this.abort.abort();
        LK.api('/api/conversations/' + this.id + '/stop', { method: 'POST' }).catch(() => {});
      },
      async feedback(m, rating) {
        if (String(m.id).startsWith('tmp')) return;
        try { await LK.api('/api/messages/' + m.id + '/feedback', { method: 'POST', body: { rating, comment: '' } }); LK.toast('感谢反馈'); }
        catch (e) { LK.toast(LK.err(e)); }
      },
      async share() {
        try { const d = await LK.api('/api/shares', { method: 'POST', body: { conversation_id: Number(this.id) } }); LK.toast('分享链接：' + d.url); }
        catch (e) { LK.toast(LK.err(e)); }
      },
      async exportMd() {
        try {
          const r = await fetch('/api/conversations/' + this.id + '/export',
            { headers: { Authorization: 'Bearer ' + LK.state.token } });
          if (!r.ok) throw new Error('导出失败');
          const blob = await r.blob();
          const a = document.createElement('a');
          a.href = URL.createObjectURL(blob);
          a.download = 'conversation-' + this.id + '.md';
          a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
        } catch (e) { LK.toast(LK.err(e)); }
      },
    },
    template: `<div><div class="nav">
        <button class="iconbtn" @click="LK.go('#/msgs')"><AppIcon name="back"/></button>
        <h1 class="ellipsis">AI 对话</h1>
        <select v-model="modelId" style="width:auto;min-width:100px;padding:6px 8px;font-size:12px">
          <option v-for="m in models" :key="m.id" :value="m.id">{{ m.display_name }}</option></select>
        <button class="iconbtn" @click="share" aria-label="分享"><AppIcon name="share" :size="18"/></button>
        <button class="iconbtn" @click="exportMd" aria-label="导出"><AppIcon name="download" :size="18"/></button></div>
      <div class="chat-wrap"><div class="chat-scroll" ref="sc">
        <div v-for="m in messages" :key="m.id">
          <div class="bubble" :class="m.role==='user'?'me':'ai'">{{ m.content }}
            <div class="meta">{{ LK.fmtTime(m.created_at) }}
              <button v-if="m.role==='assistant'" class="btn ghost sm" style="padding:1px 5px;font-size:11px" @click="feedback(m,5)">赞</button>
              <button v-if="m.role==='assistant'" class="btn ghost sm" style="padding:1px 5px;font-size:11px" @click="feedback(m,1)">踩</button>
            </div></div>
        </div>
        <div v-if="streamText" class="bubble ai"><span class="typing"></span>{{ streamText }}</div>
        <div v-if="generating && !streamText" class="bubble ai sub">正在思考…</div>
        <div v-if="usage" class="sub" style="text-align:center">本次用量 {{ usage.tokens_in }} + {{ usage.tokens_out }} tokens · ¥{{ usage.cost }}</div>
      </div>
      <div class="composer"><input v-model="input" placeholder="输入消息，Enter 发送…" @keyup.enter="send" :disabled="generating"/>
        <button v-if="!generating" class="btn primary" aria-label="发送" @click="send"><AppIcon name="send" :size="18"/></button>
        <button v-else class="btn danger" aria-label="停止生成" @click="stop"><AppIcon name="stop" :size="18"/></button></div>
      </div></div>`,
  };

  V.NewRoomDrawer = {
    emits: ['done'],
    data() { return { name: '', description: '' }; },
    methods: {
      async create() {
        try { const d = await LK.api('/api/rooms', { method: 'POST', body: { name: this.name, description: this.description }, idem: LK.idem() });
          this.$emit('done'); LK.go('#/room/' + d.item.id); } catch (e) { LK.toast(LK.err(e)); }
      },
    },
    template: `<div><div class="field"><label>房间名称</label><input v-model="name" placeholder="例如：产品脑暴"/></div>
      <div class="field"><label>简介</label><input v-model="description" placeholder="随便聊聊"/></div>
      <button class="btn primary" style="width:100%" @click="create">创建房间</button></div>`,
  };

  V.RoomsView = {
    data() { return { items: [], q: '' }; },
    async mounted() { await this.load(); },
    methods: {
      async load() { try { const d = await LK.api('/api/rooms' + (this.q ? '?q=' + encodeURIComponent(this.q) : '')); this.items = d.items; } catch (e) { LK.toast(LK.err(e)); } },
      async join(r) { try { await LK.api('/api/rooms/' + r.id + '/join', { method: 'POST' }); LK.go('#/room/' + r.id); } catch (e) { LK.toast(LK.err(e)); } },
    },
    template: `<div><div class="nav"><h1>房间广场</h1>
        <button class="iconbtn" @click="LK.openDrawer('创建房间','NewRoomDrawer')"><AppIcon name="plus"/></button></div>
      <div class="page"><div class="row" style="margin-bottom:12px"><input v-model="q" placeholder="搜索房间" @keyup.enter="load"/>
        <button class="btn sm" @click="load"><AppIcon name="search" :size="16"/></button></div>
        <div class="list"><div class="card" v-for="r in items" :key="r.id">
          <div class="between"><div class="grow"><div class="strong">{{ r.name }}</div><div class="sub ellipsis">{{ r.description }}</div></div>
            <span class="chip gray">{{ r.member_count }} 人</span></div>
          <div class="row" style="margin-top:10px"><span class="sub">房主 {{ r.owner_name }}</span><span class="grow"></span>
            <button class="btn sm primary" @click="join(r)">{{ r.joined?'进入':'加入并进入' }}</button></div>
        </div></div></div></div>`,
  };

  V.RoomView = {
    props: ['id'],
    data() { return { room: null, msgs: [], input: '', after: 0, timer: null, aiBusy: false }; },
    async mounted() {
      try {
        const d = await LK.api('/api/rooms/' + this.id); this.room = d.item;
        if (!d.item.joined) await LK.api('/api/rooms/' + this.id + '/join', { method: 'POST' });
        await this.poll();
        this.timer = setInterval(() => this.poll(), 3000);
      } catch (e) { LK.toast(LK.err(e)); }
    },
    beforeUnmount() { clearInterval(this.timer); },
    methods: {
      async poll() {
        try {
          const d = await LK.api('/api/rooms/' + this.id + '/messages?after=' + this.after);
          if (d.items.length) { this.msgs.push(...d.items); this.after = d.items[d.items.length - 1].id; this.$nextTick(() => { const el = this.$refs.sc; if (el) el.scrollTop = el.scrollHeight; }); }
        } catch (e) {}
      },
      async send() {
        const t = this.input.trim(); if (!t) return; this.input = '';
        try { await LK.api('/api/rooms/' + this.id + '/messages', { method: 'POST', body: { content: t }, idem: LK.idem() }); await this.poll(); }
        catch (e) { LK.toast(LK.err(e)); this.input = t; }
      },
      async askAI() {
        const t = this.input.trim(); if (!t) return LK.toast('先输入要问 AI 的内容');
        this.input = ''; this.aiBusy = true;
        try { await LK.api('/api/rooms/' + this.id + '/ai', { method: 'POST', body: { content: t } }); await this.poll(); }
        catch (e) { LK.toast(LK.err(e)); this.input = t; } finally { this.aiBusy = false; }
      },
    },
    template: `<div><NavBar :title="room?room.name:'房间'" back="#/rooms"/>
      <div class="chat-wrap" style="height:calc(100dvh - var(--nav-h) - var(--tab-h))">
        <div class="chat-scroll" ref="sc" style="gap:6px">
          <div v-for="m in msgs" :key="m.id">
            <div v-if="m.kind==='system'" class="sub" style="text-align:center;margin:6px 0">{{ m.content }}</div>
            <div v-else class="card" style="padding:8px 11px"><div class="row" style="gap:6px">
              <Avatar :name="m.nickname" :size="24"/><span class="strong" style="font-size:12px">{{ m.nickname }}</span>
              <span class="chip" v-if="m.kind==='ai'">AI</span><span class="grow"></span><span class="sub">{{ LK.fmtTime(m.created_at) }}</span></div>
              <div style="margin-top:5px;white-space:pre-wrap;word-break:break-word">{{ m.content }}</div></div>
          </div>
        </div>
        <div class="composer"><input v-model="input" placeholder="发消息，或点 @AI 提问" @keyup.enter="send"/>
          <button class="btn sm" :disabled="aiBusy" @click="askAI"><AppIcon name="robot" :size="16"/> @AI</button>
          <button class="btn primary" @click="send"><AppIcon name="send" :size="18"/></button></div>
      </div></div>`,
  };

  V.MeView = {
    data() { return { me: null }; },
    async mounted() { await this.load(); },
    methods: {
      async load() { try { this.me = await LK.api('/api/auth/me'); LK.state.user = this.me.user; LK.state.quota = this.me.quota; LK.state.features = this.me.features; } catch (e) { LK.toast(LK.err(e)); } },
      async toggleTheme() { const t = LK.state.theme === 'dark' ? 'light' : 'dark'; LK.setTheme(t); try { await LK.api('/api/auth/theme', { method: 'PUT', body: { theme: t } }); } catch (e) {} },
    },
    template: `<div><div class="nav"><h1>我的</h1></div><div class="page page-narrow">
      <div class="card" v-if="me"><div class="row"><Avatar :name="me.user.nickname" :size="48"/>
        <div class="grow"><div class="strong" style="font-size:16px">{{ me.user.nickname }}</div>
          <div class="sub">{{ me.user.email || me.user.phone }} · {{ me.user.role==='admin'?'管理员':'成员' }}</div></div>
        <span class="chip">{{ me.user.role==='admin'?'ADMIN':'MEMBER' }}</span></div>
        <div class="section-title">今日用量（{{ me.quota.date }}）</div>
        <div class="kv"><span>消息</span><span>{{ me.quota.msg_used }} / {{ me.quota.msg_limit }}</span></div>
        <ProgressBar :value="me.quota.msg_used" :max="me.quota.msg_limit" :warn="me.quota.msg_used/me.quota.msg_limit>=me.quota.warn_ratio"/>
        <div class="kv" style="margin-top:10px"><span>Token</span><span>{{ me.quota.token_used }} / {{ me.quota.token_limit }}</span></div>
        <ProgressBar :value="me.quota.token_used" :max="me.quota.token_limit" :warn="me.quota.token_used/me.quota.token_limit>=me.quota.warn_ratio"/>
      </div>
      <div class="section-title">设置</div>
      <div class="card"><div class="between" style="padding:4px 0"><span>深色主题</span><Switch :model-value="LK.state.theme==='dark'" @update:modelValue="toggleTheme"/></div>
        <div class="between" style="padding:10px 0;cursor:pointer" @click="LK.go('#/friends')"><span>好友与私聊</span><AppIcon name="users" :size="18"/></div>
        <div class="between" style="padding:10px 0;cursor:pointer" @click="LK.go('#/search')"><span>全局搜索</span><AppIcon name="search" :size="18"/></div>
      </div>
      <template v-if="me && me.user.role==='admin'"><div class="section-title">管理端</div>
        <div class="card"><div class="admin-cards">
          <button class="btn" @click="LK.go('#/admin/channels')"><AppIcon name="link" :size="17"/> 渠道配置</button>
          <button class="btn" @click="LK.go('#/admin/models')"><AppIcon name="bolt" :size="17"/> 模型注册表</button>
          <button class="btn" @click="LK.go('#/admin/invites')"><AppIcon name="key" :size="17"/> 邀请码</button>
          <button class="btn" @click="LK.go('#/admin/stats')"><AppIcon name="chart" :size="17"/> 数据统计</button>
          <button class="btn" @click="LK.go('#/admin/settings')"><AppIcon name="settings" :size="17"/> 系统设置</button>
          <button class="btn" @click="LK.go('#/admin/users')"><AppIcon name="users" :size="17"/> 用户管理</button>
        </div></div></template>
      <div class="section-title"></div>
      <button class="btn danger" style="width:100%" @click="LK.logout()"><AppIcon name="logout" :size="17"/> 退出登录</button>
      <p class="sub" style="text-align:center;margin-top:18px">Vue 3 + PHP 8 + MySQL 8 · 无容器</p>
    </div></div>`,
  };

  V.ShareView = {
    props: ['id'],
    data() { return { data: null }; },
    async mounted() { try { this.data = await LK.api('/api/shares/' + this.id); } catch (e) { LK.toast(LK.err(e)); } },
    template: `<div><NavBar title="分享的对话" back="#/msgs"/><div class="page page-narrow">
      <div class="card" v-if="data"><h2 class="card-title">{{ data.title }}</h2>
        <div v-for="(m,i) in data.messages" :key="i" style="margin-top:12px">
          <div class="sub">{{ m.role==='user'?'我':'AI' }} · {{ LK.fmtTime(m.created_at) }}</div>
          <div class="bubble" :class="m.role==='user'?'me':'ai'" style="margin-top:4px">{{ m.content }}</div></div>
      </div></div></div>`,
  };

  V.FriendsView = {
    data() { return { items: [], uid: '' }; },
    async mounted() { await this.load(); },
    methods: {
      async load() { try { this.items = (await LK.api('/api/friends')).items; } catch (e) { LK.toast(LK.err(e)); } },
      async add() { try { await LK.api('/api/friends/request', { method: 'POST', body: { user_id: Number(this.uid) } }); this.uid = ''; this.load(); LK.toast('已发送申请'); } catch (e) { LK.toast(LK.err(e)); } },
      async act(f, s) { try { await LK.api('/api/friends/' + f.id + '/accept', { method: 'POST', body: { action: s } }); this.load(); } catch (e) { LK.toast(LK.err(e)); } },
    },
    template: `<div><NavBar title="好友与私聊" back="#/me"/><div class="page page-narrow">
      <div class="card"><div class="row"><input v-model="uid" placeholder="输入用户 ID 添加好友"/><button class="btn primary sm" @click="add">添加</button></div></div>
      <div class="list" style="margin-top:10px"><div class="card" v-for="f in items" :key="f.id"><div class="between">
        <div class="row"><Avatar :name="f.peer_name" :size="34"/><div><div class="strong">{{ f.peer_name }}</div><div class="sub">ID {{ f.peer_id }} · {{ f.status }}</div></div></div>
        <div class="row"><button v-if="f.status==='pending' && f.requester_id!=LK.state.user.id" class="btn sm primary" @click="act(f,'accept')">同意</button>
          <button v-if="f.status==='accepted'" class="btn sm" @click="LK.go('#/dm/'+f.peer_id)">私聊</button></div>
      </div></div></div></div></div>`,
  };

  V.DirectChatView = {
    props: ['id'],
    data() { return { msgs: [], input: '' }; },
    async mounted() { await this.load(); },
    methods: {
      async load() { try { this.msgs = (await LK.api('/api/dm/' + this.id)).items; } catch (e) { LK.toast(LK.err(e)); } },
      async send() { const t = this.input.trim(); if (!t) return; this.input = '';
        try { await LK.api('/api/dm/' + this.id, { method: 'POST', body: { content: t } }); this.load(); } catch (e) { LK.toast(LK.err(e)); } },
    },
    template: `<div><NavBar title="私聊" back="#/friends"/><div class="page page-narrow">
      <div class="card" v-for="m in msgs" :key="m.id" style="margin-bottom:8px">
        <div class="sub">{{ m.from_id==LK.state.user.id?'我':'对方' }} · {{ LK.fmtTime(m.created_at) }}</div><div>{{ m.content }}</div></div>
      <div class="composer" style="position:sticky;bottom:var(--tab-h);border-radius:12px"><input v-model="input" placeholder="说点什么…" @keyup.enter="send"/>
        <button class="btn primary" @click="send"><AppIcon name="send" :size="18"/></button></div>
    </div></div>`,
  };

  V.SearchView = {
    data() { return { q: '', res: null }; },
    methods: {
      async run() { if (!this.q.trim()) return; try { this.res = await LK.api('/api/search?q=' + encodeURIComponent(this.q)); } catch (e) { LK.toast(LK.err(e)); } },
    },
    template: `<div><NavBar title="全局搜索" back="#/me"/><div class="page page-narrow">
      <div class="row"><input v-model="q" placeholder="搜用户 / 会话 / 房间 / 消息" @keyup.enter="run"/><button class="btn primary" @click="run">搜索</button></div>
      <template v-if="res"><div class="section-title">会话</div>
        <div class="card" v-for="c in res.conversations" :key="c.id" @click="LK.go('#/chat/'+c.id)">{{ c.title }}</div>
        <div class="section-title">房间</div>
        <div class="card" v-for="r in res.rooms" :key="r.id" @click="LK.go('#/room/'+r.id)">{{ r.name }}</div>
        <div class="section-title">用户</div>
        <div class="card" v-for="u in res.users" :key="u.id">{{ u.nickname }} <span class="sub">{{ u.email }}</span>
          <button class="btn sm" @click.stop="LK.go('#/dm/'+u.id)">私聊</button></div>
        <div class="section-title">消息</div>
        <div class="card" v-for="m in res.messages" :key="m.id" @click="LK.go('#/chat/'+m.conversation_id)">{{ m.content.slice(0,80) }}</div>
      </template></div></div>`,
  };
})();
