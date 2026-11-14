<?php
declare(strict_types=1);
/**
 * Mini_LinkAI PHP 版单入口
 * 用法：php -c .runtime/php.ini -S 0.0.0.0:8080 -t public public/index.php
 * 静态文件交给内置服务器；/api/* 走路由；其余回退到 SPA index.html
 */
require_once dirname(__DIR__) . '/src/lib.php';
require_once dirname(__DIR__) . '/src/upstream.php';
require_once dirname(__DIR__) . '/src/handlers_auth.php';
require_once dirname(__DIR__) . '/src/handlers_admin.php';
require_once dirname(__DIR__) . '/src/handlers_chat.php';
require_once dirname(__DIR__) . '/src/handlers_rooms.php';
require_once dirname(__DIR__) . '/src/handlers_misc.php';

$origin = cfg('cors_origins');
header('Access-Control-Allow-Origin: ' . ($origin === '*' ? ($_SERVER['HTTP_ORIGIN'] ?? '*') : $origin));
header('Access-Control-Allow-Headers: Authorization, Content-Type, Idempotency-Key, X-Requested-With');
header('Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS');
header('Access-Control-Allow-Credentials: true');
header('X-Request-ID: ' . trace_id());
header('X-Content-Type-Options: nosniff');
if (method() === 'OPTIONS') { http_response_code(204); exit; }

$p = path();

/* ── 内置 mock 上游（不要求用户登录，只校验渠道 Key 非空）── */
if (str_starts_with($p, '/api/mock/v1/')) {
    $sub = substr($p, strlen('/api/mock/v1/'));
    $b = body();
    $r = mock_handle($sub, $b, (bool) ($b['stream'] ?? false));
    if (($r['__sse_done'] ?? false) === true) exit;
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($r, JSON_UNESCAPED_UNICODE);
    exit;
}

/* ── 静态资源 ─────────────────────────────────────── */
if (!str_starts_with($p, '/api/')) {
    $file = __DIR__ . $p;
    if (is_file($file) && !str_contains($p, '..')) return false; // 交给内置服务器
    // SPA 回退
    header('Content-Type: text/html; charset=utf-8');
    readfile(__DIR__ . '/index.html');
    exit;
}

/* ── 路由表 ───────────────────────────────────────── */
$routes = [
    ['GET',  '#^/api/health$#',                              'h_health'],
    ['GET',  '#^/api/presets$#',                             'h_presets'],
    ['POST', '#^/api/auth/login$#',                          'h_login'],
    ['POST', '#^/api/auth/register$#',                       'h_register'],
    ['POST', '#^/api/auth/password$#',                      'h_password'],
    ['POST', '#^/api/auth/logout$#',                         'h_logout'],
    ['GET',  '#^/api/auth/me$#',                             'h_me'],
    ['PUT',  '#^/api/auth/theme$#',                          'h_theme'],

    ['GET',  '#^/api/admin/channels$#',                      'h_channels_list'],
    ['POST', '#^/api/admin/channels$#',                      'h_channels_create'],
    ['PUT',  '#^/api/admin/channels/(\d+)$#',                'h_channels_update'],
    ['DELETE','#^/api/admin/channels/(\d+)$#',               'h_channels_delete'],
    ['POST', '#^/api/admin/channels/(\d+)/toggle$#',         'h_channels_toggle'],
    ['GET',  '#^/api/admin/channels/(\d+)/impact$#',         'h_channels_impact'],
    ['POST', '#^/api/admin/channels/(\d+)/probe$#',          'h_channel_probe'],
    ['POST', '#^/api/admin/channels/(\d+)/sync$#',           'h_channel_sync'],

    ['GET',  '#^/api/admin/models$#',                        'h_models_list'],
    ['POST', '#^/api/admin/models$#',                        'h_models_create'],
    ['PUT',  '#^/api/admin/models/(\d+)$#',                  'h_models_update'],
    ['DELETE','#^/api/admin/models/(\d+)$#',                 'h_models_delete'],
    ['POST', '#^/api/admin/models/(\d+)/default$#',          'h_models_default'],
    ['POST', '#^/api/admin/models/(\d+)/bind$#',             'h_models_bind'],
    ['DELETE','#^/api/admin/models/(\d+)/bind/(\d+)$#',      'h_models_unbind'],

    ['GET',  '#^/api/admin/invites$#',                       'h_invites_list'],
    ['POST', '#^/api/admin/invites$#',                       'h_invites_create'],
    ['POST', '#^/api/admin/invites/(\d+)/revoke$#',          'h_invites_revoke'],
    ['GET',  '#^/api/admin/settings$#',                      'h_settings_get'],
    ['PUT',  '#^/api/admin/settings$#',                      'h_settings_put'],
    ['GET',  '#^/api/admin/users$#',                         'h_admin_users'],
    ['POST', '#^/api/admin/users/(\d+)/status$#',            'h_admin_user_status'],
    ['POST', '#^/api/admin/users/(\d+)/reset-password$#',    'h_admin_reset_pw'],
    ['GET',  '#^/api/admin/stats$#',                         'h_admin_stats'],
    ['GET',  '#^/api/admin/audit$#',                         'h_admin_audit'],
    ['GET',  '#^/api/admin/experiments$#',                   'h_experiments'],
    ['PUT',  '#^/api/admin/experiments/(\d+)$#',             'h_experiment_update'],
    ['POST', '#^/api/admin/scheduler/run$#',                 'h_scheduler_run'],

    ['GET',  '#^/api/conversations$#',                       'h_conversations_list'],
    ['POST', '#^/api/conversations$#',                       'h_conversations_create'],
    ['GET',  '#^/api/conversations/(\d+)/messages$#',        'h_messages_list'],
    ['GET',  '#^/api/conversations/(\d+)/export$#',          'h_export'],
    ['POST', '#^/api/conversations/(\d+)/completions$#',     'h_completions'],
    ['POST', '#^/api/conversations/(\d+)/stop$#',            'h_stop'],
    ['PUT',  '#^/api/conversations/(\d+)$#',                 'h_conversations_update'],
    ['DELETE','#^/api/conversations/(\d+)$#',                'h_conversations_delete'],
    ['POST', '#^/api/conversations/(\d+)/undelete$#',        'h_conversations_undelete'],
    ['POST', '#^/api/messages/(\d+)/feedback$#',             'h_feedback'],
    ['GET',  '#^/api/quota$#',                               'h_quota'],
    ['GET',  '#^/api/templates$#',                           'h_templates_list'],
    ['POST', '#^/api/templates$#',                           'h_templates_create'],

    ['GET',  '#^/api/rooms$#',                               'h_rooms_list'],
    ['POST', '#^/api/rooms$#',                               'h_rooms_create'],
    ['GET',  '#^/api/rooms/(\d+)$#',                         'h_rooms_detail'],
    ['POST', '#^/api/rooms/(\d+)/join$#',                    'h_rooms_join'],
    ['GET',  '#^/api/rooms/(\d+)/messages$#',                'h_room_messages'],
    ['POST', '#^/api/rooms/(\d+)/messages$#',                'h_room_message_post'],
    ['POST', '#^/api/rooms/(\d+)/ai$#',                      'h_room_ai'],

    ['GET',  '#^/api/friends$#',                             'h_friends_list'],
    ['POST', '#^/api/friends/request$#',                     'h_friends_request'],
    ['POST', '#^/api/friends/(\d+)/accept$#',                'h_friends_accept'],
    ['GET',  '#^/api/dm/(\d+)$#',                            'h_dm_list'],
    ['POST', '#^/api/dm/(\d+)$#',                            'h_dm_send'],
    ['GET',  '#^/api/search$#',                              'h_search'],
    ['POST', '#^/api/shares$#',                              'h_share_create'],
    ['GET',  '#^/api/shares/([A-Za-z0-9]+)$#',              'h_share_get'],
    ['POST', '#^/api/uploads$#',                             'h_upload'],
    ['GET',  '#^/api/uploads/(\d+)$#',                       'h_upload_get'],
];

try {
    foreach ($routes as [$verb, $pattern, $fn]) {
        if ($verb !== method()) continue;
        if (preg_match($pattern, $p, $m)) {
            $fn($m);
            exit; // handler 正常都会 ok()/exit
        }
    }
    fail('NOT_FOUND', '接口不存在: ' . $p, 404);
} catch (AppError $e) {
    fail($e->errCode, $e->getMessage(), $e->http, $e->detail);
} catch (Throwable $e) {
    error_log('[LinkAI] ' . get_class($e) . ': ' . $e->getMessage() . ' @ ' . $e->getFile() . ':' . $e->getLine());
    fail('INTERNAL', '服务器开小差了', 500,
        cfg('environment') === 'development' ? ['error' => $e->getMessage(), 'line' => $e->getLine(), 'file' => basename($e->getFile())] : null);
}
