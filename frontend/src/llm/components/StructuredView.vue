<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ mode: string; content: string }>()

function stripFences(text: string): { body: string; lang: string } {
  const t = text.trim()
  if (!t.startsWith('```')) return { body: t, lang: '' }
  const lines = t.split('\n')
  const lang = lines[0].slice(3).trim()
  let body = lines.slice(1)
  if (body.length && body[body.length - 1].trim().startsWith('```')) body = body.slice(0, -1)
  return { body: body.join('\n').trim(), lang }
}

const parsed = computed(() => {
  if (props.mode !== 'json') return null
  try { return JSON.parse(stripFences(props.content).body) } catch { return null }
})

interface Token { text: string; cls: string }
const jsonTokens = computed<Token[]>(() => {
  if (parsed.value === null) return []
  const pretty = JSON.stringify(parsed.value, null, 2)
  const out: Token[] = []
  const re = /("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g
  let last = 0
  for (const m of pretty.matchAll(re)) {
    const i = m.index ?? 0
    if (i > last) out.push({ text: pretty.slice(last, i), cls: '' })
    if (m[1] !== undefined) out.push({ text: m[1] + (m[2] ?? ''), cls: m[2] ? 'tk-key' : 'tk-str' })
    else if (m[3] !== undefined) out.push({ text: m[3], cls: 'tk-bool' })
    else out.push({ text: m[0], cls: 'tk-num' })
    last = i + m[0].length
  }
  if (last < pretty.length) out.push({ text: pretty.slice(last), cls: '' })
  return out
})

const tableData = computed(() => {
  if (props.mode !== 'table') return null
  const rows = props.content.trim().split('\n')
    .map((l) => l.trim())
    .filter((l) => l.startsWith('|'))
    .map((l) => l.replace(/^\||\|$/g, '').split('|').map((c) => c.trim()))
  const body = rows.filter((r) => !r.every((c) => /^:?-{2,}:?$/.test(c)))
  if (body.length < 1) return null
  return { head: body[0], rows: body.slice(1) }
})

const codeData = computed(() => {
  if (props.mode !== 'code') return null
  const { body, lang } = stripFences(props.content)
  return { body, lang: lang || 'text' }
})
</script>

<template>
  <pre v-if="mode === 'json' && parsed !== null" class="sv-json"><template
    v-for="(t, i) in jsonTokens" :key="i"><span v-if="t.cls" :class="t.cls">{{ t.text }}</span><template v-else>{{ t.text }}</template></template></pre>
  <table v-else-if="mode === 'table' && tableData" class="sv-table">
    <thead><tr><th v-for="(h, i) in tableData.head" :key="i">{{ h }}</th></tr></thead>
    <tbody>
      <tr v-for="(r, i) in tableData.rows" :key="i">
        <td v-for="(c, j) in r" :key="j">{{ c }}</td>
      </tr>
    </tbody>
  </table>
  <div v-else-if="mode === 'code' && codeData" class="sv-code">
    <span class="sv-lang">{{ codeData.lang }}</span>
    <pre><code>{{ codeData.body }}</code></pre>
  </div>
  <pre v-else class="sv-plain">{{ content }}</pre>
</template>

<style scoped>
.sv-json, .sv-plain { margin: 0; white-space: pre-wrap; word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; line-height: 1.6; }
.tk-key { color: var(--accent); font-weight: 600; }
.tk-str { color: var(--ok, #16a34a); }
.tk-num { color: var(--warn, #d97706); }
.tk-bool { color: var(--err, #dc2626); }
.sv-table { border-collapse: collapse; width: 100%; font-size: 12px; }
.sv-table th, .sv-table td { border: 1px solid var(--line); padding: 5px 8px; text-align: left; }
.sv-table th { background: var(--surface-2); font-weight: 700; }
.sv-code { position: relative; }
.sv-lang { position: absolute; top: 4px; right: 6px; font-size: 10px; color: var(--t4);
  background: var(--surface-2); border-radius: 4px; padding: 1px 6px; }
.sv-code pre { margin: 0; padding: 8px; background: var(--surface-2); border-radius: 6px;
  overflow-x: auto; font-size: 12px; line-height: 1.6; }
</style>