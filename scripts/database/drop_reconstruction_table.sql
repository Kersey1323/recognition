-- 删除三维重构记录表
DROP TABLE IF EXISTS parts.reconstruction_records CASCADE;
DROP FUNCTION IF EXISTS parts.update_reconstruction_time_updated() CASCADE;
