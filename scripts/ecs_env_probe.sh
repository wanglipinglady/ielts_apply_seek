#!/usr/bin/env bash
# IELTS Buddy · ECS 环境探测脚本
# 用途：在新服务器上跑一遍，看现有依赖，再决定部署方案
# 用法：bash ecs_env_probe.sh > probe-output.txt 2>&1
#       把 probe-output.txt 发给 AI 即可

set +e  # 任何命令失败不终止，方便看全貌

sep() {
    echo ""
    echo "============================================================"
    echo "$1"
    echo "============================================================"
}

sep "1. 系统信息"
echo "日期:    $(date)"
echo "主机名:  $(hostname)"
echo "内核:    $(uname -a)"
echo "发行版:  $(cat /etc/os-release 2>/dev/null | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"')"
echo "运行时间: $(uptime -p 2>/dev/null || uptime)"

sep "2. 当前用户 / sudo 权限"
echo "当前用户: $(whoami)"
echo "UID:      $(id -u)"
echo "sudo:     $(sudo -n true 2>&1 | head -1)"
echo "在 sudoers:"
getent group sudo 2>/dev/null
getent group wheel 2>/dev/null

sep "3. 已有 Web 服务器（冲突检测）"
echo "--- nginx ---"
which nginx
nginx -v 2>&1 | head -1
ls /etc/nginx/sites-enabled/ 2>&1 | head
echo ""
echo "--- apache ---"
which apache2 2>&1
which httpd 2>&1
echo ""
echo "--- caddy ---"
which caddy 2>&1
echo ""
echo "80/443 占用情况:"
sudo ss -tlnp 2>/dev/null | grep -E ":80|:443\b" | head
echo ""
echo "/var/www/ 现有内容:"
ls -la /var/www/ 2>&1 | head -10

sep "4. 现有应用（判断有没有"电子 MOM 问答系统"在跑）"
echo "--- 进程列表（Python / Node / Java）---"
ps -ef 2>/dev/null | grep -iE "python|node|java|gunicorn|uvicorn" | grep -v grep | head -20
echo ""
echo "--- uvicorn / gunicorn 进程 ---"
ps -ef 2>/dev/null | grep -iE "uvicorn|gunicorn" | grep -v grep
echo ""
echo "--- systemd 服务列表（自启动项）---"
ls /etc/systemd/system/*.service 2>&1 | head -20

sep "5. 编程语言 + 包管理"
echo "--- Python ---"
which python3 python3.10 python3.11 python3.12 2>&1
python3 --version 2>&1
echo "pip3:  $(which pip3 2>&1)"
echo ""
echo "--- Node ---"
which node npm 2>&1
node --version 2>&1 | head -1
echo ""
echo "--- Java ---"
which java javac 2>&1
echo ""
echo "--- 其他常用 ---"
which ffmpeg git curl wget 2>&1

sep "6. 数据库"
echo "--- MySQL ---"
which mysql mysqld 2>&1
mysql --version 2>&1 | head -1
ls /var/lib/mysql/ 2>&1 | head
echo ""
echo "MySQL 端口:"
sudo ss -tlnp 2>/dev/null | grep ":3306"
echo ""
echo "--- PostgreSQL ---"
which psql pg_ctl 2>&1
echo ""
echo "--- SQLite ---"
which sqlite3 2>&1

sep "7. SSL 证书现状"
echo "/etc/nginx/ssl/ 内容:"
ls -la /etc/nginx/ssl/ 2>&1 | head -10
echo ""
echo "/etc/letsencrypt/ 内容:"
ls -la /etc/letsencrypt/live/ 2>&1 | head -5

sep "8. 磁盘 + 内存"
echo "--- 磁盘 ---"
df -h | grep -vE "tmpfs|devtmpfs" | head -5
echo ""
echo "--- 内存 ---"
free -h | head -3
echo ""
echo "--- CPU ---"
nproc
echo "CPU 型号: $(grep 'model name' /proc/cpuinfo | head -1 | cut -d: -f2 | xargs)"

sep "9. 网络"
echo "公网 IP:"
curl -s -m 5 https://api.ipify.org 2>&1
curl -s -m 5 https://ifconfig.me 2>&1
echo ""
echo "DNS:"
cat /etc/resolv.conf 2>&1 | head -5
echo ""
echo "防火墙:"
sudo ufw status 2>&1 | head -10
sudo iptables -L -n 2>&1 | head -10

sep "10. 已监听的端口（关键）"
sudo ss -tlnp 2>/dev/null | head -30

sep "11. 域名解析情况（看是否已配 DNS）"
echo "本机 hostname 解析:"
getent hosts $(hostname) 2>&1
echo ""
echo "如果域名已解析，dig / nslookup 验证:"
nslookup wanglipingresume.com 8.8.8.8 2>&1 | head -10
nslookup ielts.wanglipingresume.com 8.8.8.8 2>&1 | head -10

sep "12. 现有部署代码（找出电子 MOM 系统）"
echo "--- /opt 目录 ---"
ls -la /opt/ 2>&1
echo ""
echo "--- /srv 目录 ---"
ls -la /srv/ 2>&1
echo ""
echo "--- /root 工作目录 ---"
ls -la /root/ 2>&1 | head -20
echo ""
echo "--- systemd timer (自动备份等) ---"
systemctl list-timers --no-pager 2>&1 | head -10

echo ""
echo "===== 探测完成 ====="
echo "请把整个输出发给 AI"