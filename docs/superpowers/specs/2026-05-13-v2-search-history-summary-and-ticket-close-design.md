# V2 检索历史摘要与核验单自动关闭设计

## Goal

针对 V2 检索历史补齐两个业务优化：

- 为 `POST /railway/parts/v2/search/history/summary` 新增 `recognition_accuracy` 返回字段
- 当用户在检索历史中将一条记录的反馈结果改为 `correct` 时，自动关闭该记录对应的未关闭核验单

本次设计目标是补强现有 V2 检索历史与核验单闭环，不新增新的业务入口，不改变现有前端调用路径。

## Non-Goals

本次不包含以下内容：

- 不改 `POST /railway/parts/v2/search/history/list` 的查询条件、分页结构和公共状态映射规则
- 不新增新的核验单状态枚举
- 不改技术部核验单的人工处理流程
- 不改 V2 检索召回、排序、反馈选中逻辑
- 不处理 CPU 模式部署和三维重建能力开关

## Current State

当前 V2 检索历史已经具备以下能力：

- `POST /railway/parts/v2/search/history/list`
- `POST /railway/parts/v2/search/history/detail`
- `POST /railway/parts/v2/search/history/summary`
- `POST /railway/parts/v2/search/history/feedback`
- `POST /railway/parts/v2/search/reviewTicket/list`
- `POST /railway/parts/v2/search/reviewTicket/update`

现状上有两个问题：

### 1. 历史摘要缺少“识别准确率”

当前 `summary` 只返回：

- `total`
- `pending_count`
- `correct_count`
- `wrong_count`
- `user_misjudged_count`
- `open_ticket_count`

前端如果要展示“识别准确率”，只能自己再拿 `correct_count` 和 `wrong_count` 做计算，不适合作为统一口径。

### 2. “用户修正为正确”这条核验单闭环规则缺少明确 contract

业务真实流程是：

1. 用户检索配件
2. 如果找到正确结果，反馈为 `correct`
3. 如果没找到正确结果，反馈为 `wrong`
4. 该历史记录进入待校验状态，并生成核验单供技术部处理
5. 用户之后可能在历史列表中修正反馈，将原来的错误反馈改成 `correct`
6. 此时对应核验单应该自动关闭

当前代码链路已经部分具备该能力，但接口 contract 和测试覆盖还不够明确，容易在后续改动中回归。

## Design Options

### Option A: 只改前端计算准确率，不动后端 contract

做法：

- `summary` 保持原样
- 前端根据 `correct_count` 和 `wrong_count` 自算准确率
- 核验单关闭逻辑继续依赖隐式后端实现

优点：

- 后端改动最少

缺点：

- 准确率口径无法统一
- 不同调用方可能出现不同计算方式
- 核验单自动关闭缺少接口级保证

### Option B: 扩展摘要字段，并把“correct 自动关闭核验单”固化为正式行为

做法：

- `summary` 新增 `recognition_accuracy`
- 保持现有 `history/feedback` 入口不变
- 将“用户反馈改为 `correct` 时自动关闭 active 核验单”作为显式业务规则保留
- 用测试锁定该规则

优点：

- 改动小
- 不新增接口
- 风险最低
- 对外 contract 更清晰

缺点：

- 核验单状态变化仍通过现有反馈接口间接触发，不是单独动作

### Option C: 新增独立接口专门处理“用户修正关闭核验单”

做法：

- 新增一条专用接口用于关闭核验单
- 历史反馈和核验单流转拆成两个动作

优点：

- 语义最显式

缺点：

- 增加前端联调成本
- 会把一个本应原子化的业务动作拆开
- 不符合当前系统已有反馈流

## Recommendation

采用 Option B。

理由：

- 用户要求的是现有业务上的收口优化，不是新流程
- 现有 `history/feedback` 已经是唯一用户反馈入口，继续沿用最稳妥
- 识别准确率属于标准摘要口径，应该由后端统一输出

## API Design

## 1. `POST /railway/parts/v2/search/history/summary`

### Response Change

在现有 `data` 对象中新增：

- `recognition_accuracy`

返回示例：

```json
{
  "data": {
    "total": 93,
    "pending_count": 72,
    "correct_count": 12,
    "wrong_count": 5,
    "user_misjudged_count": 4,
    "open_ticket_count": 9,
    "recognition_accuracy": 0.7058823529
  },
  "datetime": 1778656383824,
  "requestID": "d55e23d7-c283-4607-bce5-bbc47cca20ac",
  "status": "success"
}
```

### Calculation Rule

固定公式：

`recognition_accuracy = correct_count / (correct_count + wrong_count)`

边界规则：

- 当 `correct_count + wrong_count == 0` 时，返回 `0`
- 不返回 `null`
- 不将 `pending_count` 和 `user_misjudged_count` 计入分母

### Reasoning

该指标表达的是“已形成明确正确/错误判断的识别结果中，正确结果占比”，不应把待校验和用户误判混入准确率分母。

## 2. `POST /railway/parts/v2/search/history/feedback`

### Request Contract

本次不改请求结构，继续使用现有参数：

- `history_id`
- `feedback_result`
- `remark`
- `selected_item_id`

### Business Rule Change

将以下规则显式固化为正式 contract：

- 当 `feedback_result == "wrong"` 时：
  - 若该历史记录没有未关闭核验单，则新建核验单
  - 若已有未关闭核验单，则复用已有核验单

- 当 `feedback_result == "correct"` 时：
  - 更新该条历史记录的反馈状态为 `correct`
  - 若该历史记录存在未关闭核验单，则自动关闭该核验单

### Auto-Close Rule

自动关闭核验单时，更新字段如下：

- `review_status = "closed"`
- `closed_at = 当前反馈时间`
- `resolved_at = 当前反馈时间`，若此前为空
- `resolution_remark` 保留原值；若此前为空，则写入：
  - `用户反馈改为正确，自动关闭核验单`

### Public Effect

这样当用户在历史列表中把一条原本进入核验清单的记录改为 `correct` 后：

- 历史列表会显示其状态为 `correct`
- 核验单列表中的对应记录会变为“已关闭”

不需要前端再额外调用关闭核验单接口。

## Data Flow

### 场景一：用户首次反馈错误

1. 用户调用 `history/feedback`，提交 `feedback_result = wrong`
2. 系统更新 `search_history.verify_status = wrong`
3. 系统查询该历史记录是否已有未关闭核验单
4. 若没有，则创建一张新的 `search_review_ticket`
5. 该记录在公共历史列表中按既有规则展示为 `pending`
6. 该记录进入技术部核验清单

### 场景二：用户后续修正为正确

1. 用户调用 `history/feedback`，提交 `feedback_result = correct`
2. 系统更新 `search_history.verify_status = correct`
3. 系统查询该历史记录是否存在未关闭核验单
4. 若存在，则将该核验单更新为 `closed`
5. 历史列表显示 `correct`
6. 核验单列表显示“已关闭”

## Data Model Impact

本次不新增表字段，不新增表结构迁移。

影响范围仅包括：

- `SearchHistorySummaryRes` 增加一个响应字段
- `RailwayPartsManager.summary_v2_search_history` 增加准确率计算
- `RailwayPartsManager.submit_v2_search_feedback` 的自动关闭行为作为正式契约被保留并测试化

## Testing Strategy

新增或补强以下测试：

### 1. Summary Response Tests

- `summary` 返回中包含 `recognition_accuracy`
- 当 `correct_count = 12`、`wrong_count = 5` 时，准确率等于 `12 / 17`
- 当 `correct_count = 0` 且 `wrong_count = 0` 时，准确率返回 `0`

### 2. Feedback-to-Ticket Close Tests

- 当一条历史记录已有 active 核验单时，提交 `feedback_result = correct` 后：
  - `review_status` 更新为 `closed`
  - `closed_at` 被写入
  - `resolved_at` 在为空时被补齐
  - `resolution_remark` 在为空时写入默认关闭文案

### 3. Regression Tests

- `feedback_result = wrong` 时仍然保持现有建单/复用单逻辑
- 历史摘要现有字段保持兼容
- 不改变 `history/list` 现有公共状态映射：
  - `correct` 仍显示为 `correct`
  - `wrong` / `user_misjudged` 仍按既有规则对外展示为 `pending`

## Risks

### 1. 前端误解“识别准确率”含义

风险：

- 有人可能误以为分母是 `total`

控制方式：

- 在 spec、接口模型和联调说明中明确公式是：
  - `correct_count / (correct_count + wrong_count)`

### 2. 历史列表状态与数据库原始状态容易混淆

风险：

- 数据库里 `wrong` 与对外列表里的 `pending` 不是同一概念层

控制方式：

- 保持现有公共映射规则不变
- 将“关闭核验单”与“历史对外状态展示”作为两条独立规则分别测试

### 3. 后续改动可能破坏自动关闭行为

风险：

- 如果有人只关注历史反馈字段，可能忽略核验单联动

控制方式：

- 用单元测试显式锁定 `correct -> close active ticket` 的行为

## Success Criteria

满足以下条件即视为完成：

- `summary` 接口稳定返回 `recognition_accuracy`
- 当没有明确 correct/wrong 样本时，准确率返回 `0`
- 用户把历史反馈修正为 `correct` 后，对应 active 核验单自动变为 `closed`
- 不新增前端调用步骤，不破坏现有 V2 历史与核验单接口结构
