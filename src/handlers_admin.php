<?php
declare(strict_types=1);
require_once __DIR__ . '/upstream.php';

/** 参数白名单：上层永不接触厂商私有字段 */
const CHANNEL_FIELDS = ['name', 'protocol', 'base_url', 'api_key', 'priority', 'weight', 'enabled', 'params'];

function channel_public(array $r): array {
    return [
        'id' => (int) $r['id'], 'name' => $r['name'], 'protocol' => $r['protocol'],
        'base_url' => $r['base_url'], 'api_key_hint' => $r['api_key_hint'],
        'priority' => (int) $r['priority'], 'weight' => (int) $r['weight'],
        'enabled' => (bool) $r['enabled'], 'fail_count' => (int) $r['fail_count'],
        'last_error' => $r['last_error'], 'cooldown_until' => $r['cooldown_until'],
        'last_checked_at' => $r['last_checked_at'], 'version' => (int) $r['version'],
        'created_at' => $r['created_at'],
        'upstream_models' => array_column(all('SELECT upstream_model FROM channel_models WHERE channel_id=? ORDER BY upstream_model', [$r['id']]), 'upstream_model'),
    ];
}

function h_channels_list(): never {
    require_admin();
    $rows = all('SELECT * FROM channels ORDER BY priority DESC,id ASC');
    ok(['items' => array_map('channel_public', $rows), 'presets' => protocol_presets()]);
}

function h_channels_create(): never {
    require_admin();
    $name = trim((string) require_param('name'));
    $protocol = (string) (bparam('protocol') ?: 'openai_compatible');
    if (!in_array($protocol, ['openai_compatible', 'anthropic', 'gemini'], true)) fail('INVALID_PROTOCOL', '协议类型不支持', 422);
    $base = rtrim(trim((string) require_param('base_url')), '/');
    if (one('SELECT id FROM channels WHERE name=?', [$name])) fail('NAME_EXISTS', '渠道名称已存在', 409);
    $key = (string) (bparam('api_key') ?? '');
    $id = (int) insert('INSERT INTO channels (name,protocol,base_url,api_key_enc,api_key_hint,priority,weight,enabled,params)
        VALUES (?,?,?,?,?,?,?,?,?)',
        [$name, $protocol, $base, $key !== '' ? encrypt_key($key) : null, $key !== '' ? key_hint($key) : '****',
         (int) (bparam('priority') ?? 0), (int) (bparam('weight') ?? 100), (int) (bparam('enabled') ?? 1),
         bparam('params') ? json_encode(bparam('params'), JSON_UNESCAPED_UNICODE) : null]);
    audit('channel.create', 'channel', (string) $id, ['name' => $name, 'protocol' => $protocol]);
    ok(['item' => channel_public(one('SELECT * FROM channels WHERE id=?', [$id]))], 201);
}

function h_channels_update(array $m): never {
    require_admin();
    $id = (int) $m[1];
    $old = one('SELECT * FROM channels WHERE id=?', [$id]);
    if (!$old) fail('NOT_FOUND', '渠道不存在', 404);
    if (bparam('version') !== null && (int) bparam('version') !== (int) $old['version']) fail('VERSION_CONFLICT', '配置已被他人修改，请刷新后重试', 409);
    $sets = []; $args = [];
    foreach (CHANNEL_FIELDS as $f) {
        if ($f === 'api_key' || bparam($f) === null) continue;
        $v = bparam($f);
        if ($f === 'name' && one('SELECT id FROM channels WHERE name=? AND id<>?', [trim((string) $v), $id])) fail('NAME_EXISTS', '渠道名称已存在', 409);
        if ($f === 'protocol' && !in_array($v, ['openai_compatible', 'anthropic', 'gemini'], true)) fail('INVALID_PROTOCOL', '协议类型不支持', 422);
        $sets[] = "`$f`=?"; $args[] = $f === 'base_url' ? rtrim(trim((string) $v), '/') : (is_bool($v) ? (int) $v : $v);
    }
    $key = (string) (bparam('api_key') ?? '');
    if ($key !== '') { $sets[] = 'api_key_enc=?'; $args[] = encrypt_key($key); $sets[] = 'api_key_hint=?'; $args[] = key_hint($key); }
    if (!$sets) ok(['item' => channel_public($old)]);
    $sets[] = 'version=version+1'; $args[] = $id;
    q('UPDATE channels SET ' . implode(',', $sets) . ' WHERE id=?', $args);
    audit('channel.update', 'channel', (string) $id, ['fields' => array_keys(array_filter(body(), fn($k) => in_array($k, CHANNEL_FIELDS, true), ARRAY_FILTER_USE_KEY))]);
    ok(['item' => channel_public(one('SELECT * FROM channels WHERE id=?', [$id]))]);
}

function h_channels_toggle(array $m): never {
    require_admin();
    $id = (int) $m[1];
    $c = one('SELECT * FROM channels WHERE id=?', [$id]);
    if (!$c) fail('NOT_FOUND', '渠道不存在', 404);
    $want = (int) (bparam('enabled') ?? 1) ? 1 : 0;
    if (!$want && (int) val('SELECT COUNT(*) FROM channels WHERE enabled=1', [], 0) <= 1) {
        fail('LAST_CHANNEL_PROTECTED', '至少保留一个启用渠道', 409);
    }
    q('UPDATE channels SET enabled=?,version=version+1 WHERE id=?', [$want, $id]);
    audit('channel.toggle', 'channel', (string) $id, ['enabled' => $want]);
    ok(['enabled' => (bool) $want]);
}

function h_channels_impact(array $m): never {
    require_admin();
    $id = (int) $m[1];
    ok(['models' => all('SELECT m.public_name,m.display_name FROM model_channels mc JOIN models m ON m.id=mc.model_id WHERE mc.channel_id=?', [$id]),
        'bindings' => (int) val('SELECT COUNT(*) FROM model_channels WHERE channel_id=?', [$id], 0),
        'usage_logs' => (int) val('SELECT COUNT(*) FROM usage_logs WHERE channel_id=?', [$id], 0)]);
}

function h_channels_delete(array $m): never {
    require_admin();
    $id = (int) $m[1];
    $c = one('SELECT * FROM channels WHERE id=?', [$id]);
    if (!$c) fail('NOT_FOUND', '渠道不存在', 404);
    if ($c['enabled'] && (int) val('SELECT COUNT(*) FROM channels WHERE enabled=1', [], 0) <= 1) {
        fail('LAST_CHANNEL_PROTECTED', '至少保留一个启用渠道', 409);
    }
    q('DELETE FROM channels WHERE id=?', [$id]); // channel_models / model_channels 级联
    audit('channel.delete', 'channel', (string) $id, ['name' => $c['name']]);
    ok(['deleted' => true]);
}

function h_channel_probe(array $m): never {
    require_admin();
    $c = one('SELECT * FROM channels WHERE id=?', [(int) $m[1]]);
    if (!$c) fail('NOT_FOUND', '渠道不存在', 404);
    try {
        $r = upstream_probe($c, (string) (bparam('model') ?? ''));
        channel_success((int) $c['id']);
        $result = ['ok' => true, 'latency_ms' => $r['latency_ms'] ?? 0, 'models' => array_slice($r['models'] ?? [], 0, 30)];
    } catch (Throwable $e) {
        $authFail = str_contains(strtolower($e->getMessage()), '401') || str_contains(strtolower($e->getMessage()), '403');
        channel_fail((int) $c['id'], $authFail, $e->getMessage());
        audit('channel.probe_failed', 'channel', (string) $c['id'], ['error' => $e->getMessage()]);
        $result = ['ok' => false, 'message' => $e->getMessage()];
    }
    ok($result);
}

function h_channel_sync(array $m): never {
    require_admin();
    $c = one('SELECT * FROM channels WHERE id=?', [(int) $m[1]]);
    if (!$c) fail('NOT_FOUND', '渠道不存在', 404);
    try {
        $models = upstream_sync_models($c);
        foreach ($models as $n) {
            if ($n === '') continue;
            q('INSERT INTO channel_models (channel_id,upstream_model) VALUES (?,?) ON DUPLICATE KEY UPDATE synced_at=UTC_TIMESTAMP()', [$c['id'], $n]);
        }
        q('DELETE FROM channel_models WHERE channel_id=? AND synced_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL 2 MINUTE)', [$c['id']]);
        channel_success((int) $c['id']);
        audit('channel.sync', 'channel', (string) $c['id'], ['count' => count($models)]);
        ok(['models' => $models]);
    } catch (Throwable $e) {
        channel_fail((int) $c['id'], false, $e->getMessage());
        fail('SYNC_FAILED', $e->getMessage(), 502);
    }
}

/* ── 模型注册表 ───────────────────────────────────── */
function h_models_list(): never {
    current_user();
    $rows = all('SELECT * FROM models ORDER BY is_default DESC,id ASC');
    foreach ($rows as &$r) {
        $r['channels'] = all('SELECT mc.channel_id,mc.upstream_model,mc.weight,c.name AS channel_name,c.enabled
            FROM model_channels mc JOIN channels c ON c.id=mc.channel_id WHERE mc.model_id=?', [$r['id']]);
    }
    ok(['items' => $rows]);
}
function h_models_create(): never {
    require_admin();
    $public = trim((string) require_param('public_name'));
    if (one('SELECT id FROM models WHERE public_name=?', [$public])) fail('NAME_EXISTS', '对外名已存在', 409);
    $id = (int) insert('INSERT INTO models (public_name,display_name,tier,context_limit,price_input,price_output) VALUES (?,?,?,?,?,?)',
        [$public, trim((string) (bparam('display_name') ?: $public)), (string) (bparam('tier') ?: 'standard'),
         (int) (bparam('context_limit') ?? 32768), num(bparam('price_input')), num(bparam('price_output'))]);
    audit('model.create', 'model', (string) $id, ['public_name' => $public]);
    ok(['item' => one('SELECT * FROM models WHERE id=?', [$id])], 201);
}
function h_models_update(array $m): never {
    require_admin();
    $id = (int) $m[1];
    $old = one('SELECT * FROM models WHERE id=?', [$id]);
    if (!$old) fail('NOT_FOUND', '模型不存在', 404);
    if (bparam('version') !== null && (int) bparam('version') !== (int) $old['version']) fail('VERSION_CONFLICT', '配置已被他人修改，请刷新', 409);
    $map = ['display_name' => 'display_name', 'tier' => 'tier', 'context_limit' => 'context_limit',
            'price_input' => 'price_input', 'price_output' => 'price_output'];
    $sets = []; $args = [];
    foreach ($map as $f => $col) if (bparam($f) !== null) { $sets[] = "`$col`=?"; $args[] = bparam($f); }
    if (!$sets) ok(['item' => $old]);
    $sets[] = 'version=version+1'; $args[] = $id;
    q('UPDATE models SET ' . implode(',', $sets) . ' WHERE id=?', $args);
    ok(['item' => one('SELECT * FROM models WHERE id=?', [$id])]);
}
function h_models_default(array $m): never {
    require_admin();
    $id = (int) $m[1];
    tx(function () use ($id) { q('UPDATE models SET is_default=0'); q('UPDATE models SET is_default=1 WHERE id=?', [$id]); });
    audit('model.set_default', 'model', (string) $id);
    ok(['default_id' => $id]);
}
function h_models_bind(array $m): never {
    require_admin();
    $id = (int) $m[1];
    $cid = (int) require_param('channel_id');
    $up = trim((string) require_param('upstream_model'));
    if (!one('SELECT id FROM models WHERE id=?', [$id]) || !one('SELECT id FROM channels WHERE id=?', [$cid])) fail('NOT_FOUND', '模型或渠道不存在', 404);
    q('INSERT INTO model_channels (model_id,channel_id,upstream_model,weight) VALUES (?,?,?,?)
       ON DUPLICATE KEY UPDATE upstream_model=VALUES(upstream_model),weight=VALUES(weight)',
        [$id, $cid, $up, (int) (bparam('weight') ?? 100)]);
    audit('model.bind', 'model', (string) $id, ['channel_id' => $cid, 'upstream' => $up]);
    ok(['bound' => true]);
}
function h_models_unbind(array $m): never {
    require_admin();
    q('DELETE FROM model_channels WHERE model_id=? AND channel_id=?', [(int) $m[1], (int) $m[2]]);
    ok(['unbound' => true]);
}
function h_models_delete(array $m): never {
    require_admin();
    $id = (int) $m[1];
    $r = one('SELECT * FROM models WHERE id=?', [$id]);
    if (!$r) fail('NOT_FOUND', '模型不存在', 404);
    if ($r['is_default']) fail('DEFAULT_MODEL_PROTECTED', '默认模型不可删除，请先切换默认', 409);
    q('DELETE FROM models WHERE id=?', [$id]);
    audit('model.delete', 'model', (string) $id);
    ok(['deleted' => true]);
}

/* ── 邀请码 ───────────────────────────────────────── */
function h_invites_list(): never {
    require_admin();
    $rows = all('SELECT * FROM invite_codes ORDER BY id DESC LIMIT 200');
    ok(['items' => array_map(fn($r) => [
        'id' => (int) $r['id'], 'code_masked' => mask_code($r['code']), 'code' => $r['code'],
        'max_uses' => (int) $r['max_uses'], 'used_count' => (int) $r['used_count'],
        'revoked' => (bool) $r['revoked'], 'created_at' => $r['created_at'],
    ], $rows)]);
}
function h_invites_create(): never {
    $u = require_admin();
    $n = max(1, min(50, (int) (bparam('count') ?? 5)));
    $codes = [];
    for ($i = 0; $i < $n; $i++) {
        $c = invite_code(); $codes[] = $c;
        q('INSERT INTO invite_codes (code,created_by,max_uses) VALUES (?,?,?)', [$c, $u['id'], (int) (bparam('max_uses') ?? 1)]);
    }
    audit('invite.generate', 'invite_code', '', ['count' => $n]);
    ok(['codes' => $codes]);
}
function h_invites_revoke(array $m): never {
    require_admin();
    q('UPDATE invite_codes SET revoked=1 WHERE id=?', [(int) $m[1]]);
    audit('invite.revoke', 'invite_code', (string) $m[1]);
    ok(['revoked' => true]);
}

/* ── 系统设置 / 用户 / 统计 ───────────────────────── */
function h_settings_get(): never { require_admin(); ok(['settings' => settings_all()]); }
function h_settings_put(): never {
    require_admin();
    $k = (string) require_param('key');
    $v = require_param('value');
    if (!is_array($v)) fail('INVALID_VALUE', '设置值必须是对象', 422);
    if (!array_key_exists($k, default_settings())) fail('UNKNOWN_SETTING', '未知设置组', 422);
    save_setting($k, $v);
    audit('settings.update', 'settings', $k, ['value' => $v]);
    ok(['settings' => settings_all()]);
}
function h_admin_users(): never {
    require_admin();
    $kw = trim((string) (param('q') ?? ''));
    $sql = 'SELECT id,email,phone,nickname,role,status,must_change_password,created_at FROM users';
    $args = [];
    if ($kw !== '') { $sql .= ' WHERE email LIKE ? OR phone LIKE ? OR nickname LIKE ?'; $args = ["%$kw%", "%$kw%", "%$kw%"]; }
    $sql .= ' ORDER BY id DESC LIMIT 200';
    ok(['items' => all($sql, $args)]);
}
function h_admin_user_status(array $m): never {
    require_admin();
    $id = (int) $m[1];
    $st = (string) require_param('status');
    if (!in_array($st, ['active', 'banned'], true)) fail('INVALID_STATUS', '状态不合法', 422);
    q('UPDATE users SET status=?,token_version=token_version+1 WHERE id=?', [$st, $id]);
    audit('user.status_changed', 'user', (string) $id, ['status' => $st]);
    ok(['status' => $st]);
}
function h_admin_reset_pw(array $m): never {
    require_admin();
    $id = (int) $m[1];
    $pw = (string) require_param('password');
    if (mb_strlen($pw) < 8) fail('WEAK_PASSWORD', '密码至少 8 位', 422);
    q('UPDATE users SET password_hash=?,must_change_password=1,token_version=token_version+1 WHERE id=?', [hash_pw($pw), $id]);
    audit('user.password_reset', 'user', (string) $id);
    ok(['reset' => true]);
}
function h_admin_stats(): never {
    require_admin();
    $overview = [
        'users' => (int) val('SELECT COUNT(*) FROM users', [], 0),
        'conversations' => (int) val('SELECT COUNT(*) FROM conversations WHERE deleted_at IS NULL', [], 0),
        'messages' => (int) val('SELECT COUNT(*) FROM messages', [], 0),
        'rooms' => (int) val('SELECT COUNT(*) FROM rooms', [], 0),
        'tokens_in' => (int) val("SELECT COALESCE(SUM(tokens_in),0) FROM usage_logs WHERE status='settled'", [], 0),
        'tokens_out' => (int) val("SELECT COALESCE(SUM(tokens_out),0) FROM usage_logs WHERE status='settled'", [], 0),
        'cost' => (float) val("SELECT COALESCE(SUM(cost),0) FROM usage_logs WHERE status='settled'", [], 0),
        'pending' => (int) val("SELECT COUNT(*) FROM usage_logs WHERE status='pending'", [], 0),
        'channels_enabled' => (int) val('SELECT COUNT(*) FROM channels WHERE enabled=1', [], 0),
        'channels_total' => (int) val('SELECT COUNT(*) FROM channels', [], 0),
    ];
    $trend = all("SELECT DATE_FORMAT(created_at,'%Y-%m-%d') AS d, COUNT(*) AS msgs,
        SUM(tokens_in+tokens_out) AS tokens FROM usage_logs
        WHERE created_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 7 DAY) GROUP BY d ORDER BY d");
    $channels = all('SELECT id,name,protocol,enabled,fail_count,last_error,last_checked_at,cooldown_until FROM channels ORDER BY priority DESC');
    $live = ['online_users' => (int) val('SELECT COUNT(*) FROM users WHERE status=\'active\'', [], 0),
             'ai_running' => (int) val("SELECT COUNT(*) FROM ai_jobs WHERE status='running'", [], 0)];
    ok(['overview' => $overview, 'trend' => $trend, 'channels' => $channels, 'live' => $live]);
}
function h_admin_audit(): never {
    require_admin();
    ok(['items' => all('SELECT * FROM audit_logs ORDER BY id DESC LIMIT 100')]);
}
function h_experiments(): never {
    require_admin();
    ok(['items' => all('SELECT * FROM experiments ORDER BY id')]);
}
function h_experiment_update(array $m): never {
    require_admin();
    $sets = []; $args = [];
    foreach (['variant_a', 'enabled', 'name'] as $f) if (bparam($f) !== null) { $sets[] = "`$f`=?"; $args[] = bparam($f); }
    if ($sets) { $args[] = (int) $m[1]; q('UPDATE experiments SET ' . implode(',', $sets) . ' WHERE id=?', $args); }
    ok(['item' => one('SELECT * FROM experiments WHERE id=?', [(int) $m[1]])]);
}
