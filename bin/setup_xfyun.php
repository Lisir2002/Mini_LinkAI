<?php
declare(strict_types=1);
/**
 * 配置讯飞星火 MaaS（Anthropic 兼容端点）为模型渠道并自动绑定默认模型。
 *
 * 环境变量：
 *   XF_API_KEY   必填，例如 ak-xxxxxxxx
 *   XF_BASE_URL  默认 https://maas-api.cn-huabei-1.xf-yun.com/anthropic
 *                （注意：不带 /v1/messages，程序会自动拼 /v1/messages）
 *   XF_MODEL     可选；当端点不提供 /v1/models 时手工指定模型名
 *
 * 用法：php bin/setup_xfyun.php
 */
$S = dirname(__DIR__);
require_once "$S/src/lib.php";
require_once "$S/src/upstream.php";

$base = rtrim(getenv('XF_BASE_URL') ?: 'https://maas-api.cn-huabei-1.xf-yun.com/anthropic', '/');
$key  = (string) (getenv('XF_API_KEY') ?: '');
$fixModel = trim((string) (getenv('XF_MODEL') ?: ''));
$name = '讯飞星火 MaaS';

if ($key === '') {
    echo json_encode(['ok' => false, 'message' => '缺少 XF_API_KEY'], JSON_UNESCAPED_UNICODE) . "\n";
    exit(1);
}

$out = ['base_url' => $base, 'steps' => []];
try {
    // 1) 渠道 upsert（Key 加密存储，只回显末 4 位）
    $old = one('SELECT * FROM channels WHERE name=?', [$name]);
    if ($old) {
        q('UPDATE channels SET protocol=?,base_url=?,api_key_enc=?,api_key_hint=?,enabled=1,
            fail_count=0,last_error=NULL,cooldown_until=NULL,version=version+1 WHERE id=?',
            ['anthropic', $base, encrypt_key($key), key_hint($key), $old['id']]);
        $cid = (int) $old['id'];
        $out['steps'][] = '更新已有渠道 #' . $cid;
    } else {
        $cid = (int) insert('INSERT INTO channels (name,protocol,base_url,api_key_enc,api_key_hint,priority,weight,enabled)
            VALUES (?,?,?,?,?,?,?,1)', [$name, 'anthropic', $base, encrypt_key($key), key_hint($key), 100, 100]);
        $out['steps'][] = '创建渠道 #' . $cid;
    }
    $ch = one('SELECT * FROM channels WHERE id=?', [$cid]);

    // 2) 连通性测试（会真实请求 /v1/models 或 /v1/messages）
    $probe = upstream_probe($ch, $fixModel);
    channel_success($cid);
    $out['probe'] = $probe;
    $out['steps'][] = '连通测试通过' . (isset($probe['latency_ms']) ? " ({$probe['latency_ms']}ms)" : '');

    // 3) 同步模型
    $models = upstream_sync_models($ch);
    if ($fixModel !== '') array_unshift($models, $fixModel);
    $models = array_values(array_unique(array_filter($models, fn($m) => $m !== '')));
    foreach ($models as $m) {
        q('INSERT INTO channel_models (channel_id,upstream_model) VALUES (?,?)
           ON DUPLICATE KEY UPDATE synced_at=UTC_TIMESTAMP()', [$cid, $m]);
    }
    $out['models'] = $models;
    $out['steps'][] = '同步到 ' . count($models) . ' 个上游模型';

    // 4) 绑定默认对外模型（smart）到第一个真实上游模型
    $upstream = $models[0] ?? '';
    if ($upstream === '') throw new RuntimeException('未拿到任何上游模型名，请用 XF_MODEL 指定');
    $defaultModel = one('SELECT * FROM models WHERE is_default=1 LIMIT 1')
        ?: one('SELECT * FROM models ORDER BY id LIMIT 1');
    if (!$defaultModel) throw new RuntimeException('模型注册表为空，请先执行 migrate.php');
    q('INSERT INTO model_channels (model_id,channel_id,upstream_model,weight) VALUES (?,?,?,100)
       ON DUPLICATE KEY UPDATE upstream_model=VALUES(upstream_model),weight=VALUES(weight)',
        [$defaultModel['id'], $cid, $upstream]);
    $out['binding'] = ['public_name' => $defaultModel['public_name'], 'upstream_model' => $upstream];
    $out['steps'][] = "已绑定 {$defaultModel['public_name']} → {$upstream}";

    // 5) 本地 Mock 降为备用（不删除，保留可回滚）
    q('UPDATE channels SET priority=0 WHERE name=? AND id<>?', ['本地 Mock', $cid]);
    audit('channel.xfyun_setup', 'channel', (string) $cid, ['base_url' => $base, 'models' => $models]);

    $out['ok'] = true;
    echo json_encode($out, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT) . "\n";
} catch (Throwable $e) {
    if (isset($cid)) channel_fail($cid, false, $e->getMessage());
    $out['ok'] = false;
    $out['message'] = $e->getMessage();
    echo json_encode($out, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_PRETTY_PRINT) . "\n";
    exit(1);
}
