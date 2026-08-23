#!/usr/bin/env bash
# ============================================================================
# IELTS Buddy · 一键安装 whisper.cpp 语音转写(v3.7 P1)
# ----------------------------------------------------------------------------
# 用法:bash scripts/setup_whisper.sh
# 依赖:
#   - macOS(测试平台;Linux 改用 apt-get 装 ffmpeg)
#   - 已激活项目虚拟环境(.venv/bin/activate)
# 行为:
#   1. 检查 / 安装系统依赖(ffmpeg,仅 macOS Homebrew)
#   2. pip install pywhispercpp(whisper.cpp Python binding)
#   3. 探测模型(M4 + Core ML 路径可选)
# 幂等性:重复运行安全,跳过已安装步骤。
# ============================================================================
set -e

# 颜色
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

# 激活 venv
if [[ ! -d ".venv" ]]; then
  error ".venv 不存在;先跑 ./start_web.sh"
fi
source .venv/bin/activate
info "虚拟环境已激活: $(python --version)"

# === 步骤 1: 系统依赖 ===
info "=== 步骤 1: 系统依赖 ==="
if command -v ffmpeg >/dev/null 2>&1; then
  info "  ✓ ffmpeg 已安装: $(ffmpeg -version 2>&1 | head -1)"
else
  warn "  · ffmpeg 未安装"
  if command -v brew >/dev/null 2>&1; then
    warn "  · 正在 brew install ffmpeg(macOS)"
    brew install ffmpeg
    info "  ✓ ffmpeg 已装: $(ffmpeg -version 2>&1 | head -1)"
  elif command -v apt-get >/dev/null 2>&1; then
    warn "  · 正在 apt-get install ffmpeg(Linux)"
    sudo apt-get update && sudo apt-get install -y ffmpeg
  else
    error "请先手动安装 ffmpeg(macOS: brew install ffmpeg)"
  fi
fi

# === 步骤 2: Python 包 ===
info "=== 步骤 2: Python 依赖 pywhispercpp ==="
if python -c "import pywhispercpp" 2>/dev/null; then
  info "  ✓ pywhispercpp 已装: $(python -c 'import pywhispercpp; print(pyipc_version if False else getattr(pywhispercpp, \"__version__\", \"installed\"))')"
else
  warn "  · 正在 pip install pywhispercpp"
  pip install --quiet --upgrade pywhispercpp
  info "  ✓ pywhispercpp 已装"
fi

# === 步骤 3: 选择模型 ===
info "=== 步骤 3: 选择 whisper 模型 ==="
# 默认 small.en(PRD §4.2 决策)
MODEL_NAME="${IELTS_BUDDY_WHISPER_MODEL:-small.en}"
info "  模型: $MODEL_NAME"
info "  (~466 MB 磁盘,~852 MB 内存,M4 + Core ML 30s 音频 ≈ 5s 出结果)"

# === 步骤 4: 模型探活 ===
info "=== 步骤 4: 模型探活 ==="
PROBE_OUTPUT=$(python <<PY 2>&1
from pywhispercpp.model import Model
print("loading...")
m = Model("$MODEL_NAME", print_progress=False, n_threads=4)
print("loaded ok:", m)
PY
)
EXIT_CODE=$?
if [[ $EXIT_CODE -eq 0 ]]; then
  info "  ✓ $MODEL_NAME 已可用"
else
  warn "  · 模型未下载,首次 transcribe 时会自动从 HuggingFace 拉"
  warn "  · 也可手动:huggingface-cli download ggerganov/whisper.cpp \$MODEL_NAME"
fi

# === 步骤 5: 提示 Core ML 可选加速 ===
info "=== 步骤 5: Core ML 加速(Apple Silicon 推荐) ==="
ARCH=$(uname -m)
if [[ "$ARCH" == "arm64" ]]; then
  warn "  · 检测到 Apple Silicon"
  warn "  · 首次启动 web 时,pywhispercpp 会自动编译 Core ML 模型"
  warn "  · 第一次编译约 60-90 秒,之后秒开"
  warn "  · 如需手动编译,跑:"
  warn "      pip install ane_transformers openai-whisper coremltools"
  warn "      python -m pywhispercpp.generate_coreml_model --model $MODEL_NAME"
else
  info "  · 非 Apple Silicon,跳过 Core ML 编译(只走 CPU)"
fi

# === 总结 ===
cat <<EOF

${GREEN}=== 安装完成 ===${NC}

已装好:
  ✓ ffmpeg              $(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')
  ✓ pywhispercpp         (Python)
  ✓ 模型 $MODEL_NAME(按需下载,首次 transcribe 时自动)

下一步:
  1. 启动 web: ./start_web.sh --reload
  2. 浏览器访问 http://127.0.0.1:8000/speak/practice
  3. 第一次提交录音会触发 whisper 模型加载 + Core ML 编译
     等待 60-90 秒后即可正常转写

如果遇到 pywhispercpp 安装失败(macOS):
  - 可能是 Xcode CLI 缺失 → xcode-select --install
  - 可能是缺 C compiler → brew install gcc

如需回滚: pip uninstall pywhispercpp
EOF
