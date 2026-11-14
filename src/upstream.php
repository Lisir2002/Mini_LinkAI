<?php
declare(strict_types=1);
require_once __DIR__ . '/lib.php';

/* ── SSE 输出 ──────────────────────────────────────── */
function sse_start(): void {
    http_response_code(200);
    header('Content-Type: text/event-stream; charset=utf-8');
    header('Cache-Control: no-cache, no-transform');
    header('X-Accel-Buffering: no');
    header('Connection: keep-alive');
    while (ob_get_level() > 0) @ob_end_flush();
    @ob_implicit_flush(true);
    ignore_user_abort(false);
}
function sse_emit(string $event, array $data): void {
    echo 'event: ' . $event . "\n";
    echo 'data: ' . json_encode($data, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . "\n\n";
    @flush();
}
function ai_cancelled(?string $gen): bool {
    if (!$gen) return false;
    if (connection_aborted() === 1) return true;
    try { return (bool) val('SELECT cancel_requested FROM ai_jobs WHERE generation_id=?', [$gen], 0); }
    catch (Throwable) { return false; }
}
function ai_job_start(string $gen, int $uid, ?int $convId, ?int $roomId): void {
    q('INSERT INTO ai_jobs (generation_id,conversation_id,room_id,user_id,status) VALUES (?,?,?,?,?) ON DUPLICATE KEY UPDATE status=\'running\',cancel_requested=0',
        [$gen, $convId, $roomId, $uid, 'running']);
}
function ai_job_end(string $gen, string $status): void {
    q('UPDATE ai_jobs SET status=? WHERE generation_id=?', [$status, $gen]);
}

/* ── 协议预设（管理端一键填充）────────────────────── */
function protocol_presets(): array {
    return [
        ['key' => 'openai_compatible', 'label' => 'OpenAI 兼容', 'fields' => ['base_url', 'api_key'],
         'presets' => [
             ['name' => '本地 Mock', 'base_url' => 'http://127.0.0.1:8080/api/mock/v1', 'api_key' => 'sk-mock-local'],
             ['name' => 'DeepSeek', 'base_url' => 'https://api.deepseek.com/v1', 'api_key' => ''],
             ['name' => '通义千问', 'base_url' => 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'api_key' => ''],
             ['name' => 'OpenAI', 'base_url' => 'https://api.openai.com/v1', 'api_key' => ''],
             ['name' => 'Moonshot', 'base_url' => 'https://api.moonshot.cn/v1', 'api_key' => ''],
         ]],
        ['key' => 'anthropic', 'label' => 'Anthropic', 'fields' => ['base_url', 'api_key'],
         'presets' => [['name' => 'Anthropic', 'base_url' => 'https://api.anthropic.com', 'api_key' => '']]],
        ['key' => 'gemini', 'label' => 'Gemini', 'fields' => ['base_url', 'api_key'],
         'presets' => [['name' => 'Google AI Studio', 'base_url' => 'https://generativelanguage.googleapis.com', 'api_key' => '']]],
    ];
}

/**
 * Anthropic 兼容端点鉴权头。
 * 标准 Anthropic 用 x-api-key；国内 MaaS（如讯飞星火 maas-api）多要求
 * Authorization: Bearer。两种同时发送，兼容面更广，服务端只认其中一个即可。
 */
function anthropic_headers(string $key): array {
    return [
        'Content-Type: application/json',
        'x-api-key: ' . $key,
        'Authorization: Bearer ' . $key,
        'anthropic-version: 2023-06-01',
    ];
}

/* ── 统一上游请求构造 ─────────────────────────────── */
function upstream_build(array $ch, string $model, array $messages, bool $stream): array {
    $base = rtrim($ch['base_url'], '/');
    $key = decrypt_key($ch['api_key_enc'] ?? null);
    $proto = $ch['protocol'];
    if ($proto === 'anthropic') {
        $sys = '';
        $msgs = [];
        foreach ($messages as $m) {
            if ($m['role'] === 'system') { $sys .= ($sys ? "\n" : '') . $m['content']; continue; }
            $msgs[] = ['role' => $m['role'] === 'assistant' ? 'assistant' : 'user', 'content' => $m['content']];
        }
        $b = ['model' => $model, 'max_tokens' => 4096, 'messages' => $msgs, 'stream' => $stream];
        if ($sys !== '') $b['system'] = $sys;
        return [$base . '/v1/messages', anthropic_headers($key), $b];
    }
    if ($proto === 'gemini') {
        $contents = [];
        foreach ($messages as $m) {
            $contents[] = ['role' => $m['role'] === 'assistant' ? 'model' : 'user', 'parts' => [['text' => $m['content']]]];
        }
        return [$base . '/v1beta/models/' . rawurlencode($model) . ':streamGenerateContent?alt=sse&key=' . rawurlencode($key),
            ['Content-Type: application/json'], ['contents' => $contents, 'generationConfig' => ['maxOutputTokens' => 4096]]];
    }
    $b = ['model' => $model, 'messages' => $messages, 'stream' => $stream];
    if ($stream) $b['stream_options'] = ['include_usage' => true];
    return [$base . '/chat/completions',
        ['Content-Type: application/json', 'Authorization: Bearer ' . $key], $b];
}

/** 从一条上游 SSE data 中提取增量文本与用量（三协议归一） */
function upstream_parse_event(array $ch, array $j, &$usage): string {
    $proto = $ch['protocol'];
    if ($proto === 'anthropic') {
        $t = $j['type'] ?? '';
        if ($t === 'content_block_delta') return (string) ($j['delta']['text'] ?? '');
        if ($t === 'message_start') $usage['in'] = (int) ($j['message']['usage']['input_tokens'] ?? 0);
        if ($t === 'message_delta') $usage['out'] = (int) ($j['usage']['output_tokens'] ?? 0);
        if ($t === 'error') throw new RuntimeException('Anthropic: ' . ($j['error']['message'] ?? 'unknown'));
        return '';
    }
    if ($proto === 'gemini') {
        if (isset($j['usageMetadata'])) {
            $usage['in'] = (int) ($j['usageMetadata']['promptTokenCount'] ?? 0);
            $usage['out'] = (int) ($j['usageMetadata']['candidatesTokenCount'] ?? 0);
        }
        return (string) ($j['candidates'][0]['content']['parts'][0]['text'] ?? '');
    }
    if (isset($j['usage'])) {
        $usage['in'] = (int) ($j['usage']['prompt_tokens'] ?? 0);
        $usage['out'] = (int) ($j['usage']['completion_tokens'] ?? 0);
    }
    if (isset($j['error'])) throw new RuntimeException('上游错误: ' . ($j['error']['message'] ?? 'unknown'));
    return (string) ($j['choices'][0]['delta']['content'] ?? '');
}

/**
 * 流式调用上游。$emit('delta'|'usage'|'done'|'error', data)
 * 返回 ['text'=>..., 'in'=>..., 'out'=>...]
 */
function upstream_stream(array $ch, string $model, array $messages, callable $emit, ?string $gen = null): array {
    [$url, $headers, $body] = upstream_build($ch, $model, $messages, true);
    $buf = ''; $text = ''; $usage = ['in' => 0, 'out' => 0]; $err = null;
    $curl = curl_init($url);
    curl_setopt_array($curl, [
        CURLOPT_POST => true,
        CURLOPT_HTTPHEADER => $headers,
        CURLOPT_POSTFIELDS => json_encode($body, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES),
        CURLOPT_CONNECTTIMEOUT => 10,
        CURLOPT_TIMEOUT => (int) ceil(cfg('ai_total_timeout_ms') / 1000) + 10,
        CURLOPT_SSL_VERIFYPEER => true,
        CURLOPT_SSL_VERIFYHOST => 2,
        CURLOPT_WRITEFUNCTION => function ($h, $chunk) use (&$buf, &$text, &$usage, &$err, $ch, $emit, $gen) {
            if (ai_cancelled($gen)) return 0;
            $buf .= str_replace("\r\n", "\n", $chunk);
            while (($pos = strpos($buf, "\n\n")) !== false) {
                $block = substr($buf, 0, $pos); $buf = substr($buf, $pos + 2);
                foreach (explode("\n", $block) as $line) {
                    $line = trim($line);
                    if (!str_starts_with($line, 'data:')) continue;
                    $raw = trim(substr($line, 5));
                    if ($raw === '' || $raw === '[DONE]') continue;
                    $j = json_decode($raw, true);
                    if (!is_array($j)) continue;
                    try {
                        $delta = upstream_parse_event($ch, $j, $usage);
                        if ($delta !== '') { $text .= $delta; $emit('delta', ['content' => $delta]); }
                    } catch (Throwable $e) { $err = $e->getMessage(); }
                }
                if ($err) return 0;
            }
            return strlen($chunk);
        },
    ]);
    $ok = curl_exec($curl);
    $httpCode = (int) curl_getinfo($curl, CURLINFO_HTTP_CODE);
    $cerr = curl_error($curl);
    curl_close($curl);
    if ($err) throw new RuntimeException($err);
    if ($httpCode >= 400) throw new RuntimeException("上游 HTTP $httpCode");
    if ($ok === false && $cerr && !ai_cancelled($gen)) throw new RuntimeException('上游连接失败: ' . $cerr);
    if ($usage['out'] === 0 && $text !== '') $usage['out'] = (int) ceil(mb_strlen($text) / 2);
    if ($usage['in'] === 0) $usage['in'] = (int) ceil(mb_strlen(implode('', array_column($messages, 'content'))) / 3);
    return ['text' => $text, 'in' => $usage['in'], 'out' => $usage['out'], 'cancelled' => ai_cancelled($gen)];
}

/** 非流式请求：用于连通性测试 / 同步模型 */
function upstream_http(string $url, array $headers = [], ?array $post = null, string $method = 'GET'): array {
    $c = curl_init($url);
    $opts = [CURLOPT_RETURNTRANSFER => true, CURLOPT_TIMEOUT => 20, CURLOPT_CONNECTTIMEOUT => 8,
        CURLOPT_HTTPHEADER => $headers, CURLOPT_SSL_VERIFYPEER => true, CURLOPT_SSL_VERIFYHOST => 2];
    if ($post !== null) { $opts[CURLOPT_POST] = true; $opts[CURLOPT_POSTFIELDS] = json_encode($post, JSON_UNESCAPED_UNICODE); }
    if ($method !== 'GET' && $post === null) $opts[CURLOPT_CUSTOMREQUEST] = $method;
    curl_setopt_array($c, $opts);
    $raw = curl_exec($c);
    $code = (int) curl_getinfo($c, CURLINFO_HTTP_CODE);
    $err = curl_error($c);
    curl_close($c);
    if ($raw === false) throw new RuntimeException($err ?: '请求失败');
    if ($code >= 400) throw new RuntimeException("HTTP $code: " . mb_substr((string) $raw, 0, 200));
    return json_decode((string) $raw, true) ?: [];
}

function upstream_probe(array $ch, string $model = ''): array {
    $base = rtrim($ch['base_url'], '/');
    $key = decrypt_key($ch['api_key_enc'] ?? null);
    if ($ch['protocol'] === 'anthropic') {
        // 兼容端点（如讯飞 MaaS）模型名不是 claude-*，不能硬编码。
        // 优先用 /v1/models 探活并取回真实模型列表；端点不支持时再用已绑定的模型名发一条短消息。
        $t0 = microtime(true);
        try {
            $r = upstream_http($base . '/v1/models', anthropic_headers($key));
            $models = array_values(array_filter(array_map(
                fn($m) => (string) ($m['id'] ?? $m['name'] ?? ''), $r['data'] ?? $r['models'] ?? [])));
            if ($models) {
                return ['ok' => true, 'latency_ms' => (int) ((microtime(true) - $t0) * 1000), 'models' => $models];
            }
        } catch (Throwable $e) {
            $modelsErr = $e->getMessage();
        }
        if ($model === '') {
            $model = (string) val('SELECT upstream_model FROM model_channels WHERE channel_id=? ORDER BY id LIMIT 1', [$ch['id'] ?? 0], '');
        }
        if ($model === '') $model = 'claude-3-5-haiku-latest';
        try {
            upstream_http($base . '/v1/messages', anthropic_headers($key),
                ['model' => $model, 'max_tokens' => 16, 'messages' => [['role' => 'user', 'content' => 'hi']]]);
            return ['ok' => true, 'latency_ms' => (int) ((microtime(true) - $t0) * 1000),
                    'models' => [$model], 'note' => '/v1/models 不可用，已用绑定模型名探活'];
        } catch (Throwable $e2) {
            throw new RuntimeException('Anthropic 兼容端点探活失败：' . ($modelsErr ?? '') . ' / ' . $e2->getMessage());
        }
    }
    if ($ch['protocol'] === 'gemini') {
        $r = upstream_http($base . '/v1beta/models?key=' . rawurlencode($key));
        return ['ok' => true, 'models' => array_column($r['models'] ?? [], 'name')];
    }
    $t0 = microtime(true);
    $r = upstream_http($base . '/models', ['Authorization: Bearer ' . $key]);
    return ['ok' => true, 'latency_ms' => (int) ((microtime(true) - $t0) * 1000),
            'models' => array_column($r['data'] ?? [], 'id')];
}

function upstream_sync_models(array $ch): array {
    if ($ch['protocol'] === 'anthropic') {
        $key = decrypt_key($ch['api_key_enc'] ?? null);
        $base = rtrim($ch['base_url'], '/');
        try {
            $r = upstream_http($base . '/v1/models', anthropic_headers($key));
            $models = array_values(array_filter(array_map(
                fn($m) => (string) ($m['id'] ?? $m['name'] ?? ''), $r['data'] ?? $r['models'] ?? [])));
            if ($models) return $models;
        } catch (Throwable) { /* 兼容端点可能不提供 models */ }
        // 回退：返回该渠道已经绑定过的真实上游模型名，而不是虚构 claude-*
        $bound = array_column(all('SELECT DISTINCT upstream_model FROM model_channels WHERE channel_id=?', [$ch['id'] ?? 0]), 'upstream_model');
        if ($bound) return array_values($bound);
        return ['claude-3-5-sonnet-latest', 'claude-3-5-haiku-latest', 'claude-3-opus-latest'];
    }
    if ($ch['protocol'] === 'gemini') {
        $r = upstream_http(rtrim($ch['base_url'], '/') . '/v1beta/models?key=' . rawurlencode(decrypt_key($ch['api_key_enc'] ?? null)));
        return array_values(array_map(fn($n) => preg_replace('#^models/#', '', (string) $n), array_column($r['models'] ?? [], 'name')));
    }
    $r = upstream_http(rtrim($ch['base_url'], '/') . '/models', ['Authorization: Bearer ' . decrypt_key($ch['api_key_enc'] ?? null)]);
    return array_values(array_column($r['data'] ?? [], 'id'));
}

/* ── 内置 mock 上游：零外部依赖即可跑通全链路 ─────── */
function mock_handle(string $sub, array $body, bool $stream): array {
    if (!str_starts_with(bearer(), 'Bearer ') && !($_SERVER['HTTP_X_API_KEY'] ?? '')) {
        // mock 只校验非空 Authorization
        $auth = '';
        foreach ($_SERVER as $k => $v) if (stripos($k, 'AUTHORIZATION') !== false) $auth = (string) $v;
        if ($auth === '') { http_response_code(401); return ['error' => ['message' => 'missing key']]; }
    }
    if ($sub === 'models') return ['data' => [['id' => 'mock-chat'], ['id' => 'mock-fast']]];
    if ($sub === 'chat/completions') {
        $reply = '这是来自内置 mock 上游的流式回复：Vue + PHP + MySQL 链路已打通，配额按实际用量结算。';
        if (!$stream) {
            return ['choices' => [['message' => ['content' => $reply], 'finish_reason' => 'stop']],
                    'usage' => ['prompt_tokens' => 12, 'completion_tokens' => (int) ceil(mb_strlen($reply) / 2), 'total_tokens' => 12 + (int) ceil(mb_strlen($reply) / 2)]];
        }
        sse_start();
        foreach (mb_str_split($reply) as $ch) {
            sse_emit('message', ['choices' => [['delta' => ['content' => $ch]]]]);
            usleep(12000);
            if (connection_aborted() === 1) break;
        }
        $out = (int) ceil(mb_strlen($reply) / 2);
        sse_emit('message', ['choices' => [['delta' => [], 'finish_reason' => 'stop']],
            'usage' => ['prompt_tokens' => 12, 'completion_tokens' => $out, 'total_tokens' => 12 + $out]]);
        sse_emit('message', ['[DONE]' => true]);
        return ['__sse_done' => true];
    }
    http_response_code(404);
    return ['error' => 'not found'];
}
