<?php
declare(strict_types=1);
$S = dirname(__DIR__);
require_once "$S/src/lib.php";

echo "[1/3] 建表 ...\n";
$sql = file_get_contents("$S/src/schema.sql");
$sql = implode("\n", array_filter(explode("\n", $sql), fn($l) => !str_starts_with(trim($l), '--')));
$stmts = array_filter(array_map('trim', explode(";", $sql)), fn($s) => $s !== '');
foreach ($stmts as $stmt) {
    try { db()->exec($stmt); }
    catch (Throwable $e) { fwrite(STDERR, "SQL 失败: " . mb_substr($stmt, 0, 80) . " => {$e->getMessage()}\n"); exit(1); }
}
echo '      ' . count($stmts) . " 张表就绪\n";

echo "[2/3] 种子数据 ...\n";
$adminEmail = getenv('SEED_ADMIN_EMAIL') ?: 'admin@demo.com';
$adminPass  = getenv('SEED_ADMIN_PASSWORD') ?: 'AdminPass2026';

if (!val('SELECT id FROM users WHERE email=?', [$adminEmail])) {
    q('INSERT INTO users (email,nickname,password_hash,role,must_change_password) VALUES (?,?,?,?,1)',
        [$adminEmail, '管理员', hash_pw($adminPass), 'admin']);
    echo "      管理员 $adminEmail 已创建（首次登录需改密）\n";
} else {
    echo "      管理员已存在，跳过\n";
}
$adminId = (int) val('SELECT id FROM users WHERE email=?', [$adminEmail]);

foreach (default_settings() as $k => $v) save_setting($k, $v);

foreach ([['smart', '主力模型', 'premium', 32768, 2.4, 9.6, 1], ['fast', '低价模型', 'fast', 65536, 1.0, 2.0, 0]] as $m) {
    q('INSERT INTO models (public_name,display_name,tier,context_limit,price_input,price_output,is_default)
       VALUES (?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE display_name=VALUES(display_name)', $m);
}

// 预置内置 mock 渠道，登录即可跑通全链路（可在管理端删除后按 README 流程重建）
$mockUrl = 'http://127.0.0.1:8080/api/mock/v1';
$ch = one('SELECT * FROM channels WHERE name=?', ['本地 Mock']);
if (!$ch) {
    $cid = (int) insert('INSERT INTO channels (name,protocol,base_url,api_key_enc,api_key_hint,priority,weight,enabled)
        VALUES (?,?,?,?,?,?,?,1)', ['本地 Mock', 'openai_compatible', $mockUrl, encrypt_key('sk-mock-local'), key_hint('sk-mock-local'), 100, 100]);
    q('INSERT INTO channel_models (channel_id,upstream_model) VALUES (?,?)', [$cid, 'mock-chat']);
    q('INSERT INTO channel_models (channel_id,upstream_model) VALUES (?,?)', [$cid, 'mock-fast']);
    $smart = (int) val('SELECT id FROM models WHERE public_name=?', ['smart']);
    q('INSERT INTO model_channels (model_id,channel_id,upstream_model,weight) VALUES (?,?,?,100)
       ON DUPLICATE KEY UPDATE upstream_model=VALUES(upstream_model)', [$smart, $cid, 'mock-chat']);
    echo "      已预置「本地 Mock」渠道并绑定 smart → mock-chat\n";
}

if (!val("SELECT id FROM rooms WHERE name='闲聊室'", [])) {
    $rid = (int) insert('INSERT INTO rooms (name,description,owner_id,access_type,member_count) VALUES (?,?,?,?,1)',
        ['闲聊室', '随便聊，@AI 才触发模型', $adminId, 'public']);
    q('INSERT INTO room_members (room_id,user_id,role) VALUES (?,?,?)', [$rid, $adminId, 'owner']);
    q('INSERT INTO room_messages (room_id,user_id,nickname,kind,content) VALUES (?,NULL,?,?,?)',
        [$rid, '系统', 'system', '欢迎来到闲聊室，@AI 可以唤起助手']);
    echo "      已创建示例房间「闲聊室」\n";
}

echo "[3/3] 邀请码 ...\n";
$n = (int) val('SELECT COUNT(*) FROM invite_codes', [], 0);
if ($n === 0) {
    $codes = [];
    for ($i = 0; $i < 5; $i++) {
        $c = invite_code(); $codes[] = $c;
        q('INSERT INTO invite_codes (code,created_by,max_uses) VALUES (?,?,1)', [$c, $adminId]);
    }
    echo '      邀请码（仅此一次打印）：' . implode('  ', $codes) . "\n";
} else {
    echo "      已有 $n 个邀请码，跳过\n";
}

q('INSERT INTO experiments (name,variant_a,enabled) VALUES (?,?,1) ON DUPLICATE KEY UPDATE name=name', ['默认回复长度', 50]);
foreach ([['日常助手', '请用简洁口语化中文回答，控制在 100 字内。'], ['代码评审', '请从正确性、性能、可读性三方面评审以下代码。']] as $t) {
    if (!val('SELECT id FROM templates WHERE name=? AND scope=\'system\'', [$t[0]])) {
        q('INSERT INTO templates (name,content,scope) VALUES (?,?,?)', [$t[0], $t[1], 'system']);
    }
}
echo "完成：http://127.0.0.1:8080  管理员 $adminEmail / $adminPass\n";
