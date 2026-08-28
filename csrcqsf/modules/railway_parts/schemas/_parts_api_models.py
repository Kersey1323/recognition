from pydantic import BaseModel
from bfrcommon.api_models import PageReq, PageRes
from pydantic import Field, validator

from csrcqsf.models.orm.search_history import MatchedImage, SearchParameters, SearchResults
from csrcqsf.modules.sgo.schemas import ImageSourceType


class CreateItemReq(BaseModel):
    item_name: str
    obj_url: str | None
    item_code: str
    height: float | None
    length: float | None
    width: float | None
    weight: float | None = None
    parent_item_id: str | None = None

    @validator("parent_item_id", pre=True, allow_reuse=True)
    def normalize_parent_item_id(cls, value):
        if value in ("", None):
            return None
        return str(value)


class ListItemReq(PageReq):
    query: str | None = Field(default=None, description='搜索关键词', example="司机室")
    item_code: str | None = Field(default=None, description='配件编码精确筛选', example="12312321")
    parent_item_id: str | None = Field(default=None, description='父配件ID', example=None)
    only_has_index: int = Field(description='只查看有索引的配件.1 为是 0为否', default=0, example=0)
    has_inquery_code: int = Field(description='只查看有询码记录的配件.1为是 0为否', default=0, example=0)
    has_images: int = Field(description='只查看有图片的配件.1 为是 0为否', default=0, example=0)
    has_source_video: int = Field(description='原视频筛选.0未上传 1已上传 2不筛选', default=2, example=2)

    class Config:
        json_schema_extra = {
            "example": {
                "page": 1,
                "pageSize": 20,
                "query": "司机室",
                "item_code": "12312321",
                "parent_item_id": None,
                "only_has_index": 0,
                "has_inquery_code": 0,
                "has_images": 0,
                "has_source_video": 2,
            }
        }


class ListItem(BaseModel):
    item_name: str
    ply_url: str | None
    item_code: str
    height: float | None
    length: float | None
    width: float | None
    weight: float | None
    video_path: str | None
    created_at: str
    has_index: int = Field(default=0, description='为1时表示已具备完整V2索引')
    has_source_video: int = Field(default=0, description='为1时表示已上传原视频')
    features: list[str] = Field(default=[], description='文字特征')
    features_num: int = 0
    images_total_num: int = Field(description='图片总数', default=0)
    images_total_indexed_num: int = Field(description='图片已索引的总数', default=0)
    images_url: list[str] = Field(default_factory=list, description='该配件的全部图片地址')
    inquiry_nums: list[str] = Field(default_factory=list, description='该配件的全部询码流水号，按时间从新到旧排列')
    inquiry_count: int = Field(default=0, description='该配件关联的询码记录总数')
    id: str


class LisItemRes(PageRes):
    items: list[ListItem] = []


class DeleteItemReq(BaseModel):
    item_id_list: list[str]


class DeleteItemImageReq(BaseModel):
    item_id: str = Field(description="配件ID", example="1980083913525903360")
    image_id: str = Field(description="图片ID", example="1981662795271376896")
    delete_reason: str | None = Field(default=None, description="删除原因")

    @validator("item_id", "image_id", pre=True, allow_reuse=True)
    def normalize_id(cls, value):
        return str(value)


class DeleteItemImageRes(BaseModel):
    item_id: str
    image_id: str
    image_url: str | None
    db_deleted: bool
    minio_deleted: bool
    milvus_deleted: bool
    milvus_delete_count: int = 0
    message: str


class UpdateItemReq(BaseModel):
    id: str
    height: float | None = None
    length: float | None = None
    width: float | None = None
    weight: float | None = None
    item_name: str | None = None
    item_code: str | None = None
    parent_item_id: str | None = None

    @validator("parent_item_id", pre=True, allow_reuse=True)
    def normalize_parent_item_id(cls, value):
        if value in ("", None):
            return None
        return str(value)

    class Config:
        extra = "forbid"


class ItemImageIndexInfo(BaseModel):
    image_id: str
    image_url: str


class ItemImageItem(BaseModel):
    image_id: str
    has_indexed: int = Field(default=0, description='为1时已经进行过索引，其他为未索引')
    image_url: str | None
    source_type: ImageSourceType = None


class ListItemImagesReq(BaseModel):
    item_id: str = Field(description='配件ID', example="1557988408477880320")

    class Config:
        json_schema_extra = {
            "example": {
                "item_id": "1557988408477880320"
            }
        }


class ListItemImageItem(BaseModel):
    image_id: str = ''
    has_indexed: int = Field(default=0, description='是否已经加入配件的索引库，1为已索引 2为未索引')
    image_url: str = ''
    image_source_type: ImageSourceType | None = Field(
        description='来自SGO系统的图片来源，分别为询码记录和基本信息'
    )


class ListItemImagesRes(BaseModel):
    items: list[ListItemImageItem] = []


class GetItemDetailReq(BaseModel):
    item_id: str = Field(description='配件ID', example="2023080809420000001")

    class Config:
        json_schema_extra = {
            "example": {
                "item_id": "2023080809420000001"
            }
        }


class GetItemDetailRes(BaseModel):
    ply_url: str | None
    height: float | None
    length: float | None
    width: float | None
    weight: float | None
    video_path: str | None
    name: str
    item_code: str
    id: str
    created_at: str
    updated_at: str
    images: list[ItemImageItem] = []
    images_index_list: list[ItemImageIndexInfo] | None = []
    parent_item_name: str | None
    parent_item_code: str | None
    parent_item_id: str | None
    size_str: str | None
    features: list[str] = []


class CreateItemImagesReq(BaseModel):
    item_id: str
    images_url: list[str] = Field(default_factory=list)


class CreateItemImageRecord(BaseModel):
    image_id: str
    image_url: str
    filename: str

    @validator("image_id", pre=True, allow_reuse=True)
    def normalize_image_id(cls, value):
        return str(value)


class CreateItemImagesRes(BaseModel):
    item_id: str
    uploaded_count: int = 0
    records: list[CreateItemImageRecord] = Field(default_factory=list)
    message: str
    auto_index_pending: bool = Field(
        False,
        description="本次是否新增了等待自动索引的自主采集图片",
    )

    @validator("item_id", pre=True, allow_reuse=True)
    def normalize_item_id(cls, value):
        return str(value)


class UpdateItemSizeStr(BaseModel):
    item_id: str
    item_size_desc: str


class SearchTextReq(BaseModel):
    query_text: str = Field(
        description="自然语言配件描述，将与历史询码中的名称描述进行语义匹配",
        example="监控室对面窗帘",
    )
    top_k: int = Field(
        default=10,
        description="最终返回的配件数量",
        example=5,
        ge=1,
        le=100,
    )
    search_equipment: str = Field(
        default="web",
        description="检索来源，支持 `web`、`terminal`",
        example="web",
    )

    class Config:
        schema_extra = {
            "example": {
                "query_text": "监控室对面窗帘",
                "top_k": 5,
                "search_equipment": "web",
            }
        }


class SearchItem(BaseModel):
    item_id: str = 0
    item_code: str = ''
    item_name: str = ''
    image_url: str = ''
    rate: float = 0
    matched_images: list[MatchedImage] = []
    matched_description: str | None = Field(
        None,
        description="文本检索命中的历史询码名称描述；图片检索为空",
    )
    matched_inquiry_id: str | None = Field(
        None,
        description="命中描述对应的询码记录 ID；图片检索为空",
    )


class SearchRes(BaseModel):
    history_id: str | None = None
    data: list[SearchItem] = []
    message: str | None


class ContextualSearchSnapshotRes(BaseModel):
    query_images: list[str] = Field(default_factory=list)
    parameters: SearchParameters
    searched_at: str
    data: list[SearchItem] = Field(default_factory=list)


class ContextualSearchRes(BaseModel):
    history_id: str
    previous: ContextualSearchSnapshotRes | None = None
    current: ContextualSearchSnapshotRes
    message: str | None = None

    @validator("history_id", pre=True, allow_reuse=True)
    def normalize_contextual_history_id(cls, value):
        return str(value)


class SearchHistoryListReq(PageReq):
    page: int = Field(description="页码，从1开始", example=1, ge=0)
    per_page: int = Field(description="每页数量", example=10, ge=0, alias='pageSize')
    search_type: str = Field(
        default="all",
        description="检索类型筛选：all 全部，text 文本检索，image 图片检索",
        example="image",
    )
    search_equipment: str = Field(
        default="all",
        description="检索设备筛选：all 全部，web WEB端，terminal 手持终端",
        example="terminal",
    )
    keyword: str | None = Field(
        default=None,
        description="关键词筛选，会匹配查询文本、检索结果物料编码/名称、人工纠正物料编码",
        example="19010036737",
    )
    status: str = Field(
        default="all",
        description="校验状态筛选：all 全部，pending 待校验，correct 正确，wrong 错误，user_misjudged 用户误判",
        example="pending",
    )
    date_from: str | None = Field(
        default=None,
        description="开始日期，格式 YYYY-MM-DD",
        example="2026-04-27",
    )
    date_to: str | None = Field(
        default=None,
        description="结束日期，格式 YYYY-MM-DD",
        example="2026-04-28",
    )

    class Config:
        schema_extra = {
            "example": {
                "page": 1,
                "pageSize": 10,
                "search_type": "image",
                "search_equipment": "terminal",
                "keyword": "19010036737",
                "status": "pending",
                "date_from": "2026-04-27",
                "date_to": "2026-04-28",
            }
        }


class SearchHistoryListItem(BaseModel):
    history_id: str
    search_type: str
    time_created: str
    query_text: str | None = None
    query_image: str | None = None
    query_images: list[str] = Field(default_factory=list)
    search_parameter: SearchParameters | None = None
    previous_query_images: list[str] = Field(default_factory=list)
    previous_search_parameter: SearchParameters | None = None
    previous_result: SearchResults | None = None
    previous_searched_at: str | None = None
    search_revision: int = 0
    status: str = "pending"
    result: SearchResults | None
    inquery_id: str | None
    inquery_num: str | None
    search_item_name: str | None
    search_item_code: str | None
    correct_item_id: str | None = None
    correct_item_name: str | None
    correct_item_code: str | None
    correct_image_url: str | None = None
    correct_rank: int | None = None
    correct_source: str | None = None
    ranking_feedback_type: str | None = None
    verify_remark: str | None = None
    verified_at: str | None = None
    search_equipment: str | None = None
    feedback_remark: str | None = None
    feedback_at: str | None = None
    has_open_review_ticket: bool = False
    latest_ticket_id: str | None = None
    latest_review_status: str | None = None
    latest_issue_type: str | None = None

    @validator("history_id", pre=True, allow_reuse=True)
    def normalize_history_id(cls, value):
        return str(value)

    @validator("correct_item_id", pre=True, allow_reuse=True)
    def normalize_optional_item_id(cls, value):
        if value is None:
            return None
        return str(value)

    @validator("status", pre=True, allow_reuse=True)
    def normalize_public_status(cls, value):
        if value == "correct":
            return "correct"
        if value == "wrong":
            return "wrong"
        return "pending"

    @validator("verify_remark", "feedback_remark", pre=True, allow_reuse=True)
    def normalize_nullable_remark(cls, value):
        if value is None:
            return None
        if isinstance(value, str) and value.strip().lower() == "null":
            return None
        return value


class SearchHistoryListRes(BaseModel):
    total: int = Field(..., description="总数")
    page: int = Field(..., description="当前页码")
    pageSize: int = Field(..., description="每页数量")
    items: list[SearchHistoryListItem] = Field(default_factory=list)


class SearchHistoryDetailReq(BaseModel):
    history_id: str = Field(description="检索历史ID", example="2048696242753638400")

    @validator("history_id", pre=True, allow_reuse=True)
    def normalize_history_id(cls, value):
        return str(value)

    class Config:
        schema_extra = {
            "example": {
                "history_id": "2048696242753638400",
            }
        }


class SearchHistoryVerifyReq(BaseModel):
    history_id: str = Field(description="检索历史ID", example="2048696242753638400")
    verify_status: str = Field(
        description="校验结果：correct 正确，wrong 错误，user_misjudged 用户误判，partial 部分正确（兼容旧值）",
        example="correct",
    )
    correct_item_code: str | None = Field(
        default=None,
        description="人工确认后的正确物料编码。verify_status=correct 且不传时，默认回填首条检索结果编码",
        example="19010036737",
    )
    remark: str | None = Field(
        default=None,
        description="人工校验备注",
        example="人工确认正确",
    )

    @validator("history_id", pre=True, allow_reuse=True)
    def normalize_history_id(cls, value):
        return str(value)

    class Config:
        schema_extra = {
            "example": {
                "history_id": "2048696242753638400",
                "verify_status": "correct",
                "correct_item_code": "19010036737",
                "remark": "人工确认正确",
            }
        }


class SearchHistoryVerifyRes(BaseModel):
    history_id: str
    status: str
    correct_item_id: str | None = None
    correct_item_code: str | None = None
    correct_item_name: str | None = None
    correct_image_url: str | None = None
    correct_rank: int | None = None
    correct_source: str | None = None
    verify_remark: str | None = None
    verified_at: str | None = None
    message: str

    @validator("history_id", pre=True, allow_reuse=True)
    def normalize_history_id(cls, value):
        return str(value)

    @validator("correct_item_id", pre=True, allow_reuse=True)
    def normalize_correct_item_id(cls, value):
        if value is None:
            return None
        return str(value)


class SearchHistorySummaryRes(BaseModel):
    total: int
    pending_count: int
    correct_count: int
    wrong_count: int
    user_misjudged_count: int
    open_ticket_count: int
    recognition_accuracy: float


class SearchHistoryFeedbackReq(BaseModel):
    history_id: str = Field(description="检索历史ID", example="2048696242753638400")
    feedback_result: str = Field(
        description="用户反馈结果：correct 正确，wrong 错误",
        example="wrong",
    )
    remark: str | None = Field(
        default=None,
        description="反馈备注",
        example="识别错误，建议技术部核验",
    )
    selected_item_id: str | None = Field(
        default=None,
        description="用户最终确认正确的配件ID",
        example="1950361513125318656",
    )

    @validator("history_id", pre=True, allow_reuse=True)
    def normalize_history_id(cls, value):
        return str(value)

    class Config:
        schema_extra = {
            "example": {
                "history_id": "2048696242753638400",
                "feedback_result": "wrong",
                "remark": "识别错误，建议技术部核验",
            }
        }


class SearchHistoryFeedbackRes(BaseModel):
    history_id: str
    verify_status: str
    ranking_feedback_type: str | None = None
    feedback_remark: str | None = None
    feedback_at: str | None = None
    correct_item_id: str | None = None
    correct_item_code: str | None = None
    correct_item_name: str | None = None
    correct_image_url: str | None = None
    correct_rank: int | None = None
    correct_source: str | None = None
    ticket_id: str | None = None
    ticket_created: bool = False
    message: str

    @validator("history_id", pre=True, allow_reuse=True)
    def normalize_history_id(cls, value):
        return str(value)

    @validator("ticket_id", pre=True, allow_reuse=True)
    def normalize_ticket_id(cls, value):
        if value is None:
            return None
        return str(value)

    @validator("correct_item_id", pre=True, allow_reuse=True)
    def normalize_optional_item_id(cls, value):
        if value is None:
            return None
        return str(value)


class SearchReviewTicketListReq(PageReq):
    page: int = Field(description="页码，从1开始", example=1, ge=0)
    per_page: int = Field(description="每页数量", example=10, ge=0, alias='pageSize')
    review_status: str = Field(
        default="all",
        description="核验单状态筛选：all 默认全部（不含 deleted），open 新建，reviewing 核验中，resolved 已解决，closed 已关闭，deleted 已移出清单",
        example="open",
    )
    issue_type: str = Field(
        default="all",
        description="问题类型筛选：all 全部，missing_index 未建索引，precision_issue 精度问题，system_bug 系统问题，user_misjudged 用户误判",
        example="precision_issue",
    )
    search_equipment: str = Field(
        default="all",
        description="检索设备筛选：all 全部，web WEB端，terminal 手持终端",
        example="terminal",
    )
    keyword: str | None = Field(
        default=None,
        description="关键词筛选，支持 history_id/ticket_id/物料编码/物料名称",
        example="19010036737",
    )
    date_from: str | None = Field(
        default=None,
        description="开始日期，格式 YYYY-MM-DD",
        example="2026-04-27",
    )
    date_to: str | None = Field(
        default=None,
        description="结束日期，格式 YYYY-MM-DD",
        example="2026-04-28",
    )


class SearchReviewTicketItem(BaseModel):
    ticket_id: str
    history_id: str
    review_status: str
    issue_type: str | None = None
    time_created: str
    time_updated: str
    search_type: str | None = None
    query_text: str | None = None
    query_image: str | None = None
    query_images: list[str] = Field(default_factory=list)
    search_equipment: str | None = None
    search_item_name: str | None = None
    search_item_code: str | None = None
    feedback_remark: str | None = None
    correct_item_id: str | None = None
    correct_item_name: str | None = None
    correct_item_code: str | None = None
    correct_image_url: str | None = None
    correct_rank: int | None = None
    correct_source: str | None = None

    @validator("ticket_id", pre=True, allow_reuse=True)
    def normalize_ticket_id(cls, value):
        return str(value)

    @validator("history_id", pre=True, allow_reuse=True)
    def normalize_history_id(cls, value):
        return str(value)

    @validator("correct_item_id", pre=True, allow_reuse=True)
    def normalize_correct_item_id(cls, value):
        if value is None:
            return None
        return str(value)

    @validator("feedback_remark", pre=True, allow_reuse=True)
    def normalize_feedback_remark(cls, value):
        if value is None:
            return None
        if isinstance(value, str) and value.strip().lower() == "null":
            return None
        return value


class SearchReviewTicketListRes(BaseModel):
    total: int = Field(..., description="总数")
    page: int = Field(..., description="当前页码")
    pageSize: int = Field(..., description="每页数量")
    items: list[SearchReviewTicketItem] = Field(default_factory=list)


class SearchReviewTicketDetailReq(BaseModel):
    ticket_id: str = Field(description="核验单ID", example="2048696242753638400")

    @validator("ticket_id", pre=True, allow_reuse=True)
    def normalize_ticket_id(cls, value):
        return str(value)


class SearchReviewTicketDetailRes(BaseModel):
    ticket_id: str
    history_id: str
    review_status: str
    issue_type: str | None = None
    time_created: str | None = None
    time_updated: str | None = None
    review_remark: str | None = None
    resolution_remark: str | None = None
    review_started_at: str | None = None
    resolved_at: str | None = None
    closed_at: str | None = None
    search_type: str | None = None
    query_text: str | None = None
    query_image: str | None = None
    query_images: list[str] = Field(default_factory=list)
    search_equipment: str | None = None
    result: SearchResults | None = None
    search_item_name: str | None = None
    search_item_code: str | None = None
    feedback_remark: str | None = None
    correct_item_id: str | None = None
    correct_item_name: str | None = None
    correct_item_code: str | None = None
    correct_image_url: str | None = None
    correct_rank: int | None = None
    correct_source: str | None = None

    @validator("ticket_id", pre=True, allow_reuse=True)
    def normalize_ticket_id(cls, value):
        return str(value)

    @validator("history_id", pre=True, allow_reuse=True)
    def normalize_history_id(cls, value):
        return str(value)

    @validator("correct_item_id", pre=True, allow_reuse=True)
    def normalize_correct_item_id(cls, value):
        if value is None:
            return None
        return str(value)

    @validator("feedback_remark", pre=True, allow_reuse=True)
    def normalize_feedback_remark(cls, value):
        if value is None:
            return None
        if isinstance(value, str) and value.strip().lower() == "null":
            return None
        return value


class SearchReviewTicketUpdateReq(BaseModel):
    ticket_id: str = Field(description="核验单ID", example="2048696242753638400")
    review_status: str = Field(
        description="核验单状态：reviewing 核验中，resolved 已解决，closed 已关闭",
        example="resolved",
    )
    issue_type: str | None = Field(
        default=None,
        description="问题类型：missing_index 未建索引，precision_issue 精度问题，system_bug 系统问题，user_misjudged 用户误判",
        example="precision_issue",
    )
    review_remark: str | None = Field(default=None, description="核验备注", example="已接单核验")
    resolution_remark: str | None = Field(default=None, description="解决备注", example="已修复")
    correct_item_code: str | None = Field(default=None, description="纠正后的物料编码", example="19010036737")

    @validator("ticket_id", pre=True, allow_reuse=True)
    def normalize_ticket_id(cls, value):
        return str(value)


class SearchReviewTicketUpdateRes(BaseModel):
    ticket_id: str
    review_status: str
    verify_status: str | None = None
    issue_type: str | None = None
    review_remark: str | None = None
    resolution_remark: str | None = None
    correct_item_id: str | None = None
    correct_item_code: str | None = None
    correct_item_name: str | None = None
    correct_image_url: str | None = None
    correct_rank: int | None = None
    correct_source: str | None = None
    message: str

    @validator("ticket_id", pre=True, allow_reuse=True)
    def normalize_ticket_id(cls, value):
        return str(value)

    @validator("correct_item_id", pre=True, allow_reuse=True)
    def normalize_correct_item_id(cls, value):
        if value is None:
            return None
        return str(value)


class SearchReviewTicketDeleteReq(BaseModel):
    ticket_id_list: list[str] = Field(
        description="待移出校验清单的核验单ID列表",
        example=["2048696242753638400", "2048696242753638401"],
        min_items=1,
    )
    delete_remark: str | None = Field(
        default=None,
        description="移出清单备注",
        example="前端手动移出校验清单",
    )

    class Config:
        schema_extra = {
            "example": {
                "ticket_id_list": ["2048696242753638400", "2048696242753638401"],
                "delete_remark": "前端手动移出校验清单",
            }
        }


class SearchReviewTicketDeleteRes(BaseModel):
    deleted_count: int
    message: str


class SearchReviewTicketSummaryRes(BaseModel):
    total: int
    open_count: int
    reviewing_count: int
    resolved_count: int
    closed_count: int
    missing_index_count: int
    precision_issue_count: int
    system_bug_count: int
    user_misjudged_count: int


class ItemSuggestReq(BaseModel):
    keyword: str = Field(
        description="联想关键词，可输入物料编码或物料名称片段",
        example="1901",
    )
    limit: int = Field(
        default=10,
        description="最多返回的联想条数",
        example=10,
    )

    class Config:
        schema_extra = {
            "example": {
                "keyword": "1901",
                "limit": 10,
            }
        }


class ItemSuggestItem(BaseModel):
    item_id: str
    item_code: str
    item_name: str

    @validator("item_id", pre=True, allow_reuse=True)
    def normalize_item_id(cls, value):
        return str(value)


class ItemSuggestRes(BaseModel):
    items: list[ItemSuggestItem] = Field(default_factory=list)


class SearchHistoryDeleteReq(BaseModel):
    history_id_list: list[str] = Field(
        description="待删除的检索历史ID列表",
        example=["2048696242753638400", "2048696242753638401"],
    )

    class Config:
        schema_extra = {
            "example": {
                "history_id_list": ["2048696242753638400", "2048696242753638401"],
            }
        }


class SearchHistoryDeleteRes(BaseModel):
    deleted_count: int
    message: str


class V2IndexDeleteRes(BaseModel):
    item_id: str = Field(..., description="配件ID，字符串返回以避免前端精度丢失")
    siglip_deleted: int = Field(default=0, description="删除的 SigLIP 记录数")
    dinov2_deleted: int = Field(default=0, description="删除的 DINOv2 记录数")
    message: str = Field(..., description="消息")

    @validator("item_id", pre=True, allow_reuse=True)
    def normalize_item_id(cls, value):
        return str(value)


class IndexStatisticsRes(BaseModel):
    total_item_num: int = Field(default=0, description='配件总数')
    total_indexed_item_num: int = Field(default=0, description='V2中同时存在SigLIP和DINOv2索引的配件数')
    total_index: int = Field(default=0, description='V2索引总数')
    total_image_index: int = Field(default=0, description='SigLIP collection记录数')
    total_feature_index: int = Field(default=0, description='DINOv2 collection记录数')
    recognition_number: int = Field(default=0, description='已废弃字段，固定返回0')
    corrrect_recognition_number: int = Field(default=0, description='已废弃字段，固定返回0')
    recognition_ration: float = Field(default=0, description='已废弃字段，固定返回0')


class IndexStatisticsReq(BaseModel):
    pass
