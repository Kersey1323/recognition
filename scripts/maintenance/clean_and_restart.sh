#!/bin/bash
# 清理缓存并重启服务

echo "=========================================="
echo "清理 Python 缓存和重启服务"
echo "=========================================="

# 1. 停止服务
echo ""
echo "[1/3] 停止服务..."
pkill -f "uvicorn.*csrcqsf.core.app:app" && echo "✓ 服务已停止" || echo "⚠ 没有找到运行中的服务"

# 等待进程完全停止
sleep 2

# 2. 清理 Python 缓存
echo ""
echo "[2/3] 清理 Python 缓存..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
echo "✓ Python 缓存已清理"

# 3. 提示用户启动服务
echo ""
echo "[3/3] 准备启动服务"
echo "=========================================="
echo "清理完成！"
echo ""
echo "请使用以下命令启动服务："
echo "  .venv/bin/uvicorn csrcqsf.core.app:app --host 0.0.0.0 --port 65432"
echo ""
echo "或者如果使用 nohup 后台运行："
echo "  nohup .venv/bin/uvicorn csrcqsf.core.app:app --host 0.0.0.0 --port 65432 > logs/app.log 2>&1 &"
echo "=========================================="
