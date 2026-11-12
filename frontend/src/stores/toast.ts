import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface ToastItem { id: number; text: string; kind: 'info' | 'error' | 'success' }

export const useToastStore = defineStore('toast', () => {
  const items = ref<ToastItem[]>([])
  let seq = 0
  function show(text: string, kind: ToastItem['kind'] = 'info', ms = 2600) {
    const id = ++seq
    items.value.push({ id, text, kind })
    setTimeout(() => { items.value = items.value.filter((t) => t.id !== id) }, ms)
  }
  function dismiss(id: number) { items.value = items.value.filter((t) => t.id !== id) }
  return { items, show, dismiss }
})
