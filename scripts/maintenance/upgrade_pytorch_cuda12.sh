#!/bin/bash
# 升级 PyTorch 到 CUDA 12.4 版本以支持 RTX 5090

set -e

echo "=========================================="
echo "升级 PyTorch 到 CUDA 12.4"
echo "=========================================="

# 检查 uv 是否安装
if ! command -v uv &> /dev/null; then
    echo "错误: uv 未安装"
    echo "请先安装 uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

echo ""
echo "[1/5] 备份当前配置..."
cp pyproject.toml pyproject.toml.backup
echo "✓ 已备份到 pyproject.toml.backup"

echo ""
echo "[2/5] 更新 pyproject.toml 配置..."
# 使用 sed 更新配置
sed -i 's/pytorch-cu118/pytorch-cu124/g' pyproject.toml
sed -i 's|https://download.pytorch.org/whl/cu118|https://download.pytorch.org/whl/cu124|g' pyproject.toml
echo "✓ 配置已更新为 CUDA 12.4"

echo ""
echo "[3/5] 卸载旧的 PyTorch..."
uv pip uninstall torch torchvision torchaudio -y || true
echo "✓ 旧版本已卸载"

echo ""
echo "[4/5] 安装新的 PyTorch (CUDA 12.4)..."
uv pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
echo "✓ PyTorch CUDA 12.4 已安装"

echo ""
echo "[5/5] 验证安装..."
.venv/bin/python -c "
import torch
print(f'PyTorch 版本: {torch.__version__}')
print(f'CUDA 版本: {torch.version.cuda}')
print(f'CUDA 可用: {torch.cuda.is_available()}')
if torch.cuda.is_available():
    print(f'GPU: {torch.cuda.get_device_name(0)}')
    print(f'计算能力: {torch.cuda.get_device_capability(0)}')
"

echo ""
echo "=========================================="
echo "升级完成！"
echo "=========================================="
echo ""
echo "如果遇到问题，可以恢复备份："
echo "  cp pyproject.toml.backup pyproject.toml"
echo ""
