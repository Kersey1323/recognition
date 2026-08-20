# 检索历史详情接口前端简要说明

## 接口

```http
POST /railway/parts/v2/search/history/detail
Content-Type: application/json
```

请求体：

```json
{
  "history_id": "2090264125937684480"
}
```

`history_id` 必须按字符串传递和保存，不能转换成 JavaScript `number`，否则可能丢失精度。

## 两轮检索数据

详情接口最多返回最近两轮检索。前端可将它们展示为“上一次检索”和“本次检索”。

| 页面内容 | 上一次检索 | 本次检索 |
| --- | --- | --- |
| 查询图片 | `previous_query_images` | `query_image` 或 `query_images` |
| 检索条件 | `previous_search_parameter` | `search_parameter` |
| 检索结果 | `previous_result.items` | `result.items` |
| 检索时间 | `previous_searched_at` | 当前响应暂不单独提供 |

显示规则：

- `previous_result` 为 `null` 时，说明只有一轮检索，不显示“上一次检索”。
- `previous_result` 有值时，显示最近两轮检索结果。
- 用户继续精准检索后，原本次结果会变成上一次结果，更早的结果不再保留。
- `search_revision` 表示成功检索次数，仅用于判断记录版本，不需要展示。

## 前端建议展示字段

### 检索条件

只展示以下非空字段：

| 字段 | 页面名称 |
| --- | --- |
| `vehicle_batch` | 车型项目号 |
| `item_name` | 名称描述 |
| `train_no` | 列号 |
| `car_num` | 车厢号 |
| `subordinate_component` | 隶属部件 |
| `search_mode` | 检索模式 |

`features`、`images`、`query_images`、`vechile`、`parent_item_id`、`lower_rate` 是兼容字段，本页面无需展示。

### 检索结果

`previous_result.items` 和 `result.items` 中的单条结果建议只展示：

| 字段 | 页面用途 |
| --- | --- |
| `item_name` | 配件名称 |
| `item_code` | 物料编码 |
| `image_url` | 配件代表图片 |
| `similar` | 综合匹配度，可格式化为百分比 |

`item_id` 用于列表 key、选择配件和后续接口传参，不建议作为业务文本展示。

`matched_images` 是同一配件的图片命中明细，简约列表可不展示；需要展开详情时再使用其中的 `image_url` 和 `rate`。

## 前端数据整理示例

```ts
const detail = response.data;

const previousSearch = detail.previous_result
  ? {
      title: "上一次检索",
      images: detail.previous_query_images ?? [],
      parameters: detail.previous_search_parameter,
      items: detail.previous_result.items ?? [],
      searchedAt: detail.previous_searched_at,
    }
  : null;

const currentImages = detail.query_images?.length
  ? detail.query_images
  : detail.query_image
    ? [detail.query_image]
    : [];

const currentSearch = {
  title: "本次检索",
  images: currentImages,
  parameters: detail.search_parameter,
  items: detail.result?.items ?? [],
};
```

## 其他状态字段

| 字段 | 简要说明 |
| --- | --- |
| `status` | 校验状态：`pending` 待校验、`correct` 正确、`wrong` 错误、`user_misjudged` 用户误判 |
| `history_id` | 当前检索历史 ID，关闭弹窗后重新获取详情时使用 |
| `search_item_name` | 当前检索结果第一名的配件名称 |
| `search_item_code` | 当前检索结果第一名的物料编码 |
| `correct_item_*` | 人工校验后最终确认的配件信息，未确认时为空 |
| `has_open_review_ticket` | 是否存在未结束的校验清单 |

## 图片地址

接口返回的是 OSS 内部路径，例如：

```text
bfr-ai-files/202315870112146132023.jpg
bfr-search-history-files/query-images/20260820/example.png
```

前端按现有资源代理规则拼接算法服务地址，并沿用当前项目的鉴权方式访问图片。
