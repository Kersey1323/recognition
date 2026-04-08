# 常见问题 FAQ

## 1. 数据库字段缺失错误

### 问题现象
```
column item_info.parent_num does not exist
```

### 原因
代码模型中定义了新字段，但数据库表结构未更新。

### 解决方法

**快速修复（推荐）：**
```bash
python fix_db_columns.py
```

**手动修复：**
```sql
ALTER TABLE parts.item_info ADD COLUMN IF NOT EXISTS parent_num INTEGER NOT NULL DEFAULT 0;
ALTER TABLE parts.item_info ADD COLUMN IF NOT EXISTS son_num INTEGER NOT NULL DEFAULT 0;
```

---

## 2. Milvus 连接失败

### 问题现象
```
Failed to connect to Milvus
```

### 解决方法
1. 检查 Milvus 服务是否启动
2. 检查配置文件中的 Milvus 地址和端口
3. 确认网络连接正常

---

## 3. MinIO 上传失败

### 问题现象
图片上传后无法访问

### 解决方法
1. 检查 MinIO 服务状态
2. 确认 bucket 已创建且权限正确
3. 检查 MinIO 配置（endpoint、access_key、secret_key）

---

## 4. 3D 重建任务卡住

### 问题现象
任务进度长时间不更新

### 解决方法
1. 查看后台日志，检查是否有错误
2. 确认 COLMAP 和相关依赖已正确安装
3. 检查图片质量和数量（建议 50-100 张）
4. 确认服务器有足够的 GPU 资源

---

## 5. 图片检索结果不准确

### 问题现象
检索返回的配件不相关

### 解决方法
1. 调整 `radius` 参数（建议 0.7-0.9）
2. 使用高精度模式（DINOv2）
3. 确保索引已正确建立
4. 检查图片质量（清晰度、角度、光照）

---

## 6. OCR 识别失败

### 问题现象
无法识别图片中的文字

### 解决方法
1. 确保图片清晰，文字可见
2. 检查 OCR 服务是否正常
3. 尝试调整图片大小和对比度

---

## 7. SAM 分割失败

### 问题现象
自动分割无法提取配件主体

### 解决方法
1. 确保图片背景简单
2. 配件主体清晰可见
3. 尝试手动裁剪后再建立索引

---

## 8. 性能问题

### 问题现象
接口响应慢

### 解决方法
1. 检查数据库连接池配置
2. 为常用查询添加索引
3. 使用 Redis 缓存热点数据
4. 考虑使用 CDN 加速图片访问

---

## 9. 依赖安装问题

### Python 包安装失败

```bash
# 使用国内镜像
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 或使用 conda
conda install --file requirements.txt
```

### CUDA 相关错误

确保安装了正确版本的 CUDA 和 cuDNN，与 PyTorch 版本匹配。

---

## 10. 权限问题

### 问题现象
无法访问某些接口

### 解决方法
1. 检查中间件配置
2. 确认用户权限设置
3. 查看日志中的详细错误信息

---

## 获取帮助

如果以上方法无法解决问题：

1. 查看完整的错误日志
2. 检查系统资源使用情况
3. 联系技术支持团队
