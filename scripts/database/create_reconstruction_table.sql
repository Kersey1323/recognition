-- 创建三维重构记录表
-- 用于记录配件的三维重构任务和结果

CREATE TABLE IF NOT EXISTS parts.reconstruction_records (
    id BIGSERIAL PRIMARY KEY,
    
    -- 关联字段
    item_id BIGINT NOT NULL,  -- 配件ID，关联 item_info 表
    
    -- 任务信息
    task_id VARCHAR(100) NOT NULL UNIQUE,  -- Celery 任务ID
    task_type VARCHAR(50) NOT NULL,  -- 任务类型: train/video
    status VARCHAR(50) NOT NULL DEFAULT 'pending',  -- 任务状态
    
    -- 输入参数
    video_path VARCHAR(500),  -- 视频文件路径（video模式）
    scene_name VARCHAR(200),  -- 场景名称
    iterations INT NOT NULL DEFAULT 30000,  -- 训练迭代次数
    
    -- 进度信息
    progress INT NOT NULL DEFAULT 0,  -- 进度百分比 0-100
    current_stage VARCHAR(100),  -- 当前阶段描述
    
    -- 统计信息
    total_frames INT,  -- 总帧数
    filtered_frames INT,  -- 筛选后帧数
    colmap_points INT,  -- COLMAP点云数量
    
    -- 结果信息
    output_path VARCHAR(500),  -- 输出目录路径
    ply_url VARCHAR(500),  -- PLY文件URL
    obj_url VARCHAR(500),  -- OBJ文件URL
    glb_url VARCHAR(500),  -- GLB文件URL
    
    -- 错误信息
    error_message TEXT,  -- 错误信息
    
    -- 审计字段（与 Base 类保持一致）
    created_by BIGINT NOT NULL DEFAULT 0,
    updated_by BIGINT NOT NULL DEFAULT 0,
    time_created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    time_updated TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    
    -- 索引
    CONSTRAINT fk_item FOREIGN KEY (item_id) REFERENCES parts.item_info(id) ON DELETE CASCADE
);

-- 创建索引
CREATE INDEX IF NOT EXISTS idx_reconstruction_item_id ON parts.reconstruction_records(item_id);
CREATE INDEX IF NOT EXISTS idx_reconstruction_task_id ON parts.reconstruction_records(task_id);
CREATE INDEX IF NOT EXISTS idx_reconstruction_status ON parts.reconstruction_records(status);
CREATE INDEX IF NOT EXISTS idx_reconstruction_time_created ON parts.reconstruction_records(time_created DESC);

-- 创建更新时间触发器
CREATE OR REPLACE FUNCTION parts.update_reconstruction_time_updated()
RETURNS TRIGGER AS $$
BEGIN
    NEW.time_updated = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_reconstruction_time_updated ON parts.reconstruction_records;
CREATE TRIGGER trigger_update_reconstruction_time_updated
    BEFORE UPDATE ON parts.reconstruction_records
    FOR EACH ROW
    EXECUTE FUNCTION parts.update_reconstruction_time_updated();

-- 添加注释
COMMENT ON TABLE parts.reconstruction_records IS '三维重构记录表';
COMMENT ON COLUMN parts.reconstruction_records.item_id IS '配件ID，关联item_info表';
COMMENT ON COLUMN parts.reconstruction_records.task_id IS 'Celery任务ID';
COMMENT ON COLUMN parts.reconstruction_records.task_type IS '任务类型: train/video';
COMMENT ON COLUMN parts.reconstruction_records.status IS '任务状态: pending/extracting/filtering/colmap/sam3/training/converting/success/failed/cancelled';
COMMENT ON COLUMN parts.reconstruction_records.progress IS '进度百分比 0-100';
COMMENT ON COLUMN parts.reconstruction_records.ply_url IS 'PLY文件URL（3DGS原始输出）';
COMMENT ON COLUMN parts.reconstruction_records.obj_url IS 'OBJ文件URL（网格模型）';
COMMENT ON COLUMN parts.reconstruction_records.glb_url IS 'GLB文件URL（Web展示）';
