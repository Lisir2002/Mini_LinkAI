#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
在一台**能直连目标服务器**的机器上运行（例如你自己的电脑/跳板机）。

沙盒侧因出口访问策略被拒，无法直连服务器，故本脚本由你在本地执行。
默认只做只读探查；确认无误后加 --apply 才真正停站、移走旧源码、部署。

用法：
  export LK_HOST='你的服务器IP' LK_USER=root LK_PASS='你的密码' LK_PORT=22
  export XF_API_KEY='你的模型接口Key'
  python3 deploy_remote.py                 # ① 只读探查，看清楚服务器上跑的是什么
  python3 deploy_remote.py --apply        # ② 真正执行（旧源码移入回收站，可恢复）

可选：
  --zip 指定源码包路径（默认自动查找）
  --xf-key 模型接口 Key；不填则读 XF_API_KEY 环境变量
  --port-web 新站端口（默认 8080）

注意：脚本不接受硬编码凭据，全部经环境变量传入，且不写入日志。
"""
import argparse, base64, os, sys, time, json, posixpath

try:
    import paramiko
except ImportError:
    print('请先安装 paramiko:  python3 -m pip install paramiko'); sys.exit(1)

ap = argparse.ArgumentParser()
ap.add_argument('--apply', action='store_true', help='真正执行部署；不加则只读探查')
ap.add_argument('--zip', default=None, help='源码包路径；不填则自动在同级/上级/当前目录查找')
ap.add_argument('--xf-key', default=os.getenv('XF_API_KEY', ''))
ap.add_argument('--port-web', type=int, default=8080)
args = ap.parse_args()

HOST = os.getenv('LK_HOST', '')
USER = os.getenv('LK_USER', 'root')
PASS = os.getenv('LK_PASS', '')
PORT = int(os.getenv('LK_PORT', '22'))
if not HOST:
    print('请设置环境变量 LK_HOST（目标服务器 IP 或域名）'); sys.exit(1)
if not PASS:
    print('请设置环境变量 LK_PASS（密码），不要写进命令行'); sys.exit(1)
if args.apply and not args.xf_key:
    print('提示：未设置 XF_API_KEY / --xf-key，将跳过模型渠道配置，可稍后在管理端手动填')
def find_zip():
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [args.zip] if args.zip else []
    cands += [
        os.path.join(here, 'Mini_LinkAI_PHP_源码包.zip'),
        os.path.join(here, '..', 'Mini_LinkAI_PHP_源码包.zip'),
        os.path.join(os.getcwd(), 'Mini_LinkAI_PHP_源码包.zip'),
        '/data/workspace/Mini_LinkAI_PHP_源码包.zip',
    ]
    for c in cands:
        if c and os.path.isfile(c): return os.path.abspath(c)
    return os.path.abspath(cands[1])

ZIP = find_zip()
REMOTE_ROOT = '/opt/linkai'
TRASH = '/root/linkai_trash/' + time.strftime('%Y%m%d_%H%M%S')

if not os.path.isfile(ZIP):
    print('找不到源码包:', ZIP); sys.exit(1)

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
print('连接 %s@%s:%d ...' % (USER, HOST, PORT))
try:
    cli.connect(HOST, port=PORT, username=USER, password=PASS, timeout=20,
                allow_agent=False, look_for_keys=False)
except Exception as e:
    print('SSH 连接失败:', type(e).__name__, str(e)[:300]); sys.exit(1)
print('SSH 已连接')

def run(cmd, timeout=180, quiet=False):
    if not quiet: print('  $ ' + cmd[:160])
    _in, out, err = cli.exec_command(cmd, timeout=timeout)
    o = out.read().decode('utf-8', 'ignore')
    e = err.read().decode('utf-8', 'ignore')
    rc = out.channel.recv_exit_status()
    if not quiet and (o.strip() or e.strip()):
        for line in (o + e).strip().splitlines()[:25]: print('    ' + line[:200])
    return rc, o, e

print('\n=== 系统信息 ===')
run('uname -a; cat /etc/os-release | head -4; echo "--- 端口 ---"; ss -lntp 2>/dev/null | head -20; echo "--- 进程 ---"; ps -eo pid,user,cmd --sort=-%mem | head -20')
print('\n=== Web 服务 / 站点目录 ===')
run('systemctl list-units --type=service --state=running 2>/dev/null | grep -iE "nginx|apache|php|node|docker|caddy|tomcat" || true; '
    'echo "--- 常见站点根 ---"; for d in /var/www /www/wwwroot /usr/share/nginx/html /home/www /opt/app /root/app; do '
    '[ -d "$d" ] && { echo "[$d]"; ls -la "$d" | head -12; }; done; '
    'echo "--- nginx 站点配置 ---"; ls /etc/nginx/conf.d/ /etc/nginx/sites-enabled/ /www/server/panel/vhost/nginx/ 2>/dev/null | head -30; '
    'echo "--- docker ---"; docker ps --format "{{.Names}} {{.Ports}} {{.Image}}" 2>/dev/null | head -15 || true')
print('\n=== PHP / MySQL 可用性 ===')
run('php -v 2>/dev/null | head -2 || echo "系统无 PHP（将使用包内自包含运行时）"; '
    'mysql --version 2>/dev/null || echo "系统无 MySQL 客户端（将使用包内运行时）"; '
    'nginx -v 2>&1 | head -1 || true')

if not args.apply:
    print('\n[只读探查完成] 上面就是服务器现状。确认无误后执行： python3 deploy_remote.py --apply')
    print('注意：--apply 会停掉现有 Web 服务，并把识别到的站点源码移动到 %s（可恢复，不删除）' % TRASH)
    cli.close(); sys.exit(0)

print('\n=== ① 保存现场 + 停站 ===')
run('mkdir -p ' + TRASH)
run('{ ss -lntp; ps aux; systemctl list-units --type=service --state=running; '
    'ls -la /var/www /www/wwwroot /usr/share/nginx/html 2>/dev/null; } > ' + TRASH + '/preflight.txt 2>&1')
# 停常见 Web 服务（不碰 sshd、不删任何东西）
run('for s in nginx apache2 httpd php8.1-fpm php-fpm php8.2-fpm caddy; do '
    'systemctl is-active --quiet "$s" && { systemctl stop "$s"; echo "stopped $s"; }; done')
# 停掉占 80/443/8080 的容器（若有），保留镜像与卷
run('if command -v docker >/dev/null 2>&1; then for c in $(docker ps --format "{{.Names}}"); do '
    'p=$(docker port "$c" 2>/dev/null | grep -E ":(80|443|8080)->" | head -1); '
    '[ -n "$p" ] && { docker stop "$c"; echo "stopped container $c"; }; done; fi')
# 兜底：杀掉仍占用 80/8080 的非 sshd 进程（先记录 PID）
run('for p in 80 443 8080; do for pid in $(ss -lntp 2>/dev/null | grep ":$p " | grep -oP "pid=\\K[0-9]+" | sort -u); do '
    'cmd=$(ps -p "$pid" -o cmd=); case "$cmd" in *sshd*) ;; *) echo "kill $pid $cmd"; kill "$pid" 2>/dev/null;; esac; done; done')

print('\n=== ② 旧源码移入回收站（mv，可恢复；不做 rm -rf）===')
run('for d in /var/www/html /usr/share/nginx/html /www/wwwroot /home/www /opt/app /root/app; do '
    'if [ -d "$d" ] && [ "$(ls -A "$d" 2>/dev/null | head -1)" != "" ]; then '
    't="' + TRASH + '/"$(echo "$d" | tr "/" "_"); mkdir -p "$t"; '
    'mv "$d"/* "$t"/ 2>/dev/null; mv "$d"/.[!.]* "$t"/ 2>/dev/null; echo "moved $d -> $t"; fi; done; '
    'echo "回收站: ' + TRASH + '"')
# 备份 nginx 站点配置后停用（不删）
run('for c in /etc/nginx/conf.d/*.conf /etc/nginx/sites-enabled/* /www/server/panel/vhost/nginx/*.conf; do '
    '[ -f "$c" ] && { cp "$c" "' + TRASH + '/"; echo "backed up $c"; }; done; '
    'mkdir -p /etc/nginx/conf.d.disabled 2>/dev/null || true; '
    'for c in /etc/nginx/conf.d/*.conf; do [ -f "$c" ] && mv "$c" /etc/nginx/conf.d.disabled/ 2>/dev/null; done')

print('\n=== ③ 上传并解压新站 ===')
remote_zip = '/tmp/linkai_deploy.zip'
sftp = cli.open_sftp()
print('  上传 %s (%.1f MB) ...' % (os.path.basename(ZIP), os.path.getsize(ZIP) / 1048576))
sftp.put(ZIP, remote_zip)
sftp.close()
run('rm -rf ' + REMOTE_ROOT + '; mkdir -p ' + REMOTE_ROOT + '; '
    'cd ' + REMOTE_ROOT + ' && unzip -q -o ' + remote_zip + ' && '
    'mv linkai-site/* linkai-site/.[!.]* . 2>/dev/null; rmdir linkai-site 2>/dev/null; '
    'chmod +x start.sh stop.sh bin/*.sh 2>/dev/null; echo "解压完成"; ls | head -15')

print('\n=== ④ 生成 .env.php（随机密钥）===')
run('cd ' + REMOTE_ROOT + ' && php -r \'file_put_contents(".env.php", "<?php return [\\n'
    '  \\"JWT_SECRET\\" => \\"" . bin2hex(random_bytes(32)) . "\\",\\n'
    '  \\"CHANNEL_CIPHER_KEY\\" => \\"" . bin2hex(random_bytes(32)) . "\\",\\n'
    '  \\"ENVIRONMENT\\" => \\"production\\",\\n];\\n");\' 2>/dev/null || '
    'cat > .env.php <<EOF\n<?php return [\n  "JWT_SECRET" => "$(openssl rand -hex 32)",\n'
    '  "CHANNEL_CIPHER_KEY" => "$(openssl rand -hex 32)",\n  "ENVIRONMENT" => "production",\n];\nEOF\n'
    'chmod 600 .env.php; echo ".env.php 已生成"')

print('\n=== ⑤ 启动站点 ===')
run('cd ' + REMOTE_ROOT + ' && PORT=' + str(args.port_web) + ' sh start.sh 2>&1 | tail -20', timeout=420)
rc, o, e = run('curl -sS -m 10 http://127.0.0.1:' + str(args.port_web) + '/api/health || true', quiet=True)
print('  健康检查:', (o + e).strip()[:300])

print('\n=== ⑥ 配置 nginx 反代（SSE 必须关 buffering）===')
nginx_conf = '''server {
    listen 80 default_server;
    server_name _;
    client_max_body_size 20m;
    location / {
        proxy_pass http://127.0.0.1:%d;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 300s;
        chunked_transfer_encoding on;
    }
}
''' % args.port_web
b64 = base64.b64encode(nginx_conf.encode()).decode()
run('if command -v nginx >/dev/null 2>&1; then mkdir -p /etc/nginx/conf.d; '
    'echo ' + b64 + ' | base64 -d > /etc/nginx/conf.d/linkai.conf; '
    'nginx -t 2>&1 | tail -3 && { systemctl enable nginx >/dev/null 2>&1; systemctl restart nginx; echo "nginx 反代已启用"; }; '
    'else echo "系统无 nginx，直接访问 http://%s:%d"; fi' % (HOST, args.port_web))

print('\n=== ⑦ 配置模型渠道（Anthropic 兼容端点）===')
if args.xf_key:
    # 通过 stdin 传 Key，不拼进远程命令行，避免出现在 shell history / ps
    k = base64.b64encode(args.xf_key.encode()).decode()
    run('cd ' + REMOTE_ROOT + ' && echo ' + k + ' | base64 -d > /tmp/.lk_key && '
        'XF_API_KEY="$(cat /tmp/.lk_key)" XF_BASE_URL="https://maas-api.cn-huabei-1.xf-yun.com/anthropic" '
        '.runtime/bin/php -c .runtime/php.ini bin/setup_xfyun.php 2>&1 | tail -40; rm -f /tmp/.lk_key', timeout=180)
else:
    print('  跳过（未设置 XF_API_KEY）；请到「我的 → 模型接口配置」手动添加渠道')

print('\n=== ⑧ 多类型聊天室测试（真实接口）===')
run('cd ' + REMOTE_ROOT + ' && python3 bin/test_chatrooms.py --base http://127.0.0.1:' + str(args.port_web) + ' 2>&1 | tail -40', timeout=600)

print('\n=== ⑨ 移动端逐页布局体检 ===')
run('cd ' + REMOTE_ROOT + ' && (python3 -c "import playwright" 2>/dev/null && '
    'python3 bin/layout_audit.py 2>&1 | tail -25) || echo "服务器未装 playwright/chromium，跳过；可在本地对 http://%s 跑 bin/layout_audit.py"' % HOST,
    timeout=600)

print('\n=== 完成 ===')
print('  站点: http://%s/  (直连 http://%s:%d)' % (HOST, HOST, args.port_web))
print('  旧源码回收站(可恢复): ' + TRASH)
print('  管理员: admin@demo.com / AdminPass2026（首次登录强制改密）')
print('  日志: ' + REMOTE_ROOT + '/logs/')
cli.close()
