#!/bin/bash
# Linux/Mac 启动脚本

# 激活虚拟环境并运行应用
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$SCRIPT_DIR/.venv/Scripts/python.exe" "$SCRIPT_DIR/main.py" "$@"
