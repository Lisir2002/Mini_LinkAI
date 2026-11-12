// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { icons, LEGACY_MAP } from '../theme/icons'

function vueFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n)
    return statSync(p).isDirectory() ? vueFiles(p) : (p.endsWith('.vue') ? [p] : [])
  })
}

describe('图标源码扫描', () => {
  it('页面中用到的每个静态图标名都能在图标库中找到', () => {
    const used = new Set<string>()
    for (const f of vueFiles('src')) {
      const src = readFileSync(f, 'utf-8')
      for (const m of src.matchAll(/<AppIcon[^>]*\sname="([a-z-]+)"/g)) used.add(m[1])
      for (const m of src.matchAll(/icon: '([a-z-]+)'/g)) used.add(m[1])
      for (const m of src.matchAll(/icon="([a-z-]+)"/g)) used.add(m[1])
      for (const m of src.matchAll(/<AppIcon[^>]*:name="([^"]*)"/g)) {
        // 去掉比较运算的操作数（如 c.type === 'anthropic'），只留真正作为图标名的分支
        const branches = m[1].replace(/[!=]==?\s*'[a-z-]+'/g, '')
        for (const q of branches.matchAll(/'([a-z-]+)'/g)) used.add(q[1])
      }
    }
    const known = new Set([...Object.keys(icons), ...Object.keys(LEGACY_MAP)])
    const missing = [...used].filter((n) => !known.has(n))
    expect(missing, `未定义的图标名: ${missing.join(', ')}`).toEqual([])
    expect(used.size).toBeGreaterThan(25)
  })

  it('工程内不再残留图标字体用法', () => {
    for (const f of vueFiles('src')) {
      expect(readFileSync(f, 'utf-8').includes('material-icons'), f).toBe(false)
    }
    expect(readFileSync('index.html', 'utf-8').includes('fonts.googleapis')).toBe(false)
  })
})
