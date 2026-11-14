#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""真实跑一遍站点：API 全链路 + 浏览器三宽度截图，逐项记录，不假装成功。"""
import json, os, sys, time, urllib.request, urllib.error, urllib.parse, traceback

BASE = 'http://127.0.0.1:8080'
OUT = '/data/workspace/linkai-site/logs'
SHOTS = '/data/workspace/screenshots'
os.makedirs(SHOTS, exist_ok=True)
report = {'api': [], 'browser': [], 'screenshots': [], 'issues': []}

def req(path, method='GET', body=None, token=None, timeout=30, raw=False):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {'Content-Type': 'application/json'}
    if token: headers['Authorization'] = 'Bearer ' + token
    r = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            b = resp.read()
            return resp.status, (b if raw else (json.loads(b) if b else {})), None
    except urllib.error.HTTPError as e:
        b = e.read()
        try: j = json.loads(b)
        except Exception: j = {'raw': b[:200].decode('utf-8', 'ignore')}
        return e.code, j, None
    except Exception as e:
        return 0, {}, str(e)

def check(name, fn):
    try:
        ok, detail = fn()
        report['api'].append({'name': name, 'ok': bool(ok), 'detail': detail})
        print(('  PASS  ' if ok else '  FAIL  ') + name + '  ' + str(detail)[:160])
        if not ok: report['issues'].append(name + ': ' + str(detail)[:200])
        return ok
    except Exception as e:
        report['api'].append({'name': name, 'ok': False, 'detail': traceback.format_exc()[-400:]})
        print('  ERROR ' + name + ' ' + str(e))
        report['issues'].append(name + ': ' + str(e))
        return False

print('=== A. API 全链路 ===')
# 每次都恢复到「首次登录强制改密」，保证断言可重复执行
import subprocess
_S = '/data/workspace/linkai-site'
_restore = ('require "' + _S + '/src/db.php"; '
            'q("UPDATE users SET must_change_password=1 WHERE email=?", ["admin@demo.com"]);')
try:
    subprocess.run([_S + '/.runtime/bin/php', '-c', _S + '/.runtime/php.ini', '-r', _restore],
                   env=dict(os.environ, LD_LIBRARY_PATH=_S + '/.runtime/lib'),
                   capture_output=True, timeout=20)
except Exception as _e:
    print('  (恢复演示状态失败，可忽略:', str(_e)[:80], ')')
st, j, _ = req('/api/health')
check('健康检查', lambda: (st == 200 and j.get('data', {}).get('db') == 'ok', j.get('data')))

st, j, _ = req('/api/auth/login', 'POST', {'account': 'admin@demo.com', 'password': 'AdminPass2026'})
login = j.get('data') or {}
tok0 = login.get('token')
check('管理员登录', lambda: (st == 200 and bool(tok0) and login.get('user', {}).get('must_change_password') is True,
                            {'status': st, 'role': login.get('user', {}).get('role'), 'must_change': login.get('user', {}).get('must_change_password')}))

def guard():
    s, x, _ = req('/api/conversations', token=tok0)
    return s == 403 and x.get('code') == 'PASSWORD_CHANGE_REQUIRED', {'status': s, 'code': x.get('code')}
check('未改密守卫拦截', guard)

st, j, _ = req('/api/auth/password', 'POST',
               {'old_password': 'AdminPass2026', 'new_password': 'AdminPass2026'}, token=tok0)
tok = (j.get('data') or {}).get('token') or tok0
check('首次强制改密', lambda: (st == 200 and bool((j.get('data') or {}).get('token')) and
                            (j.get('data') or {}).get('user', {}).get('must_change_password') is False,
                            {'status': st, 'code': j.get('code')}))

def me():
    s, x, _ = req('/api/auth/me', token=tok)
    d = x.get('data') or {}
    return s == 200 and len(d.get('models') or []) >= 1, {'status': s, 'models': len(d.get('models') or []), 'features': d.get('features')}
check('个人信息 / 模型 / 配额', me)

st, j, _ = req('/api/admin/channels', token=tok)
channels = (j.get('data') or {}).get('items') or []
cid = channels[0]['id'] if channels else None
check('管理端渠道列表', lambda: (st == 200 and len(channels) >= 1, {'count': len(channels), 'first': channels[0]['name'] if channels else None}))

if cid:
    def probe():
        s, x, _ = req('/api/admin/channels/%d/probe' % cid, 'POST', {}, token=tok, timeout=40)
        return s == 200 and (x.get('data') or {}).get('ok') is True, {'status': s, 'data': x.get('data'), 'msg': x.get('message')}
    check('渠道连通性测试（回调本机 mock）', probe)
    def sync():
        s, x, _ = req('/api/admin/channels/%d/sync' % cid, 'POST', {}, token=tok, timeout=40)
        return s == 200 and len((x.get('data') or {}).get('models') or []) >= 1, {'status': s, 'data': x.get('data')}
    check('同步上游模型', sync)

st, j, _ = req('/api/admin/models', token=tok)
models = (j.get('data') or {}).get('items') or []
mid = next((m['id'] for m in models if m.get('is_default')), models[0]['id'] if models else None)
check('模型注册表', lambda: (st == 200 and len(models) >= 1 and
                          any(m.get('channels') for m in models), {'count': len(models), 'with_bindings': sum(1 for m in models if m.get('channels'))}))

st, j, _ = req('/api/conversations', 'POST', {'title': '端到端验证会话'}, token=tok,
               )
# 带幂等键再来一次
conv_id = (j.get('data') or {}).get('item', {}).get('id')
check('新建会话', lambda: (st == 201 and bool(conv_id), {'status': st, 'id': conv_id, 'code': j.get('code')}))

if conv_id:
    def sse():
        s, x, err = req('/api/conversations/%d/completions' % conv_id, 'POST',
                        {'content': '你好，请用一句话介绍你自己', 'model_id': mid}, token=tok, timeout=90, raw=True)
        text = x.decode('utf-8', 'ignore') if isinstance(x, bytes) else str(x)
        has_meta = 'event: meta' in text
        has_delta = 'event: delta' in text
        has_usage = 'event: usage' in text
        has_done = 'event: done' in text
        has_err = 'event: error' in text
        return s == 200 and has_meta and has_delta and has_usage and has_done and not has_err, {
            'status': s, 'bytes': len(text), 'meta': has_meta, 'delta': has_delta,
            'usage': has_usage, 'done': has_done, 'error': has_err,
            'tail': text[-220:].replace('\n', ' | ')}
    check('SSE 流式对话（打字机→用量结算）', sse)

    def msgs():
        s, x, _ = req('/api/conversations/%d/messages' % conv_id, token=tok)
        items = (x.get('data') or {}).get('items') or []
        return s == 200 and len(items) >= 2 and any(i['role'] == 'assistant' for i in items), {
            'count': len(items), 'roles': [i['role'] for i in items],
            'assistant_preview': (next((i['content'] for i in items if i['role'] == 'assistant'), '') or '')[:60]}
    check('消息落库（含 AI 回复）', msgs)

    def export_md():
        r = urllib.request.Request(BASE + '/api/conversations/%d/export' % conv_id,
                                   headers={'Authorization': 'Bearer ' + tok})
        with urllib.request.urlopen(r, timeout=20) as resp:
            b = resp.read().decode('utf-8', 'ignore')
        return resp.status == 200 and '端到端验证会话' in b, {'bytes': len(b), 'head': b[:50]}
    check('导出 Markdown（带鉴权）', export_md)

    def quota():
        s, x, _ = req('/api/quota', token=tok)
        d = x.get('data') or {}
        return s == 200 and d.get('msg_used', 0) >= 1 and d.get('token_used', 0) > 0, {'status': s, 'data': d}
    check('配额与用量结算', quota)

st, j, _ = req('/api/rooms', token=tok)
rooms = (j.get('data') or {}).get('items') or []
rid = rooms[0]['id'] if rooms else None
check('房间广场', lambda: (st == 200 and len(rooms) >= 1, {'count': len(rooms)}))
if rid:
    def join():
        s, x, _ = req('/api/rooms/%d/join' % rid, 'POST', {}, token=tok)
        return s == 200, {'status': s, 'data': x.get('data')}
    check('加入房间', join)
    def roommsg():
        s, x, _ = req('/api/rooms/%d/messages' % rid, 'POST', {'content': '大家好'}, token=tok)
        return s == 201, {'status': s, 'id': (x.get('data') or {}).get('item', {}).get('id')}
    check('房间发言', roommsg)
    def roomai():
        s, x, _ = req('/api/rooms/%d/ai' % rid, 'POST', {'content': '用一句话总结这个房间'}, token=tok, timeout=90)
        return s == 200 and bool((x.get('data') or {}).get('item')), {'status': s, 'code': x.get('code'),
            'preview': ((x.get('data') or {}).get('item') or {}).get('content', '')[:60], 'msg': x.get('message')}
    check('房间 @AI', roomai)
    def poll():
        s, x, _ = req('/api/rooms/%d/messages?after=0' % rid, token=tok)
        items = (x.get('data') or {}).get('items') or []
        return s == 200 and any(i.get('kind') == 'ai' for i in items), {'count': len(items), 'kinds': [i.get('kind') for i in items]}
    check('3 秒增量轮询取到 AI 回复', poll)

for name, path in [('邀请码列表', '/api/admin/invites'), ('系统设置', '/api/admin/settings'),
                   ('统计面板', '/api/admin/stats'), ('用户管理', '/api/admin/users'),
                   ('审计日志', '/api/admin/audit'), ('全局搜索', '/api/search?q=' + urllib.parse.quote('你好')),
                   ('好友列表', '/api/friends'), ('模板列表', '/api/templates')]:
    def g(p=path, n=name):
        s, x, _ = req(p, token=tok)
        return s == 200 and x.get('code') == 0, {'status': s, 'code': x.get('code'), 'message': x.get('message')}
    check(name, g)

def scheduler():
    s, x, _ = req('/api/admin/scheduler/run', 'POST', {}, token=tok)
    return s == 200 and x.get('code') == 0, {'status': s, 'data': x.get('data')}
check('定时兜底与渠道巡检', scheduler)

print('=== B. 浏览器实测 ===')
try:
    # 恢复「首次强制改密」，让浏览器真实走一遍 登录 → 改密 → 主界面
    import subprocess
    S = '/data/workspace/linkai-site'
    restore = ('require "' + S + '/src/db.php"; '
               'q("UPDATE users SET must_change_password=1 WHERE email=?", ["admin@demo.com"]);')
    subprocess.run([S + '/.runtime/bin/php', '-c', S + '/.runtime/php.ini', '-r', restore],
                   env=dict(os.environ, LD_LIBRARY_PATH=S + '/.runtime/lib'),
                   capture_output=True, timeout=20)
    from playwright.sync_api import sync_playwright
    exe = None
    for c in ['/usr/local/bin/chromium', '/usr/bin/google-chrome', '/usr/local/bin/chrome']:
        if os.path.exists(c): exe = c; break
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, executable_path=exe,
                                     args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'])
        errors = []
        ctx = browser.new_context(viewport={'width': 375, 'height': 780}, device_scale_factor=1)
        page = ctx.new_page()
        page.on('console', lambda m: errors.append('console.' + m.type + ': ' + m.text) if m.type == 'error' else None)
        page.on('pageerror', lambda e: errors.append('pageerror: ' + str(e)))

        def visit(hash_path, label, width, height, shot):
            page.set_viewport_size({'width': width, 'height': height})
            page.goto(BASE + '/#' + hash_path, wait_until='domcontentloaded', timeout=30000)
            page.wait_for_timeout(900)
            scroll_x = page.evaluate('document.documentElement.scrollWidth - document.documentElement.clientWidth')
            page.screenshot(path=os.path.join(SHOTS, shot), full_page=False)
            report['screenshots'].append({'file': shot, 'label': label, 'width': width, 'overflow_x': scroll_x})
            report['browser'].append({'view': label, 'width': width, 'overflow_x': scroll_x,
                                      'body_len': len(page.inner_text('body'))})
            print('  SHOT  %-22s %4dpx  overflowX=%d  text=%d' % (label, width, scroll_x, len(page.inner_text('body'))))
            return scroll_x

        # 真实登录 + 改密流程
        page.goto(BASE + '/#/login', wait_until='domcontentloaded', timeout=30000)
        page.wait_for_timeout(500)
        page.screenshot(path=os.path.join(SHOTS, '01_登录页_375.png'))
        report['screenshots'].append({'file': '01_登录页_375.png', 'label': '登录页', 'width': 375, 'overflow_x': 0})
        page.fill('input[placeholder="admin@demo.com"]', 'admin@demo.com')
        page.fill('input[type="password"]', 'AdminPass2026')
        page.click('button.btn.primary')
        page.wait_for_timeout(1200)
        landed = page.evaluate('location.hash')
        report['browser'].append({'flow': '登录后落地路由', 'hash': landed})
        print('  FLOW  登录后落地: ' + landed)

        # 若落在改密页，真实走一遍改密
        if landed.startswith('#/password'):
            page.fill('input[type="password"] >> nth=0', 'AdminPass2026')
            page.fill('input[type="password"] >> nth=1', 'AdminPass2026')
            page.fill('input[type="password"] >> nth=2', 'AdminPass2026')
            page.click('button.btn.primary')
            page.wait_for_timeout(1200)
            landed2 = page.evaluate('location.hash')
            report['browser'].append({'flow': '改密后落地路由', 'hash': landed2})
            print('  FLOW  改密后落地: ' + landed2)

        visits = [
            ('/msgs', '消息列表', 375, 780, '02_消息列表_375.png'),
            ('/rooms', '房间广场', 375, 780, '03_房间广场_375.png'),
            ('/me', '我的页', 375, 780, '04_我的页_375.png'),
            ('/admin/channels', '渠道配置', 375, 780, '05_渠道配置_375.png'),
            ('/admin/stats', '数据统计', 375, 780, '06_统计面板_375.png'),
            ('/admin/channels', '桌面双栏', 1440, 900, '07_管理后台_1440.png'),
            ('/msgs', '平板宽度', 768, 900, '08_消息列表_768.png'),
        ]
        for h, label, w, hh, f in visits:
            try: visit(h, label, w, hh, f)
            except Exception as e:
                report['issues'].append('浏览器 ' + label + ': ' + str(e)[:200])
                print('  ERROR 浏览器 ' + label + ': ' + str(e)[:120])

        ctx.close(); browser.close()

    report['browser_errors'] = errors
    bad = [e for e in errors if 'favicon' not in e.lower()]
    report['issues'].extend(['控制台: ' + e[:180] for e in bad[:5]])
    print('  CONSOLE ERRORS: %d' % len(bad))
    for e in bad[:5]: print('    ' + e[:180])
except Exception as e:
    report['browser'].append({'error': traceback.format_exc()[-600:]})
    report['issues'].append('浏览器不可用: ' + str(e)[:200])
    print('  BROWSER UNAVAILABLE: ' + str(e)[:200])

report['summary'] = {
    'api_total': len(report['api']),
    'api_pass': sum(1 for x in report['api'] if x['ok']),
    'screenshots': len(report['screenshots']),
    'issues': len(report['issues']),
}
with open(os.path.join(OUT, 'e2e_report.json'), 'w', encoding='utf-8') as f:
    json.dump(report, f, ensure_ascii=False, indent=2)
print('=== 汇总 ===')
print(json.dumps(report['summary'], ensure_ascii=False))
for i in report['issues']: print('  ISSUE ' + i[:220])
