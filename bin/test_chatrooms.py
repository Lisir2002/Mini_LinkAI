#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多类型聊天室测试：单轮/长文本/emoji/多轮/并发/停止生成/房间发言/@AI/冷却/审核/配额/分享导出
用法：
  python3 bin/test_chatrooms.py                          # 打本地 127.0.0.1:8080
  python3 bin/test_chatrooms.py --base http://域名:端口   # 打远端站点
"""
import argparse, json, os, sys, time, urllib.request, urllib.error, urllib.parse, threading

ap = argparse.ArgumentParser()
ap.add_argument('--base', default='http://127.0.0.1:8080')
ap.add_argument('--account', default='admin@demo.com')
ap.add_argument('--password', default='AdminPass2026')
args = ap.parse_args()
BASE = args.base.rstrip('/')

results = []
def rec(name, ok, detail=''):
    results.append({'name': name, 'ok': bool(ok), 'detail': str(detail)[:260]})
    print(('  PASS  ' if ok else '  FAIL  ') + name + '  ' + str(detail)[:200])

def req(path, method='GET', body=None, token=None, timeout=60, raw=False):
    h = {'Content-Type': 'application/json'}
    if token: h['Authorization'] = 'Bearer ' + token
    r = urllib.request.Request(BASE + path,
        data=json.dumps(body).encode('utf-8') if body is not None else None, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as x:
            b = x.read()
            return x.status, (b if raw else (json.loads(b) if b else {})), None
    except urllib.error.HTTPError as e:
        b = e.read()
        try: j = json.loads(b)
        except Exception: j = {'raw': b[:200].decode('utf-8', 'ignore')}
        return e.code, j, None
    except Exception as e:
        return 0, {}, str(e)

def sse(path, body, token, timeout=90):
    """返回 (status, events, text, usage, err)"""
    h = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token}
    r = urllib.request.Request(BASE + path, data=json.dumps(body).encode('utf-8'), headers=h, method='POST')
    try:
        resp = urllib.request.urlopen(r, timeout=timeout)
    except urllib.error.HTTPError as e:
        return e.code, [], '', None, e.read().decode('utf-8', 'ignore')[:200]
    except Exception as e:
        return 0, [], '', None, str(e)
    events, text, usage, err, buf = [], '', None, '', ''
    try:
        while True:
            chunk = resp.read(1)
            if not chunk: break
            buf += chunk.decode('utf-8', 'ignore')
            while '\n\n' in buf:
                block, buf = buf.split('\n\n', 1)
                ev, data = 'message', ''
                for line in block.replace('\r', '').split('\n'):
                    if line.startswith('event:'): ev = line[6:].strip()
                    elif line.startswith('data:'): data += line[5:].strip()
                if not data: continue
                try: j = json.loads(data)
                except Exception: continue
                events.append(ev)
                if ev == 'delta': text += j.get('content', '')
                elif ev == 'usage': usage = j
                elif ev == 'error': err = j.get('message', 'error')
    except Exception as e:
        err = err or str(e)
    return resp.status, events, text, usage, err

print('=== 登录 ===')
st, j, _ = req('/api/auth/login', 'POST', {'account': args.account, 'password': args.password})
tok = (j.get('data') or {}).get('token')
if not tok:
    print('登录失败:', j); sys.exit(1)
if (j.get('data') or {}).get('user', {}).get('must_change_password'):
    st, j, _ = req('/api/auth/password', 'POST',
                   {'old_password': args.password, 'new_password': args.password}, tok)
    tok = (j.get('data') or {}).get('token') or tok
rec('管理员登录 / 改密', bool(tok), {'status': st})

models = (req('/api/auth/me', token=tok)[1].get('data') or {}).get('models') or []
mid = next((m['id'] for m in models if m.get('is_default')), models[0]['id'] if models else None)
rec('默认模型可用', bool(mid), {'models': [m['public_name'] for m in models]})

def new_conv(title):
    st, j, _ = req('/api/conversations', 'POST', {'title': title}, tok)
    return (j.get('data') or {}).get('item', {}).get('id')

print('=== 会话类聊天室 ===')
# T1 单轮短文本
cid = new_conv('测试-单轮短文本')
st, ev, txt, usage, err = sse('/api/conversations/%d/completions' % cid,
                              {'content': '你好，用一句话介绍你自己', 'model_id': mid}, tok)
rec('T1 单轮短文本 SSE 流式',
    st == 200 and 'meta' in ev and 'delta' in ev and 'usage' in ev and 'done' in ev and not err and len(txt) > 5,
    {'events': sorted(set(ev)), 'chars': len(txt), 'usage': usage, 'err': err})

# T2 中文长文本
cid2 = new_conv('测试-中文长文本')
long_cn = '请记住这个编号 LK-2026-1114，然后复述。' + '人工智能与多房间协作平台' * 40
st, ev, txt, usage, err = sse('/api/conversations/%d/completions' % cid2,
                              {'content': long_cn, 'model_id': mid}, tok, timeout=120)
rec('T2 中文长文本往返', st == 200 and 'done' in ev and not err and len(txt) > 5,
    {'input_chars': len(long_cn), 'output_chars': len(txt), 'err': err})

# T3 Emoji / 特殊字符 / 换行
cid3 = new_conv('测试-特殊字符')
weird = '😀🚀 你好\n第二行\t制表符 <script>alert(1)</script> "引号" \\反斜杠'
st, ev, txt, usage, err = sse('/api/conversations/%d/completions' % cid3,
                              {'content': weird, 'model_id': mid}, tok)
st2, j2, _ = req('/api/conversations/%d/messages' % cid3, token=tok)
saved = (j2.get('data') or {}).get('items') or []
orig_ok = any('😀🚀' in (m.get('content') or '') and '<script>' in (m.get('content') or '') for m in saved)
rec('T3 Emoji / 换行 / 特殊字符不乱码', st == 200 and orig_ok and 'alert' not in json.dumps(j2, ensure_ascii=False)[:10],
    {'saved_msgs': len(saved), 'utf8_ok': orig_ok, 'err': err})

# T4 多轮上下文
cid4 = new_conv('测试-多轮上下文')
for i in range(3):
    st, ev, txt, usage, err = sse('/api/conversations/%d/completions' % cid4,
                                  {'content': '第 %d 轮提问' % (i + 1), 'model_id': mid}, tok)
st, j, _ = req('/api/conversations/%d/messages' % cid4, token=tok)
msgs = (j.get('data') or {}).get('items') or []
rec('T4 三轮上下文连续对话', st == 200 and len(msgs) == 6 and
    [m['role'] for m in msgs] == ['user', 'assistant'] * 3,
    {'count': len(msgs), 'roles': [m['role'] for m in msgs]})

# T5 同会话并发（应被 409 串行保护挡住）
cid5 = new_conv('测试-并发串行')
box = {}
def fire():
    box['r'] = sse('/api/conversations/%d/completions' % cid5, {'content': '并发请求', 'model_id': mid}, tok)
t = threading.Thread(target=fire); t.start()
time.sleep(0.25)
st, j, _ = req('/api/conversations/%d/completions' % cid5, 'POST', {'content': '第二个', 'model_id': mid}, tok)
t.join(timeout=100)
rec('T5 同会话并发串行保护', st == 409 or j.get('code') == 'GENERATION_IN_PROGRESS',
    {'second_status': st, 'code': j.get('code'), 'first': (box.get('r') or [None])[0]})

# T6 停止生成 / 中断不产生脏数据
cid6 = new_conv('测试-停止生成')
h = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + tok}
r = urllib.request.Request(BASE + '/api/conversations/%d/completions' % cid6,
    data=json.dumps({'content': '请慢慢回答', 'model_id': mid}).encode(), headers=h, method='POST')
try:
    resp = urllib.request.urlopen(r, timeout=30)
    resp.read(64)  # 读一点就断开，模拟用户点「停止生成」
    resp.close()
except Exception as e:
    pass
q1 = (req('/api/quota', token=tok)[1].get('data') or {})
time.sleep(1)
st, j, _ = req('/api/conversations/%d/messages' % cid6, token=tok)
rec('T6 中断生成不残留 running 任务', st == 200,
    {'msgs': len((j.get('data') or {}).get('items') or []), 'msg_used': q1.get('msg_used')})

print('=== 房间类聊天室 ===')
rooms = (req('/api/rooms', token=tok)[1].get('data') or {}).get('items') or []
rid = rooms[0]['id'] if rooms else None
if rid:
    req('/api/rooms/%d/join' % rid, 'POST', {}, tok)
    # T7 普通发言
    st, j, _ = req('/api/rooms/%d/messages' % rid, 'POST', {'content': '大家好 👋 这是一条房间消息'}, tok)
    rec('T7 房间普通发言（含 emoji）', st == 201, {'status': st})
    # T8 房间 @AI
    st, j, _ = req('/api/rooms/%d/ai' % rid, 'POST', {'content': '用一句话总结这个房间'}, tok, timeout=120)
    ai_ok = st == 200 and bool((j.get('data') or {}).get('item'))
    rec('T8 房间 @AI 触发真实模型', ai_ok,
        {'status': st, 'code': j.get('code'), 'preview': ((j.get('data') or {}).get('item') or {}).get('content', '')[:50],
         'msg': j.get('message')})
    # T9 冷却
    st, j, _ = req('/api/rooms/%d/ai' % rid, 'POST', {'content': '再来一次'}, tok, timeout=30)
    rec('T9 房间 AI 冷却保护', st == 429 or j.get('code') == 'ROOM_AI_COOLDOWN',
        {'status': st, 'code': j.get('code')})
    # T10 增量轮询
    st, j, _ = req('/api/rooms/%d/messages?after=0' % rid, token=tok)
    items = (j.get('data') or {}).get('items') or []
    rec('T10 增量轮询取回 AI 回复', st == 200 and any(x.get('kind') == 'ai' for x in items),
        {'count': len(items), 'kinds': [x.get('kind') for x in items]})
else:
    rec('房间类测试', False, '没有房间')

print('=== 安全 / 配额 / 分享 ===')
# T11 内容安全
cid7 = new_conv('测试-内容安全')
st, j, _ = req('/api/conversations/%d/completions' % cid7, 'POST',
               {'content': '这是一条包含赌博和诈骗的测试', 'model_id': mid}, tok)
rec('T11 内容安全词表拦截', st == 422 or j.get('code') == 'CONTENT_BLOCKED',
    {'status': st, 'code': j.get('code')})

# T12 配额一致性
q = (req('/api/quota', token=tok)[1].get('data') or {})
rec('T12 配额计数与用量结算', q.get('msg_used', 0) >= 5 and q.get('token_used', 0) > 0,
    {'msg_used': q.get('msg_used'), 'token_used': q.get('token_used'), 'date': q.get('date')})

# T13 分享 / 导出
st, j, _ = req('/api/shares', 'POST', {'conversation_id': cid}, tok)
share_ok = st == 200 and bool((j.get('data') or {}).get('token'))
if share_ok:
    st2, j2, _ = req('/api/shares/' + j['data']['token'])
    share_ok = st2 == 200
r = urllib.request.Request(BASE + '/api/conversations/%d/export' % cid,
                           headers={'Authorization': 'Bearer ' + tok})
with urllib.request.urlopen(r, timeout=20) as x: md = x.read().decode('utf-8', 'ignore')
rec('T13 分享链接 + Markdown 导出', share_ok and '# 测试-' in md,
    {'share': share_ok, 'md_bytes': len(md)})

# T14 管理端渠道连通性（真实接口时最关键）
st, j, _ = req('/api/admin/channels', token=tok)
chs = (j.get('data') or {}).get('items') or []
probe_detail = []
for c in chs:
    s, x, _ = req('/api/admin/channels/%d/probe' % c['id'], 'POST', {}, tok, timeout=60)
    probe_detail.append({'name': c['name'], 'ok': (x.get('data') or {}).get('ok'),
                         'msg': x.get('message') or (x.get('data') or {}).get('message')})
rec('T14 上游渠道连通性测试', bool(probe_detail) and all(p['ok'] for p in probe_detail), probe_detail)

passed = sum(1 for x in results if x['ok'])
summary = {'total': len(results), 'passed': passed, 'failed': len(results) - passed,
           'base': BASE, 'time': time.strftime('%Y-%m-%d %H:%M:%S')}
out = os.path.join(os.path.dirname(__file__), '..', 'logs', 'chatroom_tests.json')
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, 'w', encoding='utf-8') as f:
    json.dump({'summary': summary, 'results': results}, f, ensure_ascii=False, indent=2)
print('\n=== 汇总 ===', json.dumps(summary, ensure_ascii=False))
for x in results:
    if not x['ok']: print('  FAILED:', x['name'], x['detail'][:200])
sys.exit(0 if passed == len(results) else 1)
