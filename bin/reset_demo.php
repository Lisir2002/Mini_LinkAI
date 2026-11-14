<?php
declare(strict_types=1);
// 把站点恢复到「刚跑完 migrate」的干净状态，保留 schema / 种子 / 配置
$S = dirname(__DIR__);
require_once "$S/src/lib.php";
$tables = ['messages','conversations','usage_logs','quota_daily','ai_jobs','audit_logs',
           'jwt_blacklist','idempotency','shares','feedback','friends','dm_messages',
           'uploads','room_messages'];
foreach ($tables as $t) q("DELETE FROM `$t`");
q("UPDATE users SET must_change_password=1, token_version=1, theme='light', status='active' WHERE email=?", ['admin@demo.com']);
$rid = (int) val("SELECT id FROM rooms WHERE name='闲聊室'", [], 0);
if ($rid) {
    q('INSERT INTO room_messages (room_id,user_id,nickname,kind,content) VALUES (?,NULL,?,?,?)',
        [$rid, '系统', 'system', '欢迎来到闲聊室，@AI 可以唤起助手']);
}
echo "演示数据已清空，管理员恢复为首次登录强制改密状态\n";
