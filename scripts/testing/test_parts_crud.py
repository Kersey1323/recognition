#!/usr/bin/env python3
"""
测试配件管理 CRUD 接口
完整流程：创建 -> 查询详情 -> 修改描述 -> 修改尺寸 -> 列表查询 -> 删除
"""
import requests
import json
import time

# 配置
BASE_URL = "http://localhost:65432"
HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}

def print_response(title, response):
    """打印响应信息"""
    print(f"\n{'='*60}")
    print(f"{title}")
    print(f"{'='*60}")
    print(f"状态码: {response.status_code}")
    try:
        data = response.json()
        print(f"响应: {json.dumps(data, indent=2, ensure_ascii=False)}")
        return data
    except:
        print(f"响应: {response.text}")
        return None

def test_create_item():
    """1. 创建配件实体"""
    url = f"{BASE_URL}/railway/parts/item"
    payload = {
        "item_name": "测试配件_自动化测试",
        "item_code": f"TEST_{int(time.time())}",
        "obj_url": None,
        "height": None,
        "length": None,
        "width": None,
        "parent_item_id": "0"  # 使用 "0" 表示顶级配件
    }
    
    print("\n\n🔵 步骤 1: 创建配件实体")
    print(f"请求: POST {url}")
    print(f"数据: {json.dumps(payload, indent=2, ensure_ascii=False)}")
    
    response = requests.post(url, json=payload, headers=HEADERS)
    data = print_response("✅ 创建配件响应", response)
    
    # 检查响应状态码，如果是 200 则认为成功
    if response.status_code == 200:
        # 尝试从响应中提取 item_id
        # 注意：需要根据实际的响应格式调整
        if data:
            # 如果响应中有 data.id 字段
            if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
                item_id = data["data"].get("id")
            # 如果响应直接是 id
            elif isinstance(data, dict) and "id" in data:
                item_id = data["id"]
            else:
                # 如果无法提取 ID，需要通过列表接口查询
                print("\n⚠️  无法从响应中提取 item_id，尝试通过列表接口查询...")
                item_id = get_latest_item_id(payload["item_code"])
        else:
            item_id = get_latest_item_id(payload["item_code"])
        
        if item_id:
            print(f"\n✅ 配件创建成功！ID: {item_id}")
            return item_id
        else:
            print("\n⚠️  配件可能已创建，但无法获取 ID")
            return None
    else:
        print("\n❌ 配件创建失败！")
        return None

def get_latest_item_id(item_code):
    """通过配件编码查询最新创建的配件ID"""
    try:
        url = f"{BASE_URL}/railway/parts/list_items"
        payload = {
            "page": 1,
            "per_page": 10,
            "query": item_code
        }
        response = requests.post(url, json=payload, headers=HEADERS)
        if response.status_code == 200:
            data = response.json()
            if data and "data" in data and "items" in data["data"]:
                items = data["data"]["items"]
                if items and len(items) > 0:
                    return items[0].get("id")
    except Exception as e:
        print(f"查询配件ID失败: {e}")
    return None

def test_get_item_details(item_id):
    """2. 获取配件详细信息"""
    url = f"{BASE_URL}/railway/parts/get_item_details"
    payload = {"item_id": item_id}
    
    print("\n\n🔵 步骤 2: 获取配件详细信息")
    print(f"请求: POST {url}")
    print(f"数据: {json.dumps(payload, indent=2, ensure_ascii=False)}")
    
    response = requests.post(url, json=payload, headers=HEADERS)
    data = print_response("✅ 获取配件详情响应", response)
    
    if response.status_code == 200:
        print(f"\n✅ 成功获取配件详情")
        return True
    else:
        print("\n❌ 获取配件详情失败！")
        return False

def test_update_item_description(item_id):
    """3. 修改配件信息"""
    url = f"{BASE_URL}/railway/parts/item_put"
    payload = {
        "id": item_id,
        "item_name": "测试配件_已修改",
        "item_code": f"TEST_UPDATED_{int(time.time())}",
        "obj_url": None,
        "height": None,
        "length": None,
        "width": None,
        "parent_item_id": "0"
    }
    
    print("\n\n🔵 步骤 3: 修改配件信息")
    print(f"请求: POST {url}")
    print(f"数据: {json.dumps(payload, indent=2, ensure_ascii=False)}")
    
    response = requests.post(url, json=payload, headers=HEADERS)
    data = print_response("✅ 修改配件信息响应", response)
    
    if response.status_code == 200:
        print(f"\n✅ 配件信息修改成功")
        return True
    else:
        print("\n❌ 配件信息修改失败！")
        return False

def test_update_item_size(item_id):
    """4. 修改配件3D模型尺寸"""
    url = f"{BASE_URL}/railway/parts/item/size_put"
    payload = {
        "item_id": item_id,
        "item_size_desc": "长100.5mm × 宽50.3mm × 高30.2mm",
        "length": 100.5,
        "width": 50.3,
        "height": 30.2
    }
    
    print("\n\n🔵 步骤 4: 修改配件3D模型尺寸")
    print(f"请求: POST {url}")
    print(f"数据: {json.dumps(payload, indent=2, ensure_ascii=False)}")
    
    response = requests.post(url, json=payload, headers=HEADERS)
    data = print_response("✅ 修改配件尺寸响应", response)
    
    if response.status_code == 200:
        print(f"\n✅ 配件尺寸修改成功")
        return True
    else:
        print("\n❌ 配件尺寸修改失败！")
        return False

def test_list_items():
    """5. 列出配件列表"""
    url = f"{BASE_URL}/railway/parts/list_items"
    payload = {
        "page": 1,
        "per_page": 10,
        "query": "测试配件"
    }
    
    print("\n\n🔵 步骤 5: 列出配件列表")
    print(f"请求: POST {url}")
    print(f"数据: {json.dumps(payload, indent=2, ensure_ascii=False)}")
    
    response = requests.post(url, json=payload, headers=HEADERS)
    data = print_response("✅ 配件列表响应", response)
    
    if response.status_code == 200 and data:
        total = data.get("total", 0)
        print(f"\n✅ 成功获取配件列表，共 {total} 条记录")
        return True
    else:
        print("\n❌ 获取配件列表失败！")
        return False

def test_delete_item(item_id):
    """6. 删除配件实体"""
    url = f"{BASE_URL}/railway/parts/item_delete"
    payload = {"item_id_list": [item_id]}
    
    print("\n\n🔵 步骤 6: 删除配件实体")
    print(f"请求: POST {url}")
    print(f"数据: {json.dumps(payload, indent=2, ensure_ascii=False)}")
    
    response = requests.post(url, json=payload, headers=HEADERS)
    data = print_response("✅ 删除配件响应", response)
    
    if response.status_code == 200:
        print(f"\n✅ 配件删除成功")
        return True
    else:
        print("\n❌ 配件删除失败！")
        return False

def main():
    """主测试流程"""
    print("="*60)
    print("配件管理 CRUD 接口测试")
    print("="*60)
    print(f"服务地址: {BASE_URL}")
    print(f"开始时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 测试流程
    results = []
    
    # 1. 创建配件
    item_id = test_create_item()
    if not item_id:
        print("\n\n❌ 测试失败：无法创建配件")
        return
    results.append(("创建配件", True))
    
    # 等待一下确保数据已保存
    time.sleep(1)
    
    # 2. 获取配件详情
    success = test_get_item_details(item_id)
    results.append(("获取配件详情", success))
    
    # 3. 修改配件信息
    success = test_update_item_description(item_id)
    results.append(("修改配件信息", success))
    
    # 4. 修改配件尺寸
    success = test_update_item_size(item_id)
    results.append(("修改配件尺寸", success))
    
    # 5. 列出配件列表
    success = test_list_items()
    results.append(("列出配件列表", success))
    
    # 6. 删除配件
    success = test_delete_item(item_id)
    results.append(("删除配件", success))
    
    # 打印测试总结
    print("\n\n" + "="*60)
    print("测试总结")
    print("="*60)
    for test_name, success in results:
        status = "✅ 通过" if success else "❌ 失败"
        print(f"{test_name:20s} {status}")
    
    total = len(results)
    passed = sum(1 for _, success in results if success)
    print(f"\n总计: {passed}/{total} 个测试通过")
    print(f"结束时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n测试被用户中断")
    except Exception as e:
        print(f"\n\n❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
