import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { buildRouter } from './core/router'
import { useThemeStore } from './theme/store'
import { onUnauthorized } from './interfaces/api/client'
import './theme/tokens.css'
import './theme/base.css'

const app = createApp(App)
app.use(createPinia())
const router = buildRouter()
app.use(router)
useThemeStore().init()
onUnauthorized(() => { void router.push('/login') })
app.mount('#app')
