<?php
declare(strict_types=1);
require_once __DIR__ . '/handlers_chat.php';

function room_of(int $id): array {
    $r = one('SELECT * FROM rooms WHERE id=?', [$id]);
    if (!$r) fail('NOT_FOUND', '房间不存在', 404);
    return $r;
}
function room_member(int $rid, int $uid): bool {
    return (bool) val('SELECT 1 FROM room_members WHERE room_id=? AND user_id=?', [$rid, $uid]);
}
function require_room_member(int $rid, array $u): void {
    if ($u['role'] !== 'admin' && !room_member($rid, (int) $u['id'])) {
        audit('room.permission_denied', 'room', (string) $rid, ['code' => 'NOT_ROOM_MEMBER']);
        fail('NOT_ROOM_MEMBER', '请先加入房间', 403);
    }
}

function h_rooms_list(): never {
    $u = current_user();
    $kw = trim((string) (param('q') ?? ''));
    $sql = 'SELECT r.*, u.nickname AS owner_name,
        (SELECT 1 FROM room_members rm WHERE rm.room_id=r.id AND rm.user_id=?) AS joined
        FROM rooms r JOIN users u ON u.id=r.owner_id WHERE r.archived=0';
    $args = [$u['id']];
    if ($kw !== '') { $sql .= ' AND (r.name LIKE ? OR r.description LIKE ?)'; $args[] = "%$kw%"; $args[] = "%$kw%"; }
    $sql .= ' ORDER BY r.member_count DESC,r.id DESC LIMIT 100';
    ok(['items' => all($sql, $args)]);
}

function h_rooms_create(): never {
    $u = current_user();
    $idem = idempotency_begin();
    $name = trim((string) require_param('name'));
    if ($name === '') fail('INVALID_NAME', '房间名不能为空', 422);
    $id = tx(function () use ($name, $u) {
        $rid = (int) insert('INSERT INTO rooms (name,description,owner_id,access_type,member_count) VALUES (?,?,?,?,1)',
            [$name, trim((string) (bparam('description') ?? '')), $u['id'], (string) (bparam('access_type') ?: 'public')]);
        q('INSERT INTO room_members (room_id,user_id,role) VALUES (?,?,?)', [$rid, $u['id'], 'owner']);
        return $rid;
    });
    audit('room.create', 'room', (string) $id, ['name' => $name]);
    $data = ['item' => room_of($id)];
    idempotency_finish($idem, $data);
    ok($data, 201);
}

function h_rooms_detail(array $m): never {
    $u = current_user();
    $r = room_of((int) $m[1]);
    $r['joined'] = room_member((int) $r['id'], (int) $u['id']);
    $r['members'] = all('SELECT u.id,u.nickname,rm.role FROM room_members rm JOIN users u ON u.id=rm.user_id WHERE rm.room_id=? ORDER BY rm.joined_at', [$r['id']]);
    ok(['item' => $r]);
}

function h_rooms_join(array $m): never {
    $u = current_user();
    $r = room_of((int) $m[1]);
    if (!room_member((int) $r['id'], (int) $u['id'])) {
        q('INSERT INTO room_members (room_id,user_id,role) VALUES (?,?,?)', [$r['id'], $u['id'], 'member']);
        q('UPDATE rooms SET member_count=member_count+1 WHERE id=?', [$r['id']]);
        q('INSERT INTO room_messages (room_id,user_id,nickname,kind,content) VALUES (?,NULL,?,?,?)',
            [$r['id'], '系统', 'system', $u['nickname'] . ' 加入了房间']);
        audit('room.join', 'room', (string) $r['id']);
    }
    ok(['joined' => true]);
}

/** 3 秒增量轮询：替代原架构的 WebSocket 广播（PHP 内置服务器无长连接 WS） */
function h_room_messages(array $m): never {
    $u = current_user();
    $rid = (int) $m[1];
    room_of($rid);
    require_room_member($rid, $u);
    $after = (int) (param('after') ?? 0);
    $rows = all('SELECT id,user_id,nickname,kind,content,created_at FROM room_messages WHERE room_id=? AND id>? ORDER BY id ASC LIMIT 200', [$rid, $after]);
    ok(['items' => $rows, 'server_time' => now_utc()]);
}

function h_room_message_post(array $m): never {
    $u = current_user();
    $rid = (int) $m[1];
    room_of($rid);
    require_room_member($rid, $u);
    $content = trim((string) require_param('content'));
    if ($content === '') fail('EMPTY_MESSAGE', '消息不能为空', 422);
    moderation_check($content);
    $idem = idempotency_begin();
    $id = (int) insert('INSERT INTO room_messages (room_id,user_id,nickname,kind,content) VALUES (?,?,?,?,?)',
        [$rid, $u['id'], $u['nickname'], 'user', $content]);
    $data = ['item' => one('SELECT * FROM room_messages WHERE id=?', [$id])];
    idempotency_finish($idem, $data);
    ok($data, 201);
}

/** 房间 @AI：走同一套渠道选路 / 配额 / 结算，结果落库由轮询拉走 */
function h_room_ai(array $m): never {
    $u = current_user();
    $rid = (int) $m[1];
    room_of($rid);
    require_room_member($rid, $u);
    $flags = setting_group('feature_flags');
    if (!($flags['room_ai'] ?? true)) fail('FEATURE_DISABLED', '房间 AI 已关闭', 403);
    $content = trim((string) require_param('content'));
    if ($content === '') fail('EMPTY_MESSAGE', '请输入要问 AI 的内容', 422);
    moderation_check($content);

    $cooldown = (int) cfg('room_ai_cooldown_sec');
    $last = val("SELECT created_at FROM room_messages WHERE room_id=? AND kind='ai' ORDER BY id DESC LIMIT 1", [$rid]);
    if ($last && (time() - strtotime($last . ' UTC')) < $cooldown) {
        fail('ROOM_AI_COOLDOWN', "房间 AI 冷却中，请 {$cooldown} 秒后再试", 429);
    }

    quota_precheck((int) $u['id']);
    $modelId = (int) val('SELECT id FROM models WHERE is_default=1 LIMIT 1', [], 0);
    if (!$modelId) fail('NO_DEFAULT_MODEL', '尚未配置默认模型', 503);
    $model = one('SELECT * FROM models WHERE id=?', [$modelId]);
    $gen = gen_id();
    $userMsgId = (int) insert('INSERT INTO room_messages (room_id,user_id,nickname,kind,content) VALUES (?,?,?,?,?)',
        [$rid, $u['id'], $u['nickname'], 'user', '@AI ' . $content]);
    ai_job_start($gen, (int) $u['id'], null, $rid);
    $usageId = usage_open((int) $u['id'], null, $rid, $modelId, null, $gen);

    try {
        $ch = select_channel($modelId);
        q('UPDATE usage_logs SET channel_id=? WHERE id=?', [$ch['id'], $usageId]);
        $history = all('SELECT nickname,kind,content FROM room_messages WHERE room_id=? ORDER BY id DESC LIMIT ?', [$rid, (int) cfg('room_context_window')]);
        $history = array_reverse($history);
        $messages = [['role' => 'system', 'content' => '你在多人房间里被 @ 提问，请简洁回答，必要时称呼提问者的昵称。']];
        foreach ($history as $h) {
            if ($h['kind'] === 'system') continue;
            $messages[] = ['role' => $h['kind'] === 'ai' ? 'assistant' : 'user',
                           'content' => ($h['nickname'] ? $h['nickname'] . '：' : '') . preg_replace('/^@AI\s*/', '', $h['content'])];
        }
        // 非流式：把上游增量累积后一次性落库，前端靠 3 秒轮询取走
        $result = upstream_stream($ch, $ch['upstream_model'], $messages, function () {}, $gen);
        if ($result['text'] === '') throw new RuntimeException('上游未返回内容');
        $id = (int) insert('INSERT INTO room_messages (room_id,user_id,nickname,kind,content) VALUES (?,NULL,?,?,?)',
            [$rid, 'AI', 'ai', $result['text']]);
        $cost = ($result['in'] / 1000) * (float) $model['price_input'] + ($result['out'] / 1000) * (float) $model['price_output'];
        usage_settle($usageId, $result['in'], $result['out'], $cost, (int) $u['id']);
        channel_success((int) $ch['id']);
        ai_job_end($gen, 'done');
        audit('room.ai', 'room', (string) $rid, ['generation_id' => $gen]);
        ok(['item' => one('SELECT * FROM room_messages WHERE id=?', [$id]),
            'usage' => ['tokens_in' => $result['in'], 'tokens_out' => $result['out']]]);
    } catch (Throwable $e) {
        if (isset($ch)) channel_fail((int) $ch['id'], false, $e->getMessage());
        usage_refund($usageId);
        quota_rollback_msg((int) $u['id']);
        ai_job_end($gen, 'failed');
        insert('INSERT INTO room_messages (room_id,user_id,nickname,kind,content) VALUES (?,NULL,?,?,?)',
            [$rid, 'AI', 'ai', '（AI 暂时不可用：' . mb_substr($e->getMessage(), 0, 80) . '）']);
        fail('ROOM_AI_FAILED', $e->getMessage(), 502);
    }
}
