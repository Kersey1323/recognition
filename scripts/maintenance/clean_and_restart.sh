#!/bin/bash
# 清理缓存并重启服务

echo "=========================================="
echo "清理 Python 缓存和重启服务"
echo "=========================================="

# 1. 停止服务
echo ""
echo "[1/4] 停止服务..."
pkill -f "uvicorn.*csrcqsf.app:app" && echo "✓ 服务已停止" || echo "⚠ 没有找到运行中的服务"

# 等待进程完全停止
sleep 2

# 2. 清理 Python 缓存
echo ""
echo "[2/4] 清理 Python 缓存..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
echo "✓ Python 缓存已清理"

# 3. 清理 CUDA 缓存（可选，需要 Python 环境）
echo ""
echo "[3/4] 清理 CUDA 缓存..."
if [ -f ".venv/bin/python" ]; then
    .venv/bin/python scripts/maintenance/clear_cuda_cache.py
    echo "✓ CUDA 缓存已清理"
else
    echo "⚠ 未找到虚拟环境，跳过 CUDA 缓存清理"
fi

# 4. 提示用户启动服务
echo ""
echo "[4/4] 准备启动服务"
echo "=========================================="
echo "清理完成！"
echo ""
echo "请使用以下命令启动服务："
echo "  .venv/bin/uvicorn csrcqsf.app:app --host 0.0.0.0 --port 65432"
echo ""
echo "或者如果使用 nohup 后台运行："
echo "  nohup .venv/bin/uvicorn csrcqsf.app:app --host 0.0.0.0 --port 65432 > logs/app.log 2>&1 &"
echo "=========================================="
