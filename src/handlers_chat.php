<?php
declare(strict_types=1);
require_once __DIR__ . '/upstream.php';

function conv_of(int $id, int $uid): array {
    $c = one('SELECT * FROM conversations WHERE id=? AND user_id=? AND deleted_at IS NULL', [$id, $uid]);
    if (!$c) fail('NOT_FOUND', '会话不存在', 404);
    return $c;
}

function h_conversations_list(): never {
    $u = current_user();
    $kw = trim((string) (param('q') ?? ''));
    $sql = 'SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.conversation_id=c.id) AS msg_count,
        (SELECT content FROM messages m WHERE m.conversation_id=c.id ORDER BY m.id DESC LIMIT 1) AS last_content
        FROM conversations c WHERE c.user_id=? AND c.deleted_at IS NULL';
    $args = [$u['id']];
    if ($kw !== '') { $sql .= ' AND c.title LIKE ?'; $args[] = "%$kw%"; }
    $sql .= ' ORDER BY c.pinned DESC,c.updated_at DESC LIMIT 100';
    ok(['items' => all($sql, $args)]);
}

function h_conversations_create(): never {
    $u = current_user();
    $idem = idempotency_begin();
    $title = trim((string) (bparam('title') ?: '新会话'));
    $id = (int) insert('INSERT INTO conversations (user_id,title) VALUES (?,?)', [$u['id'], $title]);
    $data = ['item' => one('SELECT * FROM conversations WHERE id=?', [$id])];
    idempotency_finish($idem, $data);
    ok($data, 201);
}

function h_conversations_update(array $m): never {
    $u = current_user();
    $c = conv_of((int) $m[1], (int) $u['id']);
    $sets = []; $args = [];
    if (bparam('title') !== null) { $sets[] = 'title=?'; $args[] = trim((string) bparam('title')); }
    if (bparam('pinned') !== null) { $sets[] = 'pinned=?'; $args[] = (int) (bool) bparam('pinned'); }
    if ($sets) { $args[] = $c['id']; q('UPDATE conversations SET ' . implode(',', $sets) . ' WHERE id=?', $args); }
    ok(['item' => conv_of((int) $m[1], (int) $u['id'])]);
}

function h_conversations_delete(array $m): never {
    $u = current_user();
    $c = conv_of((int) $m[1], (int) $u['id']);
    q('UPDATE conversations SET deleted_at=UTC_TIMESTAMP() WHERE id=?', [$c['id']]);
    audit('conversation.delete', 'conversation', (string) $c['id']);
    ok(['deleted' => true, 'undo_token' => (string) $c['id']]);
}

function h_conversations_undelete(array $m): never {
    $u = current_user();
    q('UPDATE conversations SET deleted_at=NULL WHERE id=? AND user_id=?', [(int) $m[1], $u['id']]);
    ok(['restored' => true]);
}

function h_messages_list(array $m): never {
    $u = current_user();
    $c = conv_of((int) $m[1], (int) $u['id']);
    ok(['items' => all('SELECT * FROM messages WHERE conversation_id=? ORDER BY id ASC LIMIT 300', [$c['id']])]);
}

function h_quota(): never {
    $u = current_user();
    $d = quota_date();
    $s = setting_group('quota');
    $r = one('SELECT msg_count,token_count FROM quota_daily WHERE user_id=? AND quota_date=?', [$u['id'], $d]) ?: ['msg_count' => 0, 'token_count' => 0];
    ok(['msg_used' => (int) $r['msg_count'], 'msg_limit' => (int) ($s['daily_msg_limit'] ?? 50),
        'token_used' => (int) $r['token_count'], 'token_limit' => (int) ($s['daily_token_limit'] ?? 100000),
        'date' => $d]);
}

/** 组装上下文：system + 最近 N 轮 */
function build_context(int $convId, int $limit = 20): array {
    $rows = all('SELECT role,content FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?', [$convId, $limit]);
    $rows = array_reverse($rows);
    $out = [['role' => 'system', 'content' => '你是 LinkAI 多房间聊天平台里的 AI 助手，请用简洁、准确、友好的中文回答。']];
    foreach ($rows as $r) $out[] = ['role' => $r['role'], 'content' => $r['content']];
    return $out;
}

/**
 * SSE 流式补全：打字机 / 停止生成 / 用量显示 / 会话级串行 / generation 防覆盖
 * POST /api/conversations/{id}/completions
 */
function h_completions(array $m): never {
    $u = current_user();
    $convId = (int) $m[1];
    $c = conv_of($convId, (int) $u['id']);
    $content = trim((string) require_param('content'));
    if ($content === '') fail('EMPTY_MESSAGE', '消息不能为空', 422);
    moderation_check($content);

    // 会话级串行：同一会话不允许并发生成
    $running = val("SELECT generation_id FROM ai_jobs WHERE conversation_id=? AND status='running'", [$convId]);
    if ($running) fail('GENERATION_IN_PROGRESS', '该会话正在生成中，请等待或停止', 409);

    $modelId = (int) (bparam('model_id') ?? val('SELECT id FROM models WHERE is_default=1 LIMIT 1', [], 0));
    if (!$modelId) fail('NO_DEFAULT_MODEL', '尚未配置默认模型', 503);
    $model = one('SELECT * FROM models WHERE id=?', [$modelId]);
    if (!$model) fail('MODEL_NOT_FOUND', '模型不存在', 404);

    // 配额原子预扣（必须在事务外，上游调用绝不能包在事务里）
    quota_precheck((int) $u['id']);

    $gen = gen_id();
    $msgId = (int) insert('INSERT INTO messages (conversation_id,role,content,generation_id) VALUES (?,?,?,?)',
        [$convId, 'user', $content, $gen]);
    q('UPDATE conversations SET active_generation=?,updated_at=UTC_TIMESTAMP() WHERE id=?', [$gen, $convId]);
    ai_job_start($gen, (int) $u['id'], $convId, null);
    $usageId = usage_open((int) $u['id'], $convId, null, $modelId, null, $gen);

    try {
        $ch = select_channel($modelId);
        q('UPDATE usage_logs SET channel_id=? WHERE id=?', [$ch['id'], $usageId]);
        $messages = build_context($convId, (int) cfg('room_context_window'));
        sse_start();
        sse_emit('meta', ['generation_id' => $gen, 'model' => $model['public_name'],
                         'channel' => $ch['name'], 'message_id' => $msgId]);

        $result = upstream_stream($ch, $ch['upstream_model'], $messages,
            function (string $ev, array $d) { sse_emit($ev, $d); }, $gen);

        $text = $result['text'];
        $cancelled = $result['cancelled'];
        if ($text !== '') {
            insert('INSERT INTO messages (conversation_id,role,content,model_id,tokens_in,tokens_out,generation_id) VALUES (?,?,?,?,?,?,?)',
                [$convId, 'assistant', $text, $modelId, $result['in'], $result['out'], $gen]);
        }
        $cost = ($result['in'] / 1000) * (float) $model['price_input'] + ($result['out'] / 1000) * (float) $model['price_output'];
        usage_settle($usageId, $result['in'], $result['out'], $cost, (int) $u['id']);
        channel_success((int) $ch['id']);
        ai_job_end($gen, $cancelled ? 'cancelled' : 'done');
        q('UPDATE conversations SET active_generation=NULL,updated_at=UTC_TIMESTAMP() WHERE id=?', [$convId]);
        sse_emit('usage', ['tokens_in' => $result['in'], 'tokens_out' => $result['out'], 'cost' => round($cost, 6)]);
        sse_emit('done', ['generation_id' => $gen, 'cancelled' => $cancelled]);
    } catch (Throwable $e) {
        if (isset($ch)) channel_fail((int) $ch['id'], str_contains(strtolower($e->getMessage()), '401'), $e->getMessage());
        usage_refund($usageId, 'refunded');
        quota_rollback_msg((int) $u['id']);
        ai_job_end($gen, 'failed');
        q('UPDATE conversations SET active_generation=NULL WHERE id=?', [$convId]);
        audit('ai.failed', 'conversation', (string) $convId, ['error' => $e->getMessage()]);
        if (!headers_sent()) sse_start();
        sse_emit('error', ['code' => 'AI_FAILED', 'message' => $e->getMessage()]);
        sse_emit('done', ['generation_id' => $gen, 'failed' => true]);
    }
    exit;
}

function h_stop(array $m): never {
    $u = current_user();
    $c = conv_of((int) $m[1], (int) $u['id']);
    $gen = $c['active_generation'];
    if ($gen) {
        q('UPDATE ai_jobs SET cancel_requested=1 WHERE generation_id=?', [$gen]);
        audit('ai.stop', 'conversation', (string) $c['id'], ['generation_id' => $gen]);
    }
    ok(['stopped' => (bool) $gen]);
}

function h_feedback(array $m): never {
    $u = current_user();
    $msg = one('SELECT * FROM messages WHERE id=?', [(int) $m[1]]);
    if (!$msg) fail('NOT_FOUND', '消息不存在', 404);
    $rating = (int) require_param('rating');
    if ($rating < 1 || $rating > 5) fail('INVALID_RATING', '评分需在 1~5', 422);
    insert('INSERT INTO feedback (user_id,message_id,rating,comment) VALUES (?,?,?,?)',
        [$u['id'], $msg['id'], $rating, (string) (bparam('comment') ?? '')]);
    ok(['saved' => true]);
}

function h_templates_list(): never {
    $u = current_user();
    ok(['items' => all('SELECT * FROM templates WHERE scope=\'system\' OR owner_id=? ORDER BY id DESC', [$u['id']])]);
}
function h_templates_create(): never {
    $u = current_user();
    $id = (int) insert('INSERT INTO templates (name,content,scope,owner_id) VALUES (?,?,?,?)',
        [trim((string) require_param('name')), (string) require_param('content'), 'user', $u['id']]);
    ok(['item' => one('SELECT * FROM templates WHERE id=?', [$id])], 201);
}
