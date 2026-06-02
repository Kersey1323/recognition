#!/bin/bash
# 重启服务脚本

echo "正在停止服务..."

# 查找并停止 uvicorn 进程
pkill -f "uvicorn.*csrcqsf.core.app:app" || echo "没有找到运行中的服务"

# 等待进程完全停止
sleep 2

echo "清理 Python 缓存..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true

echo "服务已停止，请手动启动服务"
echo ""
echo "启动命令示例："
echo "  uvicorn csrcqsf.core.app:app --host 0.0.0.0 --port 65432"
