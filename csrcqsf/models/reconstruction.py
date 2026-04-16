"""
三维重构记录模型
"""
from __future__ import annotations
from enum import Enum
from sqlalchemy import String, Text, INT, BIGINT, Float, select
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.ext.asyncio import AsyncSession
from csrcqsf.data.pg import Base


class ReconstructionStatus(str, Enum):
    """重构任务状态"""
    PENDING = 'pending'           # 等待中
    EXTRACTING = 'extracting'     # 提帧中
    FILTERING = 'filtering'       # 帧筛选中
    COLMAP = 'colmap'            # COLMAP处理中
    SAM3 = 'sam3'                # SAM3分割中
    TRAINING = 'training'         # 训练中
    CONVERTING = 'converting'     # 转换中
    SUCCESS = 'success'           # 成功
    FAILED = 'failed'             # 失败
    CANCELLED = 'cancelled'       # 已取消


class ReconstructionRecord(Base):
    """三维重构记录表"""
    __tablename__ = 'reconstruction_records'
    
    # 关联字段
    item_id: Mapped[int] = mapped_column(BIGINT, nullable=False, index=True, comment='配件ID，关联item_info表')
    
    # 任务信息
    task_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True, comment='Celery任务ID')
    task_type: Mapped[str] = mapped_column(String(50), nullable=False, comment='任务类型: train/video')
    status: Mapped[str] = mapped_column(String(50), nullable=False, default=ReconstructionStatus.PENDING, comment='任务状态')
    
    # 输入参数
    video_path: Mapped[str] = mapped_column(String(500), nullable=True, comment='视频文件路径（video模式）')
    scene_name: Mapped[str] = mapped_column(String(200), nullable=True, comment='场景名称')
    iterations: Mapped[int] = mapped_column(INT, nullable=False, default=30000, comment='训练迭代次数')
    
    # 进度信息
    progress: Mapped[int] = mapped_column(INT, nullable=False, default=0, comment='进度百分比 0-100')
    current_stage: Mapped[str] = mapped_column(String(100), nullable=True, comment='当前阶段描述')
    
    # 统计信息
    total_frames: Mapped[int] = mapped_column(INT, nullable=True, comment='总帧数')
    filtered_frames: Mapped[int] = mapped_column(INT, nullable=True, comment='筛选后帧数')
    colmap_points: Mapped[int] = mapped_column(INT, nullable=True, comment='COLMAP点云数量')
    
    # 结果信息
    output_path: Mapped[str] = mapped_column(String(500), nullable=True, comment='输出目录路径')
    ply_url: Mapped[str] = mapped_column(String(500), nullable=True, comment='PLY文件URL')
    obj_url: Mapped[str] = mapped_column(String(500), nullable=True, comment='OBJ文件URL')
    glb_url: Mapped[str] = mapped_column(String(500), nullable=True, comment='GLB文件URL')
    
    # 错误信息
    error_message: Mapped[str] = mapped_column(Text, nullable=True, comment='错误信息')
    
    # 时间戳（继承自Base类）
    # time_created, time_updated 会自动添加
    
    @classmethod
    async def create_record(
        cls,
        session: AsyncSession,
        item_id: int,
        task_id: str,
        task_type: str,
        scene_name: str = None,
        video_path: str = None,
        iterations: int = 30000
    ) -> ReconstructionRecord:
        """创建重构记录"""
        record = cls(
            item_id=item_id,
            task_id=task_id,
            task_type=task_type,
            scene_name=scene_name,
            video_path=video_path,
            iterations=iterations,
            status=ReconstructionStatus.PENDING,
            progress=0
        )
        session.add(record)
        await session.flush()
        return record
    
    @classmethod
    async def get_by_task_id(cls, session: AsyncSession, task_id: str) -> ReconstructionRecord | None:
        """根据任务ID查询记录"""
        stmt = select(cls).where(cls.task_id == task_id)
        return await session.scalar(stmt)
    
    @classmethod
    async def get_by_item_id(cls, session: AsyncSession, item_id: int) -> list[ReconstructionRecord]:
        """根据配件ID查询所有重构记录"""
        stmt = select(cls).where(cls.item_id == item_id).order_by(cls.time_created.desc())
        result = await session.scalars(stmt)
        return list(result)
    
    @classmethod
    async def get_latest_by_item_id(cls, session: AsyncSession, item_id: int) -> ReconstructionRecord | None:
        """获取配件的最新重构记录"""
        stmt = select(cls).where(cls.item_id == item_id).order_by(cls.time_created.desc()).limit(1)
        return await session.scalar(stmt)
    
    @classmethod
    async def get_all_tasks(
        cls,
        session: AsyncSession,
        status: str = None,
        limit: int = 100,
        offset: int = 0
    ) -> tuple[list[ReconstructionRecord], int]:
        """
        获取所有重构任务（支持分页和状态筛选）
        
        Args:
            session: 数据库会话
            status: 任务状态筛选（可选）
            limit: 每页数量
            offset: 偏移量
            
        Returns:
            tuple: (记录列表, 总数)
        """
        from sqlalchemy import func
        
        # 构建查询
        stmt = select(cls)
        count_stmt = select(func.count(cls.id))
        
        # 状态筛选
        if status:
            stmt = stmt.where(cls.status == status)
            count_stmt = count_stmt.where(cls.status == status)
        
        # 获取总数
        total = await session.scalar(count_stmt)
        
        # 分页和排序
        stmt = stmt.order_by(cls.time_created.desc()).limit(limit).offset(offset)
        result = await session.scalars(stmt)
        
        return list(result), total or 0
    
    @classmethod
    async def update_status(
        cls,
        session: AsyncSession,
        task_id: str,
        status: str,
        progress: int = None,
        current_stage: str = None,
        error_message: str = None
    ):
        """更新任务状态"""
        record = await cls.get_by_task_id(session, task_id)
        if record:
            record.status = status
            if progress is not None:
                record.progress = progress
            if current_stage is not None:
                record.current_stage = current_stage
            if error_message is not None:
                record.error_message = error_message
            await session.flush()
    
    @classmethod
    async def update_result(
        cls,
        session: AsyncSession,
        task_id: str,
        output_path: str = None,
        ply_url: str = None,
        obj_url: str = None,
        glb_url: str = None,
        colmap_points: int = None
    ):
        """更新重构结果"""
        record = await cls.get_by_task_id(session, task_id)
        if record:
            if output_path:
                record.output_path = output_path
            if ply_url:
                record.ply_url = ply_url
            if obj_url:
                record.obj_url = obj_url
            if glb_url:
                record.glb_url = glb_url
            if colmap_points is not None:
                record.colmap_points = colmap_points
            await session.flush()
