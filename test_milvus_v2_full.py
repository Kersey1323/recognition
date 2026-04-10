#!/usr/bin/env python3
"""
MilvusManagerV2 完整功能测试
- 使用测试库名称避免破坏原数据库
- 测试10条数据的建库和检索
"""
import asyncio
import sys
import os
import numpy as np
from PIL import Image

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


async def test_basic_integration():
    """测试基本集成"""
    print("=" * 80)
    print("测试 1: 基本集成测试")
    print("=" * 80)
    
    try:
        from csrcqsf.biz.railwayparts.milvus import MilvusManagerV2
        print("✓ MilvusManagerV2 导入成功")
        
        # 获取实例（使用测试配置）
        manager = MilvusManagerV2.get_instance(
            config_path='test_config_vector_db.ini',
            db_config_path='csrcqsf/biz/railwayparts/vector_db/config/db_config.ini'
        )
        print("✓ 获取单例实例成功（使用测试配置）")
        
        # 初始化
        await manager._ensure_initialized()
        print("✓ 管理器初始化成功")
        
        return True, manager
    except Exception as e:
        print(f"✗ 基本集成测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False, None


async def test_create_collections(manager):
    """测试创建集合"""
    print("\n" + "=" * 80)
    print("测试 2: 创建测试集合")
    print("=" * 80)
    
    try:
        await manager.create_collections()
        print("✓ 测试集合创建成功")
        print("  - TEST_PARTS_SIGLIP_V2")
        print("  - TEST_PARTS_DINOV2_V2")
        return True
    except Exception as e:
        print(f"✗ 创建集合失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def get_test_data():
    """获取10条测试数据"""
    print("\n" + "=" * 80)
    print("准备测试数据")
    print("=" * 80)
    
    try:
        from csrcqsf.biz.railwayparts.vector_db.data.db_connector import DatabaseConnector
        from configparser import ConfigParser
        
        # 读取数据库配置
        config = ConfigParser()
        config.read('csrcqsf/biz/railwayparts/vector_db/config/db_config.ini', encoding='utf-8')
        
        # 创建数据库连接
        db = DatabaseConnector(
            host=config.get('postgresql', 'host'),
            port=config.getint('postgresql', 'port'),
            database=config.get('postgresql', 'database'),
            user=config.get('postgresql', 'user'),
            password=config.get('postgresql', 'password')
        )
        
        # 获取10条测试数据
        items = db.fetch_items_with_images(limit=10)
        
        if not items:
            print("✗ 未找到测试数据")
            return None
        
        # 转换为测试需要的格式
        test_data = []
        for item in items:
            if item['images']:  # 确保有图片
                for img in item['images']:
                    test_data.append({
                        'item_id': item['item_id'],
                        'item_name': item['item_name'],
                        'item_code': item['item_code'],
                        'image_id': img['image_id'],
                        'image_url': img['image_url']
                    })
                    if len(test_data) >= 10:  # 只取10条
                        break
            if len(test_data) >= 10:
                break
        
        print(f"✓ 获取到 {len(test_data)} 条测试数据")
        for idx, row in enumerate(test_data, 1):
            print(f"  {idx}. item_id={row['item_id']}, name={row['item_name'][:20]}...")
        
        db.close()
        return test_data
        
    except Exception as e:
        print(f"✗ 获取测试数据失败: {e}")
        import traceback
        traceback.print_exc()
        return None


async def test_index_images(manager, test_data):
    """测试图像索引建立"""
    print("\n" + "=" * 80)
    print("测试 3: 建立图像索引（10条数据）")
    print("=" * 80)
    
    try:
        from csrcqsf.biz.railwayparts.vector_db.data.image_loader import ImageLoader
        from configparser import ConfigParser
        
        # 读取数据库配置
        config = ConfigParser()
        config.read('csrcqsf/biz/railwayparts/vector_db/config/db_config.ini', encoding='utf-8')
        
        # 创建图像加载器
        image_loader = ImageLoader(
            minio_endpoint=config.get('minio', 'endpoint'),
            minio_access_key=config.get('minio', 'access_key'),
            minio_secret_key=config.get('minio', 'secret_key'),
            minio_bucket=config.get('minio', 'bucket'),
            minio_secure=config.getboolean('minio', 'secure'),
            local_image_root=config.get('local', 'image_root')
        )
        
        success_count = 0
        fail_count = 0
        
        for idx, row in enumerate(test_data, 1):
            try:
                print(f"\n处理 {idx}/10: item_id={row['item_id']}, image_id={row['image_id']}")
                
                # 使用 ImageLoader 加载图片
                image = image_loader.load_image(row['image_url'])
                
                if image is None:
                    print(f"  ✗ 图片加载失败")
                    fail_count += 1
                    continue
                
                print(f"  ✓ 图片加载成功: {image.size}")
                
                # 建立索引
                siglip_ok, dinov2_ok = await manager.index_image(
                    image=image,
                    item_id=row['item_id'],
                    item_name=row['item_name'],
                    item_code=row['item_code'] or '',
                    image_id=row['image_id'],
                    image_url=row['image_url'],
                    description=row['item_name']
                )
                
                if siglip_ok and dinov2_ok:
                    print(f"  ✓ 索引建立成功 (SigLIP: ✓, DINOv2: ✓)")
                    success_count += 1
                else:
                    print(f"  ⚠ 索引部分成功 (SigLIP: {'✓' if siglip_ok else '✗'}, DINOv2: {'✓' if dinov2_ok else '✗'})")
                    success_count += 1
                
            except Exception as e:
                print(f"  ✗ 处理失败: {e}")
                fail_count += 1
        
        print(f"\n索引建立完成: 成功 {success_count}, 失败 {fail_count}")
        return success_count > 0
        
    except Exception as e:
        print(f"✗ 索引建立测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_text_search(manager):
    """测试文本检索"""
    print("\n" + "=" * 80)
    print("测试 4: 文本检索")
    print("=" * 80)
    
    try:
        # 测试查询
        test_queries = ["轴承", "螺栓", "垫片"]
        
        for query in test_queries:
            print(f"\n查询: '{query}'")
            results = await manager.search_by_text(
                query_text=query,
                top_k=3
            )
            
            if results:
                print(f"  找到 {len(results)} 个结果:")
                for idx, result in enumerate(results, 1):
                    entity = result['entity']
                    distance = result['distance']
                    print(f"    {idx}. item_id={entity['item_id']}, "
                          f"name={entity['item_name'][:30]}, "
                          f"score={distance:.4f}")
            else:
                print("  未找到结果")
        
        return True
        
    except Exception as e:
        print(f"✗ 文本检索测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_image_search(manager, test_data):
    """测试图像检索"""
    print("\n" + "=" * 80)
    print("测试 5: 图像检索")
    print("=" * 80)
    
    try:
        from csrcqsf.biz.railwayparts.vector_db.data.image_loader import ImageLoader
        from configparser import ConfigParser
        
        # 读取数据库配置
        config = ConfigParser()
        config.read('csrcqsf/biz/railwayparts/vector_db/config/db_config.ini', encoding='utf-8')
        
        # 创建图像加载器
        image_loader = ImageLoader(
            minio_endpoint=config.get('minio', 'endpoint'),
            minio_access_key=config.get('minio', 'access_key'),
            minio_secret_key=config.get('minio', 'secret_key'),
            minio_bucket=config.get('minio', 'bucket'),
            minio_secure=config.getboolean('minio', 'secure'),
            local_image_root=config.get('local', 'image_root')
        )
        
        # 使用第一张图片作为查询
        query_row = test_data[0]
        print(f"查询图片: item_id={query_row['item_id']}, name={query_row['item_name']}")
        
        # 加载查询图片
        query_image = image_loader.load_image(query_row['image_url'])
        
        if query_image is None:
            print("✗ 查询图片加载失败")
            return False
        
        print(f"✓ 查询图片加载成功: {query_image.size}")
        
        # 测试不同检索模式
        modes = ["siglip", "dinov2", "hybrid"]
        
        for mode in modes:
            print(f"\n检索模式: {mode}")
            results = await manager.search_by_image(
                image=query_image,
                top_k=5,
                mode=mode,
                coarse_top_k=20,
                alpha=0.6
            )
            
            if results:
                print(f"  找到 {len(results)} 个结果:")
                for idx, result in enumerate(results, 1):
                    entity = result['entity']
                    distance = result['distance']
                    print(f"    {idx}. item_id={entity['item_id']}, "
                          f"name={entity['item_name'][:30]}, "
                          f"score={distance:.4f}")
            else:
                print("  未找到结果")
        
        return True
        
    except Exception as e:
        print(f"✗ 图像检索测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


async def cleanup_test_collections(manager):
    """清理测试集合"""
    print("\n" + "=" * 80)
    print("清理测试集合")
    print("=" * 80)
    
    try:
        # 删除测试集合
        client = manager._manager.collection_manager.client
        
        test_collections = ["TEST_PARTS_SIGLIP_V2", "TEST_PARTS_DINOV2_V2"]
        
        for collection_name in test_collections:
            if client.has_collection(collection_name):
                client.drop_collection(collection_name)
                print(f"✓ 删除测试集合: {collection_name}")
        
        print("✓ 测试集合清理完成")
        return True
        
    except Exception as e:
        print(f"⚠ 清理测试集合失败: {e}")
        return False


async def main():
    """主测试流程"""
    print("\n" + "=" * 80)
    print("MilvusManagerV2 完整功能测试")
    print("=" * 80)
    
    results = []
    manager = None
    test_data = None
    
    # 测试 1: 基本集成
    success, manager = await test_basic_integration()
    results.append(("基本集成", success))
    
    if not success or manager is None:
        print("\n✗ 基本集成失败，终止测试")
        return 1
    
    # 测试 2: 创建集合
    success = await test_create_collections(manager)
    results.append(("创建集合", success))
    
    if not success:
        print("\n✗ 创建集合失败，终止测试")
        return 1
    
    # 获取测试数据
    test_data = await get_test_data()
    if test_data is None:
        print("\n✗ 获取测试数据失败，终止测试")
        return 1
    
    # 测试 3: 建立索引
    success = await test_index_images(manager, test_data)
    results.append(("建立索引", success))
    
    if not success:
        print("\n⚠ 建立索引失败，跳过检索测试")
    else:
        # 测试 4: 文本检索
        success = await test_text_search(manager)
        results.append(("文本检索", success))
        
        # 测试 5: 图像检索
        success = await test_image_search(manager, test_data)
        results.append(("图像检索", success))
    
    # 清理测试集合
    await cleanup_test_collections(manager)
    
    # 总结
    print("\n" + "=" * 80)
    print("测试总结")
    print("=" * 80)
    
    for test_name, success in results:
        status = "✓ 通过" if success else "✗ 失败"
        print(f"{test_name}: {status}")
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    print(f"\n总计: {passed}/{total} 通过")
    
    if passed == total:
        print("\n✓ 所有测试通过！MilvusManagerV2 集成成功")
        return 0
    else:
        print(f"\n⚠ {total - passed} 个测试失败")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
