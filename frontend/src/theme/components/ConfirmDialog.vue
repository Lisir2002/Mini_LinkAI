<script setup lang="ts">
import { ref, watch } from 'vue'
const props = defineProps<{ open: boolean; title: string; message: string; confirmWord?: string; danger?: boolean }>()
const emit = defineEmits<{ close: []; confirm: [] }>()
const typed = ref('')
watch(() => props.open, (v) => { if (v) typed.value = '' })
</script>
<template>
  <teleport to="body">
    <div v-if="open" class="mask" @click="$emit('close')" />
    <div v-if="open" class="dialog" role="alertdialog">
      <h3>{{ title }}</h3>
      <p>{{ message }}</p>
      <input v-if="confirmWord" v-model="typed" class="word" :placeholder="`输入 ${confirmWord} 以确认`" />
      <div class="acts">
        <button type="button" class="ghost" @click="$emit('close')">取消</button>
        <button type="button" class="go" :class="{ danger }"
                :disabled="!!confirmWord && typed !== confirmWord" @click="$emit('confirm')">确认</button>
      </div>
    </div>
  </teleport>
</template>
<style scoped>
.mask { position: fixed; inset: 0; background: var(--mask); z-index: 300; }
.dialog { position: fixed; top: 50%; left: 50%; transform: translate(-50%,-50%); width: min(320px, 90vw);
  background: var(--surface); border-radius: var(--r-lg); padding: 18px; z-index: 301; }
h3 { font-size: var(--fs-lg); font-weight: 700; }
p { font-size: var(--fs-sm); color: var(--t2); margin: 8px 0 12px; line-height: 1.55; }
.word { width: 100%; padding: 9px 10px; border: 1px solid var(--line); border-radius: var(--r-sm);
  background: var(--surface-2); color: var(--t1); font-size: var(--fs-md); outline: none; margin-bottom: 12px; }
.acts { display: flex; gap: 8px; }
.acts button { flex: 1; padding: 10px 0; border-radius: var(--r-sm); font-size: var(--fs-md);
  font-weight: 600; cursor: pointer; border: 1px solid var(--line-2); background: var(--surface); color: var(--t2); }
.acts .go { background: var(--accent); border-color: transparent; color: #fff; }
.acts .go.danger { background: var(--err); }
.acts .go:disabled { opacity: .5; cursor: not-allowed; }
</style>
