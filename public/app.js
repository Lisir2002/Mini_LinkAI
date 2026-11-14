/* 应用装配：全局注册 + hash 路由 + 守卫 */
(function () {
  const LK = window.LK;
  const all = Object.assign({}, LK.components, LK.memberViews, LK.adminViews);
  const app = Vue.createApp({
    data() { return { ready: false }; },
    async mounted() {
      if (LK.state.token) {
        try {
          const me = await LK.api('/api/auth/me');
          LK.state.user = me.user; LK.state.models = me.models;
          LK.state.features = me.features; LK.state.quota = me.quota;
          LK.setTheme(me.user.theme || 'light');
          const r = LK.parseRoute();
          if (me.user.must_change_password && r.name !== 'password') LK.go('#/password');
          else if (['login', 'password'].includes(r.name)) LK.go('#/msgs');
        } catch (e) {
          LK.logout(true);
        }
      }
      this.ready = true;
    },
    computed: {
      r() { return LK.parseRoute(); },
      view() {
        const r = this.r;
        if (!LK.state.token && r.name !== 'share') return 'LoginView';
        if (r.name === 'login') return 'LoginView';
        if (r.name === 'password') return 'PasswordView';
        if (r.name === 'share') return 'ShareView';
        if (r.name === 'admin') {
          const m = { channels: 'ChannelsView', models: 'ModelsView', invites: 'InvitesView',
            settings: 'SettingsView', stats: 'StatsView', users: 'UsersView' };
          return m[r.id] || 'ChannelsView';
        }
        const m = { msgs: 'MsgsView', chat: 'ChatView', rooms: 'RoomsView', room: 'RoomView',
          me: 'MeView', friends: 'FriendsView', dm: 'DirectChatView', search: 'SearchView' };
        return m[r.name] || 'MsgsView';
      },
      viewProps() {
        const r = this.r;
        if (['chat', 'room', 'dm', 'share'].includes(r.name)) return { id: r.id };
        return {};
      },
      showTabs() {
        const n = this.r.name;
        return !!LK.state.token && !['login', 'password', 'share'].includes(n);
      },
    },
    template: `<div v-if="ready">
      <component :is="view" v-bind="viewProps" :key="r.raw"/>
      <TabBar v-if="showTabs"/>
      <DrawerHost/><ConfirmHost/><ToastHost/>
    </div>`,
  });
  app.config.globalProperties.LK = LK;
  Object.entries(all).forEach(([name, comp]) => app.component(name, comp));
  app.mount('#app');
})();
