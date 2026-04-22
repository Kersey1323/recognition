from csrcqsf.biz.railwayparts.reconstruction_api_models import (
    ReconstructionAllTasksRes,
    ReconstructionIndexRebuildRes,
    ReconstructionStatusRes,
    ReconstructionTrainReq,
    ReconstructionTaskListItem,
    ReconstructionTaskRes,
    ReconstructionVideoReq,
    ReconstructionVideoUploadRes,
)


BIG_ITEM_ID = 1935558010375340032


def dump_model(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def test_reconstruction_task_response_serializes_item_id_as_string():
    res = ReconstructionTaskRes(
        task_id="2db366e0-f619-476e-b365-93498be7c5a0",
        item_id=BIG_ITEM_ID,
        mode="video",
        message="视频重建任务已提交",
    )

    data = dump_model(res)

    assert data["item_id"] == str(BIG_ITEM_ID)
    assert isinstance(data["item_id"], str)


def test_reconstruction_train_request_keeps_item_id_as_string():
    req = ReconstructionTrainReq(
        item_id=str(BIG_ITEM_ID),
        scene="demo",
        iterations=10000,
    )

    assert req.item_id == str(BIG_ITEM_ID)
    assert isinstance(req.item_id, str)


def test_reconstruction_video_request_keeps_item_id_as_string():
    req = ReconstructionVideoReq(
        item_id=str(BIG_ITEM_ID),
        video_path="/tmp/demo.mp4",
        name="demo",
    )

    assert req.item_id == str(BIG_ITEM_ID)
    assert isinstance(req.item_id, str)


def test_reconstruction_video_upload_response_serializes_item_id_as_string():
    res = ReconstructionVideoUploadRes(
        item_id=BIG_ITEM_ID,
        bucket="bfr-3d-videos",
        object_name="raw-videos/1935558010375340032/demo.mp4",
        video_path="bfr-3d-videos/raw-videos/1935558010375340032/demo.mp4",
        size=1024,
        content_type="video/mp4",
        message="原始视频上传成功",
    )

    data = dump_model(res)

    assert data["item_id"] == str(BIG_ITEM_ID)
    assert isinstance(data["item_id"], str)


def test_reconstruction_status_response_serializes_item_id_as_string():
    res = ReconstructionStatusRes(
        task_id="2db366e0-f619-476e-b365-93498be7c5a0",
        item_id=BIG_ITEM_ID,
        status="success",
        progress=100,
    )

    data = dump_model(res)

    assert data["item_id"] == str(BIG_ITEM_ID)
    assert isinstance(data["item_id"], str)


def test_reconstruction_task_list_item_serializes_item_id_as_string():
    res = ReconstructionTaskListItem(
        task_id="2db366e0-f619-476e-b365-93498be7c5a0",
        item_id=BIG_ITEM_ID,
        task_type="video",
        status="success",
        progress=100,
        current_stage="完成",
        scene_name="string",
        error_message=None,
        ply_url=None,
        obj_url=None,
        glb_url=None,
        total_frames=None,
        filtered_frames=None,
        colmap_points=None,
        time_created="2026-04-21T17:17:11.087360",
        time_updated="2026-04-21T09:19:35.576566",
    )

    data = dump_model(res)

    assert data["item_id"] == str(BIG_ITEM_ID)
    assert isinstance(data["item_id"], str)


def test_reconstruction_all_tasks_response_serializes_nested_item_id_as_string():
    res = ReconstructionAllTasksRes(
        total=1,
        limit=100,
        offset=0,
        records=[
            {
                "task_id": "2db366e0-f619-476e-b365-93498be7c5a0",
                "item_id": BIG_ITEM_ID,
                "task_type": "video",
                "status": "success",
                "progress": 100,
                "current_stage": "完成",
                "scene_name": "string",
                "error_message": None,
                "ply_url": None,
                "obj_url": None,
                "glb_url": None,
                "total_frames": None,
                "filtered_frames": None,
                "colmap_points": None,
                "time_created": "2026-04-21T17:17:11.087360",
                "time_updated": "2026-04-21T09:19:35.576566",
            }
        ],
    )

    data = dump_model(res)

    assert data["records"][0]["item_id"] == str(BIG_ITEM_ID)
    assert isinstance(data["records"][0]["item_id"], str)


def test_reconstruction_index_rebuild_response_serializes_item_id_as_string():
    res = ReconstructionIndexRebuildRes(
        message="Index rebuild task started in background",
        item_id=BIG_ITEM_ID,
        limit="all",
    )

    data = dump_model(res)

    assert data["item_id"] == str(BIG_ITEM_ID)
    assert isinstance(data["item_id"], str)


def test_reconstruction_source_video_response_serializes_item_id_as_string():
    from csrcqsf.biz.railwayparts.reconstruction_api_models import ReconstructionSourceVideoRes

    res = ReconstructionSourceVideoRes(
        item_id=BIG_ITEM_ID,
        item_name="配件A",
        item_code="A001",
        height=10.0,
        length=20.0,
        width=30.0,
        weight=40.0,
        video_path="bfr-3d-videos/raw-videos/1935558010375340032/demo.mp4",
        filename="demo.mp4",
        size=1024,
        content_type="video/mp4",
        source_video_updated_at="2026-04-22T10:00:00",
        message="原始视频查询成功",
    )

    data = dump_model(res)

    assert data["item_id"] == str(BIG_ITEM_ID)
    assert isinstance(data["item_id"], str)
    assert data["video_path"] == "bfr-3d-videos/raw-videos/1935558010375340032/demo.mp4"
    assert data["length"] == 20.0


def test_reconstruction_source_video_list_response_serializes_nested_item_id_as_string():
    from csrcqsf.biz.railwayparts.reconstruction_api_models import ReconstructionSourceVideoListRes

    res = ReconstructionSourceVideoListRes(
        total=1,
        limit=100,
        offset=0,
        records=[
            {
                "item_id": BIG_ITEM_ID,
                "item_name": "配件A",
                "item_code": "A001",
                "height": 10.0,
                "length": 20.0,
                "width": 30.0,
                "weight": 40.0,
                "video_path": "bfr-3d-videos/raw-videos/1935558010375340032/demo.mp4",
                "filename": "demo.mp4",
                "size": 1024,
                "content_type": "video/mp4",
                "source_video_updated_at": "2026-04-22T10:00:00",
                "message": None,
            }
        ],
    )

    data = dump_model(res)

    assert data["records"][0]["item_id"] == str(BIG_ITEM_ID)
    assert isinstance(data["records"][0]["item_id"], str)
    assert data["records"][0]["filename"] == "demo.mp4"


def test_reconstruction_source_video_message_response_serializes_item_id_as_string():
    from csrcqsf.biz.railwayparts.reconstruction_api_models import ReconstructionSourceVideoMessageRes

    res = ReconstructionSourceVideoMessageRes(
        item_id=BIG_ITEM_ID,
        message="原始视频删除成功",
    )

    data = dump_model(res)

    assert data["item_id"] == str(BIG_ITEM_ID)
    assert data["message"] == "原始视频删除成功"
