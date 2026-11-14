<?php
declare(strict_types=1);
require_once __DIR__ . '/lib.php';

/* ── 好友 / 私聊 ──────────────────────────────────── */
function h_friends_list(): never {
    $u = current_user();
    $rows = all('SELECT f.id,f.status,f.created_at,
        CASE WHEN f.user_id=? THEN f.friend_id ELSE f.user_id END AS peer_id,
        CASE WHEN f.user_id=? THEN u2.nickname ELSE u1.nickname END AS peer_name,
        f.user_id AS requester_id
        FROM friends f JOIN users u1 ON u1.id=f.user_id JOIN users u2 ON u2.id=f.friend_id
        WHERE f.user_id=? OR f.friend_id=? ORDER BY f.id DESC',
        [$u['id'], $u['id'], $u['id'], $u['id']]);
    ok(['items' => $rows]);
}
function h_friends_request(): never {
    $u = current_user();
    $peer = (int) require_param('user_id');
    if ($peer === (int) $u['id']) fail('INVALID_PEER', '不能添加自己', 422);
    if (!one('SELECT id FROM users WHERE id=?', [$peer])) fail('NOT_FOUND', '用户不存在', 404);
    $a = min((int) $u['id'], $peer); $b = max((int) $u['id'], $peer);
    if (one('SELECT id FROM friends WHERE user_id=? AND friend_id=?', [$a, $b])) fail('ALREADY_EXISTS', '好友关系已存在', 409);
    q('INSERT INTO friends (user_id,friend_id,status) VALUES (?,?,?)', [$a, $b, 'pending']);
    ok(['requested' => true]);
}
function h_friends_accept(array $m): never {
    $u = current_user();
    $f = one('SELECT * FROM friends WHERE id=?', [(int) $m[1]]);
    if (!$f) fail('NOT_FOUND', '申请不存在', 404);
    if ((int) $f['user_id'] !== (int) $u['id'] && (int) $f['friend_id'] !== (int) $u['id']) fail('FORBIDDEN', '无权操作', 403);
    q('UPDATE friends SET status=? WHERE id=?', [(string) (bparam('action') ?: 'accepted') === 'reject' ? 'rejected' : 'accepted', $f['id']]);
    ok(['status' => bparam('action') === 'reject' ? 'rejected' : 'accepted']);
}
function h_dm_list(array $m): never {
    $u = current_user();
    $peer = (int) $m[1];
    q('UPDATE dm_messages SET read_at=UTC_TIMESTAMP() WHERE from_id=? AND to_id=? AND read_at IS NULL', [$peer, $u['id']]);
    ok(['items' => all('SELECT * FROM dm_messages WHERE (from_id=? AND to_id=?) OR (from_id=? AND to_id=?) ORDER BY id ASC LIMIT 200',
        [$u['id'], $peer, $peer, $u['id']])]);
}
function h_dm_send(array $m): never {
    $u = current_user();
    $peer = (int) $m[1];
    if (!one('SELECT id FROM users WHERE id=?', [$peer])) fail('NOT_FOUND', '用户不存在', 404);
    $content = trim((string) require_param('content'));
    if ($content === '') fail('EMPTY_MESSAGE', '消息不能为空', 422);
    moderation_check($content);
    $id = (int) insert('INSERT INTO dm_messages (from_id,to_id,content) VALUES (?,?,?)', [$u['id'], $peer, $content]);
    ok(['item' => one('SELECT * FROM dm_messages WHERE id=?', [$id])], 201);
}

/* ── 全局搜索 ─────────────────────────────────────── */
function h_search(): never {
    $u = current_user();
    $kw = trim((string) (param('q') ?? ''));
    if ($kw === '') ok(['users' => [], 'conversations' => [], 'rooms' => [], 'messages' => []]);
    $like = "%$kw%";
    ok([
        'users' => all('SELECT id,nickname,email FROM users WHERE (nickname LIKE ? OR email LIKE ?) AND id<>? LIMIT 20', [$like, $like, $u['id']]),
        'conversations' => all('SELECT id,title FROM conversations WHERE user_id=? AND title LIKE ? AND deleted_at IS NULL LIMIT 20', [$u['id'], $like]),
        'rooms' => all('SELECT id,name,description FROM rooms WHERE name LIKE ? AND archived=0 LIMIT 20', [$like]),
        'messages' => all('SELECT m.id,m.conversation_id,m.content FROM messages m JOIN conversations c ON c.id=m.conversation_id
            WHERE c.user_id=? AND m.content LIKE ? LIMIT 20', [$u['id'], $like]),
    ]);
}

/* ── 分享 / 导出 ──────────────────────────────────── */
function h_share_create(): never {
    $u = current_user();
    $cid = (int) require_param('conversation_id');
    $c = one('SELECT * FROM conversations WHERE id=? AND user_id=?', [$cid, $u['id']]);
    if (!$c) fail('NOT_FOUND', '会话不存在', 404);
    $msgs = all('SELECT role,content,created_at FROM messages WHERE conversation_id=? ORDER BY id', [$cid]);
    $token = bin2hex(random_bytes(16));
    insert('INSERT INTO shares (token,user_id,title,payload,expires_at) VALUES (?,?,?,?,DATE_ADD(UTC_TIMESTAMP(), INTERVAL 7 DAY))',
        [$token, $u['id'], $c['title'], json_encode($msgs, JSON_UNESCAPED_UNICODE)]);
    audit('share.create', 'conversation', (string) $cid);
    ok(['token' => $token, 'url' => '/#/share/' . $token]);
}
function h_share_get(array $m): never {
    $s = one('SELECT * FROM shares WHERE token=?', [(string) $m[1]]);
    if (!$s || ($s['expires_at'] && strtotime($s['expires_at'] . ' UTC') < time())) fail('NOT_FOUND', '分享不存在或已过期', 404);
    ok(['title' => $s['title'], 'messages' => jdecode($s['payload'], []), 'created_at' => $s['created_at']]);
}
function h_export(array $m): never {
    $u = current_user();
    $c = one('SELECT * FROM conversations WHERE id=? AND user_id=?', [(int) $m[1], $u['id']]);
    if (!$c) fail('NOT_FOUND', '会话不存在', 404);
    $msgs = all('SELECT role,content,created_at FROM messages WHERE conversation_id=? ORDER BY id', [$c['id']]);
    $md = '# ' . $c['title'] . "\n\n";
    foreach ($msgs as $x) $md .= '**' . ($x['role'] === 'user' ? '我' : 'AI') . "** (" . $x['created_at'] . ")\n\n" . $x['content'] . "\n\n---\n\n";
    header('Content-Type: text/markdown; charset=utf-8');
    header('Content-Disposition: attachment; filename="conversation-' . $c['id'] . '.md"');
    echo $md;
    exit;
}

/* ── 上传（本地隔离目录）──────────────────────────── */
function h_upload(): never {
    $u = current_user();
    $flags = setting_group('feature_flags');
    if (!($flags['file_upload'] ?? false)) fail('FEATURE_DISABLED', '文件上传未开启', 403);
    if (empty($_FILES['file'])) fail('NO_FILE', '未收到文件', 422);
    $f = $_FILES['file'];
    if ($f['error'] !== UPLOAD_ERR_OK) fail('UPLOAD_FAILED', '上传失败', 400);
    if ($f['size'] > 5 * 1024 * 1024) fail('FILE_TOO_LARGE', '文件不能超过 5MB', 413);
    $ext = strtolower(pathinfo($f['name'], PATHINFO_EXTENSION));
    if (!in_array($ext, ['png', 'jpg', 'jpeg', 'gif', 'webp', 'txt', 'md', 'pdf'], true)) fail('INVALID_TYPE', '文件类型不支持', 415);
    $dir = rtrim(cfg('upload_dir'), '/');
    if (!is_dir($dir)) @mkdir($dir, 0775, true);
    $name = bin2hex(random_bytes(12)) . '.' . $ext;
    if (!move_uploaded_file($f['tmp_name'], "$dir/$name")) fail('UPLOAD_FAILED', '保存失败', 500);
    $id = (int) insert('INSERT INTO uploads (user_id,filename,stored_path,mime,size_bytes) VALUES (?,?,?,?,?)',
        [$u['id'], $f['name'], "$dir/$name", mime_content_type("$dir/$name") ?: 'application/octet-stream', $f['size']]);
    ok(['id' => $id, 'url' => '/api/uploads/' . $id, 'filename' => $f['name']], 201);
}
function h_upload_get(array $m): never {
    current_user();
    $f = one('SELECT * FROM uploads WHERE id=?', [(int) $m[1]]);
    if (!$f || !is_file($f['stored_path'])) fail('NOT_FOUND', '文件不存在', 404);
    header('Content-Type: ' . $f['mime']);
    header('Content-Length: ' . filesize($f['stored_path']));
    readfile($f['stored_path']);
    exit;
}

/* ── 定时兜底：pending 退回 + 渠道健康巡检 ────────── */
function scheduler_tick(): array {
    $refunded = 0; $checked = 0;
    // 悬挂超过 10 分钟的 pending 一律退回
    $rows = all("SELECT id FROM usage_logs WHERE status='pending' AND created_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL 10 MINUTE)");
    foreach ($rows as $r) { usage_refund((int) $r['id']); $refunded++; }
    // 冷却到期的渠道重新参与选路（不自动启用被手动禁用的渠道）
    $cool = all('SELECT id FROM channels WHERE cooldown_until IS NOT NULL AND cooldown_until < UTC_TIMESTAMP()');
    foreach ($cool as $c) { q('UPDATE channels SET cooldown_until=NULL WHERE id=?', [$c['id']]); $checked++; }
    // 长期运行中的 job 标记失败
    q("UPDATE ai_jobs SET status='failed' WHERE status='running' AND created_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL 10 MINUTE)");
    // 保留天数清理审计日志
    $days = (int) (setting_group('retention')['days'] ?? 90);
    if ($days > 0) q('DELETE FROM audit_logs WHERE created_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL ? DAY)', [$days]);
    return ['refunded' => $refunded, 'cooldown_cleared' => $checked, 'ran_at' => now_utc()];
}
function h_scheduler_run(): never {
    require_admin();
    $r = scheduler_tick();
    audit('scheduler.run', 'system', '', $r);
    ok($r);
}
