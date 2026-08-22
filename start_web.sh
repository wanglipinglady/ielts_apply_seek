#!/bin/bash
# IELTS Apply Seek Web 启动脚本
#
# 功能：
#   - 自动创建/复用 Python 3.10 虚拟环境
#   - 安装依赖
#   - 自动加载项目根目录 .env 文件（如果存在）
#   - 启动 Web 服务
#
# 使用：
#   ./start_web.sh                # 默认 8000 端口
#   ./start_web.sh --port 8765   # 自定义端口
#   ./start_web.sh --host 0.0.0.0 --port 8000   # 监听所有网卡
#
# 首次使用前：
#   cp .env.example .env
#   # 编辑 .env 填入 IELTS_BUDDY_LLM_API_KEY 等真实值

set -e

cd "$(dirname "$0")"

# ---- 颜色输出（终端好看用，CI 环境不会乱码）----
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ---- 解析命令行参数 ----
HOST=""
PORT=""
RELOAD=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --host)   HOST="$2"; shift 2 ;;
        --port)   PORT="$2"; shift 2 ;;
        --reload) RELOAD=true; shift ;;
        -h|--help)
            echo "用法: $0 [--host HOST] [--port PORT] [--reload]"
            echo ""
            echo "选项:"
            echo "  --host HOST    监听地址（默认: .env 的 IELTS_BUDDY_WEB_HOST 或 127.0.0.1）"
            echo "  --port PORT    监听端口（默认: .env 的 IELTS_BUDDY_WEB_PORT 或 8000）"
            echo "  --reload       启用热重载（开发用）"
            echo ""
            echo "环境变量优先级："
            echo "  1. 命令行参数 > 2. .env 文件 > 3. 代码默认值"
            exit 0
            ;;
        *)  warn "未知参数: $1（忽略）"; shift ;;
    esac
done

# ---- Python 路径配置 ----
VENV_DIR=".venv"
PYTHON_BIN="/Users/wangliping/Library/Application Support/TRAE SOLO CN/ModularData/ai-agent/vm/tools/opt/python@3.10/3.10.20_3/libexec/bin/python3"
PIP_BIN="/Users/wangliping/Library/Application Support/TRAE SOLO CN/ModularData/ai-agent/vm/tools/opt/python@3.10/3.10.20_3/Frameworks/Python.framework/Versions/3.10/bin/pip3"

# ---- 检查/创建虚拟环境 ----
RECREATE=false
if [ -d "$VENV_DIR" ]; then
    VENV_PYTHON="$VENV_DIR/bin/python"
    if [ -f "$VENV_PYTHON" ]; then
        # macOS BSD grep 不支持 -oP，用 sed 提取版本号（兼容 GNU/BSD）
        VENV_VERSION=$("$VENV_PYTHON" --version 2>&1 | sed -n 's/^Python \([0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' | head -1)
        if [ "$VENV_VERSION" != "3.10" ]; then
            warn "虚拟环境 Python 版本不匹配 ($VENV_VERSION)，重新创建..."
            RECREATE=true
            rm -rf "$VENV_DIR"
        fi
    else
        RECREATE=true
    fi
else
    RECREATE=true
fi

if [ "$RECREATE" = true ]; then
    info "创建虚拟环境 (Python 3.10)..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    info "安装依赖..."
    "$PIP_BIN" install -e ".[web]" --target="$VENV_DIR/lib/python3.10/site-packages"
fi

# ---- 激活虚拟环境 ----
source "$VENV_DIR/bin/activate"
info "虚拟环境已激活: $(python --version)"

# ---- 设置 PYTHONPATH ----
export PYTHONPATH="$PWD/src:${PYTHONPATH:-}"

# ---- 加载 .env 文件（关键：让 LLM_API_KEY 等生效）----
# 优先级：shell 环境变量 > .env 文件；空值不覆盖 shell 已有变量
if [ -f ".env" ]; then
    info "检测到 .env 文件，加载配置..."
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
    # 统计变量数（兼容 macOS BSD grep：不支持 \d，改用 [0-9]+）
    ENV_COUNT=$(grep -c '^[A-Z_][A-Z0-9_]*=' .env 2>/dev/null || echo 0)
    info "  ✓ .env 已加载（${ENV_COUNT} 个变量）"
else
    warn "未找到 .env 文件 —— 将使用 shell 环境变量 + 代码默认值"
    warn "首次使用请执行:  cp .env.example .env  并填入真实配置"
fi

# ---- 验证安装 ----
info "验证安装..."
python -c "import ielts_buddy; print('  ✓ ielts_buddy 已安装成功')"

# ---- 验证 LLM 配置（友好提示，不阻断启动）----
python - <<'PY'
import os
api_key = os.environ.get("IELTS_BUDDY_LLM_API_KEY", "").strip()
base_url = os.environ.get("IELTS_BUDDY_LLM_BASE_URL", "").strip()
if api_key:
    print(f"  ✓ LLM_API_KEY 已配置（{api_key[:8]}...{api_key[-4:]}）")
    print(f"  ✓ LLM_BASE_URL = {base_url or '(default)'}")
else:
    print("  ⚠ LLM_API_KEY 未配置 —— LLM 功能将走 dry-run mock 模式")
PY

# ---- 决定 host / port（命令行 > .env > 默认）----
if [ -z "$HOST" ]; then
    HOST="${IELTS_BUDDY_WEB_HOST:-127.0.0.1}"
fi
if [ -z "$PORT" ]; then
    PORT="${IELTS_BUDDY_WEB_PORT:-8000}"
fi

# ---- 启动 Web 服务 ----
info "启动 Web 服务..."
info "  访问地址: http://$HOST:$PORT"
info "  按 Ctrl+C 停止"
echo "------------------------------------------------------------"

# 关键：用 `python -m ielts_buddy.web`（不带 .main）触发 __main__.py，
# __main__.py 会先调用 load_dotenv() 再启动 uvicorn
if [ "$RELOAD" = true ]; then
    exec python -m ielts_buddy.web --host "$HOST" --port "$PORT" --reload
else
    exec python -m ielts_buddy.web --host "$HOST" --port "$PORT"
fi