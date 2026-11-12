import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { buildRouter } from './router'
import { useThemeStore } from './stores/theme'
import { onUnauthorized } from './api/client'
import './styles/tokens.css'
import './styles/base.css'

const app = createApp(App)
app.use(createPinia())
const router = buildRouter()
app.use(router)
useThemeStore().init()
onUnauthorized(() => { void router.push('/login') })
app.mount('#app')
