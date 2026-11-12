import { createRouter, createWebHistory, type Router } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { request } from '../../interfaces/api/client'


export function buildRouter(): Router {
  const router = createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/', redirect: '/msgs' },
      { path: '/login', component: () => import('../../users/views/Login.vue') },
      { path: '/password', component: () => import('../../users/views/Password.vue'), meta: { requiresAuth: true, allowPasswordGate: true } },
      { path: '/msgs', component: () => import('../../users/views/Msgs.vue'), meta: { requiresAuth: true } },
      { path: '/rooms', component: () => import('../../users/views/Rooms.vue'), meta: { requiresAuth: true } },
      { path: '/me', component: () => import('../../users/views/Me.vue'), meta: { requiresAuth: true } },
      { path: '/friends', component: () => import('../../users/views/Friends.vue'), meta: { requiresAuth: true } },
      { path: '/dm/:userId', component: () => import('../../users/views/DirectChat.vue'), meta: { requiresAuth: true } },
      { path: '/c/:id', component: () => import('../../llm/views/Chat.vue'), meta: { requiresAuth: true } },
      { path: '/r/:id', component: () => import('../../users/views/Room.vue'), meta: { requiresAuth: true } },
      { path: '/s/:token', component: () => import('../../files/views/ShareView.vue') },
      { path: '/403', component: () => import('../../users/views/Forbidden.vue') },
      { path: '/admin', redirect: '/admin/channels' },
      { path: '/admin/channels', component: () => import('../../llm/views/Channels.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
      { path: '/admin/models', component: () => import('../../llm/views/Models.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
      { path: '/admin/invites', component: () => import('../../admin/views/Invites.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
      { path: '/admin/settings', component: () => import('../../admin/views/Settings.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
      { path: '/admin/stats', component: () => import('../../stats/views/Stats.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
      { path: '/admin/experiments', component: () => import('../../stats/views/Experiments.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
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
