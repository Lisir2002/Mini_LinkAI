import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

vi.mock('../interfaces/api/client', () => ({
  request: vi.fn(),
  getToken: () => 'tok',
  ApiError: class extends Error {},
}))
import { uploadsApi } from '../interfaces/api/resources'
import AuthImage from '../files/components/AuthImage.vue'

class FakeXHR {
  static last: FakeXHR | null = null
  upload: { onprogress: ((e: { loaded: number; total: number }) => void) | null } = { onprogress: null }
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  status = 200
  responseText = JSON.stringify({ code: 0, data: { id: 7, url: '/api/uploads/7/content', filename: 'a.png', content_type: 'image/png', size_bytes: 10, kind: 'image' } })
  method = ''
  url = ''
  headers: Record<string, string> = {}
  body: unknown = null
  open(method: string, url: string) { this.method = method; this.url = url }
  setRequestHeader(k: string, v: string) { this.headers[k] = v }
  send(body: unknown) { this.body = body; FakeXHR.last = this }
}

beforeEach(() => { vi.stubGlobal('XMLHttpRequest', FakeXHR) })
afterEach(() => { vi.unstubAllGlobals() })

describe('uploadsApi.upload', () => {
  it('multipart POST 带鉴权头并回报进度', async () => {
    const progress: number[] = []
    const file = new File([new Uint8Array([1, 2, 3])], 'a.png', { type: 'image/png' })
    const p = uploadsApi.upload(file, (pct) => progress.push(pct))
    const xhr = FakeXHR.last!
    expect(xhr.method).toBe('POST')
    expect(xhr.url).toContain('/api/uploads')
    expect(xhr.headers.Authorization).toBe('Bearer tok')
    expect(xhr.body).toBeInstanceOf(FormData)
    xhr.upload.onprogress!({ loaded: 50, total: 100 })
    expect(progress).toEqual([50])
    xhr.onload!()
    const d = await p
    expect(d.id).toBe(7)
  })

  it('非 200 抛出错误', async () => {
    const file = new File([new Uint8Array([1])], 'a.png')
    const p = uploadsApi.upload(file, () => {})
    FakeXHR.last!.status = 413
    FakeXHR.last!.responseText = JSON.stringify({ code: 'UPLOAD_TOO_LARGE', message: '文件不能超过 10MB' })
    FakeXHR.last!.onload!()
    await expect(p).rejects.toThrow('文件不能超过 10MB')
  })
})

describe('AuthImage 鉴权图片', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true, blob: async () => new Blob(['x'], { type: 'image/png' }),
    })))
    vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:fake'), revokeObjectURL: vi.fn() })
  })
  afterEach(() => { vi.unstubAllGlobals() })

  it('带 token 拉取并渲染 blob 图片', async () => {
    const w = mount(AuthImage, { props: { uploadId: 7 }, global: { stubs: { teleport: true } } })
    await flushPromises()
    const img = w.find('img')
    expect(img.exists()).toBe(true)
    expect(img.attributes('src')).toBe('blob:fake')
    const call = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(call[0]).toContain('/api/uploads/7/content')
    expect(call[1].headers.Authorization).toBe('Bearer tok')
  })

  it('点击放大查看', async () => {
    const w = mount(AuthImage, { props: { uploadId: 7 }, attachTo: document.body })
    await flushPromises()
    await w.find('img').trigger('click')
    await flushPromises()
    const box = document.body.querySelector('.lightbox')
    expect(box).not.toBeNull()
    box!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(document.body.querySelector('.lightbox')).toBeNull()
    w.unmount()
  })
})
