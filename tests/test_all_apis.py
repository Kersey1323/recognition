#!/usr/bin/env python3
"""
测试所有查询类 API 接口
"""
import requests
import json
from typing import Dict, Any

BASE_URL = "http://localhost:65432"

def test_api(method: str, endpoint: str, data: Dict[str, Any] = None, description: str = ""):
    """测试单个 API"""
    url = f"{BASE_URL}{endpoint}"
    print(f"\n{'='*70}")
    print(f"测试: {description}")
    print(f"方法: {method} {endpoint}")
    if data:
        print(f"请求体: {json.dumps(data, ensure_ascii=False, indent=2)}")
    print(f"{'='*70}")
    
    try:
        if method == "GET":
            response = requests.get(url, timeout=10)
        elif method == "POST":
            response = requests.post(url, json=data, timeout=10)
        
        print(f"状态码: {response.status_code}")
        
        try:
            result = response.json()
            print(f"响应: {json.dumps(result, ensure_ascii=False, indent=2)[:500]}...")
            
            if isinstance(result, dict):
                if result.get('status') == 'success' or 'total' in result or 'items' in result:
                    print("✅ 测试通过")
                    return True, result
                elif result.get('status') == 'fail':
                    print(f"❌ 测试失败: {result.get('message', 'Unknown error')[:200]}")
                    return False, result
            return True, result
        except:
            print(f"响应文本: {response.text[:500]}")
            return False, None
            
    except Exception as e:
        print(f"❌ 请求失败: {e}")
        return False, None


def main():
    """测试所有查询类接口"""
    print("="*70)
    print("开始测试所有查询类 API 接口")
    print("="*70)
    
    results = []
    
    # 1. 配件列表
    success, data = test_api(
        "POST", "/railway/parts/list_items",
        {"page": 1, "pageSize": 5, "query": ""},
        "列出配件列表"
    )
    results.append(("配件列表", success))
    
    # 获取一个配件ID用于后续测试
    item_id = None
    if success and data and 'items' in data and len(data['items']) > 0:
        item_id = data['items'][0].get('id')
        print(f"\n使用配件ID进行后续测试: {item_id}")
    
    # 2. 配件详情
    if item_id:
        success, _ = test_api(
            "POST", "/railway/parts/get_item_details",
            {"item_id": str(item_id)},
            "获取配件详情"
        )
        results.append(("配件详情", success))
    
    # 3. 配件特征列表
    if item_id:
        success, _ = test_api(
            "POST", "/railway/parts/list_item_features",
            {"item_id": str(item_id)},
            "列出配件特征"
        )
        results.append(("配件特征列表", success))
    
    # 4. 分割记录
    if item_id:
        success, _ = test_api(
            "GET", f"/railway/parts/segmented_images/{item_id}",
            description="获取分割记录"
        )
        results.append(("分割记录", success))
    
    # 5. 检索历史 (已删除旧版本接口)
    # success, _ = test_api(
    #     "POST", "/railway/parts/search/history/v2",
    #     {"page": 1, "pageSize": 5},
    #     "检索历史列表"
    # )
    # results.append(("检索历史", success))
    
    # 6. 数据统计
    success, _ = test_api(
        "POST", "/railway/parts/data/statistics",
        {},
        "索引统计"
    )
    results.append(("数据统计", success))
    
    # 7. 3D重建任务列表 (V2版本)
    success, _ = test_api(
        "GET", "/railway/parts/v2/reconstruct/scenes",
        description="列出可用场景"
    )
    results.append(("3D重建场景列表", success))
    
    # 7.1 所有3D重建任务
    success, _ = test_api(
        "GET", "/railway/parts/v2/reconstruct/tasks?limit=10&offset=0",
        description="列出所有3D重建任务"
    )
    results.append(("所有3D重建任务", success))
    
    # 8. SGO图片列表
    if item_id:
        success, _ = test_api(
            "POST", "/sgo/sgo/parts/images",
            {"item_id": str(item_id)},
            "获取SGO图片列表"
        )
        results.append(("SGO图片列表", success))
    
    # 9. 询码记录列表
    success, _ = test_api(
        "POST", "/sgo/sgo/inquery/list",
        {"page": 1, "pageSize": 5, "has_indexed": 0, "current_status": "FINISH"},
        "获取询码记录列表"
    )
    results.append(("询码记录列表", success))
    
    # 10. 文档列表
    success, _ = test_api(
        "POST", "/railway/docs/files",
        {"page": 1, "pageSize": 5, "query": ""},
        "列出文档列表"
    )
    results.append(("文档列表", success))
    
    # 总结
    print("\n" + "="*70)
    print("测试总结")
    print("="*70)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for name, success in results:
        status = "✅ 通过" if success else "❌ 失败"
        print(f"{name:20} {status}")
    
    print(f"\n总计: {passed}/{total} 个接口测试通过")
    print("="*70)


if __name__ == "__main__":
    main()
