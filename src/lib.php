<?php
declare(strict_types=1);
require_once __DIR__ . '/db.php';

const OK_CODE = 0;

function cfg(string $key = ''): mixed {
    static $c = null;
    if ($c === null) $c = require __DIR__ . '/config.php';
    return $key === '' ? $c : ($c[$key] ?? null);
}

function trace_id(): string {
    static $t = null;
    if ($t === null) {
        $d = random_bytes(16); $d[6] = chr((ord($d[6]) & 0x0f) | 0x40); $d[8] = chr((ord($d[8]) & 0x3f) | 0x80);
        $t = vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($d), 4));
    }
    return $t;
}

class AppError extends RuntimeException {
    public function __construct(public string $errCode, string $message, public int $http = 400, public mixed $detail = null) {
        parent::__construct($message);
    }
}

function ok(mixed $data = [], int $http = 200): never {
    http_response_code($http);
    header('Content-Type: application/json; charset=utf-8');
    header('X-Request-ID: ' . trace_id());
    echo json_encode(['code' => OK_CODE, 'data' => $data], JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

function fail(string $code, string $message, int $http = 400, mixed $detail = null): never {
    http_response_code($http);
    header('Content-Type: application/json; charset=utf-8');
    header('X-Request-ID: ' . trace_id());
    echo json_encode(['code' => $code, 'message' => $message, 'detail' => $detail, 'trace_id' => trace_id()], JSON_UNESCAPED_UNICODE);
    exit;
}

function method(): string { return strtoupper($_SERVER['REQUEST_METHOD'] ?? 'GET'); }
function path(): string { return rtrim(parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/', '/') ?: '/'; }
function segments(): array { return array_values(array_filter(explode('/', path()), fn($x) => $x !== '')); }

function body(): array {
    static $b = null;
    if ($b !== null) return $b;
    $raw = file_get_contents('php://input') ?: '';
    $b = $raw === '' ? [] : (json_decode($raw, true) ?: []);
    if (!is_array($b)) $b = [];
    return $b;
}

function param(string $k, mixed $default = null): mixed { return $_GET[$k] ?? $default; }
function bparam(string $k, mixed $default = null): mixed { return body()[$k] ?? $default; }
function require_param(string $k): mixed {
    $v = bparam($k);
    if ($v === null || $v === '') fail('MISSING_FIELD', "缺少参数 $k", 422);
    return $v;
}

/* ── JWT (HS256) ───────────────────────────────────── */
function b64u(string $s): string { return rtrim(strtr(base64_encode($s), '+/', '-_'), '='); }
function b64ud(string $s): string { return base64_decode(strtr($s, '-_', '+/') . str_repeat('=', (4 - strlen($s) % 4) % 4)) ?: ''; }

function jwt_sign(array $payload): string {
    $h = b64u(json_encode(['alg' => 'HS256', 'typ' => 'JWT'], JSON_UNESCAPED_SLASHES));
    $p = b64u(json_encode($payload, JSON_UNESCAPED_SLASHES));
    $sig = b64u(hash_hmac('sha256', "$h.$p", cfg('jwt_secret'), true));
    return "$h.$p.$sig";
}

function jwt_decode(string $token): ?array {
    $parts = explode('.', $token);
    if (count($parts) !== 3) return null;
    [$h, $p, $s] = $parts;
    $expect = b64u(hash_hmac('sha256', "$h.$p", cfg('jwt_secret'), true));
    if (!hash_equals($expect, $s)) return null;
    $payload = json_decode(b64ud($p), true);
    if (!is_array($payload)) return null;
    if (($payload['exp'] ?? 0) < time()) return null;
    return $payload;
}

function issue_token(array $user): string {
    $now = time();
    return jwt_sign([
        'sub' => (int) $user['id'], 'role' => $user['role'], 'jti' => trace_id(),
        'ver' => (int) $user['token_version'], 'iat' => $now,
        'exp' => $now + cfg('jwt_expire_days') * 86400,
    ]);
}

function bearer(): string {
    $h = $_SERVER['HTTP_AUTHORIZATION'] ?? '';
    if (str_starts_with($h, 'Bearer ')) return substr($h, 7);
    // 兼容 PHP 内置服务器把 header 放进 REDIRECT_ 前缀的情况
    foreach ($_SERVER as $k => $v) if ($k === 'REDIRECT_HTTP_AUTHORIZATION' && str_starts_with((string)$v, 'Bearer ')) return substr((string)$v, 7);
    return '';
}

/** 返回当前用户行；$allowMustChange=true 时允许未改密用户访问改密接口 */
function current_user(bool $required = true, bool $allowMustChange = false): ?array {
    static $cache = null;
    if ($cache !== null) return $cache;
    $token = bearer();
    if ($token === '') {
        if ($required) fail('UNAUTHORIZED', '请先登录', 401);
        return null;
    }
    $payload = jwt_decode($token);
    if (!$payload) fail('TOKEN_INVALID', '登录已失效，请重新登录', 401);
    if (val('SELECT 1 FROM jwt_blacklist WHERE jti=?', [$payload['jti'] ?? ''])) fail('TOKEN_REVOKED', '登录已失效', 401);
    $u = one('SELECT * FROM users WHERE id=?', [(int) ($payload['sub'] ?? 0)]);
    if (!$u || $u['status'] !== 'active') fail('UNAUTHORIZED', '账号不可用', 401);
    if ((int) $u['token_version'] !== (int) ($payload['ver'] ?? 0)) fail('TOKEN_REVOKED', '密码已变更，请重新登录', 401);
    if (!$allowMustChange && (int) $u['must_change_password'] === 1) fail('PASSWORD_CHANGE_REQUIRED', '请先修改初始密码', 403);
    $cache = $u;
    return $u;
}

function require_admin(): array {
    $u = current_user();
    if ($u['role'] !== 'admin') {
        audit('auth.permission_denied', 'route', path(), ['code' => 'FORBIDDEN_ADMIN_ONLY']);
        fail('FORBIDDEN_ADMIN_ONLY', '仅管理员可操作', 403);
    }
    return $u;
}

function hash_pw(string $plain): string { return password_hash($plain, PASSWORD_ARGON2ID); }
function verify_pw(string $plain, string $hash): bool { return password_verify($plain, $hash); }

/* ── 渠道 Key 加密：AES-256-GCM，只回显末 4 位 ──────── */
function cipher_key(): string {
    $k = cfg('cipher_key');
    return hash('sha256', (string) $k, true); // 统一 32 字节
}
function encrypt_key(string $plain): string {
    $iv = random_bytes(12);
    $tag = '';
    $ct = openssl_encrypt($plain, 'aes-256-gcm', cipher_key(), OPENSSL_RAW_DATA, $iv, $tag);
    if ($ct === false) throw new RuntimeException('渠道密钥加密失败');
    return base64_encode($iv . $tag . $ct);
}
function decrypt_key(?string $token): string {
    if (!$token) return '';
    $raw = base64_decode($token, true);
    if ($raw === false || strlen($raw) < 29) return '';
    $iv = substr($raw, 0, 12); $tag = substr($raw, 12, 16); $ct = substr($raw, 28);
    $plain = openssl_decrypt($ct, 'aes-256-gcm', cipher_key(), OPENSSL_RAW_DATA, $iv, $tag);
    return $plain === false ? '' : $plain;
}
function key_hint(string $plain): string { return '****' . (strlen($plain) >= 4 ? substr($plain, -4) : ''); }

/* ── 审计 / 幂等 ───────────────────────────────────── */
function audit(string $action, string $targetType = '', string $targetId = '', mixed $detail = null): void {
    try {
        $uid = null;
        $t = bearer();
        if ($t !== '') { $p = jwt_decode($t); $uid = $p['sub'] ?? null; }
        q('INSERT INTO audit_logs (actor_id,action,target_type,target_id,detail,ip,trace_id) VALUES (?,?,?,?,?,?,?)',
            [$uid, $action, $targetType, (string) $targetId, $detail === null ? null : json_encode($detail, JSON_UNESCAPED_UNICODE),
             $_SERVER['REMOTE_ADDR'] ?? '', trace_id()]);
    } catch (Throwable) { /* 审计失败不影响主流程 */ }
}

function idempotency_begin(): ?string {
    $k = $_SERVER['HTTP_IDEMPOTENCY_KEY'] ?? '';
    if ($k === '') return null;
    $u = current_user(false);
    if (!$u) return null;
    $hit = val('SELECT response FROM idempotency WHERE idem_key=? AND user_id=?', [$k, $u['id']]);
    if ($hit) {
        header('Content-Type: application/json; charset=utf-8');
        echo $hit; exit;
    }
    return $k;
}
function idempotency_finish(?string $k, mixed $data): void {
    if (!$k) return;
    $u = current_user(false);
    if (!$u) return;
    try {
        q('INSERT INTO idempotency (idem_key,user_id,response) VALUES (?,?,?) ON DUPLICATE KEY UPDATE response=VALUES(response)',
            [$k, $u['id'], json_encode(['code' => 0, 'data' => $data], JSON_UNESCAPED_UNICODE)]);
    } catch (Throwable) {}
}

/* ── 系统设置 ──────────────────────────────────────── */
function default_settings(): array {
    return [
        'quota' => ['daily_msg_limit' => 50, 'daily_token_limit' => 100000, 'room_daily_token_budget' => 500000, 'warn_ratio' => 0.8, 'reset_tz' => 'Asia/Shanghai'],
        'registration' => ['mode' => 'invite_code', 'require_invite' => true],
        'moderation' => ['enabled' => true, 'block_input' => true, 'block_output' => true, 'wordlist_version' => 1],
        'feature_flags' => ['room_ai' => true, 'web_search' => false, 'voice_input' => false, 'file_upload' => false],
        'retention' => ['days' => 90],
    ];
}
function settings_all(): array {
    $out = default_settings();
    foreach (all('SELECT `key`,`value` FROM settings') as $r) {
        $v = json_decode($r['value'], true);
        if (is_array($v)) $out[$r['key']] = array_merge($out[$r['key']] ?? [], $v);
    }
    return $out;
}
function setting_group(string $key): array { return settings_all()[$key] ?? []; }
function save_setting(string $key, array $value): void {
    q('INSERT INTO settings (`key`,`value`) VALUES (?,?) ON DUPLICATE KEY UPDATE `value`=VALUES(`value`)',
        [$key, json_encode($value, JSON_UNESCAPED_UNICODE)]);
}

/* ── 内容安全（轻量词表，可在系统设置扩展）──────────── */
function moderation_check(string $text): void {
    $m = setting_group('moderation');
    if (!($m['enabled'] ?? true) || !($m['block_input'] ?? true)) return;
    $words = ['暴力', '赌博', '诈骗', '违禁品'];
    foreach ($words as $w) {
        if (str_contains($text, $w)) fail('CONTENT_BLOCKED', '内容包含不适宜词汇，请修改后重试', 422);
    }
}

/* ── 配额：原子预扣 + 结算退回 ─────────────────────── */
function quota_precheck(int $uid): void {
    $s = setting_group('quota');
    $msgLimit = (int) ($s['daily_msg_limit'] ?? 50);
    $tokenLimit = (int) ($s['daily_token_limit'] ?? 100000);
    $d = quota_date();
    // 单条原子语句：首次插入与增量更新走同一分支；ROW_COUNT()==0 即未生效（超限）
    q('INSERT INTO quota_daily (user_id,quota_date,msg_count,token_count) VALUES (?,?,1,0)
       ON DUPLICATE KEY UPDATE msg_count = IF(msg_count < ?, msg_count + 1, msg_count)',
        [$uid, $d, $msgLimit]);
    if ((int) db()->query('SELECT ROW_COUNT()')->fetchColumn() === 0) {
        fail('QUOTA_MSG_EXCEEDED', '今日消息配额已用完', 429);
    }
    $used = (int) val('SELECT token_count FROM quota_daily WHERE user_id=? AND quota_date=?', [$uid, $d], 0);
    if ($used >= $tokenLimit) fail('QUOTA_TOKEN_EXCEEDED', '今日 Token 配额已用完', 429);
}
function quota_add_tokens(int $uid, int $tokens): void {
    if ($tokens <= 0) return;
    q('INSERT INTO quota_daily (user_id,quota_date,msg_count,token_count) VALUES (?,?,0,?)
       ON DUPLICATE KEY UPDATE token_count = token_count + VALUES(token_count)',
        [$uid, quota_date(), $tokens]);
}
function quota_rollback_msg(int $uid): void {
    q('UPDATE quota_daily SET msg_count = GREATEST(msg_count - 1, 0) WHERE user_id=? AND quota_date=?', [$uid, quota_date()]);
}
function usage_open(int $uid, ?int $convId, ?int $roomId, ?int $modelId, ?int $channelId, string $gen): int {
    return (int) insert('INSERT INTO usage_logs (user_id,conversation_id,room_id,model_id,channel_id,generation_id,status) VALUES (?,?,?,?,?,?,?)',
        [$uid, $convId, $roomId, $modelId, $channelId, $gen, 'pending']);
}
function usage_settle(int $id, int $in, int $out, float $cost, int $uid): void {
    q("UPDATE usage_logs SET status='settled',tokens_in=?,tokens_out=?,cost=?,settled_at=UTC_TIMESTAMP() WHERE id=?", [$in, $out, $cost, $id]);
    quota_add_tokens($uid, $in + $out);
}
function usage_refund(int $id, string $status = 'refunded'): void {
    q('UPDATE usage_logs SET status=?,settled_at=UTC_TIMESTAMP() WHERE id=? AND status=\'pending\'', [$status, $id]);
}

/* ── 渠道选路 / 失败处理 ───────────────────────────── */
function channel_rows(int $modelId): array {
    return all('SELECT c.*, mc.upstream_model, mc.weight AS bind_weight
        FROM model_channels mc JOIN channels c ON c.id = mc.channel_id
        WHERE mc.model_id=? AND c.enabled=1
          AND (c.cooldown_until IS NULL OR c.cooldown_until < UTC_TIMESTAMP())
        ORDER BY c.priority DESC, c.weight DESC, c.id ASC', [$modelId]);
}
function select_channel(int $modelId): array {
    $rows = channel_rows($modelId);
    if (!$rows) fail('NO_CHANNEL_AVAILABLE', '该模型没有可用渠道，请到管理端配置', 503);
    $top = $rows[0]['priority'];
    $pool = array_values(array_filter($rows, fn($r) => $r['priority'] === $top));
    $total = array_sum(array_map(fn($r) => max(1, (int) ($r['bind_weight'] ?: $r['weight'])), $pool));
    $pick = random_int(1, max(1, $total)); $acc = 0;
    foreach ($pool as $r) {
        $acc += max(1, (int) ($r['bind_weight'] ?: $r['weight']));
        if ($pick <= $acc) return $r;
    }
    return $pool[0];
}
function channel_fail(int $id, bool $authFailure, string $err): void {
    if ($authFailure) {
        q("UPDATE channels SET enabled=0,fail_count=fail_count+1,last_error=?,last_checked_at=UTC_TIMESTAMP() WHERE id=?", [mb_substr($err, 0, 400), $id]);
        audit('channel.auto_disabled', 'channel', (string) $id, ['reason' => 'auth_failed']);
        return;
    }
    $n = (int) val('SELECT fail_count+1 FROM channels WHERE id=?', [$id], 1);
    $disable = $n >= 3;
    q('UPDATE channels SET fail_count=?, last_error=?, last_checked_at=UTC_TIMESTAMP(),
        enabled=IF(?,0,enabled), cooldown_until=DATE_ADD(UTC_TIMESTAMP(), INTERVAL 60 SECOND) WHERE id=?',
        [$n, mb_substr($err, 0, 400), $disable ? 1 : 0, $id]);
}
function channel_success(int $id): void {
    q('UPDATE channels SET fail_count=0,last_error=NULL,cooldown_until=NULL,last_checked_at=UTC_TIMESTAMP() WHERE id=?', [$id]);
}

/* ── 工具 ──────────────────────────────────────────── */
function gen_id(): string {
    $d = random_bytes(16); $d[6] = chr((ord($d[6]) & 0x0f) | 0x40); $d[8] = chr((ord($d[8]) & 0x3f) | 0x80);
    return vsprintf('%s%s-%s-%s-%s-%s%s%s', str_split(bin2hex($d), 4));
}
function invite_code(): string { return 'RM-' . strtoupper(bin2hex(random_bytes(3))); }
function mask_code(string $c): string { return strlen($c) > 4 ? substr($c, 0, 3) . '****' . substr($c, -2) : '****'; }
function jdecode(?string $s, mixed $default = null): mixed {
    if (!$s) return $default;
    $v = json_decode($s, true);
    return $v === null ? $default : $v;
}
function num(mixed $v, float $default = 0): float { return is_numeric($v) ? (float) $v : $default; }
