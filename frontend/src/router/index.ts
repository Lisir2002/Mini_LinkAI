import { createRouter, createWebHistory, type Router } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { request } from '../api/client'


export function buildRouter(): Router {
  const router = createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/', redirect: '/msgs' },
      { path: '/login', component: () => import('../views/mobile/Login.vue') },
      { path: '/password', component: () => import('../views/mobile/Password.vue'), meta: { requiresAuth: true, allowPasswordGate: true } },
      { path: '/msgs', component: () => import('../views/mobile/Msgs.vue'), meta: { requiresAuth: true } },
      { path: '/rooms', component: () => import('../views/mobile/Rooms.vue'), meta: { requiresAuth: true } },
      { path: '/me', component: () => import('../views/mobile/Me.vue'), meta: { requiresAuth: true } },
      { path: '/friends', component: () => import('../views/mobile/Friends.vue'), meta: { requiresAuth: true } },
      { path: '/dm/:userId', component: () => import('../views/mobile/DirectChat.vue'), meta: { requiresAuth: true } },
      { path: '/c/:id', component: () => import('../views/mobile/Chat.vue'), meta: { requiresAuth: true } },
      { path: '/r/:id', component: () => import('../views/mobile/Room.vue'), meta: { requiresAuth: true } },
      { path: '/s/:token', component: () => import('../views/mobile/ShareView.vue') },
      { path: '/403', component: () => import('../views/mobile/Forbidden.vue') },
      { path: '/admin', redirect: '/admin/channels' },
      { path: '/admin/channels', component: () => import('../views/admin/Channels.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
      { path: '/admin/models', component: () => import('../views/admin/Models.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
      { path: '/admin/invites', component: () => import('../views/admin/Invites.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
      { path: '/admin/settings', component: () => import('../views/admin/Settings.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
      { path: '/admin/stats', component: () => import('../views/admin/Stats.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
      { path: '/admin/experiments', component: () => import('../views/admin/Experiments.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
      { path: '/:pathMatch(.*)*', redirect: '/msgs' },
    ],
  })

  router.beforeEach(async (to) => {
    const auth = useAuthStore()
    // 整页刷新后 Pinia 状态清空，但 token 仍在 localStorage：
    // 必须先用 token 回拉用户信息，否则角色判断会误判为无权限。
    if (auth.token && !auth.user) {
      try {
        const me = await request<any>('/api/auth/me')
        auth.setUser(me.data)
      } catch {
        auth.logout()
      }
    }
    const logged = Boolean(auth.token)
    if (to.path === '/login' && logged) return { path: '/msgs' }
    if (to.meta.requiresAuth && !logged) return { path: '/login', query: { redirect: to.fullPath } }
    if (logged && auth.user?.must_change_password && !to.meta.allowPasswordGate && to.path !== '/login')
      return { path: '/password' }
    if (to.meta.requiresAdmin && auth.user?.role !== 'admin') return { path: '/403' }
    return true
  })
  return router
}
