from typing import Optional
import datetime
import decimal

from sqlalchemy import BigInteger, Computed, DECIMAL, Date, DateTime, Double, ForeignKeyConstraint, Index, Integer, SmallInteger, String, TIMESTAMP, cast, select, text
from sqlalchemy.dialects.mysql import CHAR, LONGBLOB, LONGTEXT, TEXT, TINYINT, VARCHAR
from sqlalchemy.orm import DeclarativeBase, Mapped, load_only, mapped_column, relationship
from sqlalchemy.ext.asyncio import AsyncSession
from bfrcommon.db import PageQueryResult, async_get_count


class Base(DeclarativeBase):
    pass


class ActEvtLog(Base):
    __tablename__ = 'act_evt_log'
    __table_args__ = {'comment': '事件日志表'}

    LOG_NR_: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, comment='主键')
    TIME_STAMP_: Mapped[datetime.datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=text(
        'CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP'), comment='时间')
    TYPE_: Mapped[Optional[str]] = mapped_column(VARCHAR(64), comment='类型')
    PROC_DEF_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='流程定义')
    PROC_INST_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='流程实例')
    EXECUTION_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='执行')
    TASK_ID_: Mapped[Optional[str]] = mapped_column(VARCHAR(64), comment='任务')
    USER_ID_: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='用户')
    DATA_: Mapped[Optional[bytes]] = mapped_column(LONGBLOB, comment='内容')
    LOCK_OWNER_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='锁定节点')
    LOCK_TIME_: Mapped[Optional[datetime.datetime]
                       ] = mapped_column(TIMESTAMP, comment='锁定时间')
    IS_PROCESSED_: Mapped[Optional[int]] = mapped_column(
        TINYINT, server_default=text("'0'"), comment='是否正在执行')


class ActGeProperty(Base):
    __tablename__ = 'act_ge_property'
    __table_args__ = {'comment': '全局参数表'}

    NAME_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    VALUE_: Mapped[Optional[str]] = mapped_column(VARCHAR(300), comment='参数值')
    REV_: Mapped[Optional[int]] = mapped_column(Integer, comment='乐观锁')


class ActHiActinst(Base):
    __tablename__ = 'act_hi_actinst'
    __table_args__ = (
        Index('ACT_IDX_HI_ACT_INST_END', 'END_TIME_'),
        Index('ACT_IDX_HI_ACT_INST_EXEC', 'EXECUTION_ID_', 'ACT_ID_'),
        Index('ACT_IDX_HI_ACT_INST_PROCINST', 'PROC_INST_ID_', 'ACT_ID_'),
        Index('ACT_IDX_HI_ACT_INST_START', 'START_TIME_'),
        {'comment': '环节历史信息'}
    )

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    PROC_DEF_ID_: Mapped[str] = mapped_column(
        VARCHAR(64), nullable=False, comment='流程定义')
    PROC_INST_ID_: Mapped[str] = mapped_column(
        VARCHAR(64), nullable=False, comment='流程实例')
    EXECUTION_ID_: Mapped[str] = mapped_column(
        VARCHAR(64), nullable=False, comment='执行')
    ACT_ID_: Mapped[str] = mapped_column(
        VARCHAR(255), nullable=False, comment='环节ID')
    ACT_TYPE_: Mapped[str] = mapped_column(
        VARCHAR(255), nullable=False, comment='环节类型')
    START_TIME_: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, comment='开始时间')
    TASK_ID_: Mapped[Optional[str]] = mapped_column(VARCHAR(64), comment='任务')
    CALL_PROC_INST_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='父流程实例')
    ACT_NAME_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='环节名称')
    ASSIGNEE_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='负责人')
    END_TIME_: Mapped[Optional[datetime.datetime]
                      ] = mapped_column(DateTime, comment='结束时间')
    DURATION_: Mapped[Optional[int]] = mapped_column(
        BigInteger, comment='持续时间')
    TENANT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), server_default=text("''"), comment='多租户')


class ActHiAttachment(Base):
    __tablename__ = 'act_hi_attachment'
    __table_args__ = {'comment': '附件'}

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    REV_: Mapped[Optional[int]] = mapped_column(Integer, comment='乐观锁')
    USER_ID_: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='用户')
    NAME_: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='名称')
    DESCRIPTION_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(4000), comment='描述')
    TYPE_: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='类型')
    TASK_ID_: Mapped[Optional[str]] = mapped_column(VARCHAR(64), comment='任务')
    PROC_INST_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='流程实例')
    URL_: Mapped[Optional[str]] = mapped_column(VARCHAR(4000), comment='URL')
    CONTENT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='内容ACT_GE_BYTEARRAY')
    TIME_: Mapped[Optional[datetime.datetime]
                  ] = mapped_column(DateTime, comment='时间')


class ActHiComment(Base):
    __tablename__ = 'act_hi_comment'
    __table_args__ = {'comment': '评论'}

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    TIME_: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, comment='时间')
    TYPE_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='类型，默认有event,comment理解成操作和评论')
    USER_ID_: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='用户')
    TASK_ID_: Mapped[Optional[str]] = mapped_column(VARCHAR(64), comment='任务')
    PROC_INST_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='流程实例')
    ACTION_: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='操作')
    MESSAGE_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(4000), comment='消息')
    FULL_MSG_: Mapped[Optional[bytes]] = mapped_column(
        LONGBLOB, comment='完整消息')


class ActHiDetail(Base):
    __tablename__ = 'act_hi_detail'
    __table_args__ = (
        Index('ACT_IDX_HI_DETAIL_ACT_INST', 'ACT_INST_ID_'),
        Index('ACT_IDX_HI_DETAIL_NAME', 'NAME_'),
        Index('ACT_IDX_HI_DETAIL_PROC_INST', 'PROC_INST_ID_'),
        Index('ACT_IDX_HI_DETAIL_TASK_ID', 'TASK_ID_'),
        Index('ACT_IDX_HI_DETAIL_TIME', 'TIME_'),
        {'comment': '历史详情信息'}
    )

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    TYPE_: Mapped[str] = mapped_column(
        VARCHAR(255), nullable=False, comment='类型FormProperty,VariableUpadte')
    NAME_: Mapped[str] = mapped_column(
        VARCHAR(255), nullable=False, comment='名称')
    TIME_: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, comment='时间')
    PROC_INST_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='流程实例')
    EXECUTION_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='执行')
    TASK_ID_: Mapped[Optional[str]] = mapped_column(VARCHAR(64), comment='任务')
    ACT_INST_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='环节ID')
    VAR_TYPE_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='变量类型')
    REV_: Mapped[Optional[int]] = mapped_column(Integer, comment='乐观锁')
    BYTEARRAY_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='内容ACT_GE_BYTEARRAY')
    DOUBLE_: Mapped[Optional[decimal.Decimal]] = mapped_column(
        Double(asdecimal=True), comment='浮点值')
    LONG_: Mapped[Optional[int]] = mapped_column(BigInteger, comment='长整型值')
    TEXT_: Mapped[Optional[str]] = mapped_column(VARCHAR(4000), comment='文本值')
    TEXT2_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(4000), comment='jpa变量text存classame,text2存id')


class ActHiIdentitylink(Base):
    __tablename__ = 'act_hi_identitylink'
    __table_args__ = (
        Index('ACT_IDX_HI_IDENT_LNK_PROCINST', 'PROC_INST_ID_'),
        Index('ACT_IDX_HI_IDENT_LNK_TASK', 'TASK_ID_'),
        Index('ACT_IDX_HI_IDENT_LNK_USER', 'USER_ID_'),
        {'comment': '参与者历史'}
    )

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    GROUP_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='群组')
    TYPE_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='类型：assignee,candidate,owner,starter,participant')
    USER_ID_: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='用户')
    TASK_ID_: Mapped[Optional[str]] = mapped_column(VARCHAR(64), comment='任务')
    PROC_INST_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='流程实例')


class ActHiProcinst(Base):
    __tablename__ = 'act_hi_procinst'
    __table_args__ = (
        Index('ACT_IDX_HI_PRO_INST_END', 'END_TIME_'),
        Index('ACT_IDX_HI_PRO_I_BUSKEY', 'BUSINESS_KEY_'),
        Index('PROC_INST_ID_', 'PROC_INST_ID_', unique=True),
        {'comment': '流程实例历史'}
    )

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    PROC_INST_ID_: Mapped[str] = mapped_column(
        VARCHAR(64), nullable=False, comment='流程实例')
    PROC_DEF_ID_: Mapped[str] = mapped_column(
        VARCHAR(64), nullable=False, comment='流程定义')
    START_TIME_: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, comment='开始时间')
    BUSINESS_KEY_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='业务标识')
    END_TIME_: Mapped[Optional[datetime.datetime]
                      ] = mapped_column(DateTime, comment='结束时间')
    DURATION_: Mapped[Optional[int]] = mapped_column(
        BigInteger, comment='持续时间')
    START_USER_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='流程发起人')
    START_ACT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='开始环节ID')
    END_ACT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='结束环节ID')
    SUPER_PROCESS_INSTANCE_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='父流程实例')
    DELETE_REASON_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(4000), comment='删除原因')
    TENANT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), server_default=text("''"), comment='多租户')
    NAME_: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='名称')


class ActHiTaskinst(Base):
    __tablename__ = 'act_hi_taskinst'
    __table_args__ = (
        Index('ACT_IDX_HI_TASK_INST_PROCINST', 'PROC_INST_ID_'),
        {'comment': '任务历史'}
    )

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    START_TIME_: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, comment='开始时间')
    PROC_DEF_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='流程定义')
    TASK_DEF_KEY_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='任务定义标识（环节ID）')
    PROC_INST_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='流程实例')
    EXECUTION_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='执行')
    NAME_: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='名称')
    PARENT_TASK_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='父任务')
    DESCRIPTION_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(4000), comment='描述')
    OWNER_: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='被代理人')
    ASSIGNEE_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='负责人')
    CLAIM_TIME_: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='领取时间')
    END_TIME_: Mapped[Optional[datetime.datetime]
                      ] = mapped_column(DateTime, comment='结束时间')
    DURATION_: Mapped[Optional[int]] = mapped_column(
        BigInteger, comment='持续时间')
    DELETE_REASON_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(4000), comment='删除原因')
    PRIORITY_: Mapped[Optional[int]] = mapped_column(Integer, comment='优先级')
    DUE_DATE_: Mapped[Optional[datetime.datetime]
                      ] = mapped_column(DateTime, comment='截止时间')
    FORM_KEY_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='表单标识')
    CATEGORY_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='分类')
    TENANT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), server_default=text("''"), comment='多租户')


class ActHiVarinst(Base):
    __tablename__ = 'act_hi_varinst'
    __table_args__ = (
        Index('ACT_IDX_HI_PROCVAR_NAME_TYPE', 'NAME_', 'VAR_TYPE_'),
        Index('ACT_IDX_HI_PROCVAR_PROC_INST', 'PROC_INST_ID_'),
        Index('ACT_IDX_HI_PROCVAR_TASK_ID', 'TASK_ID_'),
        {'comment': '变量历史'}
    )

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    NAME_: Mapped[str] = mapped_column(
        VARCHAR(255), nullable=False, comment='名称')
    PROC_INST_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='流程时间')
    EXECUTION_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='执行')
    TASK_ID_: Mapped[Optional[str]] = mapped_column(VARCHAR(64), comment='任务')
    VAR_TYPE_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(100), comment='类型')
    REV_: Mapped[Optional[int]] = mapped_column(Integer, comment='乐观锁')
    BYTEARRAY_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='内容ACT_GE_BYTEARRAY')
    DOUBLE_: Mapped[Optional[decimal.Decimal]] = mapped_column(
        Double(asdecimal=True), comment='浮点值')
    LONG_: Mapped[Optional[int]] = mapped_column(BigInteger, comment='长整数值')
    text_: Mapped[Optional[str]] = mapped_column(TEXT, comment='文本值')
    TEXT2_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(4000), comment='jpa变量text存className，text2存id')
    CREATE_TIME_: Mapped[Optional[datetime.datetime]
                         ] = mapped_column(DateTime, comment='创建时间')
    LAST_UPDATED_TIME_: Mapped[Optional[datetime.datetime]] = mapped_column(
        DateTime, comment='最后更新时间')


class ActReDeployment(Base):
    __tablename__ = 'act_re_deployment'
    __table_args__ = {'comment': '流程部署'}

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    NAME_: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='名称')
    CATEGORY_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='分类')
    TENANT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), server_default=text("''"), comment='多租户')
    DEPLOY_TIME_: Mapped[Optional[datetime.datetime]
                         ] = mapped_column(TIMESTAMP, comment='部署时间')

    act_ge_bytearray: Mapped[list['ActGeBytearray']] = relationship(
        'ActGeBytearray', back_populates='act_re_deployment')
    act_re_model: Mapped[list['ActReModel']] = relationship(
        'ActReModel', back_populates='act_re_deployment')


class ActReDeploymentTest(Base):
    __tablename__ = 'act_re_deployment_test'
    __table_args__ = {'comment': '部署测试表'}

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    NAME_: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='名称')
    CATEGORY_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='分类')
    TENANT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), server_default=text("''"), comment='多租户')
    DEPLOY_TIME_: Mapped[Optional[datetime.datetime]
                         ] = mapped_column(TIMESTAMP, comment='部署时间')


class ActReProcdef(Base):
    __tablename__ = 'act_re_procdef'
    __table_args__ = (
        Index('ACT_UNIQ_PROCDEF', 'KEY_', 'VERSION_', 'TENANT_ID_', unique=True),
        {'comment': '流程定义'}
    )

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    KEY_: Mapped[str] = mapped_column(
        VARCHAR(255), nullable=False, comment='标识')
    VERSION_: Mapped[int] = mapped_column(
        Integer, nullable=False, comment='版本')
    REV_: Mapped[Optional[int]] = mapped_column(Integer, comment='乐观锁')
    CATEGORY_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='分类')
    NAME_: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='名称')
    DEPLOYMENT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='部署')
    RESOURCE_NAME_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(4000), comment='资源名称')
    DGRM_RESOURCE_NAME_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(4000), comment='图片资源名称')
    DESCRIPTION_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(4000), comment='描述')
    HAS_START_FORM_KEY_: Mapped[Optional[int]] = mapped_column(
        TINYINT, comment='拥有开始表单标识')
    HAS_GRAPHICAL_NOTATION_: Mapped[Optional[int]
                                    ] = mapped_column(TINYINT, comment='拥有图形信息')
    SUSPENSION_STATE_: Mapped[Optional[int]] = mapped_column(
        Integer, comment='暂停状态 1激活 2暂停')
    TENANT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), server_default=text("''"), comment='多租户')

    act_ru_execution: Mapped[list['ActRuExecution']] = relationship(
        'ActRuExecution', back_populates='act_re_procdef')
    act_procdef_info: Mapped[list['ActProcdefInfo']] = relationship(
        'ActProcdefInfo', back_populates='act_re_procdef')


class ActRuIdentitylink(Base):
    __tablename__ = 'act_ru_identitylink'
    __table_args__ = (
        Index('ACT_IDX_IDENT_LNK_TASK_ID', 'TASK_ID_'),
        {'comment': '参与者'}
    )

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    REV_: Mapped[Optional[int]] = mapped_column(Integer, comment='乐观锁')
    GROUP_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='群组')
    TYPE_: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='类型')
    USER_ID_: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='用户')
    TASK_ID_: Mapped[Optional[str]] = mapped_column(VARCHAR(64), comment='任务')
    PROC_INST_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='流程实例')
    PROC_DEF_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='流程定义')


class ActRuTask(Base):
    __tablename__ = 'act_ru_task'
    __table_args__ = (
        Index('ACT_FK_TASK_EXE', 'EXECUTION_ID_'),
        Index('ACT_FK_TASK_PROCINST', 'PROC_INST_ID_'),
        Index('ACT_IDX_TASK_CREATE', 'CREATE_TIME_'),
        Index('ACT_IDX_TASK_PARENTID', 'PARENT_TASK_ID_'),
        {'comment': '任务'}
    )

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    REV_: Mapped[Optional[int]] = mapped_column(Integer, comment='乐观锁')
    EXECUTION_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='执行')
    PROC_INST_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='流程实例')
    PROC_DEF_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='流程定义')
    NAME_: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='名称')
    PARENT_TASK_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='父任务')
    DESCRIPTION_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(4000), comment='描述')
    TASK_DEF_KEY_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='任务定义标识（环节ID）')
    OWNER_: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='被代理人')
    ASSIGNEE_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='负责人')
    DELEGATION_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='委托状态 PENDING委托中，RESOLVED已处理')
    PRIORITY_: Mapped[Optional[int]] = mapped_column(Integer, comment='优先级')
    CREATE_TIME_: Mapped[Optional[datetime.datetime]
                         ] = mapped_column(TIMESTAMP, comment='创建时间')
    DUE_DATE_: Mapped[Optional[datetime.datetime]
                      ] = mapped_column(DateTime, comment='截止时间')
    CATEGORY_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='分类')
    SUSPENSION_STATE_: Mapped[Optional[int]] = mapped_column(
        Integer, comment='暂停状态 1激活 2暂停')
    TENANT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), server_default=text("''"), comment='多租户')
    FORM_KEY_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='表单标识')


class BladeVisualDb(Base):
    __tablename__ = 'blade_visual_db'
    __table_args__ = {'comment': '可视化数据源配置表'}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, comment='主键')
    name: Mapped[Optional[str]] = mapped_column(VARCHAR(100), comment='名称')
    driver_class: Mapped[Optional[str]] = mapped_column(
        VARCHAR(100), comment='驱动类')
    url: Mapped[Optional[str]] = mapped_column(VARCHAR(500), comment='连接地址')
    username: Mapped[Optional[str]] = mapped_column(VARCHAR(50), comment='用户名')
    password: Mapped[Optional[str]] = mapped_column(VARCHAR(50), comment='密码')
    remark: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='备注')
    create_user: Mapped[Optional[int]] = mapped_column(
        BigInteger, comment='创建人')
    create_dept: Mapped[Optional[int]] = mapped_column(
        BigInteger, comment='创建部门')
    create_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='创建时间')
    update_user: Mapped[Optional[int]] = mapped_column(
        BigInteger, comment='修改人')
    update_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='修改时间')
    status: Mapped[Optional[int]] = mapped_column(Integer, comment='状态')
    is_deleted: Mapped[Optional[int]] = mapped_column(Integer, comment='是否已删除')


class BladeVisualRecord(Base):
    __tablename__ = 'blade_visual_record'
    __table_args__ = {'comment': '可视化数据集表'}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, comment='主键')
    name: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='名称')
    url: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='数据地址')
    data_type: Mapped[Optional[int]] = mapped_column(Integer, comment='数据类型')
    data_method: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='数据方法')
    data_header: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='数据请求头')
    data: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='数据集')
    data_query: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='数据查询')
    data_query_type: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='数据查询类型')
    data_formatter: Mapped[Optional[str]] = mapped_column(
        LONGTEXT, comment='数据格式化')
    ws_url: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='ws地址')
    create_user: Mapped[Optional[int]] = mapped_column(
        BigInteger, comment='创建人')
    create_dept: Mapped[Optional[int]] = mapped_column(
        BigInteger, comment='创建部门')
    create_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='创建时间')
    update_user: Mapped[Optional[int]] = mapped_column(
        BigInteger, comment='修改人')
    update_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='修改时间')
    status: Mapped[Optional[int]] = mapped_column(Integer, comment='状态')
    is_deleted: Mapped[Optional[int]] = mapped_column(Integer, comment='是否已删除')


class BpmAgentCondition(Base):
    __tablename__ = 'bpm_agent_condition'
    __table_args__ = {'comment': '流程代理条件'}

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    SETTING_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='设定ID')
    CONDITION_DESC_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(128), comment='条件描述')
    CONDITION_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(4000), comment='条件')
    AGENT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='代理人ID')
    AGENT_NAME_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(128), comment='代理人')
    TENANT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='多租户')


class BpmAgentDef(Base):
    __tablename__ = 'bpm_agent_def'
    __table_args__ = {'comment': '代理指定流程'}

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    SETTING_ID_: Mapped[str] = mapped_column(
        VARCHAR(64), nullable=False, comment='设定ID')
    FLOW_KEY_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='流程定义KEY')
    FLOW_NAME_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='流程定义名称')
    NODE_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(512), comment='节点定义ID(为空的情况,如果指定ID,那么代理只在这些ID的任务生效)')
    NODE_NAME_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(128), comment='节点名称')
    TENANT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='多租户')


class BpmAgentSetting(Base):
    __tablename__ = 'bpm_agent_setting'
    __table_args__ = {'comment': '流程代理设置'}

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    SUBJECT_: Mapped[str] = mapped_column(
        VARCHAR(64), nullable=False, comment='标题')
    AUTH_ID_: Mapped[str] = mapped_column(
        VARCHAR(64), nullable=False, comment='授权人ID')
    AUTH_NAME_: Mapped[str] = mapped_column(
        VARCHAR(64), nullable=False, comment='授权人姓名')
    IS_ENABLED_: Mapped[str] = mapped_column(
        CHAR(1), nullable=False, comment='是否有效')
    START_DATE_: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='开始时间')
    END_DATE_: Mapped[Optional[datetime.datetime]
                      ] = mapped_column(DateTime, comment='结束时间')
    AGENT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='代理人ID')
    AGENT_: Mapped[Optional[str]] = mapped_column(VARCHAR(128), comment='代理人')
    FLOW_KEY_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='流程定义KEY')
    TYPE_: Mapped[Optional[int]] = mapped_column(
        SmallInteger, comment='代理类型(1,全权代理,2,部分代理,3.条件代理)')
    CREATE_BY_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='创建人ID')
    CREATE_TIME_: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    CREATE_ORG_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='创建者所属组织ID')
    UPDATE_BY_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='更新人ID')
    UPDATE_TIME_: Mapped[Optional[datetime.datetime]] = mapped_column(DateTime)
    TENANT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='租户id')


class BpmApprovalItem(Base):
    __tablename__ = 'bpm_approval_item'
    __table_args__ = {'comment': '常用语管理'}

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    USER_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='用户ID')
    DEF_KEY_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(128), comment='流程定义KEY')
    DEF_NAME_: Mapped[Optional[str]] = mapped_column(
        CHAR(10), comment='流程定义名称')
    TYPE_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='流程分类ID')
    TYPE_: Mapped[Optional[int]] = mapped_column(
        SmallInteger, comment='常用语类型\r\n默认为1=全局\r\n2=流程分类\r\n3=流程\r\n4=个人的常用语')
    EXPRESSION_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(4000), comment='常用语        多个项用回车分开')
    CREATE_TIME_: Mapped[Optional[datetime.datetime]
                         ] = mapped_column(DateTime, comment='创建时间')
    CREATE_BY_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='创建人ID')
    CREATE_ORG_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='创建人所属组织ID')
    UPDATE_BY_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='更新人ID')
    UPDATE_TIME_: Mapped[Optional[datetime.datetime]
                         ] = mapped_column(DateTime, comment='更新时间')
    TENANT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='多租户')
    OPERATE_TIME_: Mapped[Optional[datetime.datetime]
                          ] = mapped_column(DateTime, comment='操作时间')


class BpmApprovalOrg(Base):
    __tablename__ = 'bpm_approval_org'
    __table_args__ = {'comment': '常用语组织'}

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    APPROVAL_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='常用语')
    POST_ID_: Mapped[Optional[str]] = mapped_column(VARCHAR(64), comment='岗位')
    ROLE_ID_: Mapped[Optional[str]] = mapped_column(VARCHAR(64), comment='角色')
    DEPARTMENT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='部门')
    CREATE_TIME_: Mapped[Optional[datetime.datetime]
                         ] = mapped_column(DateTime, comment='创建时间')
    CREATE_BY_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='创建者')
    UPDATE_TIME_: Mapped[Optional[datetime.datetime]
                         ] = mapped_column(DateTime, comment='更新时间')
    UPDATE_BY_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='更新者')


class BpmAttention(Base):
    __tablename__ = 'bpm_attention'
    __table_args__ = {'comment': '流程关联'}

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    PROC_INST_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='流程实例id')
    OWNER_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='用户id')
    OWNER_NAME_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='用户名称')
    CREATE_TIME_: Mapped[Optional[datetime.datetime]
                         ] = mapped_column(DateTime, comment='创建时间')


class BpmAutoStartConf(Base):
    __tablename__ = 'bpm_auto_start_conf'
    __table_args__ = {'comment': '流程自动发起配置表'}

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    DEF_KEY_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='自动发起的流程定义key')
    START_USER_: Mapped[Optional[str]] = mapped_column(TEXT, comment='自动发起人配置')
    FORM_DATA_: Mapped[Optional[str]] = mapped_column(TEXT, comment='表单数据配置')
    TRIGGER_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(512), comment='自动发起时机')
    TENANT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='租户id')


class BpmBusLink(Base):
    __tablename__ = 'bpm_bus_link'
    __table_args__ = (
        Index('IDX_BUSLINK_BUSINESSKEY', 'BUSINESSKEY_STR_'),
        Index('IDX_BUSLINK_INSTID', 'PROC_INST_ID_'),
        Index('TENANT_ID_', 'TENANT_ID_'),
        Index('idx_bpm_bus_link_tenant_proc', 'TENANT_ID_', 'PROC_INST_ID_'),
        {'comment': '流程实例与业务数据关系表，每一条记录对应业务的物理表，属于物理表的额外属性'}
    )

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    FORM_IDENTIFY_: Mapped[str] = mapped_column(
        VARCHAR(64), nullable=False, comment='表单标识')
    DEF_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='流程定义ID')
    PROC_INST_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='流程实例ID')
    BUSINESSKEY_: Mapped[Optional[int]] = mapped_column(
        BigInteger, comment='业务键')
    BUSINESSKEY_STR_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='业务键字符型')
    SYS_CODE_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='业务系统编码')
    START_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='发起人')
    STARTOR_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(128), comment='发起人')
    CREATE_DATE_: Mapped[Optional[datetime.datetime]
                         ] = mapped_column(DateTime, comment='创建时间')
    START_GROUP_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='发起组织ID')
    START_GROUP_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(128), comment='发起组织')
    IS_MAIN_: Mapped[Optional[int]] = mapped_column(
        SmallInteger, comment='主记录')
    BO_DEF_CODE_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='bodefcode数据')
    SAVE_MODE_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='保存模式 (boObject,database)')
    TENANT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='租户ID')


class BpmCallLog(Base):
    __tablename__ = 'bpm_call_log'
    __table_args__ = {'comment': 'restful接口调用日志'}

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    SUBJECT_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(600), comment=' 流程标题')
    PROC_DEF_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment=' 流程定义ID')
    PROC_DEF_KEY_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(128), comment='流程定义Key')
    TASK_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='任务ID')
    SUP_INST_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), server_default=text("'0'"), comment='父流程实例ID')
    PROC_INST_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='流程实例ID')
    TASK_KEY_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='任务定义Key')
    TASK_NAME_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='任务名称')
    USER_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='调用人员ID')
    EVENT_TYPE_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='事件类型')
    URL_: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='调用地址')
    DESC_: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='接口描述')
    INVOKE_MODE_: Mapped[Optional[int]] = mapped_column(
        Integer, comment='接口调用模式:0:同步，1:异步')
    IS_SUCCESS_: Mapped[Optional[int]] = mapped_column(
        SmallInteger, server_default=text("'0'"), comment='是否调用成功')
    RESPONSE_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(2000), comment='调用结果')
    CALL_TIME_: Mapped[Optional[datetime.datetime]
                       ] = mapped_column(DateTime, comment='调用时间')
    PARAMS_: Mapped[Optional[str]] = mapped_column(TEXT, comment='请求参数')
    HEADER_: Mapped[Optional[str]] = mapped_column(VARCHAR(512), comment='请求头')
    RETRY_COUNT_: Mapped[Optional[int]] = mapped_column(
        Integer, comment='重试次数')
    TENANT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='租户id')


class BpmCheckOpinion(Base):
    __tablename__ = 'bpm_check_opinion'
    __table_args__ = (
        Index('IDX_CHECKOPINION_SUPINSTID', 'SUP_INST_ID_'),
        Index('IDX_OPINION_AUDITOR', 'AUDITOR_'),
        Index('IDX_OPINION_INSTID', 'PROC_INST_ID_'),
        Index('IDX_OPINION_TASK', 'TASK_ID_'),
        {'comment': '流程审批意见'}
    )

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    PROC_DEF_ID_: Mapped[str] = mapped_column(
        VARCHAR(64), nullable=False, comment='流程定义ID')
    PROC_INST_ID_: Mapped[str] = mapped_column(
        VARCHAR(64), nullable=False, comment='流程实例ID')
    STATUS_: Mapped[str] = mapped_column(VARCHAR(
        40), nullable=False, comment='审批状态。start=发起流程；awaiting_check=待审批；agree=同意；against=反对；return=驳回；abandon=弃权；retrieve=追回')
    IS_DELE_: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("'0'"), comment='是否已删，1已删除，0未删除')
    IS_READ_: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("'0'"), comment='0：待阅，1：已阅')
    SUP_INST_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='父流程实例ID')
    TASK_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='任务ID')
    TASK_KEY_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='任务定义Key')
    TASK_NAME_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='任务名称')
    TOKEN_: Mapped[Optional[str]] = mapped_column(VARCHAR(64), comment='任务令牌')
    QUALFIEDS_: Mapped[Optional[str]] = mapped_column(
        TEXT, comment='有审批资格用户ID串')
    QUALFIED_NAMES_: Mapped[Optional[str]] = mapped_column(
        TEXT, comment='有审批资格用户名称串')
    AUDITOR_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='执行人ID')
    AUDITOR_NAME_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='执行人名')
    ORG_ID_: Mapped[Optional[str]] = mapped_column(VARCHAR(64), comment='组织ID')
    ORG_PATH_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(600), comment='组织全路径')
    OPINION_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(4000), comment='审批意见')
    FORM_DEF_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='表单定义ID')
    FORM_NAME_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='表单名')
    CREATE_TIME_: Mapped[Optional[datetime.datetime]
                         ] = mapped_column(DateTime, comment='执行开始时间')
    ASSIGN_TIME_: Mapped[Optional[datetime.datetime]
                         ] = mapped_column(DateTime, comment='任务分配用户时间')
    COMPLETE_TIME_: Mapped[Optional[datetime.datetime]
                           ] = mapped_column(DateTime, comment='结束时间')
    DUR_MS_: Mapped[Optional[int]] = mapped_column(BigInteger, comment='持续时间')
    FILES_: Mapped[Optional[str]] = mapped_column(VARCHAR(4000), comment='附件')
    INTERPOSE_: Mapped[Optional[int]] = mapped_column(
        SmallInteger, comment='是否干预')
    AGENT_LEADER_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='被代理的领导人id')
    PROP1_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(200), comment='扩展属性1')
    PROP2_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(200), comment='扩展属性2')
    PROP3_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(200), comment='扩展属性3')
    PROP4_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(200), comment='扩展属性4')
    PROP5_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(200), comment='扩展属性5')
    PROP6_: Mapped[Optional[str]] = mapped_column(TEXT, comment='扩展属性6')
    Z_FILES_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(1000), comment='正文附件')
    FORM_DATA_: Mapped[Optional[str]] = mapped_column(LONGTEXT, comment='表单数据')
    PARENT_TASK_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='父任务id')
    SIGN_TYPE_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='任务类型')
    SKIP_TYPE_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='跳过类型 启动跳过 审批跳过 执行人为空跳过 相同执行人跳过')
    TENANT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='租户ID')
    APPROVE_TYPE_: Mapped[Optional[str]] = mapped_column(VARCHAR(
        20), comment='审批方式 pc : pc端普通审批 ,mobile : 移动端审批,auto :超时自动审批,admin 管理员跳转')


class SgoCodeInquiry(Base):
    __tablename__ = 'sgo_code_inquiry'
    __table_args__ = (
        Index('inquiry_num', 'inquiry_num', unique=True),
        {'comment': '物料询码记录'}
    )

    id: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    inquiry_num: Mapped[Optional[str]] = mapped_column(
        VARCHAR(13), comment='询码记录流水号')
    creater: Mapped[Optional[str]] = mapped_column(
        VARCHAR(20), comment='提报人名称')
    creater_account: Mapped[Optional[str]] = mapped_column(
        VARCHAR(20), comment='提报人账号')
    creater_org_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='提报人所属部门id')
    creater_org_code: Mapped[Optional[str]] = mapped_column(
        VARCHAR(20), comment='提报人所属部门编码')
    creater_org_name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='提报人所属部门名称')
    item_name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(200), comment='名称描述')
    train_no: Mapped[Optional[str]] = mapped_column(VARCHAR(100), comment='列号')
    vehicle: Mapped[Optional[str]] = mapped_column(VARCHAR(20), comment='车型')
    car_num: Mapped[Optional[str]] = mapped_column(VARCHAR(100), comment='车厢号')
    parts_model: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='规格型号')
    subordinate_component: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='隶属部件')
    submission_date: Mapped[Optional[datetime.date]
                            ] = mapped_column(Date, comment='提报日期')
    supplier_code: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), comment='需求供应商')
    supplier_name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='需求供应商名')
    nameplate_photos: Mapped[Optional[str]] = mapped_column(
        VARCHAR(4000), comment='铭牌照片')
    detailed_photos: Mapped[Optional[str]] = mapped_column(
        VARCHAR(4000), comment='远近照片')
    remark: Mapped[Optional[str]] = mapped_column(
        VARCHAR(2000), comment='提报备注')
    create_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='创建时间')
    current_status: Mapped[Optional[str]] = mapped_column(VARCHAR(
        20), comment='CREATE:技术部待回复\r\nCONFIRMAUDIT:编码确认审核中\r\nFINISH:结束（闭环）\r\nBACKAUDIT:驳回审核中\r\nSUPPLIERRES:供应商处理中\r\nBACK:技术部驳回\r\nGREEN:绿色通道\r\nREGING:编码注册中')
    start_inst_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='对应询码启动流程id')
    supplier_inquiry_num: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='供应商回复流水号')
    tenant_id_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='租户id')
    project_type: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), comment='项目类型')
    location: Mapped[Optional[str]] = mapped_column(VARCHAR(50), comment='位置')
    inst_supplier: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='流程节点变量')
    create_org_principal: Mapped[Optional[str]] = mapped_column(
        VARCHAR(20), comment='提报人所属部门负责人')
    create_org_principal_name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(5), comment='提报人所属部门负责人名称')
    green_remark: Mapped[Optional[str]] = mapped_column(
        VARCHAR(2000), comment='记录历史数据用户反馈原因')
    sub_current_status: Mapped[Optional[str]] = mapped_column(
        VARCHAR(20), comment='子状态:待定')
    admin_remark: Mapped[Optional[str]] = mapped_column(
        VARCHAR(2000), comment='管理员备注（技术部人操作）')
    sub_creater_org_code: Mapped[Optional[str]] = mapped_column(VARCHAR(4), Computed(
        '(substr(`creater_org_code`,1,4))', persisted=True), comment='计算列：截取 creater_org_code')

    @classmethod
    async def list_code_inquiry(cls, session: AsyncSession, page: int = 0, per_page: int = 20,
                                status: str = 'FINISH',has_index:int = 0, inquiry_id_list: list[str] = []):
        """
        has_index 为1时必须做过索引的
        has_index 为2时没有做过索引
        has_index 为0时不关注
        """
        offset = (page-1) * per_page
        # 甲方 Kingbase 表包含 sys.date/sys.datetime 等非 PostgreSQL 标准类型。
        # 列表只读取前端实际展示的字段，避免 asyncpg 解码无须返回的私有类型；日期按接口口径返回字符串。
        columns = [
            cls.id,
            cls.inquiry_num,
            cls.creater,
            cls.creater_org_name,
            cls.item_name,
            cls.train_no,
            cls.vehicle,
            cls.car_num,
            cls.subordinate_component,
            cast(cls.submission_date, String).label("submission_date"),
            cls.supplier_code,
            cls.supplier_name,
            cls.nameplate_photos,
            cls.detailed_photos,
            cls.remark,
            cls.current_status,
        ]
        stmt = select(*columns)
        if status is not None and status != '' and status != 'all':
            stmt = stmt.where(cls.current_status == status)
        if len(inquiry_id_list) > 0:
            if has_index == 1:
                stmt = stmt.where(cls.id.in_(inquiry_id_list))
            elif has_index == 2:
                stmt = stmt.where(cls.id.not_in(inquiry_id_list))

        count = await async_get_count(session, stmt)
        stmt = stmt.order_by(cls.create_time.desc())
        if page != -1:
            stmt = stmt.limit(
                per_page).offset(offset)
        datas = await session.execute(stmt)
        return PageQueryResult(total=count, data=datas.all())

    @classmethod
    async def get_inquery_by_id(cls, session: AsyncSession, inquery_id: str):
        stmt = select(cls).where(cls.id == inquery_id)
        return await session.scalar(stmt)

    
    @classmethod
    async def get_inquery_by_id_list(cls, session: AsyncSession, inquery_id_list: list[str]):
        stmt = select(cls).where(cls.id.in_(inquery_id_list))
        return await session.scalars(stmt)

    @classmethod
    async def list_image_files_by_item_codes(
        cls,
        session: AsyncSession,
        item_code_list: list[str],
    ):
        if not item_code_list:
            return []
        # 图片同步只读取照片字段与物料编码，避免 Kingbase 私有时间类型解码失败。
        stmt = (
            select(
                cls.detailed_photos,
                cls.nameplate_photos,
                SgoCodeInquiryReturn.item_code,
            )
            .join(SgoCodeInquiryReturn, cls.id == SgoCodeInquiryReturn.inquiry_id)
            .where(SgoCodeInquiryReturn.item_code.is_not(None))
            .where(SgoCodeInquiryReturn.item_code != "")
            .where(SgoCodeInquiryReturn.item_code.in_(item_code_list))
        )
        result = await session.execute(stmt)
        return result.all()


class SgoCodeInquiryChange(Base):
    __tablename__ = 'sgo_code_inquiry_change'
    __table_args__ = (
        Index('inquiry_id', 'inquiry_id'),
    )

    id: Mapped[str] = mapped_column(VARCHAR(19), primary_key=True)
    inquiry_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='询码编号')
    create_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='操作时间')
    creater: Mapped[Optional[str]] = mapped_column(VARCHAR(20), comment='操作人')
    create_account: Mapped[Optional[str]] = mapped_column(
        VARCHAR(20), comment='操作人账号')
    current_status: Mapped[Optional[str]] = mapped_column(
        VARCHAR(30), comment='一级状态')
    sub_current_status: Mapped[Optional[str]] = mapped_column(
        VARCHAR(30), comment='二级状态')
    remark: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='备注')
    supplier_name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(150), comment='供应商名称')
    supplier_code: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), comment='供应商编码')
    call_person: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='联系人')
    call_content: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='沟通内容')
    tenant_id_: Mapped[Optional[str]] = mapped_column(VARCHAR(60))


class SgoCodeInquiryReturn(Base):
    __tablename__ = 'sgo_code_inquiry_return'
    __table_args__ = (
        Index('inquiry_num', 'inquiry_id'),
        {'comment': '物料询码记录回复'}
    )

    id: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    inquiry_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='询码记录id')
    creater: Mapped[Optional[str]] = mapped_column(
        VARCHAR(20), comment='提报人名称')
    creater_account: Mapped[Optional[str]] = mapped_column(
        VARCHAR(20), comment='提报人账号')
    creater_org_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='提报人所属部门id')
    creater_org_code: Mapped[Optional[str]] = mapped_column(
        VARCHAR(20), comment='提报人所属部门编码')
    creater_org_name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='提报人所属部门名称')
    item_name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='物料名称')
    item_code: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='物料编码')
    vehicle: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='车型')
    figure_number: Mapped[Optional[str]] = mapped_column(
        VARCHAR(200), comment='图号')
    parts_model: Mapped[Optional[str]] = mapped_column(
        VARCHAR(200), comment='规格型号')
    item_unit: Mapped[Optional[str]] = mapped_column(VARCHAR(50), comment='单位')
    subordinate_component: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='隶属部件')
    supplier_code: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), comment='供应商')
    supplier_name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='供应商名')
    technical_notice: Mapped[Optional[str]] = mapped_column(
        VARCHAR(200), comment='技改通知')
    technical_brief: Mapped[Optional[str]] = mapped_column(
        VARCHAR(200), comment='通知简要')
    inquiry_from: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='查询依据')
    technical_annex: Mapped[Optional[str]] = mapped_column(
        VARCHAR(2000), comment='附件')
    update_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='修改时间')
    create_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='回复时间')
    tenant_id_: Mapped[Optional[str]] = mapped_column(VARCHAR(50))
    material_quality: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='材质')
    strength_level: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='强度等级')
    remark: Mapped[Optional[str]] = mapped_column(VARCHAR(1000), comment='备注')
    tec_introduce: Mapped[Optional[str]] = mapped_column(
        VARCHAR(1000), comment='技术说明')
    current_status: Mapped[Optional[str]] = mapped_column(
        VARCHAR(30), comment='C1新建')


    @classmethod 
    async def get_return_by_code_id_list(cls,session:AsyncSession,code_list:list[str] = []):
        if code_list.__len__() == 0:
            return []

        # 已索引筛选只需要回复记录关联的询码 ID，避免读取 Kingbase 私有
        # sys.datetime 类型的 update_time/create_time 导致 asyncpg 解码失败。
        stmt = (
            select(cls)
            .options(load_only(cls.inquiry_id))
            .where(cls.item_code.in_(code_list))
        )
        return await session.scalars(stmt)

    @classmethod
    async def get_return_by_inquery_id(cls,session:AsyncSession,inquiry_id:str):
        stmt = select(cls).where(cls.inquiry_id==inquiry_id)
        return await session.scalar(stmt)

class SgoCodeSupplierReturn(Base):
    __tablename__ = 'sgo_code_supplier_return'
    __table_args__ = (
        Index('inquiry_num', 'inquiry_id'),
    )

    id: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    inquiry_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='询码记录id')
    creater: Mapped[Optional[str]] = mapped_column(
        VARCHAR(20), comment='提报人名称')
    creater_account: Mapped[Optional[str]] = mapped_column(
        VARCHAR(20), comment='提报人账号')
    creater_org_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='提报人所属部门id')
    creater_org_code: Mapped[Optional[str]] = mapped_column(
        VARCHAR(20), comment='提报人所属部门编码')
    creater_org_name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='提报人所属部门名称')
    s_item_name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='供应商回复物料名称')
    s_item_code: Mapped[Optional[str]] = mapped_column(
        VARCHAR(12), comment='供应商回复物料编码')
    s_figure_number: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='供应商回复图号')
    s_parts_model: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='供应商回复规格型号')
    item_unit: Mapped[Optional[str]] = mapped_column(VARCHAR(5), comment='单位')
    material_quality: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='材质')
    supplier_code: Mapped[Optional[str]] = mapped_column(
        VARCHAR(20), comment='供应商')
    supplier_name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='供应商名')
    technical_annex: Mapped[Optional[str]] = mapped_column(
        VARCHAR(2000), comment='附件')
    update_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='修改时间')
    create_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='回复时间')
    strength_level: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='强度等级')
    item_name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(100), comment='四方物料名称')
    item_code: Mapped[Optional[str]] = mapped_column(
        VARCHAR(100), comment='四方物料信息')
    figure_number: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='四方物料图号')
    parts_model: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='四方规格型号')
    remark: Mapped[Optional[str]] = mapped_column(VARCHAR(1000), comment='备注')
    tenant_id_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), server_default=text("'1463844437338755072'"))


class SgoManualProjectInfo(Base):
    __tablename__ = 'sgo_manual_project_info'
    __table_args__ = {'comment': 'sgo 电子手册项目信息'}

    id: Mapped[str] = mapped_column(VARCHAR(64), primary_key=True)
    title: Mapped[Optional[str]] = mapped_column(VARCHAR(254), comment='型号名')
    column_id: Mapped[Optional[str]] = mapped_column(VARCHAR(32), comment='板块')
    parent_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='技术内容库ID')
    modelident_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='型号ID')
    modelIdent_code: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='型号识别码')
    pm_code: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='型号识别码')
    model_group: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='车辆编组信息')
    modelldent_group_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='产品目录分组ID')
    model_threshold_list: Mapped[Optional[str]
                                 ] = mapped_column(TEXT, comment='项目修程列表')
    create_by: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='创建者')
    create_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='创建时间')
    update_by: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='更新者')
    update_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='更新时间')
    remark: Mapped[Optional[str]] = mapped_column(VARCHAR(254), comment='备注')
    tenant_id_: Mapped[Optional[str]] = mapped_column(VARCHAR(32))


class SgoMaterialAccessory(Base):
    __tablename__ = 'sgo_material_accessory'

    id: Mapped[str] = mapped_column(
        VARCHAR(19), primary_key=True, comment='id')
    subsidiary_name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(100), comment='子公司名称')
    subsidiary_code: Mapped[Optional[str]] = mapped_column(
        VARCHAR(20), comment='子公司编码')
    create_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='创建时间')
    create_name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='创建人')
    accessory_file_src: Mapped[Optional[str]] = mapped_column(
        VARCHAR(2000), comment='对应附件')
    accessory_date: Mapped[Optional[datetime.datetime]
                           ] = mapped_column(DateTime, comment='申请日期')
    tenant_id_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='租户id')
    accessory_info: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='申请说明')
    detail_count: Mapped[Optional[int]] = mapped_column(
        Integer, comment='采购数量')
    list_status: Mapped[Optional[str]] = mapped_column(VARCHAR(
        25), server_default=text("'normal'"), comment='列表状态(normal：正常，delete：已删除)')


class SgoMaterialAccessoryinfo(Base):
    __tablename__ = 'sgo_material_accessoryinfo'

    id: Mapped[str] = mapped_column(
        VARCHAR(19), primary_key=True, comment='序号')
    accessory_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(19), comment='主表id')
    material_code: Mapped[Optional[str]] = mapped_column(
        VARCHAR(11), comment='物料编码（四方）')
    material_code_subsidiary: Mapped[Optional[str]] = mapped_column(
        VARCHAR(11), comment='物料编码（子公司）')
    material_name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(150), comment='物料名称')
    category_code: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), server_default=text("'1'"), comment='品类编码')
    category_name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(100), comment='品类名称')
    unit: Mapped[Optional[str]] = mapped_column(VARCHAR(10), comment='单位')
    unit_price: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), comment='单价')
    supplier_code: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), comment='供应商编码')
    supplier_name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(150), comment='供应商名称')
    tenant_id_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='租户id')
    related_purchase_approval_file: Mapped[Optional[str]] = mapped_column(
        LONGTEXT, comment='关联采购审批文件')
    result: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), server_default=text("'success'"))
    remark: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='备注')
    material_message_status: Mapped[Optional[str]] = mapped_column(VARCHAR(
        255), server_default=text("'normal'"), comment='配件信息删除状态(normal：正常，delete：删除)')


class SgoMaterialStockAge(Base):
    __tablename__ = 'sgo_material_stock_age'

    id: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), server_default=text("''"), comment='供应商名称')
    code: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), server_default=text("''"), comment='供应商编码')
    stock_quantity_one: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(11, 0), comment='库存6个月以内数')
    stock_quantity_two: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(11, 0), comment='库存6个月-1年以内数')
    stock_quantity_three: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(11, 0), comment='库存1-2年以内数')
    stock_quantity_four: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(11, 0), comment='库存2-3年以内数')
    stock_quantity_five: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(11, 0), comment='库存3年以上数')
    material_type_one: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(11, 0), comment='物料种类6个月以内数')
    material_type_two: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(11, 0), comment='物料种类6个月-1年以内数')
    material_type_three: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(11, 0), comment='物料种类1-2年以内数')
    material_type_four: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(11, 0), comment='物料种类2-3年以内数')
    material_type_five: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(11, 0), comment='物料种类3年以上数')
    tenant_id_: Mapped[Optional[str]] = mapped_column(VARCHAR(255))


class SgoMaterialStockAgeMaterialType(Base):
    __tablename__ = 'sgo_material_stock_age_material_type'
    __table_args__ = {'comment': '供应商库存物料种类数统计'}

    code: Mapped[str] = mapped_column(
        VARCHAR(10), primary_key=True, server_default=text("''"), comment='供应商编码')
    name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), server_default=text("''"), comment='供应商名称')
    material_type_one: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(11, 0), comment='物料种类6个月以内数')
    material_type_two: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(11, 0), comment='物料种类6个月-1年以内数')
    material_type_three: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(11, 0), comment='物料种类1-2年以内数')
    material_type_four: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(11, 0), comment='物料种类2-3年以内数')
    material_type_five: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(11, 0), comment='物料种类3年以上数')
    tenant_id_: Mapped[Optional[str]] = mapped_column(VARCHAR(255))


class SgoMaterialStockAgeStockQuantity(Base):
    __tablename__ = 'sgo_material_stock_age_stock_quantity'
    __table_args__ = {'comment': '供应商库龄库存统计'}

    code: Mapped[str] = mapped_column(
        VARCHAR(10), primary_key=True, server_default=text("''"), comment='供应商编码')
    name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), server_default=text("''"), comment='供应商名称')
    stock_quantity_one: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(11, 0), comment='库存6个月以内数')
    stock_quantity_two: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(11, 0), comment='库存6个月-1年以内数')
    stock_quantity_three: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(11, 0), comment='库存1-2年以内数')
    stock_quantity_four: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(11, 0), comment='库存2-3年以内数')
    stock_quantity_five: Mapped[Optional[decimal.Decimal]] = mapped_column(
        DECIMAL(11, 0), comment='库存3年以上数')
    tenant_id_: Mapped[Optional[str]] = mapped_column(VARCHAR(255))


class SgoMaterielClient(Base):
    __tablename__ = 'sgo_materiel_client'
    __table_args__ = (
        Index('client_code', 'client_code'),
        Index('client_code_2', 'item_code', 'client_code',
              'masterplate_id', unique=True),
        Index('client_name', 'client_name'),
        Index('item_code', 'item_code'),
        Index('masterplate_id', 'masterplate_id'),
        {'comment': '物料模板对应业主信息'}
    )

    id: Mapped[str] = mapped_column(VARCHAR(64), primary_key=True)
    item_name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(2000), comment='业主物料名称')
    item_code: Mapped[Optional[str]] = mapped_column(
        VARCHAR(20), comment='业主物料编码')
    stock_quantity: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), comment='建议备货数量')
    client_code: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='业主编码')
    client_name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='业主名称')
    masterplate_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='物料模板id')
    supply_cycle: Mapped[Optional[str]] = mapped_column(
        VARCHAR(5), comment='业主意向供货周期')
    creater_account: Mapped[Optional[str]] = mapped_column(
        VARCHAR(20), comment='创建人账号')
    create_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='创建时间')
    creater: Mapped[Optional[str]] = mapped_column(VARCHAR(20), comment='创建人')
    tenant_id_: Mapped[Optional[str]] = mapped_column(VARCHAR(64))
    parts_model: Mapped[Optional[str]] = mapped_column(
        VARCHAR(100), comment='规格/图号')
    item_unit: Mapped[Optional[str]] = mapped_column(
        VARCHAR(30), comment='物资单位')
    brand: Mapped[Optional[str]] = mapped_column(VARCHAR(100), comment='品牌')


class SgoMaterielExtend(Base):
    __tablename__ = 'sgo_materiel_extend'
    __table_args__ = {'comment': '物料延伸表'}

    id: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    masterplate_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='模板id')
    matnr: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='物料编码')
    maktx: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='物料名称')
    zeinr: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='图号')
    extend_type: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='延伸类型 1代替 2被替 3相同 4父节点 5对应自制编码 6对应设计编码 7虚拟码')
    tenant_id_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), server_default=text("'1463844437338755072'"), comment='租户id')
    create_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='创建时间')
    creater: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='创建人')
    current_status: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='状态 删除:DELETE 新建:CREATE')
    remark: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='备注')


class SgoMaterielFile(Base):
    __tablename__ = 'sgo_materiel_file'

    id: Mapped[str] = mapped_column(VARCHAR(64), primary_key=True)
    masterplate_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='物料模板id')
    file_src: Mapped[Optional[str]] = mapped_column(
        VARCHAR(2000), comment='文件地址')
    sort: Mapped[Optional[str]] = mapped_column(VARCHAR(2), comment='顺序')
    create_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='创建时间')
    creater: Mapped[Optional[str]] = mapped_column(VARCHAR(20), comment='创建人')
    file_type: Mapped[Optional[str]] = mapped_column(
        VARCHAR(15), comment='附件类型')
    file_title: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='标题')
    tenant_id_: Mapped[Optional[str]] = mapped_column(VARCHAR(64))


class SgoMaterielFileImg(Base):
    __tablename__ = 'sgo_materiel_file_img'
    __table_args__ = (
        Index('file_type', 'file_type'),
        Index('masterplate_id', 'masterplate_id'),
        {'comment': '物料模板对应附件'}
    )

    id: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='id')
    masterplate_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='物料模板id')
    file_src: Mapped[Optional[str]] = mapped_column(
        VARCHAR(2000), comment='图片地址')
    sort: Mapped[Optional[str]] = mapped_column(VARCHAR(2), comment='顺序')
    create_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='创建时间')
    creater: Mapped[Optional[str]] = mapped_column(VARCHAR(20), comment='创建人')
    file_type: Mapped[Optional[str]] = mapped_column(
        VARCHAR(2), comment='附件类型')
    file_title: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='标题')
    tenant_id_: Mapped[Optional[str]] = mapped_column(VARCHAR(64))
    is_show: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), server_default=text("'Y'"), comment='Y:显示;N:不展示')
    is_download: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), server_default=text("'Y'"), comment='Y:允许下载;N:不允许下载')

    @classmethod
    async def list_image_file(cls, session: AsyncSession, item_id_list: list[str]):
        # 基础图同步只需要物料 ID 和文件地址，避免读取甲方 Kingbase 私有
        # sys.datetime 类型的 create_time 导致 asyncpg 在下载前解码失败。
        stmt = select(cls.masterplate_id, cls.file_src).where(
            cls.masterplate_id.in_(item_id_list)
        )
        result = await session.execute(stmt)
        return result.all()


class SgoMaterielFileUploadSpeedInfo(Base):
    __tablename__ = 'sgo_materiel_file_upload_speed_info'
    __table_args__ = {'comment': '上传进度表'}

    id: Mapped[str] = mapped_column(VARCHAR(64), primary_key=True)
    zip_name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(254), comment='批次：zip名称')
    url_name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(254), comment='全路径名称')
    simple_name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(254), comment='文件名称')
    upload_status: Mapped[Optional[str]] = mapped_column(
        CHAR(1), comment='上传状态：0：待上传  1：已上传')
    column_id: Mapped[Optional[str]] = mapped_column(VARCHAR(12), comment='板块')
    create_by: Mapped[Optional[str]] = mapped_column(
        VARCHAR(32), comment='创建人账号')
    create_by_name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='创建人名称')
    create_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='录入时间')
    update_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='更新时间')
    tenant_id_: Mapped[Optional[str]] = mapped_column(VARCHAR(32))


class SgoMaterielImgSup(Base):
    __tablename__ = 'sgo_materiel_img_sup'
    __table_args__ = (
        Index('file_type', 'file_type'),
        Index('masterplate_id', 'sup_info_id'),
        {'comment': '物料模板对应附件'}
    )

    id: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='id')
    sup_info_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='物料模板id')
    file_src: Mapped[Optional[str]] = mapped_column(
        VARCHAR(2000), comment='图片地址')
    sort: Mapped[Optional[str]] = mapped_column(VARCHAR(2), comment='顺序')
    create_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='创建时间')
    creater: Mapped[Optional[str]] = mapped_column(VARCHAR(20), comment='创建人')
    file_type: Mapped[Optional[str]] = mapped_column(
        VARCHAR(2), comment='附件类型')
    file_title: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='标题')
    tenant_id_: Mapped[Optional[str]] = mapped_column(VARCHAR(64))
    is_show: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), server_default=text("'Y'"), comment='Y:显示;N:不展示')
    is_download: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), server_default=text("'Y'"), comment='Y:允许下载;N:不允许下载')


class SgoMaterielInfo(Base):
    __tablename__ = 'sgo_materiel_info'
    __table_args__ = (
        Index('item_code', 'MATNR', unique=True),
        {'comment': '物料信息表'}
    )

    id: Mapped[str] = mapped_column(VARCHAR(32), primary_key=True)
    MATNR: Mapped[str] = mapped_column(
        VARCHAR(12), nullable=False, comment='物料编码')
    data_source_flag: Mapped[str] = mapped_column(
        VARCHAR(32), nullable=False, server_default=text("'sgo'"), comment='sgo 来源标识')
    MAKTX: Mapped[Optional[str]] = mapped_column(VARCHAR(150), comment='物料名称')
    VRKME: Mapped[Optional[str]] = mapped_column(VARCHAR(150), comment='单位')
    ZEINR: Mapped[Optional[str]] = mapped_column(VARCHAR(150), comment='图号')
    WRKST: Mapped[Optional[str]] = mapped_column(VARCHAR(150), comment='规格型号')
    CPUTM: Mapped[Optional[str]] = mapped_column(VARCHAR(19), comment='数据同步时间')
    tenant_id_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), server_default=text("'1463844437338755072'"))
    NTGEW: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), comment='\u200c净重')
    GROES: Mapped[Optional[str]] = mapped_column(VARCHAR(155), comment='强度')
    MTART: Mapped[Optional[str]] = mapped_column(VARCHAR(10))
    MATERIEL_TYPE: Mapped[Optional[str]] = mapped_column(
        VARCHAR(2), comment='物料类型 Z自制件  C采购件')
    S_MAKTX: Mapped[Optional[str]] = mapped_column(
        VARCHAR(150), comment='sap物料名称')
    S_VRKME: Mapped[Optional[str]] = mapped_column(
        VARCHAR(150), comment='sap单位')
    S_ZEINR: Mapped[Optional[str]] = mapped_column(
        VARCHAR(150), comment='sap图号')
    S_WRKST: Mapped[Optional[str]] = mapped_column(
        VARCHAR(150), comment='sap规格型号')
    WK_WEIGHT: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='微库物料重量数据')
    FEATURE_CODE: Mapped[Optional[str]] = mapped_column(
        LONGTEXT, comment='微库物料特征码')
    ISSUED_FLAG: Mapped[Optional[str]] = mapped_column(
        CHAR(1), server_default=text("'0'"), comment='是否下发：0 未下发  1 已下发')


class SgoMaterielInfoTree(Base):
    __tablename__ = 'sgo_materiel_info_tree'

    id: Mapped[str] = mapped_column(VARCHAR(32), primary_key=True)
    materiel_code: Mapped[Optional[str]] = mapped_column(VARCHAR(100))
    materiel_name: Mapped[Optional[str]] = mapped_column(VARCHAR(255))
    parent_materiel_code: Mapped[Optional[str]] = mapped_column(VARCHAR(25))
    figure_number: Mapped[Optional[str]] = mapped_column(VARCHAR(100))
    train_type_group: Mapped[Optional[str]] = mapped_column(VARCHAR(40))
    b_vehicle_id: Mapped[Optional[str]] = mapped_column(VARCHAR(32))
    serial_number: Mapped[Optional[str]] = mapped_column(VARCHAR(30))
    column_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(32), comment='板块id')
    tenant_id_: Mapped[Optional[str]] = mapped_column(VARCHAR(64))


class SgoMaterielMasterplate(Base):
    __tablename__ = 'sgo_materiel_masterplate'
    __table_args__ = (
        Index('MATNR_2', 'MATNR', 'column_id'),
        Index('materiel_info_id', 'materiel_info_id'),
        Index('materiel_info_id_2', 'materiel_info_id',
              'column_id', unique=True),
        {'comment': '物料模板数据'}
    )

    id: Mapped[str] = mapped_column(VARCHAR(64), primary_key=True)
    materiel_info_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='物料信息id')
    MATNR: Mapped[Optional[str]] = mapped_column(VARCHAR(12), comment='物料编码')
    mfc_id: Mapped[Optional[str]] = mapped_column(VARCHAR(10), comment='隶属大部件')
    technical_notes: Mapped[Optional[str]] = mapped_column(
        VARCHAR(2000), comment='技术说明')
    gross_weight: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), comment='毛重')
    picture_info: Mapped[Optional[str]] = mapped_column(
        LONGTEXT, comment='识别信息')
    column_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='板块id')
    org_code: Mapped[Optional[str]] = mapped_column(
        VARCHAR(19), comment='创建人组织编码')
    item_type: Mapped[Optional[str]] = mapped_column(
        VARCHAR(32), comment='配件分类/所属部类')
    maintenance_type: Mapped[Optional[str]] = mapped_column(
        VARCHAR(5), comment='运维分类')
    support_level: Mapped[Optional[str]] = mapped_column(
        VARCHAR(5), comment='保障级别(修改为  维护状态  0 未完成   1部分完成  2 已完成)')
    place_class: Mapped[Optional[str]] = mapped_column(
        VARCHAR(5), comment='摆放分类')
    material_class: Mapped[Optional[str]] = mapped_column(
        VARCHAR(5), comment='材质分类')
    create_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='创建时间')
    creater_account: Mapped[Optional[str]] = mapped_column(
        VARCHAR(20), comment='创建人账号')
    creater: Mapped[Optional[str]] = mapped_column(VARCHAR(10), comment='创建人')
    update_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='更新时间')
    updater_account: Mapped[Optional[str]] = mapped_column(
        VARCHAR(20), comment='更新人账号')
    updater: Mapped[Optional[str]] = mapped_column(VARCHAR(10), comment='更新人')
    is_sap: Mapped[Optional[str]] = mapped_column(
        VARCHAR(5), server_default=text("'T1'"), comment='是否SAP管理 T1管 T2不管')
    is_train: Mapped[Optional[str]] = mapped_column(
        VARCHAR(5), server_default=text("'T1'"), comment='是否现车物料 T1现车 T2非现车')
    tenant_id_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), server_default=text("'1463844437338755072'"))
    MATERIEL_TYPE: Mapped[Optional[str]] = mapped_column(
        VARCHAR(2), comment='物料类型 Z自制件  C采购件')
    maktx: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='物料名称')
    vrkme: Mapped[Optional[str]] = mapped_column(VARCHAR(150), comment='单位')
    zeinr: Mapped[Optional[str]] = mapped_column(VARCHAR(150), comment='图号')
    show_status: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='商城展示上下架 0下架 1上架')
    NTGEW: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), comment='\u200c净重')
    use_status: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='使用状态')
    use_illustrate: Mapped[Optional[str]] = mapped_column(
        LONGTEXT, comment='使用说明')
    is_batch: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='是否批次管理 0是 1否')
    inspect_flag: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='检验标识 0是 1否 (变更为采购方式：tzcg停止采购 jzcg集中采购  lscg零散采购)')
    inspect_file: Mapped[Optional[str]] = mapped_column(
        VARCHAR(100), comment='检验文件（并非上传文件类似字段内容）')
    maintenance_notes: Mapped[Optional[str]] = mapped_column(
        VARCHAR(100), comment='保养要求')
    transportation_notes: Mapped[Optional[str]] = mapped_column(
        VARCHAR(100), comment='运输要求')
    maintenance_flag: Mapped[Optional[str]] = mapped_column(
        VARCHAR(5), comment='保养标识  0否  1是')
    min_packing_quantity: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), comment='最小包装量')
    vehicle_info: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), comment='适用车型（为了适应低代码平台展示信息使用）')
    catalog_info: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), comment='目录树（不存储数据，为了适应低代码平台展示信息使用）')
    subjection_info: Mapped[Optional[str]] = mapped_column(
        VARCHAR(100), comment='隶属部件（存储数据，存储下拉框展示内容）')
    wrkst: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='规格(2024-07-09 由于一直没有存储过值，所以使用该字段存储“规格型号”信息，防止浪费)')
    material_quality: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='材料材质（2024-07-09 添加）')
    GROES: Mapped[Optional[str]] = mapped_column(
        VARCHAR(155), comment='强度(2024-07-09 由于一直没有存储过值，所以使用该字段存储“强度等级”信息，防止浪费)')
    pic_flag: Mapped[Optional[str]] = mapped_column(
        CHAR(1), server_default=text("'0'"), comment='图片标识：0 未上传    1 已上传')
    remark: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='备注')
    flag: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='不存储数据，为了低代码平台数据展示使用')
    remark_item: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='不存储数据（为了在所属部类修改时在此模块填写修改原因，加此字段）')
    is_express_suitable: Mapped[Optional[str]] = mapped_column(
        VARCHAR(5), comment='是否适合快递发运（0 适合  1不适合）')

    @classmethod
    async def list_sgo_items(cls, session: AsyncSession):
        stmt = select(cls.id, cls.maktx, cls.MATNR).where(cls.column_id == 'A1')
        result = await session.execute(stmt)
        return result.all()


class SgoMaterielSupplier(Base):
    __tablename__ = 'sgo_materiel_supplier'
    __table_args__ = (
        Index('masterplate_id', 'masterplate_id'),
        Index('supplier_code', 'supplier_code'),
        Index('supplier_code_2', 'supplier_code',
              'masterplate_id', unique=True),
        {'comment': '物料对应供应商'}
    )

    id: Mapped[str] = mapped_column(VARCHAR(64), primary_key=True)
    supplier_code: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='供应商编码')
    supplier_name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='供应商名称')
    masterplate_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='物料模板id')
    supply_cycle: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), comment='供货周期  更名采购周期')
    quality_period: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), comment='保质期')
    warranty_period: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), comment='质保期')
    min_packing_quantity: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), comment='最小包装量')
    min_order_quantity: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), comment='最小起订量')
    maintenance_notes: Mapped[Optional[str]] = mapped_column(
        VARCHAR(200), comment='保养要求')
    transportation_notes: Mapped[Optional[str]] = mapped_column(
        VARCHAR(200), comment='运输要求')
    create_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='创建时间')
    creater_account: Mapped[Optional[str]] = mapped_column(
        VARCHAR(20), comment='创建人账号')
    creater: Mapped[Optional[str]] = mapped_column(VARCHAR(20), comment='创建人')
    tenant_id_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), server_default=text("'1463844437338755072'"))
    top_falg: Mapped[Optional[str]] = mapped_column(
        VARCHAR(5), comment='是否首选供应商')
    supplier_matnr: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='供方物料编码')
    supplier_maktx: Mapped[Optional[str]] = mapped_column(
        VARCHAR(150), comment='供方物料名称')
    supplier_zeinr: Mapped[Optional[str]] = mapped_column(
        VARCHAR(150), comment='供方物料图号')
    supplier_wrkst: Mapped[Optional[str]] = mapped_column(
        VARCHAR(150), comment='供方规格型号')
    supplier_vrkme: Mapped[Optional[str]] = mapped_column(
        VARCHAR(12), comment='供方物料单位')
    maintenance_cycle: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), comment='保养周期(单位:天)')
    description: Mapped[Optional[str]] = mapped_column(
        LONGTEXT, comment='实物介绍')
    model_number: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='实物型号')
    manufacturer: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='制造商')
    technical_standard: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='技术标准')
    product_info_remark: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='实物信息备注')
    temp_price: Mapped[Optional[str]] = mapped_column(
        VARCHAR(15), comment='供应商供货商报价')
    maintenance_level: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='供应商物料维护程度')
    current_status: Mapped[Optional[str]] = mapped_column(VARCHAR(12), server_default=text(
        "'Draft'"), comment='状态：Draft 未发布  Pending 待审核  Published 已发布 Rejected 驳回')
    with_draft: Mapped[Optional[str]] = mapped_column(
        VARCHAR(12), comment='是否需要发布')
    supplier_data_rate: Mapped[Optional[str]] = mapped_column(
        VARCHAR(25), comment='供应商维护信息不为空值的百分比')


class SgoMaterielSyncSap(Base):
    __tablename__ = 'sgo_materiel_sync_sap'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, comment='id')
    matnr: Mapped[Optional[str]] = mapped_column(VARCHAR(12), comment='物料编码')
    data_source_flag: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), comment='数据来源标识：import导入；create数据平台新建')
    creater: Mapped[Optional[str]] = mapped_column(
        VARCHAR(100), comment='创建人账号')
    column_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), comment='板块id')
    sync_time: Mapped[Optional[datetime.datetime]
                      ] = mapped_column(DateTime, comment='同步时间')
    create_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='数据插入时间')
    sap_sync_flag: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), comment='Y；同步成功 N：SAP未下发(默认状态)')


class SgoMaterielVehicle(Base):
    __tablename__ = 'sgo_materiel_vehicle'
    __table_args__ = (
        Index('masterplate_id', 'masterplate_id',
              'vehicle_id', 'vehicle_batch', unique=True),
        Index('materiel_id', 'masterplate_id'),
        Index('vehicle_id', 'vehicle_batch')
    )

    id: Mapped[str] = mapped_column(VARCHAR(32), primary_key=True)
    masterplate_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(32), comment='物料模板id')
    vehicle_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(32), comment='车型id')
    vehicle_batch: Mapped[Optional[str]] = mapped_column(
        VARCHAR(32), comment='车型项目号')
    vehicle_name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='线路名称')
    single_quantity: Mapped[Optional[str]] = mapped_column(
        VARCHAR(10), comment='单组数量')
    create_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='创建时间')
    creater_account: Mapped[Optional[str]] = mapped_column(
        VARCHAR(20), comment='创建人账号')
    creater: Mapped[Optional[str]] = mapped_column(VARCHAR(20), comment='创建人')
    tenant_id_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), server_default=text("'1463844437338755072'"))
    compartment_info: Mapped[Optional[str]] = mapped_column(
        LONGTEXT, comment='车厢详情')


class SgoMaterielVehicleAudit(Base):
    __tablename__ = 'sgo_materiel_vehicle_audit'
    __table_args__ = (
        Index('materiel_id', 'masterplate_id'),
        Index('vehicle_id', 'vehicle_batch')
    )

    id: Mapped[str] = mapped_column(VARCHAR(32), primary_key=True)
    masterplate_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(32), comment='物料模板id')
    vehicle_id: Mapped[Optional[str]] = mapped_column(
        VARCHAR(32), comment='车型id')
    vehicle_batch: Mapped[Optional[str]] = mapped_column(
        VARCHAR(32), comment='车型项目号')
    vehicle_name: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='线路名称')
    audit_status: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='审核状态（Y: 已审核发布  N: 未审核发布）')
    create_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='创建时间')
    creater_account: Mapped[Optional[str]] = mapped_column(
        VARCHAR(20), comment='创建人账号')
    creater: Mapped[Optional[str]] = mapped_column(VARCHAR(20), comment='创建人')
    tenant_id_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), server_default=text("'1463844437338755072'"))
    update_time: Mapped[Optional[datetime.datetime]
                        ] = mapped_column(DateTime, comment='更新时间')
    update_account: Mapped[Optional[str]] = mapped_column(
        VARCHAR(50), comment='更新人账号')
    updater: Mapped[Optional[str]] = mapped_column(
        VARCHAR(20), comment='更新人姓名')
    combined_column: Mapped[Optional[str]] = mapped_column(VARCHAR(255), Computed(
        "(concat_ws(_utf8mb3'_',`masterplate_id`,`vehicle_batch`))", persisted=True), comment='计算列：masterplate_id+"_"+vehicle_batch 确定唯一值')


class SgoVehicle(Base):
    __tablename__ = 'sgo_vehicle'
    __table_args__ = {'comment': '车型'}

    id: Mapped[str] = mapped_column(VARCHAR(32), primary_key=True)
    column_id: Mapped[Optional[str]] = mapped_column(VARCHAR(32), comment='板块')
    vehicle_batch: Mapped[Optional[str]] = mapped_column(VARCHAR(20))
    vehicle_name: Mapped[Optional[str]] = mapped_column(VARCHAR(50))
    vehicle_desc: Mapped[Optional[str]] = mapped_column(VARCHAR(150))
    IS_IETM: Mapped[Optional[str]] = mapped_column(
        VARCHAR(5), server_default=text("'N'"))
    vehicle_type: Mapped[Optional[str]] = mapped_column(
        VARCHAR(5), comment='A1:动车;A3地铁')
    tenant_id_: Mapped[Optional[str]] = mapped_column(VARCHAR(32))
    sap_vehicle_no: Mapped[Optional[str]] = mapped_column(VARCHAR(5))
    first_item: Mapped[Optional[str]] = mapped_column(
        VARCHAR(150), comment='顶级节点编码')
    yz_vehicle_no: Mapped[Optional[str]] = mapped_column(
        VARCHAR(32), comment='pms(云平台)线别对应id')
    marshalling: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='编组')
    mro_code: Mapped[Optional[str]] = mapped_column(
        VARCHAR(12), comment='MRO代号')
    phm_code: Mapped[Optional[str]] = mapped_column(
        VARCHAR(12), comment='PHM代号')
    grouping_count: Mapped[Optional[str]] = mapped_column(
        VARCHAR(12), comment='编组数量')
    grouping_info: Mapped[Optional[str]] = mapped_column(
        VARCHAR(254), comment='编组信息')


class ActGeBytearray(Base):
    __tablename__ = 'act_ge_bytearray'
    __table_args__ = (
        ForeignKeyConstraint(['DEPLOYMENT_ID_'], ['act_re_deployment.ID_'],
                             ondelete='RESTRICT', onupdate='RESTRICT', name='ACT_FK_BYTEARR_DEPL'),
        Index('ACT_FK_BYTEARR_DEPL', 'DEPLOYMENT_ID_'),
        {'comment': '二进制内容表'}
    )

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    REV_: Mapped[Optional[int]] = mapped_column(Integer, comment='乐观锁')
    NAME_: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='名称')
    DEPLOYMENT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='部署')
    BYTES_: Mapped[Optional[bytes]] = mapped_column(LONGBLOB, comment='内容')
    GENERATED_: Mapped[Optional[int]] = mapped_column(
        TINYINT, comment='0为用户上传，1为系统自动生成')

    act_re_deployment: Mapped[Optional['ActReDeployment']] = relationship(
        'ActReDeployment', back_populates='act_ge_bytearray')
    act_procdef_info: Mapped[list['ActProcdefInfo']] = relationship(
        'ActProcdefInfo', back_populates='act_ge_bytearray')
    act_re_model: Mapped[list['ActReModel']] = relationship(
        'ActReModel', foreign_keys='[ActReModel.EDITOR_SOURCE_EXTRA_VALUE_ID_]', back_populates='act_ge_bytearray')
    act_re_model_: Mapped[list['ActReModel']] = relationship(
        'ActReModel', foreign_keys='[ActReModel.EDITOR_SOURCE_VALUE_ID_]', back_populates='act_ge_bytearray_')
    act_ru_job: Mapped[list['ActRuJob']] = relationship(
        'ActRuJob', back_populates='act_ge_bytearray')
    act_ru_variable: Mapped[list['ActRuVariable']] = relationship(
        'ActRuVariable', back_populates='act_ge_bytearray')


class ActRuExecution(Base):
    __tablename__ = 'act_ru_execution'
    __table_args__ = (
        ForeignKeyConstraint(['PROC_DEF_ID_'], ['act_re_procdef.ID_'],
                             ondelete='RESTRICT', onupdate='RESTRICT', name='ACT_FK_EXE_PROCDEF'),
        Index('ACT_FK_EXE_PROCDEF', 'PROC_DEF_ID_'),
        Index('ACT_IDX_EXEC_BUSKEY', 'BUSINESS_KEY_'),
        {'comment': '执行'}
    )

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    REV_: Mapped[Optional[int]] = mapped_column(Integer, comment='乐观锁')
    PROC_INST_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='流程实例')
    BUSINESS_KEY_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='业务标识')
    PARENT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='父执行')
    PROC_DEF_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='流程定义')
    SUPER_EXEC_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='父流程实例中对应的执行')
    ACT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='环节ID')
    IS_ACTIVE_: Mapped[Optional[int]] = mapped_column(TINYINT, comment='是否激活')
    IS_CONCURRENT_: Mapped[Optional[int]] = mapped_column(
        TINYINT, comment='是否并行分支')
    IS_SCOPE_: Mapped[Optional[int]] = mapped_column(
        TINYINT, comment='是否处于多实例或环节嵌套状态')
    IS_EVENT_SCOPE_: Mapped[Optional[int]] = mapped_column(
        TINYINT, comment='是否激活状态')
    SUSPENSION_STATE_: Mapped[Optional[int]] = mapped_column(
        Integer, comment='暂停状态 1激活 2暂停')
    CACHED_ENT_STATE_: Mapped[Optional[int]] = mapped_column(
        Integer, comment='缓存的状态，事件监听第一位 人工任务第2位异步作业第三位')
    TENANT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), server_default=text("''"), comment='多租户')
    NAME_: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='名称')
    LOCK_TIME_: Mapped[Optional[datetime.datetime]
                       ] = mapped_column(TIMESTAMP, comment='锁定时间')

    act_re_procdef: Mapped[Optional['ActReProcdef']] = relationship(
        'ActReProcdef', back_populates='act_ru_execution')
    act_ru_event_subscr: Mapped[list['ActRuEventSubscr']] = relationship(
        'ActRuEventSubscr', back_populates='act_ru_execution')
    act_ru_variable: Mapped[list['ActRuVariable']] = relationship(
        'ActRuVariable', foreign_keys='[ActRuVariable.EXECUTION_ID_]', back_populates='act_ru_execution')
    act_ru_variable_: Mapped[list['ActRuVariable']] = relationship(
        'ActRuVariable', foreign_keys='[ActRuVariable.PROC_INST_ID_]', back_populates='act_ru_execution_')


class ActProcdefInfo(Base):
    __tablename__ = 'act_procdef_info'
    __table_args__ = (
        ForeignKeyConstraint(['INFO_JSON_ID_'], ['act_ge_bytearray.ID_'],
                             ondelete='RESTRICT', onupdate='RESTRICT', name='ACT_FK_INFO_JSON_BA'),
        ForeignKeyConstraint(['PROC_DEF_ID_'], ['act_re_procdef.ID_'],
                             ondelete='RESTRICT', onupdate='RESTRICT', name='ACT_FK_INFO_PROCDEF'),
        Index('ACT_FK_INFO_JSON_BA', 'INFO_JSON_ID_'),
        Index('ACT_IDX_INFO_PROCDEF', 'PROC_DEF_ID_'),
        Index('ACT_UNIQ_INFO_PROCDEF', 'PROC_DEF_ID_', unique=True),
        {'comment': '流程定义更新信息'}
    )

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    PROC_DEF_ID_: Mapped[str] = mapped_column(
        VARCHAR(64), nullable=False, comment='流程定义')
    REV_: Mapped[Optional[int]] = mapped_column(Integer, comment='乐观锁')
    INFO_JSON_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='内容')

    act_ge_bytearray: Mapped[Optional['ActGeBytearray']] = relationship(
        'ActGeBytearray', back_populates='act_procdef_info')
    act_re_procdef: Mapped['ActReProcdef'] = relationship(
        'ActReProcdef', back_populates='act_procdef_info')


class ActReModel(Base):
    __tablename__ = 'act_re_model'
    __table_args__ = (
        ForeignKeyConstraint(['DEPLOYMENT_ID_'], ['act_re_deployment.ID_'],
                             ondelete='RESTRICT', onupdate='RESTRICT', name='ACT_FK_MODEL_DEPLOYMENT'),
        ForeignKeyConstraint(['EDITOR_SOURCE_EXTRA_VALUE_ID_'], ['act_ge_bytearray.ID_'],
                             ondelete='RESTRICT', onupdate='RESTRICT', name='ACT_FK_MODEL_SOURCE_EXTRA'),
        ForeignKeyConstraint(['EDITOR_SOURCE_VALUE_ID_'], ['act_ge_bytearray.ID_'],
                             ondelete='RESTRICT', onupdate='RESTRICT', name='ACT_FK_MODEL_SOURCE'),
        Index('ACT_FK_MODEL_DEPLOYMENT', 'DEPLOYMENT_ID_'),
        Index('ACT_FK_MODEL_SOURCE', 'EDITOR_SOURCE_VALUE_ID_'),
        Index('ACT_FK_MODEL_SOURCE_EXTRA', 'EDITOR_SOURCE_EXTRA_VALUE_ID_'),
        {'comment': '模型'}
    )

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    REV_: Mapped[Optional[int]] = mapped_column(Integer, comment='乐观锁')
    NAME_: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='名称')
    KEY_: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='标识')
    CATEGORY_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='分类')
    CREATE_TIME_: Mapped[Optional[datetime.datetime]
                         ] = mapped_column(TIMESTAMP, comment='创建时间')
    LAST_UPDATE_TIME_: Mapped[Optional[datetime.datetime]
                              ] = mapped_column(TIMESTAMP, comment='最后更新时间')
    VERSION_: Mapped[Optional[int]] = mapped_column(Integer, comment='版本')
    META_INFO_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(4000), comment='元数据')
    DEPLOYMENT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='部署')
    EDITOR_SOURCE_VALUE_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='设计器原始信息')
    EDITOR_SOURCE_EXTRA_VALUE_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='设计器扩展信息')
    TENANT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), server_default=text("''"), comment='多租户')

    act_re_deployment: Mapped[Optional['ActReDeployment']] = relationship(
        'ActReDeployment', back_populates='act_re_model')
    act_ge_bytearray: Mapped[Optional['ActGeBytearray']] = relationship(
        'ActGeBytearray', foreign_keys=[EDITOR_SOURCE_EXTRA_VALUE_ID_], back_populates='act_re_model')
    act_ge_bytearray_: Mapped[Optional['ActGeBytearray']] = relationship(
        'ActGeBytearray', foreign_keys=[EDITOR_SOURCE_VALUE_ID_], back_populates='act_re_model_')


class ActRuEventSubscr(Base):
    __tablename__ = 'act_ru_event_subscr'
    __table_args__ = (
        ForeignKeyConstraint(['EXECUTION_ID_'], ['act_ru_execution.ID_'],
                             ondelete='RESTRICT', onupdate='RESTRICT', name='ACT_FK_EVENT_EXEC'),
        Index('ACT_FK_EVENT_EXEC', 'EXECUTION_ID_'),
        Index('ACT_IDX_EVENT_SUBSCR_CONFIG_', 'CONFIGURATION_'),
        {'comment': '事件订阅'}
    )

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    EVENT_TYPE_: Mapped[str] = mapped_column(
        VARCHAR(255), nullable=False, comment='类型')
    CREATED_: Mapped[datetime.datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text('CURRENT_TIMESTAMP'), comment='创建时间')
    REV_: Mapped[Optional[int]] = mapped_column(Integer, comment='乐观锁')
    EVENT_NAME_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='名称')
    EXECUTION_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='执行')
    PROC_INST_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='流程实例')
    ACTIVITY_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='环节ID')
    CONFIGURATION_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='配置')
    PROC_DEF_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='流程定义')
    TENANT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), server_default=text("''"), comment='多租户')

    act_ru_execution: Mapped[Optional['ActRuExecution']] = relationship(
        'ActRuExecution', back_populates='act_ru_event_subscr')


class ActRuJob(Base):
    __tablename__ = 'act_ru_job'
    __table_args__ = (
        ForeignKeyConstraint(['EXCEPTION_STACK_ID_'], ['act_ge_bytearray.ID_'],
                             ondelete='RESTRICT', onupdate='RESTRICT', name='ACT_FK_JOB_EXCEPTION'),
        Index('ACT_FK_JOB_EXCEPTION', 'EXCEPTION_STACK_ID_'),
        {'comment': '异步作业'}
    )

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    TYPE_: Mapped[str] = mapped_column(
        VARCHAR(255), nullable=False, comment='类型')
    REV_: Mapped[Optional[int]] = mapped_column(Integer, comment='乐观锁')
    LOCK_EXP_TIME_: Mapped[Optional[datetime.datetime]
                           ] = mapped_column(TIMESTAMP, comment='锁定过期时间')
    LOCK_OWNER_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='锁定节点')
    EXCLUSIVE_: Mapped[Optional[int]] = mapped_column(
        TINYINT(1), comment='是否唯一')
    EXECUTION_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='执行')
    PROCESS_INSTANCE_ID_: Mapped[Optional[str]
                                 ] = mapped_column(VARCHAR(64), comment='流程实例')
    PROC_DEF_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='流程定义')
    RETRIES_: Mapped[Optional[int]] = mapped_column(Integer, comment='重试次数')
    EXCEPTION_STACK_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='异常堆栈')
    EXCEPTION_MSG_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(4000), comment='异常信息')
    DUEDATE_: Mapped[Optional[datetime.datetime]
                     ] = mapped_column(TIMESTAMP, comment='截止时间')
    REPEAT_: Mapped[Optional[str]] = mapped_column(VARCHAR(255), comment='重复')
    HANDLER_TYPE_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), comment='处理器类型')
    HANDLER_CFG_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(4000), comment='处理器配置')
    TENANT_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(255), server_default=text("''"), comment='多租户')

    act_ge_bytearray: Mapped[Optional['ActGeBytearray']] = relationship(
        'ActGeBytearray', back_populates='act_ru_job')


class ActRuVariable(Base):
    __tablename__ = 'act_ru_variable'
    __table_args__ = (
        ForeignKeyConstraint(['BYTEARRAY_ID_'], ['act_ge_bytearray.ID_'],
                             ondelete='RESTRICT', onupdate='RESTRICT', name='ACT_FK_VAR_BYTEARRAY'),
        ForeignKeyConstraint(['EXECUTION_ID_'], ['act_ru_execution.ID_'],
                             ondelete='RESTRICT', onupdate='RESTRICT', name='ACT_FK_VAR_EXE'),
        ForeignKeyConstraint(['PROC_INST_ID_'], ['act_ru_execution.ID_'],
                             ondelete='RESTRICT', onupdate='RESTRICT', name='ACT_FK_VAR_PROCINST'),
        Index('ACT_FK_VAR_BYTEARRAY', 'BYTEARRAY_ID_'),
        Index('ACT_FK_VAR_EXE', 'EXECUTION_ID_'),
        Index('ACT_FK_VAR_PROCINST', 'PROC_INST_ID_'),
        Index('ACT_IDX_VARIABLE_TASK_ID', 'TASK_ID_'),
        {'comment': '变量'}
    )

    ID_: Mapped[str] = mapped_column(
        VARCHAR(64), primary_key=True, comment='主键')
    TYPE_: Mapped[str] = mapped_column(
        VARCHAR(255), nullable=False, comment='类型')
    NAME_: Mapped[str] = mapped_column(
        VARCHAR(255), nullable=False, comment='名称')
    REV_: Mapped[Optional[int]] = mapped_column(Integer, comment='乐观锁')
    EXECUTION_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='执行')
    PROC_INST_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='流程实例')
    TASK_ID_: Mapped[Optional[str]] = mapped_column(VARCHAR(64), comment='任务')
    BYTEARRAY_ID_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(64), comment='内容')
    DOUBLE_: Mapped[Optional[decimal.Decimal]] = mapped_column(
        Double(asdecimal=True), comment='浮点值')
    LONG_: Mapped[Optional[int]] = mapped_column(BigInteger, comment='长整数值')
    TEXT_: Mapped[Optional[str]] = mapped_column(VARCHAR(4000), comment='文本值')
    TEXT2_: Mapped[Optional[str]] = mapped_column(
        VARCHAR(4000), comment='jpa变量text存className,text2存id')

    act_ge_bytearray: Mapped[Optional['ActGeBytearray']] = relationship(
        'ActGeBytearray', back_populates='act_ru_variable')
    act_ru_execution: Mapped[Optional['ActRuExecution']] = relationship(
        'ActRuExecution', foreign_keys=[EXECUTION_ID_], back_populates='act_ru_variable')
    act_ru_execution_: Mapped[Optional['ActRuExecution']] = relationship(
        'ActRuExecution', foreign_keys=[PROC_INST_ID_], back_populates='act_ru_variable_')
