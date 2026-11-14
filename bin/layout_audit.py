#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐页 × 逐宽度体检：横向溢出、元素越界、切割点定位（真实 Chromium）"""
import json, os, sys, urllib.request, urllib.error
from playwright.sync_api import sync_playwright

DRAWER_ONLY = '--drawer-only' in sys.argv
BASE = os.environ.get('LK_BASE', 'http://127.0.0.1:8080')
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SHOTS = os.environ.get('LK_AUDIT_SHOTS', os.path.join(ROOT, 'audit_shots'))
OUT_JSON = os.path.join(ROOT, 'logs', 'layout_audit.json')
os.makedirs(SHOTS, exist_ok=True)
os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)

def req(path, method='GET', body=None, token=None):
    h = {'Content-Type': 'application/json'}
    if token: h['Authorization'] = 'Bearer ' + token
    r = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body else None,
                               headers=h, method=method)
    with urllib.request.urlopen(r, timeout=30) as x: return json.loads(x.read())

# 拿一个可用 token（登录 → 若强制改密则改掉）
d = req('/api/auth/login', 'POST', {'account': 'admin@demo.com', 'password': 'AdminPass2026'})['data']
tok = d['token']
if d['user']['must_change_password']:
    tok = req('/api/auth/password', 'POST',
              {'old_password': 'AdminPass2026', 'new_password': 'AdminPass2026'}, tok)['data']['token']

# 准备一个会话和一个房间，保证聊天页/房间页有真实内容
conv = req('/api/conversations', 'POST', {'title': '布局体检用会话'}, tok)['data']['item']['id']
rooms = req('/api/rooms', token=tok)['data']['items']
rid = rooms[0]['id'] if rooms else 1
req('/api/rooms/%d/join' % rid, 'POST', {}, tok)

ROUTES = [
    ('登录页', '#/login', False), ('改密页', '#/password', True),
    ('消息列表', '#/msgs', True), ('AI 对话', '#/chat/%d' % conv, True),
    ('房间广场', '#/rooms', True), ('房间详情', '#/room/%d' % rid, True),
    ('我的', '#/me', True), ('好友与私聊', '#/friends', True),
    ('全局搜索', '#/search', True), ('渠道配置', '#/admin/channels', True),
    ('模型注册表', '#/admin/models', True), ('邀请码', '#/admin/invites', True),
    ('系统设置', '#/admin/settings', True), ('数据统计', '#/admin/stats', True),
    ('用户管理', '#/admin/users', True),
]
WIDTHS = [320, 360, 375, 390, 414, 768, 1024, 1440]

AUDIT_JS = r"""() => {
  const vw = document.documentElement.clientWidth;
  const de = document.documentElement, bd = document.body;
  const bad = [];
  const all = document.querySelectorAll('body *');
  for (const el of all) {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const overRight = r.right - vw;
    const overLeft = -r.left;
    if (overRight > 1.5 || overLeft > 1.5) {
      bad.push({
        tag: el.tagName.toLowerCase(),
        cls: (el.className && typeof el.className === 'string') ? el.className.slice(0, 60) : '',
        txt: (el.innerText || '').trim().slice(0, 28),
        right: Math.round(r.right), left: Math.round(r.left),
        w: Math.round(r.width), overRight: Math.round(overRight), overLeft: Math.round(overLeft),
        pos: cs.position, white: cs.whiteSpace
      });
    }
  }
  return {
    vw, docOverflow: de.scrollWidth - de.clientWidth, bodyOverflow: bd.scrollWidth - bd.clientWidth,
    bad: bad.slice(0, 12), badCount: bad.length,
    composer: (() => { const e = document.querySelector('.composer'); if (!e) return null;
      const r = e.getBoundingClientRect(); return {right: Math.round(r.right), w: Math.round(r.width)}; })(),
    nav: (() => { const e = document.querySelector('.nav'); if (!e) return null;
      const r = e.getBoundingClientRect(); return {right: Math.round(r.right), w: Math.round(r.width)}; })(),
    tabbar: (() => { const e = document.querySelector('.tabbar'); if (!e) return null;
      const r = e.getBoundingClientRect(); return {right: Math.round(r.right), w: Math.round(r.width)}; })(),
  };
}"""

report = {'token_ok': bool(tok), 'routes': [], 'verdict': {}}
problems = []

exe = '/usr/local/bin/chromium'
if not os.path.exists(exe): exe = '/usr/bin/google-chrome'

with sync_playwright() as pw:
    b = pw.chromium.launch(headless=True, executable_path=exe,
                           args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'])
    ctx = b.new_context(viewport={'width': 375, 'height': 780})
    ctx.add_init_script("localStorage.setItem('chatroom-token', '%s');" % tok)
    page = ctx.new_page()
    console_errs = []
    page.on('pageerror', lambda e: console_errs.append(str(e)))
    page.on('console', lambda m: console_errs.append(m.text) if m.type == 'error' else None)

    for label, route, need_auth in ([] if DRAWER_ONLY else ROUTES):
        # 登录页不该带 token，单独用无 token 上下文
        if not need_auth:
            continue
        for w in WIDTHS:
            page.set_viewport_size({'width': w, 'height': 780 if w < 768 else 900})
            page.goto(BASE + '/' + route, wait_until='domcontentloaded', timeout=30000)
            page.wait_for_timeout(500)
            try:
                a = page.evaluate(AUDIT_JS)
            except Exception as e:
                a = {'error': str(e)}
                problems.append('%s@%d evaluate: %s' % (label, w, e))
            rec = {'page': label, 'width': w, **a}
            report['routes'].append(rec)
            flag = (a.get('docOverflow', 0) > 1 or a.get('bodyOverflow', 0) > 1 or a.get('badCount', 0) > 0)
            if flag:
                problems.append('%s @ %dpx: doc+%d body+%d bad=%d %s' % (
                    label, w, a.get('docOverflow', 0), a.get('bodyOverflow', 0), a.get('badCount', 0),
                    json.dumps(a.get('bad', [])[:3], ensure_ascii=False)))
            print('%s %-14s %4dpx  doc=%+d body=%+d bad=%d' % (
                'WARN' if flag else ' OK ', label, w, a.get('docOverflow', 0),
                a.get('bodyOverflow', 0), a.get('badCount', 0)))
            if w in (320, 375, 1440):
                page.screenshot(path=os.path.join(SHOTS, '%s_%d.png' % (label.replace('/', '_'), w)))

    # 抽屉 / 弹层在窄屏下单独体检
    for w in (320, 375, 414):
        page.set_viewport_size({'width': w, 'height': 780})
        page.goto(BASE + '/#/admin/channels', wait_until='domcontentloaded')
        # 同 hash 的 goto 是 same-document navigation，不会重建 Vue 组件，
        # 上一轮打开的抽屉会挡住按钮，必须显式关闭
        page.evaluate("if(window.LK){LK.closeDrawer();LK.closeConfirm();LK.state.toast=null;}")
        page.wait_for_timeout(900)
        try:
            page.wait_for_selector('button.btn.primary', state='visible', timeout=10000)
            page.locator('button.btn.primary').filter(has_text='添加接口').first.click(timeout=10000)
            page.wait_for_timeout(350)
            a = page.evaluate(AUDIT_JS)
            report['routes'].append({'page': '渠道抽屉', 'width': w, **a})
            flag = a.get('docOverflow', 0) > 1 or a.get('badCount', 0) > 0
            if flag: problems.append('渠道抽屉 @ %dpx: %s' % (w, json.dumps(a.get('bad', [])[:3], ensure_ascii=False)))
            print('%s %-14s %4dpx  doc=%+d bad=%d' % ('WARN' if flag else ' OK ', '渠道抽屉', w,
                  a.get('docOverflow', 0), a.get('badCount', 0)))
            page.screenshot(path=os.path.join(SHOTS, '渠道抽屉_%d.png' % w))
        except Exception as e:
            problems.append('渠道抽屉 @ %dpx 打不开: %s' % (w, str(e)[:120]))

    # 登录页（无 token）：复用同一 context，避免第二个浏览器上下文偶发启动超时
    p2 = page
    for w in (320, 375, 1440):
        p2.set_viewport_size({'width': w, 'height': 780})
        p2.goto(BASE + '/#/login', wait_until='domcontentloaded')
        p2.evaluate("localStorage.removeItem('chatroom-token'); if(window.LK){LK.state.token=null;LK.state.user=null;LK.closeDrawer();LK.closeConfirm();LK.go('#/login');}")
        p2.wait_for_timeout(700)
        a = p2.evaluate(AUDIT_JS)
        report['routes'].append({'page': '登录页', 'width': w, **a})
        flag = a.get('docOverflow', 0) > 1 or a.get('badCount', 0) > 0
        if flag: problems.append('登录页 @ %dpx: %s' % (w, json.dumps(a.get('bad', [])[:3], ensure_ascii=False)))
        print('%s %-14s %4dpx  doc=%+d bad=%d' % ('WARN' if flag else ' OK ', '登录页', w,
              a.get('docOverflow', 0), a.get('badCount', 0)))

    report['console_errors'] = [e for e in console_errs if 'favicon' not in e.lower()]
    b.close()

report['problems'] = problems
report['verdict'] = {
    'checks': len(report['routes']),
    'problem_checks': len(problems),
    'console_errors': len(report['console_errors']),
}
with open(OUT_JSON, 'w', encoding='utf-8') as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print('\n=== 汇总 ===', json.dumps(report['verdict'], ensure_ascii=False))
for p in problems[:30]: print('  ISSUE', p[:300])
