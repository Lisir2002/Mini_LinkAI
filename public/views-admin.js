/* 管理端视图（移动卡片 / 桌面双栏） */
(function () {
  const LK = window.LK;
  const V = LK.adminViews = {};

  V.AdminLayout = {
    computed: { cur() { return LK.parseRoute().raw; } },
    template: `<div><NavBar title="管理后台" back="#/me"/>
      <div class="admin"><aside class="admin-side">
        <div class="sub" style="padding:6px 12px 12px">LINKAI ADMIN</div>
        <a v-for="n in nav" :key="n.h" :href="n.h" :class="{on:cur===n.h}"><AppIcon :name="n.i" :size="18"/>{{ n.t }}</a>
      </aside><div class="admin-main"><slot></slot></div></div></div>`,
    data() { return { nav: [
      { h: '#/admin/channels', t: '渠道配置', i: 'link' }, { h: '#/admin/models', t: '模型注册表', i: 'bolt' },
      { h: '#/admin/invites', t: '邀请码', i: 'key' }, { h: '#/admin/stats', t: '数据统计', i: 'chart' },
      { h: '#/admin/settings', t: '系统设置', i: 'settings' }, { h: '#/admin/users', t: '用户管理', i: 'users' },
    ] }; },
  };

  /* ── 渠道抽屉：先选协议 → 动态表单 → 预设一键填充 ── */
  V.ChannelDrawer = {
    props: { item: Object }, emits: ['done'],
    data() {
      return {
        presets: [], form: { name: '', protocol: 'openai_compatible', base_url: '', api_key: '', priority: 0, weight: 100, enabled: 1, version: 1 },
        busy: false, result: '',
      };
    },
    async mounted() {
      try { this.presets = (await LK.api('/api/presets')).protocols; } catch (e) {}
      if (this.item) Object.assign(this.form, {
        name: this.item.name, protocol: this.item.protocol, base_url: this.item.base_url,
        priority: this.item.priority, weight: this.item.weight, enabled: this.item.enabled ? 1 : 0,
        version: this.item.version, api_key: '',
      });
    },
    computed: {
      proto() { return this.presets.find(p => p.key === this.form.protocol) || { fields: [], presets: [], label: '' }; },
    },
    methods: {
      fill(p) { this.form.name = p.name; this.form.base_url = p.base_url; if (p.api_key) this.form.api_key = p.api_key; },
      async save() {
        this.busy = true;
        const body = Object.assign({}, this.form);
        if (this.item && !body.api_key) delete body.api_key;
        try {
          const url = this.item ? '/api/admin/channels/' + this.item.id : '/api/admin/channels';
          await LK.api(url, { method: this.item ? 'PUT' : 'POST', body });
          LK.toast(this.item ? '渠道已更新' : '渠道已创建'); this.$emit('done');
        } catch (e) { LK.toast(LK.err(e)); } finally { this.busy = false; }
      },
    },
    template: `<div>
      <div class="field"><label>协议类型</label>
        <select v-model="form.protocol"><option v-for="p in presets" :key="p.key" :value="p.key">{{ p.label }}</option></select></div>
      <div class="field" v-if="proto.presets.length"><label>厂商预设（一键填充）</label>
        <div class="row wrap"><button class="btn sm" v-for="p in proto.presets" :key="p.name" @click="fill(p)">{{ p.name }}</button></div></div>
      <div class="field"><label>渠道名称</label><input v-model="form.name" placeholder="例如：DeepSeek 主账号"/></div>
      <div class="field"><label>Base URL</label><input v-model="form.base_url" placeholder="https://api.deepseek.com/v1"/></div>
      <div class="field"><label>API Key {{ item?'(留空表示不修改)':'' }}</label><input v-model="form.api_key" type="password" placeholder="sk-..."/></div>
      <div class="row"><div class="field grow"><label>优先级</label><input v-model.number="form.priority" type="number"/></div>
        <div class="field grow"><label>权重</label><input v-model.number="form.weight" type="number"/></div></div>
      <div class="between" style="margin-bottom:14px"><span>启用</span><Switch :model-value="!!form.enabled" @update:modelValue="form.enabled=$event?1:0"/></div>
      <button class="btn primary" style="width:100%" :disabled="busy" @click="save">{{ item?'保存修改':'创建渠道' }}</button>
      <p class="sub" style="margin-top:10px">参数白名单：name / protocol / base_url / api_key / priority / weight / enabled；Key 加密存储，只回显末 4 位。</p>
    </div>`,
  };

  V.ChannelsView = {
    data() { return { items: [], presets: [] }; },
    async mounted() { await this.load(); },
    methods: {
      async load() { try { const d = await LK.api('/api/admin/channels'); this.items = d.items; this.presets = d.presets; } catch (e) { LK.toast(LK.err(e)); } },
      edit(c) { LK.openDrawer('编辑渠道', 'ChannelDrawer', { item: c }); },
      add() { LK.openDrawer('添加接口', 'ChannelDrawer'); },
      async probe(c) {
        LK.toast('正在测试连通…');
        try { const r = await LK.api('/api/admin/channels/' + c.id + '/probe', { method: 'POST' }); LK.toast(r.ok ? '连通成功 ' + (r.latency_ms || 0) + 'ms' : '连通失败：' + r.message); await this.load(); }
        catch (e) { LK.toast(LK.err(e)); }
      },
      async sync(c) {
        try { const r = await LK.api('/api/admin/channels/' + c.id + '/sync', { method: 'POST' }); LK.toast('同步到 ' + r.models.length + ' 个上游模型'); await this.load(); }
        catch (e) { LK.toast(LK.err(e)); }
      },
      async toggle(c) {
        try { await LK.api('/api/admin/channels/' + c.id + '/toggle', { method: 'POST', body: { enabled: !c.enabled } }); await this.load(); }
        catch (e) { LK.toast(LK.err(e)); }
      },
      async del(c) {
        let impact = null;
        try { impact = await LK.api('/api/admin/channels/' + c.id + '/impact'); } catch (e) {}
        const msg = '删除「' + c.name + '」将影响 ' + (impact?.bindings ?? 0) + ' 个模型绑定、' + (impact?.models?.length ?? 0) + ' 个对外模型，且不可恢复。';
        LK.confirm(msg, async () => {
          try { await LK.api('/api/admin/channels/' + c.id, { method: 'DELETE' }); LK.toast('已删除'); await this.load(); }
          catch (e) { LK.toast(LK.err(e)); }
        }, '删除影响范围确认');
      },
    },
    template: `<AdminLayout><div class="between" style="margin-bottom:12px"><div><h2 class="card-title">模型接口配置</h2>
        <div class="sub">按协议接入上游，选路按优先级 + 权重</div></div><button class="btn primary" @click="add"><AppIcon name="plus" :size="16"/>添加接口</button></div>
      <div class="admin-cards"><div class="card" v-for="c in items" :key="c.id">
        <div class="between"><div class="row grow"><Avatar :name="c.name" :size="34"/>
          <div class="grow"><div class="strong">{{ c.name }}</div><div class="sub ellipsis">{{ c.base_url }}</div></div></div>
          <span class="chip" :class="c.enabled?'ok':'bad'">{{ c.enabled?'启用':'停用' }}</span></div>
        <div class="row wrap" style="margin-top:10px"><span class="chip gray">{{ c.protocol }}</span>
          <span class="chip gray">Key {{ c.api_key_hint }}</span><span class="chip gray">优先级 {{ c.priority }}</span>
          <span class="chip gray">权重 {{ c.weight }}</span><span class="chip gray" v-if="c.fail_count>0">失败 {{ c.fail_count }}</span></div>
        <div class="row wrap" style="margin-top:8px" v-if="c.upstream_models.length">
          <span class="sub">已同步：</span><span class="chip" v-for="m in c.upstream_models" :key="m">{{ m }}</span></div>
        <div class="sub" v-if="c.last_error" style="color:var(--danger);margin-top:8px">{{ c.last_error }}</div>
        <div class="row wrap" style="margin-top:12px">
          <button class="btn sm" @click="edit(c)"><AppIcon name="edit" :size="15"/>编辑</button>
          <button class="btn sm" @click="probe(c)">测试连通</button>
          <button class="btn sm" @click="sync(c)"><AppIcon name="refresh" :size="15"/>同步模型</button>
          <button class="btn sm" @click="toggle(c)">{{ c.enabled?'停用':'启用' }}</button>
          <button class="btn sm danger" @click="del(c)"><AppIcon name="trash" :size="15"/>删除</button>
        </div>
      </div></div>
      <EmptyState v-if="!items.length" text="还没有渠道，点「添加接口」新建一个" icon="link"/>
    </AdminLayout>`,
  };

  V.ModelDrawer = {
    emits: ['done'], data() { return { form: { public_name: '', display_name: '', tier: 'standard', context_limit: 32768, price_input: 0, price_output: 0 } }; },
    methods: {
      async save() { try { await LK.api('/api/admin/models', { method: 'POST', body: this.form }); LK.toast('模型已创建'); this.$emit('done'); } catch (e) { LK.toast(LK.err(e)); } },
    },
    template: `<div><div class="field"><label>对外名（唯一，解耦上游）</label><input v-model="form.public_name" placeholder="例如：smart"/></div>
      <div class="field"><label>展示名</label><input v-model="form.display_name" placeholder="主力模型"/></div>
      <div class="field"><label>档位</label><select v-model="form.tier"><option value="premium">premium</option><option value="standard">standard</option><option value="fast">fast</option></select></div>
      <div class="row"><div class="field grow"><label>上下文上限</label><input v-model.number="form.context_limit" type="number"/></div>
        <div class="field grow"><label>输入价 ¥/K</label><input v-model.number="form.price_input" type="number" step="0.1"/></div></div>
      <div class="field"><label>输出价 ¥/K</label><input v-model.number="form.price_output" type="number" step="0.1"/></div>
      <button class="btn primary" style="width:100%" @click="save">新建模型</button></div>`,
  };
  V.BindDrawer = {
    props: { model: Object }, emits: ['done'],
    data() { return { channels: [], form: { channel_id: null, upstream_model: '', weight: 100 } }; },
    async mounted() { try { const d = await LK.api('/api/admin/channels'); this.channels = d.items; this.form.channel_id = d.items[0]?.id || null; } catch (e) {} },
    methods: {
      async save() { try { await LK.api('/api/admin/models/' + this.model.id + '/bind', { method: 'POST', body: this.form }); LK.toast('已绑定'); this.$emit('done'); } catch (e) { LK.toast(LK.err(e)); } },
    },
    template: `<div><div class="field"><label>渠道</label><select v-model.number="form.channel_id"><option v-for="c in channels" :key="c.id" :value="c.id">{{ c.name }}</option></select></div>
      <div class="field"><label>上游模型名</label><input v-model="form.upstream_model" placeholder="例如：mock-chat / deepseek-chat"/></div>
      <div class="field"><label>权重</label><input v-model.number="form.weight" type="number"/></div>
      <button class="btn primary" style="width:100%" @click="save">确认绑定</button></div>`,
  };

  V.ModelsView = {
    data() { return { items: [] }; },
    async mounted() { await this.load(); },
    methods: {
      async load() { try { this.items = (await LK.api('/api/admin/models')).items; } catch (e) { LK.toast(LK.err(e)); } },
      async setDefault(m) { try { await LK.api('/api/admin/models/' + m.id + '/default', { method: 'POST' }); LK.toast('已设为默认'); await this.load(); } catch (e) { LK.toast(LK.err(e)); } },
      async unbind(m, b) { try { await LK.api('/api/admin/models/' + m.id + '/bind/' + b.channel_id, { method: 'DELETE' }); await this.load(); } catch (e) { LK.toast(LK.err(e)); } },
      del(m) { LK.confirm('删除模型「' + m.public_name + '」？', async () => { try { await LK.api('/api/admin/models/' + m.id, { method: 'DELETE' }); await this.load(); } catch (e) { LK.toast(LK.err(e)); } }); },
    },
    template: `<AdminLayout><div class="between" style="margin-bottom:12px"><div><h2 class="card-title">模型注册表</h2>
        <div class="sub">对外名与上游解耦，支持乐观锁</div></div><button class="btn primary" @click="LK.openDrawer('新建模型','ModelDrawer')"><AppIcon name="plus" :size="16"/>新建模型</button></div>
      <div class="admin-cards"><div class="card" v-for="m in items" :key="m.id"><div class="between">
        <div><div class="strong">{{ m.display_name }} <span class="chip gray">{{ m.public_name }}</span></div>
          <div class="sub">{{ m.tier }} · {{ m.context_limit }} ctx · ¥{{ m.price_input }}/¥{{ m.price_output }}</div></div>
        <span class="chip ok" v-if="m.is_default">默认</span></div>
        <div style="margin-top:10px" v-for="b in m.channels" :key="b.channel_id"><div class="kv"><span class="code">{{ b.channel_name }} → {{ b.upstream_model }}</span>
          <button class="btn sm danger" @click="unbind(m,b)">解绑</button></div></div>
        <div class="row wrap" style="margin-top:12px"><button class="btn sm" @click="LK.openDrawer('绑定渠道','BindDrawer',{model:m})"><AppIcon name="link" :size="15"/>绑定渠道</button>
          <button class="btn sm" v-if="!m.is_default" @click="setDefault(m)">设为默认</button>
          <button class="btn sm danger" @click="del(m)">删除</button></div>
      </div></div></AdminLayout>`,
  };

  V.InvitesView = {
    data() { return { items: [], count: 5, fresh: [] }; },
    async mounted() { await this.load(); },
    methods: {
      async load() { try { this.items = (await LK.api('/api/admin/invites')).items; } catch (e) { LK.toast(LK.err(e)); } },
      async gen() { try { const d = await LK.api('/api/admin/invites', { method: 'POST', body: { count: this.count } }); this.fresh = d.codes; LK.toast('已生成 ' + d.codes.length + ' 个邀请码'); await this.load(); } catch (e) { LK.toast(LK.err(e)); } },
      async revoke(i) { LK.confirm('作废邀请码 ' + i.code_masked + '？', async () => { try { await LK.api('/api/admin/invites/' + i.id + '/revoke', { method: 'POST' }); await this.load(); } catch (e) { LK.toast(LK.err(e)); } }); },
      copy(c) { navigator.clipboard?.writeText(c); LK.toast('已复制 ' + c); },
    },
    template: `<AdminLayout><h2 class="card-title">邀请码</h2><div class="sub" style="margin-bottom:12px">批量生成、掩码列表、作废</div>
      <div class="card"><div class="row"><input v-model.number="count" type="number" min="1" max="50" style="width:90px"/>
        <button class="btn primary" @click="gen"><AppIcon name="plus" :size="16"/>批量生成</button></div>
        <div v-if="fresh.length" style="margin-top:12px"><div class="sub">本次生成（仅此一次完整显示）：</div>
          <div class="code" v-for="c in fresh" :key="c" @click="copy(c)" style="cursor:pointer;padding:3px 0">{{ c }}</div></div></div>
      <div class="card" style="margin-top:12px"><div class="kv" v-for="i in items" :key="i.id">
        <div><span class="code">{{ i.code_masked }}</span> <span class="sub">已用 {{ i.used_count }}/{{ i.max_uses }}</span></div>
        <div class="row"><span class="chip" :class="i.revoked?'bad':'ok'">{{ i.revoked?'已作废':'有效' }}</span>
          <button class="btn sm" @click="copy(i.code)"><AppIcon name="copy" :size="14"/></button>
          <button class="btn sm danger" v-if="!i.revoked" @click="revoke(i)">作废</button></div></div></div>
    </AdminLayout>`,
  };

  V.SettingsView = {
    data() { return { s: null, dirty: {} }; },
    async mounted() { try { this.s = (await LK.api('/api/admin/settings')).settings; } catch (e) { LK.toast(LK.err(e)); } },
    methods: {
      async save(k) { try { await LK.api('/api/admin/settings', { method: 'PUT', body: { key: k, value: this.s[k] } }); LK.toast(k + ' 已保存'); } catch (e) { LK.toast(LK.err(e)); } },
    },
    template: `<AdminLayout><h2 class="card-title">系统设置</h2><div class="sub" style="margin-bottom:12px">配额 / 注册 / 内容安全 / 特性开关 / 保留天数</div>
      <div class="admin-cards" v-if="s"><div class="card"><div class="card-title">配额</div>
        <div class="field"><label>每日消息上限</label><input v-model.number="s.quota.daily_msg_limit" type="number"/></div>
        <div class="field"><label>每日 Token 上限</label><input v-model.number="s.quota.daily_token_limit" type="number"/></div>
        <div class="field"><label>房间每日 Token 预算</label><input v-model.number="s.quota.room_daily_token_budget" type="number"/></div>
        <div class="field"><label>告警比例</label><input v-model.number="s.quota.warn_ratio" type="number" step="0.1"/></div>
        <div class="sub" style="margin-bottom:10px">配额日切时区固定 Asia/Shanghai，禁止改成 UTC</div>
        <button class="btn primary sm" @click="save('quota')">保存配额</button></div>
        <div class="card"><div class="card-title">注册方式</div>
          <div class="field"><label>模式</label><select v-model="s.registration.mode"><option value="invite_code">invite_code</option><option value="open">open</option><option value="closed">closed</option></select></div>
          <div class="between" style="margin-bottom:12px"><span>强制邀请码</span><Switch v-model="s.registration.require_invite"/></div>
          <button class="btn primary sm" @click="save('registration')">保存</button></div>
        <div class="card"><div class="card-title">内容安全</div>
          <div class="between" style="margin-bottom:10px"><span>启用审核</span><Switch v-model="s.moderation.enabled"/></div>
          <div class="between" style="margin-bottom:10px"><span>拦截输入</span><Switch v-model="s.moderation.block_input"/></div>
          <div class="between" style="margin-bottom:12px"><span>拦截输出</span><Switch v-model="s.moderation.block_output"/></div>
          <button class="btn primary sm" @click="save('moderation')">保存</button></div>
        <div class="card"><div class="card-title">特性开关</div>
          <div class="between" v-for="(v,k) in s.feature_flags" :key="k" style="margin-bottom:10px"><span>{{ k }}</span><Switch v-model="s.feature_flags[k]"/></div>
          <button class="btn primary sm" @click="save('feature_flags')">保存</button></div>
        <div class="card"><div class="card-title">数据保留</div>
          <div class="field"><label>审计日志保留天数</label><input v-model.number="s.retention.days" type="number"/></div>
          <button class="btn primary sm" @click="save('retention')">保存</button></div>
      </div></AdminLayout>`,
  };

  V.StatsView = {
    data() { return { d: null, timer: null }; },
    async mounted() { await this.load(); this.timer = setInterval(() => this.load(), 10000); },
    beforeUnmount() { clearInterval(this.timer); },
    methods: {
      async load() { try { this.d = await LK.api('/api/admin/stats'); } catch (e) { LK.toast(LK.err(e)); } },
      async runScheduler() { try { const r = await LK.api('/api/admin/scheduler/run', { method: 'POST' }); LK.toast('兜底完成：退回 ' + r.refunded + ' 笔'); await this.load(); } catch (e) { LK.toast(LK.err(e)); } },
      bar(v, max) { return Math.max(3, Math.round((v / (max || 1)) * 52)) + 'px'; },
    },
    template: `<AdminLayout><div class="between"><div><h2 class="card-title">数据统计</h2><div class="sub">用量 / 趋势 / 渠道健康 / 实时</div></div>
        <button class="btn sm" @click="runScheduler"><AppIcon name="refresh" :size="15"/>跑兜底</button></div>
      <div class="stat-grid" style="margin-top:12px" v-if="d">
        <div class="stat"><div class="num">{{ d.overview.users }}</div><div class="lbl">用户</div></div>
        <div class="stat"><div class="num">{{ d.overview.messages }}</div><div class="lbl">消息</div></div>
        <div class="stat"><div class="num">{{ d.overview.tokens_in + d.overview.tokens_out }}</div><div class="lbl">Token</div></div>
        <div class="stat"><div class="num">¥{{ d.overview.cost.toFixed(4) }}</div><div class="lbl">成本</div></div>
      </div>
      <div class="card" style="margin-top:12px" v-if="d"><div class="card-title">近 7 天消息趋势</div>
        <div class="spark" style="margin-top:12px"><i v-for="(t,i) in d.trend" :key="i" :style="{height:bar(t.msgs,Math.max(...d.trend.map(x=>x.msgs),1))}"></i></div>
        <div class="row" style="justify-content:space-between;margin-top:6px"><span class="sub">{{ d.trend[0]?.d || '-' }}</span><span class="sub">{{ d.trend[d.trend.length-1]?.d || '-' }}</span></div></div>
      <div class="card" style="margin-top:12px" v-if="d"><div class="card-title">渠道健康</div>
        <div class="kv" v-for="c in d.channels" :key="c.id"><span>{{ c.name }}</span>
          <span><span class="chip" :class="c.enabled?'ok':'bad'">{{ c.enabled?'启用':'停用' }}</span> 失败 {{ c.fail_count }}</span></div></div>
      <div class="card" style="margin-top:12px" v-if="d"><div class="card-title">实时</div>
        <div class="kv"><span>运行中的 AI 任务</span><span>{{ d.live.ai_running }}</span></div>
        <div class="kv"><span>悬挂待结算</span><span>{{ d.overview.pending }}</span></div></div>
    </AdminLayout>`,
  };

  V.UsersView = {
    data() { return { items: [], q: '' }; },
    async mounted() { await this.load(); },
    methods: {
      async load() { try { this.items = (await LK.api('/api/admin/users' + (this.q ? '?q=' + encodeURIComponent(this.q) : ''))).items; } catch (e) { LK.toast(LK.err(e)); } },
      async status(u) { try { await LK.api('/api/admin/users/' + u.id + '/status', { method: 'POST', body: { status: u.status === 'active' ? 'banned' : 'active' } }); await this.load(); } catch (e) { LK.toast(LK.err(e)); } },
      reset(u) { LK.confirm('重置用户 ' + u.nickname + ' 的密码？', async () => {
        const pw = prompt('输入新密码（至少 8 位）', 'NewPass2026');
        if (!pw) return;
        try { await LK.api('/api/admin/users/' + u.id + '/reset-password', { method: 'POST', body: { password: pw } }); LK.toast('已重置，用户下次登录需改密'); } catch (e) { LK.toast(LK.err(e)); }
      }); },
    },
    template: `<AdminLayout><h2 class="card-title">用户管理</h2>
      <div class="row" style="margin:12px 0"><input v-model="q" placeholder="搜索昵称 / 邮箱 / 手机号" @keyup.enter="load"/><button class="btn" @click="load">搜索</button></div>
      <div class="admin-cards"><div class="card" v-for="u in items" :key="u.id"><div class="between">
        <div class="row"><Avatar :name="u.nickname" :size="34"/><div><div class="strong">{{ u.nickname }}</div>
          <div class="sub">{{ u.email || u.phone }} · ID {{ u.id }}</div></div></div>
        <span class="chip" :class="u.status==='active'?'ok':'bad'">{{ u.status }}</span></div>
        <div class="row wrap" style="margin-top:10px"><span class="chip gray">{{ u.role }}</span>
          <span class="chip gray" v-if="u.must_change_password">待改密</span>
          <span class="grow"></span><button class="btn sm" @click="reset(u)">重置密码</button>
          <button class="btn sm danger" @click="status(u)">{{ u.status==='active'?'禁用':'启用' }}</button></div>
      </div></div></AdminLayout>`,
  };
})();
