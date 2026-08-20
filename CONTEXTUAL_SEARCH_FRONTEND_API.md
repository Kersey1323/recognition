# 带业务条件的图片检索接口（前端联调说明）

## 1. 功能说明

该接口同时支持首次检索和基于同一条检索历史的再次检索。

- 首次检索：上传图片，可同时提供车型、名称描述等业务条件。
- 再次检索：传入首次检索返回的 `history_id`，可以替换图片或调整业务条件。
- 同一个 `history_id` 最多展示最近两次检索：`previous`（上一次）和 `current`（本次）。
- 用户继续检索时，原 `current` 变成新的 `previous`，更早的结果不再保留。
- 后端固定返回 TOP 10，前端不需要传 `top_k`。

接口地址：

```http
POST /railway/parts/v2/search/contextual
Content-Type: multipart/form-data
```

> 使用浏览器 `FormData` 或 `curl -F` 时不要手动设置 `Content-Type`，由客户端自动添加 multipart boundary。

## 2. 请求参数

| 参数 | 类型 | 必填 | 默认值 | 含义 |
| --- | --- | --- | --- | --- |
| `history_id` | string | 首次否，再次是 | 无 | 首次检索不传；再次检索传首次返回的 ID。前端应按字符串保存，避免 JavaScript 大整数精度丢失。 |
| `file` | File[] | 首次是，再次否 | 无 | 查询图片，可上传多张。再次检索传新图片时会整体替换当前查询图片，不是追加。 |
| `vehicle_batch` | string | 否 | 无 | 车型项目号，用于硬过滤候选配件，例如 `SFE27`、`SFE11`。 |
| `item_name` | string | 否 | 无 | 名称描述，例如“司机室门锁整体及钥匙”，用于名称语义和文本相似度排序。 |
| `train_no` | string | 否 | 无 | 列号，例如 `2667`，根据历史询码记录对候选加权。 |
| `car_num` | string | 否 | 无 | 车厢号，例如 `01` 或 `01,08`，根据历史询码记录对候选加权。 |
| `subordinate_component` | string | 否 | 无 | 隶属部件，例如“门锁”，根据历史询码记录对候选加权。 |
| `search_mode` | string | 否 | `siglip` | 图片检索模式：`siglip`、`dinov2`、`hybrid`。前端默认使用 `siglip`。 |
| `search_equipment` | string | 否 | `web` | 检索来源，Web 端传 `web`，手持终端传 `terminal`。 |

### 2.1 车型参数注意事项

`vehicle_batch` 必须传车型项目号，后端会对该字段做精确匹配。

正确示例：

```text
SFE27
SFE11
E27
```

错误示例：

```text
SFE11_CRH380A
E11_CRH380A
CRH380A
```

`SFE11_CRH380A` 属于“车型项目号 + 车型名称”的组合描述，不是 `vehicle_batch`。如果前端下拉框同时展示项目号和车型名称，应使用：

```ts
{ label: "SFE11 / CRH380A", value: "SFE11" }
```

### 2.2 首次检索规则

- 不传 `history_id`。
- 至少上传一张 `file`。
- 其他业务条件均可选。

### 2.3 再次检索规则

- 必须传已有的 `history_id`。
- 只有 `pending` 状态的检索历史允许再次检索。
- 上传新图片时，新图片替换当前图片；业务条件可以全部不传。
- 不上传新图片时，后端复用当前图片，但至少要传一个业务条件。
- 每次请求中的业务条件都是完整快照。未传字段会清空为 `null`，不会继承上一次的值。

## 3. 前端请求示例

### 3.1 首次检索

```ts
const form = new FormData();
form.append("file", imageFile);
form.append("vehicle_batch", "SFE27");
form.append("item_name", "司机室门锁整体及钥匙");
form.append("train_no", "2667");
form.append("car_num", "01,08");
form.append("subordinate_component", "门锁");
form.append("search_mode", "siglip");
form.append("search_equipment", "web");

const response = await fetch(
  `${apiBase}/railway/parts/v2/search/contextual`,
  {
    method: "POST",
    body: form,
    headers: { "U-Token": token },
  },
);
```

### 3.2 使用原图片再次检索

```ts
const form = new FormData();
form.append("history_id", historyId);
form.append("vehicle_batch", "SFE27");
form.append("item_name", "司机室隔门锁左");
form.append("search_mode", "siglip");
form.append("search_equipment", "web");

const response = await fetch(
  `${apiBase}/railway/parts/v2/search/contextual`,
  {
    method: "POST",
    body: form,
    headers: { "U-Token": token },
  },
);
```

### 3.3 替换图片再次检索

```ts
const form = new FormData();
form.append("history_id", historyId);
form.append("file", newImageFile);
form.append("search_mode", "siglip");
form.append("search_equipment", "web");
```

## 4. 响应结构

服务使用统一响应外层，业务结果位于外层的 `data` 字段：

```json
{
  "status": "success",
  "data": {
    "history_id": "2089920864551309312",
    "previous": null,
    "current": {
      "query_images": [
        "bfr-search-history-files/query-images/20260819/2089920864551309312/query.png"
      ],
      "parameters": {
        "vehicle_batch": "SFE27",
        "item_name": "司机室门锁整体及钥匙",
        "train_no": "2667",
        "car_num": "01,08",
        "subordinate_component": "门锁",
        "search_mode": "siglip"
      },
      "searched_at": "2026-08-19 11:42:17",
      "data": [
        {
          "item_id": "1557989344063524864",
          "item_code": "19010059703",
          "item_name": "司机室隔门锁左",
          "image_url": "bfr-ai-files/202315870112146132023.jpg",
          "rate": 0.92,
          "matched_images": [
            {
              "image_url": "bfr-ai-files/202315870112146132023.jpg",
              "rate": 0.89,
              "matched_query_indexes": [0]
            }
          ]
        }
      ]
    },
    "message": null
  },
  "datetime": 1787110937667,
  "requestID": "8f6ca356-7ad7-4473-bc0f-d442573b61e3"
}
```

再次检索成功后，`previous` 和 `current` 都有值：

```json
{
  "history_id": "2089920864551309312",
  "previous": {
    "query_images": ["上一轮图片路径"],
    "parameters": {},
    "searched_at": "2026-08-19 11:42:17",
    "data": []
  },
  "current": {
    "query_images": ["本轮图片路径"],
    "parameters": {},
    "searched_at": "2026-08-19 11:45:30",
    "data": []
  },
  "message": null
}
```

## 5. 响应字段含义

### 5.1 业务响应

| 字段 | 类型 | 含义 | 前端处理 |
| --- | --- | --- | --- |
| `history_id` | string | 当前检索历史 ID，首次和再次检索始终不变。 | 保存到页面状态，后续再次检索继续传入；不要转成 number。 |
| `previous` | SearchSnapshot \| null | 上一次检索快照。首次检索为 `null`。 | 有值时显示“上一次检索”，无值时隐藏该区域。 |
| `current` | SearchSnapshot | 本次检索快照。 | 显示“本次检索”。 |
| `message` | string \| null | 空结果或业务提示。 | 有值时显示在结果空状态区域，例如“车型 SFE27 下没有可检索配件”。 |

### 5.2 检索快照 SearchSnapshot

| 字段 | 类型 | 含义 | 前端处理 |
| --- | --- | --- | --- |
| `query_images` | string[] | 本轮使用的查询图片。 | 显示查询图片缩略图。 |
| `parameters` | object | 本轮完整业务条件。 | 只显示非空条件。 |
| `searched_at` | string | 检索时间，格式 `YYYY-MM-DD HH:mm:ss`。 | 显示在该轮标题旁。 |
| `data` | SearchItem[] | 本轮 TOP 10 配件结果。 | 渲染结果列表；空数组显示空状态。 |

`parameters` 中还可能存在 `features`、`images`、`query_images`、`vechile`、`parent_item_id`、`lower_rate` 等兼容旧接口的字段，本功能前端无需展示。

### 5.3 配件结果 SearchItem

| 字段 | 类型 | 含义 | 前端处理 |
| --- | --- | --- | --- |
| `item_id` | string | 配件主键。 | 用作列表 key 和后续选择值，不建议直接展示。 |
| `item_code` | string | 物料编码。 | 展示。 |
| `item_name` | string | 配件名称。 | 作为结果主标题展示。 |
| `image_url` | string | 结果代表图片路径。 | 作为结果主图展示。 |
| `rate` | number | 图片、名称和历史条件融合后的最终分数，范围约为 0 到 1。 | 建议展示为 `Math.round(rate * 100) + "%"`。 |
| `matched_images` | MatchedImage[] | 该配件的其他图片匹配明细。 | 简约列表可不展示；详情或展开区域显示。 |

### 5.4 图片匹配 MatchedImage

| 字段 | 类型 | 含义 | 前端处理 |
| --- | --- | --- | --- |
| `image_url` | string | 命中的配件图片路径。 | 显示缩略图。 |
| `rate` | number | 该图片的原始视觉匹配分数。 | 可选展示，不要替代 SearchItem 的最终 `rate`。 |
| `matched_query_indexes` | number[] | 该图片命中了第几张查询图，从 0 开始。 | 多图检索详情中可显示；普通列表忽略。 |

## 6. 前端简约展示字段

前端主页面只需要以下字段：

| 页面区域 | 使用字段 |
| --- | --- |
| 再次检索状态 | `history_id` |
| 两轮切换或对比 | `previous`、`current` |
| 查询图片 | `snapshot.query_images` |
| 条件摘要 | `vehicle_batch`、`item_name`、`train_no`、`car_num`、`subordinate_component` |
| 检索时间 | `snapshot.searched_at` |
| 结果主图 | `item.image_url` |
| 结果名称 | `item.item_name` |
| 物料编码 | `item.item_code` |
| 综合匹配度 | `item.rate` |
| 空结果提示 | 业务响应 `message` |

推荐界面结构：

```text
上一次检索（previous，有值时显示）
  查询图片 + 非空条件 + 检索时间
  配件结果列表

本次检索（current）
  查询图片 + 非空条件 + 检索时间
  配件结果列表
```

不建议直接展示：

- `item_id`
- `search_revision`
- 兼容旧接口的 parameters 字段
- `matched_query_indexes`（除非实现多图匹配详情）

## 7. 图片路径处理

接口中的图片通常是存储路径，不一定是完整 URL，例如：

```text
bfr-ai-files/202315870112146132023.jpg
bfr-search-history-files/query-images/.../query.png
```

前端可以拼接当前算法服务地址：

```ts
function resolveAssetUrl(path: string): string {
  if (/^https?:\/\//.test(path)) return path;
  return `${apiBase}/${path.replace(/^\/+/, "")}`;
}
```

图片请求需要沿用项目现有鉴权方式携带 `U-Token`。路径中包含中文或空格时，应交给浏览器 URL API 编码，不要手工拼接未编码路径。

## 8. TypeScript 简化类型

```ts
type SearchMode = "siglip" | "dinov2" | "hybrid";

interface ContextualParameters {
  vehicle_batch: string | null;
  item_name: string | null;
  train_no: string | null;
  car_num: string | null;
  subordinate_component: string | null;
  search_mode: SearchMode;
}

interface MatchedImage {
  image_url: string;
  rate: number;
  matched_query_indexes: number[];
}

interface SearchItem {
  item_id: string;
  item_code: string;
  item_name: string;
  image_url: string;
  rate: number;
  matched_images: MatchedImage[];
}

interface SearchSnapshot {
  query_images: string[];
  parameters: ContextualParameters;
  searched_at: string;
  data: SearchItem[];
}

interface ContextualSearchData {
  history_id: string;
  previous: SearchSnapshot | null;
  current: SearchSnapshot;
  message: string | null;
}

interface ApiResponse<T> {
  status: "success" | "fail";
  data?: T;
  datetime: number;
  requestID: string;
  message?: string;
}
```

## 9. 状态与异常处理

| HTTP 状态 | 场景 | 前端建议 |
| --- | --- | --- |
| `404` | `history_id` 不存在。 | 清除本地 history ID，提示用户重新发起首次检索。 |
| `409` | 检索历史已不是 `pending`，或并发请求已更新该历史。 | 刷新检索历史；禁止重复提交。 |
| `422` | 首次未上传图片、参数不合法、无新图片且无业务条件等。 | 直接展示后端 `detail` 或统一响应中的 `message`。 |

前端同时检查 HTTP 状态和统一响应中的 `status`。只有 `status === "success"` 且 `data` 存在时，才使用业务数据更新页面。

空候选属于成功响应，判断方式为：

```ts
payload.status === "success" &&
payload.data.current.data.length === 0
```

此时优先展示 `payload.data.message`，不要按系统异常处理。
