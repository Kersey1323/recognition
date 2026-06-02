#!/usr/bin/env python3
"""
测试 MilvusManagerV2 集成
验证新算法的包装是否正确
"""
import asyncio
import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_import():
    """测试导入"""
    print("=" * 60)
    print("测试 1: 导入模块")
    print("=" * 60)
    
    try:
        from csrcqsf.modules.railway_parts.integrations.milvus_state_manager import MilvusManagerV2
        print("✓ MilvusManagerV2 导入成功")
    except Exception as e:
        print(f"✗ 导入失败: {e}")
        import traceback
        traceback.print_exc()
        raise


def test_initialization():
    """测试初始化"""
    print("\n" + "=" * 60)
    print("测试 2: 初始化管理器")
    print("=" * 60)
    
    async def _run():
        from csrcqsf.modules.railway_parts.integrations.milvus_state_manager import MilvusManagerV2

        manager = MilvusManagerV2.get_instance()
        print("✓ MilvusManagerV2 实例创建成功")
        await manager._ensure_initialized()
        print("✓ 底层 MilvusManager 初始化成功")

    try:
        asyncio.run(_run())
    except Exception as e:
        print(f"✗ 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        raise


def test_method_signatures():
    """测试方法签名"""
    print("\n" + "=" * 60)
    print("测试 3: 检查方法签名")
    print("=" * 60)
    
    try:
        from csrcqsf.modules.railway_parts.integrations.milvus_state_manager import MilvusManagerV2
        import inspect

        manager = MilvusManagerV2.get_instance()

        sig = inspect.signature(manager.search_by_text)
        params = list(sig.parameters.keys())
        print(f"search_by_text 参数: {params}")
        assert 'query_text' in params, "缺少 query_text 参数"
        assert 'top_k' in params, "缺少 top_k 参数"
        print("✓ search_by_text 方法签名正确")

        sig = inspect.signature(manager.search_by_image)
        params = list(sig.parameters.keys())
        print(f"search_by_image 参数: {params}")
        assert 'image' in params, "缺少 image 参数"
        assert 'top_k' in params, "缺少 top_k 参数"
        assert 'mode' in params, "缺少 mode 参数"
        assert 'coarse_top_k' in params, "缺少 coarse_top_k 参数"
        assert 'alpha' in params, "缺少 alpha 参数"
        print("✓ search_by_image 方法签名正确")

        sig = inspect.signature(manager.index_image)
        params = list(sig.parameters.keys())
        print(f"index_image 参数: {params}")
        assert 'image' in params, "缺少 image 参数"
        assert 'item_id' in params, "缺少 item_id 参数"
        print("✓ index_image 方法签名正确")
    except Exception as e:
        print(f"✗ 方法签名检查失败: {e}")
        import traceback
        traceback.print_exc()
        raise


def test_backward_compatibility():
    """测试向后兼容性"""
    print("\n" + "=" * 60)
    print("测试 4: 向后兼容性")
    print("=" * 60)
    
    try:
        from csrcqsf.modules.railway_parts.integrations.milvus_state_manager import MilvusManager

        print("✓ MilvusManager 类仍然可用（向后兼容）")
        assert hasattr(MilvusManager, 'extract_image_tensor'), "缺少 extract_image_tensor 方法"
        assert hasattr(MilvusManager, 'embedding_encode'), "缺少 embedding_encode 方法"
        print("✓ 旧方法仍然可用")
    except Exception as e:
        print(f"✗ 向后兼容性检查失败: {e}")
        import traceback
        traceback.print_exc()
        raise


async def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("MilvusManagerV2 集成测试")
    print("=" * 60)
    
    results = []
    
    # 测试 1: 导入
    results.append(await test_import())
    
    if results[-1]:
        # 测试 2: 初始化（需要配置文件和模型）
        results.append(await test_initialization())
    
    # 测试 3: 方法签名（不需要初始化）
    results.append(await test_method_signatures())
    
    # 测试 4: 向后兼容性
    results.append(await test_backward_compatibility())
    
    # 总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    passed = sum(results)
    total = len(results)
    print(f"通过: {passed}/{total}")
    
    if passed == total:
        print("\n✓ 所有测试通过！MilvusManagerV2 集成正确")
        return 0
    else:
        print(f"\n✗ {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
