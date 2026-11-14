<?php
declare(strict_types=1);
require_once __DIR__ . '/lib.php';

function public_user(array $u): array {
    return [
        'id' => (int) $u['id'], 'email' => $u['email'], 'phone' => $u['phone'],
        'nickname' => $u['nickname'], 'role' => $u['role'], 'status' => $u['status'],
        'must_change_password' => (bool) $u['must_change_password'],
        'theme' => $u['theme'], 'created_at' => $u['created_at'],
    ];
}

function h_login(): never {
    $account = trim((string) require_param('account'));
    $pw = (string) require_param('password');
    $u = one('SELECT * FROM users WHERE email=? OR phone=? LIMIT 1', [$account, $account]);
    if (!$u || !verify_pw($pw, $u['password_hash'])) {
        audit('auth.login_failed', 'user', $account, ['account' => $account]);
        fail('INVALID_CREDENTIALS', '账号或密码错误', 401);
    }
    if ($u['status'] !== 'active') fail('ACCOUNT_BANNED', '账号已被禁用', 403);
    audit('auth.login', 'user', (string) $u['id']);
    ok(['token' => issue_token($u), 'user' => public_user($u)]);
}

function h_register(): never {
    $reg = setting_group('registration');
    $mode = $reg['mode'] ?? 'invite_code';
    if ($mode === 'closed') fail('REGISTRATION_CLOSED', '注册已关闭', 403);
    $account = trim((string) require_param('account'));
    $pw = (string) require_param('password');
    $nickname = trim((string) (bparam('nickname') ?: '成员'));
    if (mb_strlen($pw) < 8) fail('WEAK_PASSWORD', '密码至少 8 位', 422);
    $isEmail = filter_var($account, FILTER_VALIDATE_EMAIL) !== false;
    $isPhone = preg_match('/^1[3-9]\d{9}$/', $account) === 1;
    if (!$isEmail && !$isPhone) fail('INVALID_ACCOUNT', '请填写有效邮箱或手机号', 422);
    if (one('SELECT id FROM users WHERE ' . ($isEmail ? 'email=?' : 'phone=?'), [$account])) {
        fail('ACCOUNT_EXISTS', '该账号已注册', 409);
    }
    $code = trim((string) (bparam('invite_code') ?? ''));
    $inviteId = null;
    if ($mode === 'invite_code' || ($reg['require_invite'] ?? false)) {
        $inv = one('SELECT * FROM invite_codes WHERE code=? AND revoked=0', [$code]);
        if (!$inv || (int) $inv['used_count'] >= (int) $inv['max_uses']) fail('INVALID_INVITE', '邀请码无效或已用完', 422);
        $inviteId = (int) $inv['id'];
    }
    $uid = tx(function () use ($account, $pw, $nickname, $isEmail, $inviteId) {
        $id = (int) insert('INSERT INTO users (' . ($isEmail ? 'email' : 'phone') . ',nickname,password_hash,role) VALUES (?,?,?,?)',
            [$account, $nickname, hash_pw($pw), 'member']);
        if ($inviteId) q('UPDATE invite_codes SET used_count=used_count+1 WHERE id=?', [$inviteId]);
        return $id;
    });
    $u = one('SELECT * FROM users WHERE id=?', [$uid]);
    audit('auth.register', 'user', (string) $uid);
    ok(['token' => issue_token($u), 'user' => public_user($u)], 201);
}

function h_password(): never {
    $u = current_user(true, true); // 允许未改密用户调用
    $old = (string) require_param('old_password');
    $new = (string) require_param('new_password');
    if (!verify_pw($old, $u['password_hash'])) fail('OLD_PASSWORD_WRONG', '原密码不正确', 422);
    if (mb_strlen($new) < 8) fail('WEAK_PASSWORD', '新密码至少 8 位', 422);
    q('UPDATE users SET password_hash=?,must_change_password=0,token_version=token_version+1 WHERE id=?',
        [hash_pw($new), $u['id']]);
    // 把本次登录的 jti 加入黑名单（其余 token 因 token_version 变化自动失效）
    $p = jwt_decode(bearer());
    if ($p) q('INSERT IGNORE INTO jwt_blacklist (jti,user_id,expires_at) VALUES (?,?,DATE_ADD(UTC_TIMESTAMP(), INTERVAL 7 DAY))',
        [$p['jti'], $u['id']]);
    $fresh = one('SELECT * FROM users WHERE id=?', [$u['id']]);
    audit('auth.password_changed', 'user', (string) $u['id']);
    ok(['token' => issue_token($fresh), 'user' => public_user($fresh)]);
}

function h_logout(): never {
    $u = current_user();
    $p = jwt_decode(bearer());
    if ($p) q('INSERT IGNORE INTO jwt_blacklist (jti,user_id,expires_at) VALUES (?,?,DATE_ADD(UTC_TIMESTAMP(), INTERVAL 7 DAY))',
        [$p['jti'], $u['id']]);
    audit('auth.logout', 'user', (string) $u['id']);
    ok(['logged_out' => true]);
}

function h_me(): never {
    // 允许未改密用户读取自身信息（其余业务接口仍由守卫拦截）
    $u = current_user(true, true);
    $d = quota_date();
    $s = setting_group('quota');
    $qd = one('SELECT msg_count,token_count FROM quota_daily WHERE user_id=? AND quota_date=?', [$u['id'], $d]) ?: ['msg_count' => 0, 'token_count' => 0];
    ok([
        'user' => public_user($u),
        'quota' => [
            'msg_limit' => (int) ($s['daily_msg_limit'] ?? 50), 'msg_used' => (int) $qd['msg_count'],
            'token_limit' => (int) ($s['daily_token_limit'] ?? 100000), 'token_used' => (int) $qd['token_count'],
            'warn_ratio' => (float) ($s['warn_ratio'] ?? 0.8), 'date' => $d,
        ],
        'features' => setting_group('feature_flags'),
        'models' => all('SELECT id,public_name,display_name,tier,is_default FROM models ORDER BY is_default DESC,id ASC'),
        'settings' => settings_all(),
    ]);
}

function h_theme(): never {
    $u = current_user();
    $t = (string) require_param('theme');
    if (!in_array($t, ['light', 'dark'], true)) fail('INVALID_THEME', '主题只支持 light / dark', 422);
    q('UPDATE users SET theme=? WHERE id=?', [$t, $u['id']]);
    ok(['theme' => $t]);
}

function h_presets(): never {
    ok(['protocols' => protocol_presets()]);
}

function h_health(): never {
    try {
        db()->query('SELECT 1')->fetchColumn();
        ok(['db' => 'ok', 'mysql' => val('SELECT VERSION()'), 'environment' => cfg('environment'),
            'version' => 'php-1.0.0', 'time_utc' => now_utc()]);
    } catch (Throwable $e) {
        fail('DEPENDENCY_UNAVAILABLE', '数据库不可用', 503, ['failed' => 'db']);
    }
}
