# 甲方 SGO 网关与算法服务接口对接说明

## 1. 文档目的

本文档用于说明甲方部署场景下，`工装采集端`、`SGO 网关`、`我方算法服务`、`MinIO 对象存储` 之间的接口交互关系、必需数据项和现有接口清单。

本文档只描述**当前项目已经实现的真实接口**，重点面向以下两个业务场景：

1. 配件图片检索
2. 配件视频三维重构

同时，文档也会补充当前项目中已经存在的 `SGO` 集成接口，便于甲方评估是直接复用现有实现，还是需要在部署前做网关适配。

---

## 2. 系统边界与职责

| 系统 | 主要职责 | 说明 |
| --- | --- | --- |
| 工装采集端 | 操作员登录、选择配件、拍照、录视频、发起检索/重构 | 登录能力由甲方 `SGO` 侧承接，不在当前算法服务中实现 |
| SGO 网关 | 统一登录、鉴权、转发请求、汇聚甲方业务系统数据 | 可以理解为甲方外部系统访问算法服务的唯一入口 |
| 算法服务 | 配件查询、图片检索、三维重构、任务状态查询、部分 SGO 数据同步 | 当前项目基于 `FastAPI` 实现 |
| MinIO | 存储图片、原始视频、重构结果文件 | 当前项目默认有两个 bucket：`bfr-ai-files`、`bfr-3d-videos` |

### 2.1 当前实现的边界结论

根据当前项目实现，算法服务本身**没有独立登录接口**，也没有单独启用面向甲方的鉴权逻辑。因此推荐部署方式为：

1. 操作员先在工装采集端通过 `SGO` 完成登录。
2. `SGO` 网关完成鉴权后，再将业务请求转发给算法服务。
3. 算法服务只处理业务参数，不负责登录态管理。

这意味着：

- 登录接口不在本服务范围内。
- 算法服务当前更适合部署在甲方内网，由 `SGO` 网关统一暴露。

---

## 3. 基础约定

## 3.1 服务地址

部署后请将算法服务统一配置为：

```text
${ALGORITHM_BASE_URL}
```

示例：

```text
http://10.0.0.20:65432
```

## 3.2 统一响应格式

当前服务使用统一响应包裹，成功时结构如下：

```json
{
  "status": "success",
  "data": {},
  "requestID": "9a6d1c2d-2e3f-4f18-8c2c-f215c7f66111",
  "datetime": 1776720000000
}
```

失败时结构如下：

```json
{
  "status": "fail",
  "message": "错误描述",
  "requestID": "14c18b42-a9fb-4fd3-aef4-c4fb0f56eb48",
  "datetime": 1776720000000
}
```

### 3.2.1 联调注意事项

- 当前实现中，很多业务异常最终会以响应体中的 `status=fail` 返回。
- **网关侧请不要只依赖 HTTP 状态码判断成功与否，应以响应体中的 `status` 字段为准。**

## 3.3 数据标识约定

### 3.3.1 `item_id`

- 含义：算法服务中配件主键，对应 `parts.item_info.id`
- 用途：三维重构、图片登记、任务查询等接口的核心主键
- 重要说明：**三维重构接口必须传 `item_id`，不能传 `item_code`**

根据当前 `SGO` 同步实现，如果配件是通过现有 `SGO` 同步接口写入算法库，则：

- `item_id` 通常等于 `SGO` 主数据中的配件主键 ID

### 3.3.2 `item_code`

- 含义：物料编码 / 配件编码
- 用途：展示、检索、业务侧识别
- 注意：`item_code` 不是重构任务的外键，**不能替代 `item_id`**

### 3.3.3 当 `SGO` 侧只有 `item_code` 时的联调约定

当前项目中，`SGO` 侧很多业务数据天然只有 `item_code`，没有直接可用的 `item_id`。这在当前实现下**不是接口设计缺陷**，也不要求额外改造现有检索或三维重构接口；推荐做法是先通过算法服务把 `item_code` 映射成真实 `item_id`，再继续后续业务。

推荐调用顺序如下：

1. `SGO` 网关先调用 `/railway/parts/list_items`
2. 在请求体 `query` 中传入 `item_code`
3. 从返回结果中读取算法服务侧真实配件主键 `id`
4. 后续图片登记、已保存图片查询、三维重构上传、三维重构任务查询等接口，统一使用该 `id` 作为 `item_id`

补充说明：

- 由于算法服务的 `parts.item_info` 主数据是由 `SGO` 同步而来，正常情况下同一配件的 `item_code` 在两边保持一致
- 联调时，`SGO` 侧不应自行构造或猜测 `item_id`，必须以算法服务查询返回的 `id` 为准
- 如果通过 `item_code` 未查询到对应配件，说明该配件尚未同步到算法服务，此时不应继续调用依赖 `item_id` 的接口
- 当前受此规则影响最大的业务主要是：图片登记、已保存图片查询、三维重构视频上传、发起三维重构、查询某配件历史重构任务

### 3.3.4 `task_id`

- 含义：三维重构异步任务 ID
- 用途：查询任务进度、结果、失败原因

### 3.3.5 `image_url`

- 含义：已登记到算法服务中的图片地址
- 当前项目常用格式：`bucket/object`
- 常见示例：`bfr-ai-files/xxx.jpg`

### 3.3.6 `video_path`

- 含义：三维重构输入视频路径
- 推荐来源：先调用上传接口，由算法服务写入 `MinIO` 后返回
- 当前项目支持的路径形式：
  - `bfr-3d-videos/raw-videos/xxx.mp4`
  - `minio://bfr-3d-videos/raw-videos/xxx.mp4`
  - `s3://bfr-3d-videos/raw-videos/xxx.mp4`
  - `http://minio-host:9000/bfr-3d-videos/raw-videos/xxx.mp4`
  - 服务器本地绝对路径

## 3.4 MinIO bucket 约定

| bucket | 用途 | 默认值 |
| --- | --- | --- |
| 通用图片存储 | 配件图片、同步图片等 | `bfr-ai-files` |
| 三维重构原始视频存储 | 原始视频上传与重构读取 | `bfr-3d-videos` |

---

## 4. 联调最小数据清单

下表说明甲方在对接时，算法服务实际需要哪些数据。

| 数据项 | 来源 | 是否必需 | 适用场景 | 说明 |
| --- | --- | --- | --- | --- |
| `item_id` | SGO 主数据或算法服务查询结果 | 是 | 图片登记、视频上传、视频重构、任务查询 | 三维重构必须使用该值 |
| `item_code` | SGO 主数据 | 否 | 展示、检索辅助、业务关联 | 不能替代 `item_id` |
| `item_name` | SGO 主数据 | 否 | 展示、结果回显 | 推荐保留 |
| `width` / `length` / `height` | SGO 主数据或工装录入 | 否 | 配件基础信息 | 当前主要用于展示和补充信息 |
| 查询图片文件 | 工装采集端 | 是 | 图片检索 | 通过 `multipart/form-data` 上传 |
| 原始视频文件 | 工装采集端 | 是 | 视频三维重构 | 通过上传接口写入 MinIO |
| `name` | 工装采集端或 SGO 网关生成 | 是 | 视频三维重构 | 作为场景名/任务名使用 |
| `iterations` | SGO 网关或算法默认值 | 否 | 视频三维重构 | 默认 `30000` |
| `top_k` | SGO 网关 | 否 | 图片检索/文本检索 | 默认 `10` |
| `search_mode` | SGO 网关 | 否 | 图片检索 | 推荐 `hybrid` |

### 4.1 当前算法服务不直接消费的数据

以下信息当前算法接口中没有强制要求：

- 登录账号
- 登录密码
- `SGO token`
- 操作员姓名
- 操作员工号

这些字段可以由 `SGO` 网关自行管理；如甲方后续希望算法服务记录操作人，需要再补充审计字段或网关透传头。

---

## 5. 推荐交互流程

## 5.1 总体流程

```text
工装采集端
  -> SGO 登录 / 鉴权
  -> SGO 网关
  -> 算法服务
  -> MinIO / PostgreSQL / Celery
```

## 5.2 图片检索流程

```text
1. 工装采集端在 SGO 完成登录
2. 工装采集端选择配件或拍摄待检图片
3. SGO 网关调用算法服务图片检索接口
4. 算法服务返回候选配件列表（item_id、item_code、item_name、相似度）
5. SGO 网关将结果回显给工装采集端
6. 如需查看更多信息，可继续查询配件详情接口
```

## 5.3 视频三维重构流程

推荐流程：

```text
1. 工装采集端在 SGO 完成登录
2. SGO 网关确认当前配件的 item_id
3. SGO 网关调用视频上传接口，将原始视频写入 MinIO
4. 算法服务返回 video_path
5. SGO 网关调用视频重构接口，传入 item_id + video_path + name
6. 算法服务返回 task_id
7. SGO 网关轮询任务状态接口
8. 任务完成后获取 obj_url / ply_url / glb_url
9. SGO 网关将结果地址返回工装采集端或写回业务系统
```

如果甲方已经自行把视频放入了算法服务可访问的 `MinIO`，则可以跳过第 3 步，直接调用重构接口并传入 `video_path`。

---

## 6. 接口清单总览

## 6.1 SGO 网关直接调用算法服务的核心接口

| 方向 | 方法 | 路径 | 用途 |
| --- | --- | --- | --- |
| SGO -> 算法服务 | `POST` | `/railway/parts/list_items` | 分页查询配件列表 |
| SGO -> 算法服务 | `POST` | `/railway/parts/get_item_details` | 查询配件详情 |
| SGO -> 算法服务 | `POST` | `/railway/parts/create_item_image` | 为某个配件登记图片地址 |
| SGO -> 算法服务 | `POST` | `/railway/parts/v2/search/image` | 上传单张或多张图片做检索 |
| SGO -> 算法服务 | `POST` | `/railway/parts/v2/search/text` | 文本检索，可选 |
| SGO -> 算法服务 | `POST` | `/railway/parts/v2/reconstruct/video/upload` | 上传原始视频到 MinIO |
| SGO -> 算法服务 | `POST` | `/railway/parts/v2/reconstruct/video` | 发起视频三维重构 |
| SGO -> 算法服务 | `GET` | `/railway/parts/v2/reconstruct/status/{task_id}` | 查询任务状态 |
| SGO -> 算法服务 | `GET` | `/railway/parts/v2/reconstruct/item/{item_id}` | 查询某配件历史重构任务 |

## 6.2 当前项目中已实现的 SGO 集成接口

这组接口已经存在于算法服务中，但它们的定位更接近“算法服务内部触发同步”而不是“SGO 主动推送完整数据”。

| 方向 | 方法 | 路径 | 用途 |
| --- | --- | --- | --- |
| 算法服务 -> SGO 数据源 | `POST` | `/sgo/sgo/parts/sync` | 触发全量同步配件主数据 |
| 算法服务 -> SGO 数据源 | `POST` | `/sgo/sgo/parts/images/sync` | 按配件 ID 同步图片 |
| SGO -> 算法服务 | `POST` | `/railway/parts/list_item_images` | 查询某个配件已保存图片 |
| SGO -> 算法服务 | `POST` | `/sgo/sgo/inquery/list` | 查询询码记录及图片 |

### 6.1.1 多图检索接口约定

当 `SGO` 侧一次拿到同一配件的多张图片时，推荐调用：

- `POST /railway/parts/v2/search/image`

接口语义如下：

- 一次请求可上传 1 张或多张查询图
- 后端会对每张图独立检索
- 再在服务端统一融合排序
- 最终仍按 `item_id` 聚合返回候选配件

联调注意：

- `top_k` 仍表示“每张查询图的图片级候选窗口”
- 返回结果中的 `matched_images[].matched_query_indexes` 可用于表示某张命中图被第几张查询图共同支持
- 一次多图询码只会生成一个 `history_id`

### 6.2.1 适配说明

当前 `/sgo/sgo/*` 这组接口的真实实现是：

- 算法服务根据自身配置，去访问 `SGO` 侧数据源
- 并不是由 `SGO` 网关直接把完整配件主数据 JSON 推送给算法服务

因此，如果甲方的部署要求是：

- 算法服务不能直连 `SGO` 数据库/接口
- 所有数据必须只经过 `SGO` 网关 API 传递

那么当前这组同步接口需要再做一层改造，改成“网关推送式同步”。**本文档先按当前已实现接口说明。**

---

## 7. 接口详细说明

以下示例中的返回结构，默认只展示 `data` 部分；完整响应请参考本文档第 3.2 节。

## 7.1 查询配件列表

- 方法：`POST`
- 路径：`/railway/parts/list_items`
- 调用方：`SGO` 网关
- 用途：分页查询配件，拿到 `item_id`、`item_code`、`item_name`
- 请求类型：`application/json`

请求示例：

```json
{
  "page": 1,
  "pageSize": 20,
  "query": "控制主机",
  "parent_item_id": null,
  "only_has_index": 0,
  "has_inquery_code": 0,
  "has_images": 0
}
```

`data` 返回示例：

```json
{
  "total": 1,
  "items": [
    {
      "id": "1557988408477880320",
      "item_name": "司机室控制主机",
      "item_code": "40001178346",
      "obj_url": null,
      "height": 105.0,
      "length": 205.0,
      "width": 155.0,
      "created_at": "2026-04-21 11:00:00",
      "features": [],
      "features_num": 0,
      "images_total_num": 8,
      "images_total_indexed_num": 6
    }
  ]
}
```

使用建议：

- 如果工装侧只有 `item_code`，可以先用该接口按编码查询，再拿到真实 `item_id`
- 三维重构前建议先走这一步确认 `item_id`

## 7.2 查询配件详情

- 方法：`POST`
- 路径：`/railway/parts/get_item_details`
- 调用方：`SGO` 网关
- 用途：查看单个配件详情、已登记图片、特征等
- 请求类型：`application/json`

请求示例：

```json
{
  "item_id": "1557988408477880320"
}
```

`data` 返回示例：

```json
{
  "id": "1557988408477880320",
  "name": "司机室控制主机",
  "item_code": "40001178346",
  "obj_url": null,
  "height": 105.0,
  "length": 205.0,
  "width": 155.0,
  "created_at": "2026-04-21 11:00:00",
  "updated_at": "2026-04-21 11:10:00",
  "parent_item_id": null,
  "parent_item_name": null,
  "parent_item_code": null,
  "size_str": null,
  "features": [],
  "images": [
    {
      "image_id": "2040000000000000001",
      "has_indexed": 1,
      "image_url": "bfr-ai-files/example.jpg",
      "source_type": "BASEINFO"
    }
  ],
  "images_index_list": []
}
```

## 7.3 为配件登记图片

- 方法：`POST`
- 路径：`/railway/parts/create_item_image`
- 调用方：`SGO` 网关
- 用途：将已上传的图片地址登记到指定配件名下
- 请求类型：`application/json`

请求示例：

```json
{
  "item_id": "1557988408477880320",
  "images_url": [
    "bfr-ai-files/20260421_part_01.jpg",
    "bfr-ai-files/20260421_part_02.jpg"
  ]
}
```

说明：

- 该接口**不负责接收二进制文件上传**，只负责登记图片地址
- 如果图片由工装采集端直接上传到某个对象存储，需要保证算法服务后续能够读取这些图片

## 7.4 图片检索

- 方法：`POST`
- 路径：`/railway/parts/v2/search/image`
- 调用方：`SGO` 网关
- 用途：上传一张查询图片，返回相似配件列表
- 请求类型：`multipart/form-data`

查询参数：

| 参数 | 是否必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `top_k` | 否 | `10` | 返回候选结果数量 |
| `search_mode` | 否 | `hybrid` | 检索模式，可选 `siglip`、`dinov2`、`hybrid` |

表单字段：

| 字段 | 类型 | 是否必填 | 说明 |
| --- | --- | --- | --- |
| `file` | 文件 | 是 | 查询图片 |

调用示例：

```bash
curl -X POST "${ALGORITHM_BASE_URL}/railway/parts/v2/search/image?top_k=5&search_mode=hybrid" \
  -F "file=@query.jpg"
```

`data` 返回示例：

```json
{
  "data": [
    {
      "item_id": "1557988408477880320",
      "item_code": "40001178346",
      "item_name": "司机室控制主机",
      "image_url": "bfr-ai-files/example.jpg",
      "rate": 0.9231
    },
    {
      "item_id": "1557988408477880333",
      "item_code": "40001170000",
      "item_name": "司机室控制面板",
      "image_url": "bfr-ai-files/example2.jpg",
      "rate": 0.8610
    }
  ],
  "message": null
}
```

推荐：

- 生产环境优先使用 `search_mode=hybrid`
- 检索结果出来后，如需展示完整配件信息，可再调用配件详情接口

## 7.5 文本检索

- 方法：`POST`
- 路径：`/railway/parts/v2/search/text`
- 调用方：`SGO` 网关
- 用途：按文字描述检索配件
- 参数位置：查询参数

查询参数：

| 参数 | 是否必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `query_text` | 是 | 无 | 查询文本 |
| `top_k` | 否 | `10` | 返回结果数量 |

调用示例：

```bash
curl -X POST "${ALGORITHM_BASE_URL}/railway/parts/v2/search/text?query_text=控制主机&top_k=5"
```

`data` 返回示例：

```json
{
  "data": [
    {
      "item_id": "1557988408477880320",
      "item_code": "40001178346",
      "item_name": "司机室控制主机",
      "image_url": "bfr-ai-files/example.jpg",
      "rate": 0.9012
    }
  ],
  "message": null
}
```

## 7.6 上传三维重构原始视频

- 方法：`POST`
- 路径：`/railway/parts/v2/reconstruct/video/upload`
- 调用方：`SGO` 网关
- 用途：将原始视频写入算法服务可访问的 `MinIO`
- 请求类型：`multipart/form-data`

表单字段：

| 字段 | 类型 | 是否必填 | 说明 |
| --- | --- | --- | --- |
| `item_id` | 整数 | 是 | 配件主键 |
| `file` | 文件 | 是 | 原始视频文件 |

调用示例：

```bash
curl -X POST "${ALGORITHM_BASE_URL}/railway/parts/v2/reconstruct/video/upload" \
  -F "item_id=1557988408477880320" \
  -F "file=@capture.mp4"
```

`data` 返回示例：

```json
{
  "item_id": 1557988408477880320,
  "bucket": "bfr-3d-videos",
  "object_name": "raw-videos/1557988408477880320/20260421/2046420876131438592_capture.mp4",
  "video_path": "bfr-3d-videos/raw-videos/1557988408477880320/20260421/2046420876131438592_capture.mp4",
  "size": 182736451,
  "content_type": "video/mp4",
  "message": "原始视频上传成功"
}
```

注意事项：

- 该接口会先校验 `item_id` 是否存在
- 如果传入的 `item_id` 不存在，会返回失败
- 返回的 `video_path` 可以直接作为下一步重构接口的输入

## 7.7 发起视频三维重构

- 方法：`POST`
- 路径：`/railway/parts/v2/reconstruct/video`
- 调用方：`SGO` 网关
- 用途：提交异步视频重构任务
- 请求类型：`application/json`

最小请求示例：

```json
{
  "item_id": 1557988408477880320,
  "video_path": "bfr-3d-videos/raw-videos/1557988408477880320/20260421/2046420876131438592_capture.mp4",
  "name": "part_1557988408477880320_20260421"
}
```

完整请求字段：

| 字段 | 是否必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `item_id` | 是 | 无 | 配件主键 |
| `video_path` | 是 | 无 | 视频路径，推荐使用上传接口返回值 |
| `name` | 是 | 无 | 场景名 |
| `iterations` | 否 | `30000` | 训练迭代次数 |
| `fps` | 否 | `3` | 提帧率 |
| `image_size` | 否 | `1600` | 图片最大边长 |
| `blur_threshold` | 否 | `0` | 模糊阈值，`0` 表示自适应 |
| `dedup_threshold` | 否 | `25` | 去重汉明距离 |
| `min_frames` | 否 | `30` | 最小帧数 |
| `sam3_model` | 否 | `""` | SAM3 模型路径 |
| `text_prompt` | 否 | `"object"` | 分割提示词 |
| `mask_dilate` | 否 | `15` | mask 膨胀像素 |
| `camera` | 否 | `"OPENCV"` | 相机模型 |
| `no_gpu` | 否 | `true` | 是否禁用 GPU |
| `skip_extract` | 否 | `false` | 是否跳过提帧 |
| `skip_filter` | 否 | `false` | 是否跳过帧筛选 |
| `skip_colmap` | 否 | `false` | 是否跳过 COLMAP |
| `skip_sam3` | 否 | `false` | 是否跳过 SAM3 |
| `output_name` | 否 | `null` | 输出名称 |

`data` 返回示例：

```json
{
  "task_id": "ad787a2c-14f0-4f73-87df-c26cbd3bd23b",
  "item_id": 1557988408477880320,
  "mode": "video",
  "message": "视频重建任务已提交"
}
```

关键说明：

- 该接口是异步任务提交接口，不会同步返回重构结果
- 成功后请使用 `task_id` 轮询状态接口
- **`item_id` 必须真实存在，否则会因为配件外键校验失败而无法建任务**

## 7.8 查询重构任务状态

- 方法：`GET`
- 路径：`/railway/parts/v2/reconstruct/status/{task_id}`
- 调用方：`SGO` 网关
- 用途：轮询单个任务的状态与结果

调用示例：

```text
GET /railway/parts/v2/reconstruct/status/ad787a2c-14f0-4f73-87df-c26cbd3bd23b
```

`data` 返回示例：

```json
{
  "task_id": "ad787a2c-14f0-4f73-87df-c26cbd3bd23b",
  "item_id": 1557988408477880320,
  "status": "training",
  "progress": 65,
  "current_stage": "3DGS training",
  "error_message": null,
  "ply_url": null,
  "obj_url": null,
  "glb_url": null,
  "total_frames": 580,
  "filtered_frames": 214,
  "colmap_points": 123456,
  "created_at": "2026-04-21 11:12:47",
  "updated_at": "2026-04-21 11:18:02"
}
```

状态值范围：

- `pending`
- `extracting`
- `filtering`
- `colmap`
- `sam3`
- `training`
- `converting`
- `success`
- `failed`
- `cancelled`

轮询建议：

- 轮询间隔建议 `5` 到 `10` 秒
- 当 `status=success` 时，读取 `obj_url`、`ply_url`、`glb_url`
- 当 `status=failed` 时，读取 `error_message`

## 7.9 查询某配件历史重构任务

- 方法：`GET`
- 路径：`/railway/parts/v2/reconstruct/item/{item_id}`
- 调用方：`SGO` 网关
- 用途：查看某个配件历史重构记录

调用示例：

```text
GET /railway/parts/v2/reconstruct/item/1557988408477880320
```

`data` 返回示例：

```json
{
  "records": [
    {
      "task_id": "ad787a2c-14f0-4f73-87df-c26cbd3bd23b",
      "item_id": 1557988408477880320,
      "status": "success",
      "progress": 100,
      "current_stage": "done",
      "error_message": null,
      "ply_url": "bfr-ai-files/result/demo.ply",
      "obj_url": "bfr-ai-files/result/demo.obj",
      "glb_url": "bfr-ai-files/result/demo.glb",
      "total_frames": 580,
      "filtered_frames": 214,
      "colmap_points": 123456,
      "created_at": "2026-04-21 11:12:47",
      "updated_at": "2026-04-21 11:30:12"
    }
  ]
}
```

## 7.10 触发全量同步配件主数据

- 方法：`POST`
- 路径：`/sgo/sgo/parts/sync`
- 调用方：算法服务管理任务 / 运维任务
- 用途：从当前配置的 `SGO` 数据源同步全部配件主数据到算法服务
- 请求类型：`application/json`

请求示例：

```json
{}
```

说明：

- 当前接口本身不接收完整配件主数据
- 它只是一个“触发同步”的入口
- 要正常工作，算法服务必须能够访问 `SGO` 数据源

## 7.11 按配件 ID 同步 SGO 图片

- 方法：`POST`
- 路径：`/sgo/sgo/parts/images/sync`
- 调用方：算法服务管理任务 / 运维任务
- 用途：根据配件 ID 批量同步 `SGO` 图片

请求示例：

```json
{
  "items_id_list": [
    "1557988408477880320",
    "1557988408477880333"
  ]
}
```

说明：

- 当前实现会去 `SGO` 数据源拉取图片，再存入算法服务自己的 `MinIO`
- 同步完成后，图片会作为配件图片参与后续索引或检索

## 7.12 查询某个配件已保存图片

- 方法：`POST`
- 路径：`/railway/parts/list_item_images`
- 调用方：`SGO` 网关或管理后台
- 用途：查看某个配件在算法服务中已经保存的 `SGO` 图片

请求示例：

```json
{
  "item_id": "1557988408477880320"
}
```

`data` 返回示例：

```json
{
  "items": [
    {
      "image_id": "2040000000000000001",
      "has_indexed": 1,
      "image_url": "bfr-ai-files/example.jpg",
      "image_source_type": "BASEINFO"
    }
  ]
}
```

## 7.13 查询询码记录列表

- 方法：`POST`
- 路径：`/sgo/sgo/inquery/list`
- 调用方：`SGO` 网关或管理后台
- 用途：查询询码记录及相关图片

请求示例：

```json
{
  "page": 1,
  "pageSize": 20,
  "has_indexed": 0,
  "current_status": "FINISH"
}
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `has_indexed` | `1` 为已建索引，`2` 为未建索引，`0` 为不按该条件筛选 |
| `current_status` | 询码状态，如 `FINISH`、`CREATE`、`CONFIRMAUDIT` 等 |

说明：

- 当前接口主要服务于 `SGO` 数据联动和图片入库场景
- 它不是三维重构主流程的必经接口

---

## 8. 甲方联调建议

## 8.1 推荐的对接边界

推荐甲方按下面的边界来对接：

1. `SGO` 负责登录和鉴权
2. `SGO` 负责把业务请求转发给算法服务
3. 算法服务只处理配件查询、检索、重构、任务状态查询
4. 视频优先通过算法服务上传接口写入 `MinIO`

这样做的好处是：

- 算法服务改动最少
- `item_id`、`task_id`、`video_path` 的责任边界清晰
- 重构链路可直接复用当前项目实现

## 8.2 当前实现下最容易踩坑的地方

### 8.2.1 用 `item_code` 代替 `item_id`

这是当前三维重构链路中最容易出错的问题。重构接口真正需要的是：

- `parts.item_info.id`

而不是：

- 物料编码 `item_code`

### 8.2.2 只看 HTTP 状态码，不看响应体 `status`

网关侧必须按响应体中的 `status` 判断成功或失败。

### 8.2.3 直接调用重构接口，但视频路径不可访问

如果不走上传接口，而是直接给出 `video_path`，必须确保：

- 算法服务所在机器能访问该路径
- 或者该路径是算法服务支持识别的 `MinIO` 对象路径

### 8.2.4 误以为 `/sgo/sgo/*` 是网关推送式接口

当前这组接口大多是“算法服务侧主动拉 `SGO` 数据源”的实现，并不是通用的“甲方网关推送数据”接口。

---

## 9. 部署前置条件

如需完整启用本文档中的能力，部署时至少需要满足以下条件：

1. `SGO` 网关能够访问算法服务 HTTP 接口
2. 算法服务能够访问自己的 `PostgreSQL`
3. 算法服务能够访问 `MinIO`
4. 如启用三维重构，算法服务还需要配套 `Redis + Celery Worker + Flower`
5. 如复用 `/sgo/sgo/*` 同步接口，算法服务还需要访问甲方 `SGO` 数据源

---

## 10. 结论

基于当前项目实现，甲方部署时最核心、最稳定的联调链路建议为：

1. `SGO` 统一登录
2. `SGO` 查询配件并确认 `item_id`
3. `SGO` 调用算法服务图片检索接口
4. `SGO` 调用算法服务视频上传接口
5. `SGO` 调用算法服务视频重构接口
6. `SGO` 轮询任务状态接口并回传结果

如果甲方后续希望把“主数据同步、图片同步、任务完成回调”全部纳入 `SGO` 网关统一治理，则建议在本项目现有基础上，再增加一版面向甲方的“推送式同步接口”和“结果回调接口”。
