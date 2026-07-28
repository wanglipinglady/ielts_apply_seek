#!/bin/bash
# IELTS Apply Seek Web 启动脚本

cd "$(dirname "$0")"

# 虚拟环境目录
VENV_DIR=".venv"

# 使用正确的 Python 3.10 路径
PYTHON_BIN="/Users/wangliping/Library/Application Support/TRAE SOLO CN/ModularData/ai-agent/vm/tools/opt/python@3.10/3.10.20_3/libexec/bin/python3"
PIP_BIN="/Users/wangliping/Library/Application Support/TRAE SOLO CN/ModularData/ai-agent/vm/tools/opt/python@3.10/3.10.20_3/Frameworks/Python.framework/Versions/3.10/bin/pip3"

# 检查虚拟环境是否存在或 Python 版本是否正确
RECREATE=false
if [ -d "$VENV_DIR" ]; then
    VENV_PYTHON="$VENV_DIR/bin/python"
    if [ -f "$VENV_PYTHON" ]; then
        VENV_VERSION=$("$VENV_PYTHON" --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
        if [ "$VENV_VERSION" != "3.10" ]; then
            echo "Python 版本不匹配 ($VENV_VERSION)，重新创建虚拟环境..."
            RECREATE=true
            rm -rf "$VENV_DIR"
        fi
    fi
else
    RECREATE=true
fi

# 创建虚拟环境
if [ "$RECREATE" = true ]; then
    echo "创建虚拟环境 (Python 3.10)..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    echo "安装依赖..."
    "$PIP_BIN" install -e ".[web]" --target="$VENV_DIR/lib/python3.10/site-packages"
fi

# 激活虚拟环境
source "$VENV_DIR/bin/activate"
echo "虚拟环境已激活: $(python --version)"

# 添加项目 src 目录到 PYTHONPATH
export PYTHONPATH="$PWD/src:$PYTHONPATH"

# 验证安装
echo "验证安装..."
python -c "import ielts_buddy; print('ielts_buddy 已安装成功')"

# 启动 Web 服务（使用正确的模块路径）
echo "启动 Web 服务..."
echo "访问地址: http://localhost:8000"
python -m ielts_buddy.web.main
