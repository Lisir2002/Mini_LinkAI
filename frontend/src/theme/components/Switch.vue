<script setup lang="ts">
const props = defineProps<{ modelValue: boolean; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [boolean] }>()
function toggle() { if (!props.disabled) emit('update:modelValue', !props.modelValue) }
</script>
<template>
  <button type="button" class="switch" :class="{ on: modelValue, disabled }" role="switch"
          :aria-checked="modelValue" @click="toggle"><i /></button>
</template>
<style scoped>
.switch { width: 36px; height: 20px; border-radius: 10px; background: var(--line-2); position: relative;
  cursor: pointer; border: none; padding: 0; transition: background .2s; flex-shrink: 0; }
.switch.on { background: var(--accent); }
.switch.disabled { opacity: .5; cursor: not-allowed; }
.switch i { position: absolute; top: 2px; left: 2px; width: 16px; height: 16px; border-radius: 50%;
  background: #fff; transition: left .2s; box-shadow: 0 1px 2px rgba(0,0,0,.2); }
.switch.on i { left: 18px; }
</style>
