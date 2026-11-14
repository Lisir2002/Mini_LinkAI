<?php
declare(strict_types=1);

$envFile = dirname(__DIR__) . '/.env.php';
$env = is_file($envFile) ? (require $envFile) : [];

if (!function_exists('envv')) {
    function envv(string $key, mixed $default = null): mixed {
        global $env;
        $v = getenv($key);
        if ($v !== false && $v !== '') return $v;
        return $env[$key] ?? $default;
    }
}

return [
    'db_host' => envv('DB_HOST', '127.0.0.1'),
    'db_port' => (int) envv('DB_PORT', '3308'),
    'db_name' => envv('DB_NAME', 'linkai'),
    'db_user' => envv('DB_USER', 'linkai'),
    'db_pass' => envv('DB_PASS', 'linkai_dev_2026'),
    'jwt_secret' => envv('JWT_SECRET', 'dev-only-change-me-0123456789abcdef0123456789abcdef'),
    'cipher_key' => envv('CHANNEL_CIPHER_KEY', 'dev-only-32-byte-cipher-key-000000'),
    'jwt_expire_days' => (int) envv('JWT_EXPIRE_DAYS', '7'),
    'environment' => envv('ENVIRONMENT', 'development'),
    'docs_enabled' => filter_var(envv('DOCS_ENABLED', 'false'), FILTER_VALIDATE_BOOL),
    'cors_origins' => envv('CORS_ORIGINS', '*'),
    'upload_dir' => dirname(__DIR__) . '/data/uploads',
    'quota_reset_tz' => 'Asia/Shanghai',
    'default_daily_msg_limit' => 50,
    'default_daily_token_limit' => 100000,
    'default_room_daily_token_budget' => 500000,
    'ai_first_token_timeout_ms' => 15000,
    'ai_total_timeout_ms' => 60000,
    'room_ai_cooldown_sec' => 5,
    'room_context_window' => 20,
    'global_monthly_budget' => 200.0,
];
