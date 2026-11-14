<?php
declare(strict_types=1);
$sock = '/tmp/linkai-mysql.sock';
$opts = [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION, PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC];
try {
    $pdo = new PDO("mysql:unix_socket=$sock;charset=utf8mb4", 'root', '', $opts);
    $pdo->exec('CREATE DATABASE IF NOT EXISTS linkai CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci');
    $pdo->exec("CREATE USER IF NOT EXISTS 'linkai'@'127.0.0.1' IDENTIFIED BY 'linkai_dev_2026'");
    $pdo->exec("CREATE USER IF NOT EXISTS 'linkai'@'localhost' IDENTIFIED BY 'linkai_dev_2026'");
    $pdo->exec("GRANT ALL PRIVILEGES ON linkai.* TO 'linkai'@'127.0.0.1'");
    $pdo->exec("GRANT ALL PRIVILEGES ON linkai.* TO 'linkai'@'localhost'");
    $pdo->exec('FLUSH PRIVILEGES');
    $tcp = new PDO('mysql:host=127.0.0.1;port=3308;dbname=linkai;charset=utf8mb4', 'linkai', 'linkai_dev_2026', $opts);
    $v = $tcp->query('SELECT VERSION()')->fetchColumn();
    echo "DB_READY mysql=$v\n";
} catch (Throwable $e) {
    fwrite(STDERR, 'DB_ERR ' . $e->getMessage() . "\n");
    exit(1);
}
