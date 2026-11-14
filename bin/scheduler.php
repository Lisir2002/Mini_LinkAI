<?php
declare(strict_types=1);
// 用法：php scheduler.php --once  （或前台常驻，每 60 秒一次）
$S = dirname(__DIR__);
require_once "$S/src/handlers_misc.php";
$once = in_array('--once', $argv, true);
do {
    try {
        $r = scheduler_tick();
        echo '[' . now_utc() . '] ' . json_encode($r, JSON_UNESCAPED_UNICODE) . "\n";
    } catch (Throwable $e) {
        echo '[scheduler] ' . $e->getMessage() . "\n";
    }
    if ($once) break;
    sleep(60);
} while (true);
