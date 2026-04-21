#!/usr/bin/env python3
"""
测试配件管理接口（使用现有配件）
测试：查询列表 -> 查询详情 -> 修改信息 -> 修改尺寸
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

def test_list_items():
    """1. 列出配件列表"""
    url = f"{BASE_URL}/railway/parts/list_items"
    payload = {
        "page": 1,
        "pageSize": 5
    }
    
    print("\n\n🔵 步骤 1: 列出配件列表")
    print(f"请求: POST {url}")
    print(f"数据: {json.dumps(payload, indent=2, ensure_ascii=False)}")
    
    response = requests.post(url, json=payload, headers=HEADERS)
    data = print_response("✅ 配件列表响应", response)
    
    if data and data.get("status") == "success":
        items = data.get("data", {}).get("items", [])
        total = data.get("data", {}).get("total", 0)
        print(f"\n✅ 成功获取配件列表，共 {total} 条记录")
        if items:
            first_item = items[0]
            item_id = first_item.get("id")
            item_name = first_item.get("item_name")
            print(f"第一个配件: ID={item_id}, 名称={item_name}")
            return item_id
        else:
            print("⚠️  列表为空，无法继续测试")
            return None
    else:
        print("\n❌ 获取配件列表失败！")
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
    
    if data and data.get("status") == "success":
        print(f"\n✅ 成功获取配件详情")
        return data.get("data", {})
    else:
        print("\n❌ 获取配件详情失败！")
        return None

def test_update_item(item_id, item_details):
    """3. 修改配件信息"""
    url = f"{BASE_URL}/railway/parts/item_put"
    
    # 使用现有数据，只修改名称
    payload = {
        "id": item_id,
        "item_name": f"{item_details.get('item_name', '配件')}_测试修改",
        "item_code": item_details.get("item_code", "TEST"),
        "obj_url": item_details.get("obj_url"),
        "height": item_details.get("height"),
        "length": item_details.get("length"),
        "width": item_details.get("width"),
        "parent_item_id": item_details.get("parent_item_id", "0")
    }
    
    print("\n\n🔵 步骤 3: 修改配件信息")
    print(f"请求: POST {url}")
    print(f"数据: {json.dumps(payload, indent=2, ensure_ascii=False)}")
    
    response = requests.post(url, json=payload, headers=HEADERS)
    data = print_response("✅ 修改配件信息响应", response)
    
    if data and data.get("status") == "success":
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
        "length": 100.5,
        "width": 50.3,
        "height": 30.2
    }
    
    print("\n\n🔵 步骤 4: 修改配件3D模型尺寸")
    print(f"请求: POST {url}")
    print(f"数据: {json.dumps(payload, indent=2, ensure_ascii=False)}")
    
    response = requests.post(url, json=payload, headers=HEADERS)
    data = print_response("✅ 修改配件尺寸响应", response)
    
    if data and data.get("status") == "success":
        print(f"\n✅ 配件尺寸修改成功")
        return True
    else:
        print("\n❌ 配件尺寸修改失败！")
        return False

def test_restore_item(item_id, original_details):
    """5. 恢复配件原始信息"""
    url = f"{BASE_URL}/railway/parts/item_put"
    payload = {
        "id": item_id,
        "item_name": original_details.get("item_name"),
        "item_code": original_details.get("item_code"),
        "obj_url": original_details.get("obj_url"),
        "height": original_details.get("height"),
        "length": original_details.get("length"),
        "width": original_details.get("width"),
        "parent_item_id": original_details.get("parent_item_id", "0")
    }
    
    print("\n\n🔵 步骤 5: 恢复配件原始信息")
    print(f"请求: POST {url}")
    print(f"数据: {json.dumps(payload, indent=2, ensure_ascii=False)}")
    
    response = requests.post(url, json=payload, headers=HEADERS)
    data = print_response("✅ 恢复配件信息响应", response)
    
    if data and data.get("status") == "success":
        print(f"\n✅ 配件信息已恢复")
        return True
    else:
        print("\n❌ 配件信息恢复失败！")
        return False

def main():
    """主测试流程"""
    print("="*60)
    print("配件管理接口测试（使用现有配件）")
    print("="*60)
    print(f"服务地址: {BASE_URL}")
    print(f"开始时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 测试流程
    results = []
    
    # 1. 列出配件列表并获取第一个配件ID
    item_id = test_list_items()
    if not item_id:
        print("\n\n❌ 测试失败：无法获取配件列表或列表为空")
        return
    results.append(("列出配件列表", True))
    
    # 2. 获取配件详情
    item_details = test_get_item_details(item_id)
    if not item_details:
        print("\n\n❌ 测试失败：无法获取配件详情")
        return
    results.append(("获取配件详情", True))
    
    # 保存原始数据
    original_details = item_details.copy()
    
    # 3. 修改配件信息
    success = test_update_item(item_id, item_details)
    results.append(("修改配件信息", success))
    
    # 4. 修改配件尺寸
    success = test_update_item_size(item_id)
    results.append(("修改配件尺寸", success))
    
    # 5. 恢复原始信息
    success = test_restore_item(item_id, original_details)
    results.append(("恢复原始信息", success))
    
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
