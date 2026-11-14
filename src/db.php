<?php
declare(strict_types=1);

function db(): PDO {
    static $pdo = null;
    if ($pdo instanceof PDO) return $pdo;
    $cfg = require __DIR__ . '/config.php';
    $dsn = sprintf('mysql:host=%s;port=%d;dbname=%s;charset=utf8mb4',
        $cfg['db_host'], $cfg['db_port'], $cfg['db_name']);
    $pdo = new PDO($dsn, $cfg['db_user'], $cfg['db_pass'], [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
        PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        PDO::ATTR_EMULATE_PREPARES => false,
        PDO::ATTR_STRINGIFY_FETCHES => false,
        PDO::MYSQL_ATTR_INIT_COMMAND => "SET time_zone = '+00:00', sql_mode = 'STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION'",
    ]);
    return $pdo;
}

function q(string $sql, array $args = []): PDOStatement {
    $st = db()->prepare($sql);
    foreach (array_values($args) as $i => $v) {
        $st->bindValue($i + 1, $v, is_int($v) ? PDO::PARAM_INT : (is_null($v) ? PDO::PARAM_NULL : PDO::PARAM_STR));
    }
    $st->execute();
    return $st;
}

function one(string $sql, array $args = []): ?array {
    $r = q($sql, $args)->fetch();
    return $r === false ? null : $r;
}

function all(string $sql, array $args = []): array {
    return q($sql, $args)->fetchAll();
}

function val(string $sql, array $args = [], mixed $default = null): mixed {
    $r = q($sql, $args)->fetchColumn();
    return $r === false ? $default : $r;
}

function insert(string $sql, array $args = []): string {
    q($sql, $args);
    return db()->lastInsertId();
}

/** 事务封装：异常自动回滚 */
function tx(callable $fn): mixed {
    $p = db();
    $p->beginTransaction();
    try {
        $r = $fn();
        $p->commit();
        return $r;
    } catch (Throwable $e) {
        if ($p->inTransaction()) $p->rollBack();
        throw $e;
    }
}

function now_utc(): string { return gmdate('Y-m-d H:i:s'); }

/** 配额日切必须按 Asia/Shanghai，不能用 UTC 的 date() */
function quota_date(): string {
    return (new DateTimeImmutable('now', new DateTimeZone('Asia/Shanghai')))->format('Y-m-d');
}
