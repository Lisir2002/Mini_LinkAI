import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import StructuredView from '../llm/components/StructuredView.vue'

vi.mock('../interfaces/api/client', () => ({
  request: vi.fn(),
  getToken: () => 't',
  ApiError: class extends Error {},
}))
import { request } from '../interfaces/api/client'
import { roomsApi } from '../interfaces/api/rooms'

const mockReq = request as unknown as ReturnType<typeof vi.fn>

describe('StructuredView 结构化渲染（无 v-html）', () => {
  it('json 模式渲染键值与类型着色', () => {
    const w = mount(StructuredView, {
      props: { mode: 'json', content: '{"answer":"你好","count":3,"ok":true}' },
    })
    expect(w.find('.sv-json').exists()).toBe(true)
    expect(w.text()).toContain('answer')
    expect(w.text()).toContain('你好')
    expect(w.find('.tk-key').exists()).toBe(true)
    expect(w.find('.tk-num').exists()).toBe(true)
    expect(w.find('.tk-bool').exists()).toBe(true)
    expect(w.html()).not.toContain('v-html')
  })

  it('json 模式容忍代码围栏', () => {
    const w = mount(StructuredView, {
      props: { mode: 'json', content: '```json\n{"a":1}\n```' },
    })
    expect(w.find('.sv-json').exists()).toBe(true)
  })

  it('json 解析失败回退纯文本', () => {
    const w = mount(StructuredView, { props: { mode: 'json', content: '不是JSON' } })
    expect(w.find('.sv-plain').exists()).toBe(true)
  })

  it('table 模式解析 Markdown 表格', () => {
    const md = '| 名称 | 数量 |\n| --- | --- |\n| 苹果 | 3 |\n| 梨 | 5 |'
    const w = mount(StructuredView, { props: { mode: 'table', content: md } })
    expect(w.findAll('thead th').map((x) => x.text())).toEqual(['名称', '数量'])
    expect(w.findAll('tbody tr')).toHaveLength(2)
    expect(w.findAll('tbody td')[2].text()).toBe('梨')
  })

  it('code 模式提取语言与代码体', () => {
    const w = mount(StructuredView, {
      props: { mode: 'code', content: '```python\nprint("hi")\n```' },
    })
    expect(w.find('.sv-lang').text()).toBe('python')
    expect(w.find('code').text()).toContain('print("hi")')
  })

  it('free 模式直接纯文本', () => {
    const w = mount(StructuredView, { props: { mode: 'free', content: '普通文本' } })
    expect(w.find('.sv-plain').exists()).toBe(true)
  })
})

describe('roomsApi.patch', () => {
  beforeEach(() => mockReq.mockReset())
  it('PATCH 房间设置到正确路径', async () => {
    mockReq.mockResolvedValue({ data: { updated: true } })
    await roomsApi.patch(9, { output_mode: 'json', output_schema: '{"type":"object"}' })
    expect(mockReq).toHaveBeenCalledWith('/api/rooms/9', {
      method: 'PATCH',
      body: { output_mode: 'json', output_schema: '{"type":"object"}' },
    })
  })
})