<script setup lang="ts">
import AppIcon from '../../theme/components/AppIcon.vue'
import NavBar from '../../theme/components/NavBar.vue'
import TabBar from '../../theme/components/TabBar.vue'
import Drawer from '../../theme/components/Drawer.vue'
import EmptyState from '../../theme/components/EmptyState.vue'
import { onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { friendsApi, type FriendItem, type FriendRequest, type UserHit } from '../../interfaces/api/resources'
import { getToken } from '../../interfaces/api/client'
import { DmSocket } from '../../core/composables/dmSocket'
import { useToastStore } from '../../core/stores/toast'

const router = useRouter()
const toast = useToastStore()
const tab = ref<'friends' | 'requests'>('friends')
const friends = ref<FriendItem[]>([])
const incoming = ref<FriendRequest[]>([])
const outgoing = ref<FriendRequest[]>([])
const loading = ref(true)
const adding = ref(false)
const q = ref('')
const hits = ref<UserHit[]>([])
const searching = ref(false)
let searchTimer: number | undefined

async function load() {
  loading.value = true
  try {
    const [fl, rq] = await Promise.all([friendsApi.list(), friendsApi.requests()])
    friends.value = fl
    incoming.value = rq.incoming
    outgoing.value = rq.outgoing
  } catch (e: any) { toast.show(e.message ?? '加载失败', 'error') }
  finally { loading.value = false }
}

function doSearch() {
  window.clearTimeout(searchTimer)
  const k = q.value.trim()
  if (!k) { hits.value = []; return }
  searching.value = true
  searchTimer = window.setTimeout(async () => {
    try { hits.value = await friendsApi.search(k) }
    catch (e: any) { toast.show(e.message ?? '搜索失败', 'error') }
    finally { searching.value = false }
  }, 300)
}

async function addFriend(u: UserHit) {
  try {
    const d = await friendsApi.request(u.id)
    toast.show(d.auto_accepted ? `已和 ${u.nickname} 成为好友` : `已向 ${u.nickname} 发送申请`, 'success')
    adding.value = false
    q.value = ''
    hits.value = []
    await load()
  } catch (e: any) { toast.show(e.message ?? '申请失败', 'error') }
}

async function handle(r: FriendRequest, accept: boolean) {
  try {
    if (accept) await friendsApi.accept(r.id)
    else await friendsApi.reject(r.id)
    toast.show(accept ? `已和 ${r.nickname} 成为好友` : '已拒绝', accept ? 'success' : undefined)
    await load()
  } catch (e: any) { toast.show(e.message ?? '操作失败', 'error') }
}

async function unfriend(f: FriendItem) {
  try {
    await friendsApi.unfriend(f.user_id)
    toast.show(`已删除好友 ${f.nickname}`)
    await load()
  } catch (e: any) { toast.show(e.message ?? '操作失败', 'error') }
}

const socket = new DmSocket({
  token: getToken,
  onDm: () => { void load() },
  onEvent: (e) => {
    if (e.type === 'friend_request') toast.show(`${e.nickname} 请求加你为好友`)
    if (e.type === 'friend_accepted') toast.show(`${e.nickname} 已同意你的好友申请`, 'success')
    if (e.type === 'friend_removed') toast.show(`${e.nickname} 解除了好友关系`)
    void load()
  },
  onFallback: () => {},
})

onMounted(() => { void load(); socket.start() })
onUnmounted(() => socket.stop())
</script>

<template>
  <div class="app-container">
    <NavBar title="好友">
      <template #left>
        <button class="icon-btn" aria-label="返回" @click="router.push('/msgs')">
          <AppIcon name="back" />
        </button>
      </template>
      <template #right>
        <button class="icon-btn" aria-label="添加好友" @click="adding = true">
          <AppIcon name="user-plus" />
        </button>
      </template>
    </NavBar>

    <div class="chips">
      <button class="chip" :class="{ on: tab === 'friends' }" @click="tab = 'friends'">
        好友 {{ friends.length }}
      </button>
      <button class="chip" :class="{ on: tab === 'requests' }" @click="tab = 'requests'">
        新的朋友
        <span v-if="incoming.length" class="badge">{{ incoming.length }}</span>
      </button>
    </div>

    <div class="list">
      <p v-if="loading" class="hint">加载中…</p>
      <template v-else-if="tab === 'friends'">
        <EmptyState v-if="!friends.length" icon="people" title="还没有好友"
                    desc="点右上角搜索昵称或邮箱，发送好友申请">
          <button class="primary sm" @click="adding = true">添加好友</button>
        </EmptyState>
        <article v-for="f in friends" :key="f.user_id" class="friend-row"
                 @click="router.push(`/dm/${f.user_id}`)">
          <span class="ava"><AppIcon name="user" /></span>
          <div class="main">
            <div class="name">{{ f.nickname }}</div>
            <div class="last">{{ f.last_msg ?? '打个招呼吧' }}</div>
          </div>
          <span v-if="f.unread_count" class="unread">{{ f.unread_count }}</span>
          <button class="mini danger" aria-label="删除好友" @click.stop="unfriend(f)">
            <AppIcon name="trash" />
          </button>
        </article>
      </template>
      <template v-else>
        <EmptyState v-if="!incoming.length && !outgoing.length" icon="user-plus"
                    title="暂无好友申请" desc="搜索用户发送申请，或等待别人加你" />
        <p v-if="incoming.length" class="sec">收到的申请</p>
        <article v-for="r in incoming" :key="r.id" class="req-row">
          <span class="ava"><AppIcon name="user" /></span>
          <div class="main"><div class="name">{{ r.nickname }}</div>
            <div class="last">请求加你为好友</div></div>
          <button class="go" @click="handle(r, true)">同意</button>
          <button class="mini" @click="handle(r, false)">拒绝</button>
        </article>
        <p v-if="outgoing.length" class="sec">我发出的</p>
        <article v-for="r in outgoing" :key="r.id" class="req-row">
          <span class="ava"><AppIcon name="user" /></span>
          <div class="main"><div class="name">{{ r.nickname }}</div>
            <div class="last">{{ r.status === 'rejected' ? '已拒绝' : '等待验证' }}</div></div>
        </article>
      </template>
    </div>

    <div class="pad-bottom" />
    <TabBar active="msgs" />

    <Drawer :open="adding" title="添加好友" desc="按昵称或邮箱搜索，发送好友申请"
            @close="adding = false">
      <div class="search">
        <AppIcon name="search" />
        <input v-model="q" placeholder="搜索昵称或邮箱" @input="doSearch" />
      </div>
      <p v-if="searching" class="hint">搜索中…</p>
      <p v-else-if="q.trim() && !hits.length" class="hint">没有找到匹配的用户</p>
      <article v-for="u in hits" :key="u.id" class="user-row">
        <span class="ava"><AppIcon name="user" /></span>
        <div class="main">
          <div class="name">{{ u.nickname }}</div>
          <div class="last">{{ u.email ?? '' }}</div>
        </div>
        <button class="go" @click="addFriend(u)">申请</button>
      </article>
    </Drawer>
  </div>
</template>

<style scoped>
.icon-btn { background: none; border: none; color: var(--t2); cursor: pointer; padding: 6px; }
.chips { display: flex; gap: 8px; padding: 10px 12px 4px; }
.chip { position: relative; padding: 7px 16px; border: 1px solid var(--line); border-radius: 18px;
  background: var(--surface); color: var(--t3); font-size: var(--fs-md); cursor: pointer; }
.chip.on { background: var(--accent-soft); border-color: var(--accent); color: var(--accent); font-weight: 700; }
.badge { position: absolute; top: -5px; right: -5px; min-width: 17px; height: 17px; border-radius: 9px;
  background: var(--err); color: #fff; font-size: 10px; line-height: 17px; text-align: center; padding: 0 4px; }
.list { flex: 1; overflow-y: auto; }
.hint { padding: 20px; text-align: center; color: var(--t4); font-size: var(--fs-sm); }
.sec { padding: 10px 14px 4px; font-size: var(--fs-cap); font-weight: 700; color: var(--t3); }
.friend-row, .req-row, .user-row { display: flex; align-items: center; gap: 10px; padding: 11px 14px;
  background: var(--surface); border-bottom: 1px solid var(--line); cursor: pointer; }
.req-row, .user-row { cursor: default; }
.ava { width: 38px; height: 38px; border-radius: 10px; background: var(--accent-soft); color: var(--accent);
  display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.ava .app-icon { width: 20px; height: 20px; }
.main { flex: 1; min-width: 0; }
.name { font-size: var(--fs-lg); font-weight: 600; }
.last { font-size: var(--fs-sm); color: var(--t3); margin-top: 2px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.unread { min-width: 19px; height: 19px; border-radius: 10px; background: var(--err); color: #fff;
  font-size: 11px; line-height: 19px; text-align: center; padding: 0 5px; flex-shrink: 0; }
.go { padding: 6px 14px; border: none; border-radius: var(--r-sm); background: var(--accent);
  color: #fff; font-size: var(--fs-cap); font-weight: 700; cursor: pointer; flex-shrink: 0; }
.mini { background: none; border: none; color: var(--t4); cursor: pointer; padding: 4px; flex-shrink: 0; }
.mini .app-icon { width: 16px; height: 16px; }
.mini.danger:hover { color: var(--err); }
.search { position: relative; margin-bottom: 8px; }
.search .app-icon { position: absolute; left: 10px; top: 50%; transform: translateY(-50%);
  width: 16px; height: 16px; color: var(--t4); }
.search input { width: 100%; padding: 9px 10px 9px 32px; background: var(--surface-2);
  border: 1px solid var(--line); border-radius: var(--r-sm); color: var(--t1);
  font-size: var(--fs-md); outline: none; }
.primary { width: 100%; padding: 12px 0; border: none; border-radius: var(--r-sm); background: var(--accent);
  color: #fff; font-size: var(--fs-lg); font-weight: 600; cursor: pointer; }
.primary.sm { width: auto; padding: 8px 18px; font-size: var(--fs-md); margin-top: 12px; }
.pad-bottom { height: 72px; }
</style>