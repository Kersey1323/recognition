#!/usr/bin/env python3
"""
测试 MinIO 存储
"""
from minio import Minio
from minio.error import S3Error

# MinIO 配置
MINIO_ENDPOINT = "192.168.100.2:9000"
MINIO_ACCESS_KEY = "root"
MINIO_SECRET_KEY = "REMOVED_CREDENTIAL"
MINIO_SECURE = False  # 使用 HTTP 而不是 HTTPS

def test_minio():
    """测试 MinIO 连接和数据"""
    print("=" * 70)
    print(f"测试 MinIO: {MINIO_ENDPOINT}")
    print("=" * 70)
    
    try:
        # 创建 MinIO 客户端
        print("\n[1/4] 连接 MinIO...")
        client = Minio(
            MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=MINIO_SECURE
        )
        print("✓ 连接成功")
        
        # 列出所有 bucket
        print("\n[2/4] 列出所有 Bucket...")
        buckets = client.list_buckets()
        if buckets:
            print(f"✓ 找到 {len(buckets)} 个 Bucket:")
            for bucket in buckets:
                print(f"    - {bucket.name} (创建时间: {bucket.creation_date})")
        else:
            print("✗ 没有找到任何 Bucket")
            return
        
        # 检查常用的 bucket
        print("\n[3/4] 检查常用 Bucket 的内容...")
        common_buckets = ['bfr-ai-files', 'images', 'parts', 'railway-parts']
        
        for bucket_name in common_buckets:
            try:
                if client.bucket_exists(bucket_name):
                    print(f"\n  Bucket: {bucket_name}")
                    objects = list(client.list_objects(bucket_name, recursive=True))
                    
                    if objects:
                        print(f"    ✓ 包含 {len(objects)} 个对象")
                        
                        # 显示前5个对象
                        print(f"    前5个对象:")
                        for i, obj in enumerate(objects[:5]):
                            size_mb = obj.size / (1024 * 1024)
                            print(f"      {i+1}. {obj.object_name} ({size_mb:.2f} MB)")
                        
                        # 统计文件类型
                        extensions = {}
                        for obj in objects:
                            ext = obj.object_name.split('.')[-1].lower() if '.' in obj.object_name else 'no_ext'
                            extensions[ext] = extensions.get(ext, 0) + 1
                        
                        print(f"    文件类型统计:")
                        for ext, count in sorted(extensions.items(), key=lambda x: x[1], reverse=True)[:10]:
                            print(f"      .{ext}: {count} 个")
                    else:
                        print(f"    ✗ Bucket 为空")
            except S3Error as e:
                if e.code == 'NoSuchBucket':
                    print(f"  ✗ Bucket '{bucket_name}' 不存在")
                else:
                    print(f"  ✗ 错误: {e}")
        
        # 列出所有 bucket 的对象数量
        print("\n[4/4] 统计所有 Bucket 的对象数量...")
        total_objects = 0
        total_size = 0
        
        for bucket in buckets:
            try:
                objects = list(client.list_objects(bucket.name, recursive=True))
                count = len(objects)
                size = sum(obj.size for obj in objects)
                size_gb = size / (1024 * 1024 * 1024)
                total_objects += count
                total_size += size
                
                if count > 0:
                    print(f"  {bucket.name:30} {count:8} 个对象, {size_gb:8.2f} GB")
            except Exception as e:
                print(f"  {bucket.name:30} 错误: {e}")
        
        total_size_gb = total_size / (1024 * 1024 * 1024)
        print(f"\n  {'总计':30} {total_objects:8} 个对象, {total_size_gb:8.2f} GB")
        
        print("\n" + "=" * 70)
        print("✅ MinIO 测试完成！")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n❌ 连接失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_minio()
