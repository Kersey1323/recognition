#!/usr/bin/env python3
"""检查数据库中进行中的任务"""
import sys
import asyncio
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from csrcqsf.data.pg import SessionLocal
from csrcqsf.models.reconstruction import ReconstructionRecord, ReconstructionStatus
from sqlalchemy import select, or_

async def check():
    async with SessionLocal() as session:
        stmt = select(ReconstructionRecord).where(
            or_(
                ReconstructionRecord.status == ReconstructionStatus.PENDING,
                ReconstructionRecord.status == ReconstructionStatus.TRAINING
            )
        )
        result = await session.execute(stmt)
        tasks = result.scalars().all()
        
        print(f'进行中的任务数: {len(tasks)}')
        for t in tasks[:5]:
            print(f'  - {t.task_id}: {t.status}, progress={t.progress}, stage={t.current_stage}')

asyncio.run(check())
