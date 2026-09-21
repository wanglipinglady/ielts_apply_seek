#!/usr/bin/env bash
# IELTS Buddy · 本地开发一键启动脚本
#
# 行为：
#   1. 检查 docker / docker-compose
#   2. 复制 .env.dev.example → .env（如不存在）
#   3. 启动 mysql + web
#   4. 等待 healthcheck 通过
#   5. 打印访问 URL
#
# 用法：
#   bash deploy/dev.sh             # 默认启动
#   bash deploy/dev.sh --reset     # 清数据重启（删 volumes）
#   bash deploy/dev.sh --stop      # 停止
#   bash deploy/dev.sh --logs      # 查看日志
#   bash deploy/dev.sh --status    # 状态

set -e

# 路径
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$SCRIPT_DIR"

# ---- 颜色输出 ----
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
step()  { echo -e "\n${BLUE}=== $* ===${NC}"; }

# ---- 子命令处理（help 不依赖 docker） ----
case "${1:-up}" in
    --help|-h|help)
        echo "用法: bash deploy/dev.sh [选项]"
        echo ""
        echo "选项:"
        echo "  (默认)         启动 mysql + web"
        echo "  --reset        清数据重启"
        echo "  --stop         停止服务（保留数据）"
        echo "  --purge        停止 + 清数据"
        echo "  --logs         查看日志（follow）"
        echo "  --status       状态 + 健康检查"
        echo "  --help         帮助"
        exit 0
        ;;
esac

# ---- 检查 docker ----
step "检查 Docker 环境"
if ! command -v docker >/dev/null 2>&1; then
    error "Docker 未安装。请先装一个：
  - OrbStack（推荐，轻量）: brew install --cask orbstack
  - Docker Desktop（功能全）: brew install --cask docker
  - Colima（开源）: brew install colima docker docker-compose
"
fi

# 检测 docker compose 命令（v1 / v2）
if docker compose version >/dev/null 2>&1; then
    DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    DC="docker-compose"
else
    error "docker compose 未安装。"
fi

DOCKER_INFO=$(docker info 2>&1)
if echo "$DOCKER_INFO" | grep -q "Cannot connect to the Docker daemon"; then
    error "Docker daemon 未运行。请先启动 Docker / OrbStack / Colima。"
fi

info "docker OK, 使用命令: $DC"

# ---- 主子命令处理 ----
case "${1:-up}" in
    --reset|reset)
        step "清数据重启"
        $DC down -v 2>&1 | tail -5
        info "旧数据已清空"
        # fall through to up
        ;&
    up|"")
        step "启动 mysql + web"
        # 准备 .env
        if [ ! -f .env ]; then
            if [ -f .env.dev.example ]; then
                cp .env.dev.example .env
                info ".env 已创建（从 .env.dev.example 复制）"
                warn "请编辑 .env 填入真实 LLM_API_KEY 等"
                echo "    当前 LLM_API_KEY 是 mock 占位"
            else
                error ".env.dev.example 不存在"
            fi
        fi

        # 加载 .env（仅当前 shell）
        set -a
        source .env
        set +a

        # 启动
        $DC up -d --build

        step "等待服务就绪（最长 60s）"
        for i in $(seq 1 60); do
            HEALTH=$(curl -s -m 2 http://127.0.0.1:8000/healthz 2>/dev/null || echo "")
            if echo "$HEALTH" | grep -q '"status":"ok"'; then
                info "Web 服务已就绪（耗时 ${i}s）"
                break
            fi
            sleep 1
        done

        if [ -z "$HEALTH" ]; then
            warn "60 秒内未拿到 healthz 响应，查看日志："
            $DC logs --tail=30 web
            exit 1
        fi

        step "服务状态"
        $DC ps
        echo ""

        step "健康检查"
        echo "$HEALTH" | python3 -m json.tool 2>&1 || echo "$HEALTH"
        echo ""

        step "下一步"
        echo "  Web 端访问:    http://127.0.0.1:8000"
        echo "  微信小程序:    把 miniprogram/app.js 的 apiBaseUrl 改成 http://172.20.x.x:8000"
        echo "                  (172.20.x.x 是你 Mac 的 LAN IP，ifconfig | grep 'inet ' 看)"
        echo ""
        echo "  调试命令:"
        echo "    bash deploy/dev.sh --logs        # 看日志"
        echo "    bash deploy/dev.sh --stop        # 停止"
        echo "    bash deploy/dev.sh --reset       # 清数据重启"
        echo ""
        echo "  MySQL 直连（外部工具）:"
        echo "    mysql -h 127.0.0.1 -u ${MYSQL_USER:-ielts_app} -p${MYSQL_PASSWORD:-apppass_dev_only} ${MYSQL_DATABASE:-ietls_learn_online}"
        echo ""
        ;;

    --stop|stop|down)
        step "停止服务（保留数据）"
        $DC down
        info "服务已停止，volume 数据保留"
        ;;

    --purge)
        step "停止 + 清数据"
        $DC down -v
        info "服务 + 数据全部清空"
        ;;

    --logs|logs)
        step "查看日志（Ctrl+C 退出）"
        $DC logs -f --tail=100
        ;;

    --status|status|ps)
        step "服务状态"
        $DC ps
        echo ""
        step "健康检查"
        curl -s -m 5 http://127.0.0.1:8000/healthz | python3 -m json.tool 2>&1 || echo "服务未启动"
        ;;

    *)
        error "未知选项: $1（--help 看用法）"
        ;;
esac