import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { icons, LEGACY_MAP, resolveIcon } from '../icons'
import AppIcon from '../components/common/AppIcon.vue'

describe('自绘 SVG 图标库', () => {
  it('每个图标都有图形，且不含外部字体依赖', () => {
    const names = Object.keys(icons)
    expect(names.length).toBeGreaterThanOrEqual(40)
    for (const n of names) {
      const shapes = icons[n as keyof typeof icons]
      expect(shapes.length).toBeGreaterThan(0)
      for (const s of shapes) {
        expect(['path', 'circle', 'rect', 'line', 'polyline', 'polygon', 'ellipse']).toContain(s.tag)
      }
    }
  })

  it('旧图标名全部映射到存在的自绘图标', () => {
    for (const [legacy, target] of Object.entries(LEGACY_MAP)) {
      expect(icons[target], `${legacy} → ${target} 不存在`).toBeTruthy()
    }
  })

  it('未知名称回退到警示图标而不是渲染空白', () => {
    expect(resolveIcon('totally-unknown')).toEqual(icons.warning)
  })

  it('渲染为内联 svg，颜色继承 currentColor', () => {
    const w = mount(AppIcon, { props: { name: 'robot', size: 24 } })
    const svg = w.find('svg')
    expect(svg.exists()).toBe(true)
    expect(svg.attributes('viewBox')).toBe('0 0 24 24')
    expect(svg.attributes('stroke')).toBe('currentColor')
    expect(svg.attributes('width')).toBe('24')
    expect(svg.findAll('circle').length).toBeGreaterThan(0)
    expect(w.find('span.material-icons').exists()).toBe(false)
  })

  it('传入 title 时提供无障碍名称，否则 aria-hidden', () => {
    expect(mount(AppIcon, { props: { name: 'send', title: '发送' } }).find('svg').attributes('aria-label')).toBe('发送')
    expect(mount(AppIcon, { props: { name: 'send' } }).find('svg').attributes('aria-hidden')).toBe('true')
  })

})
