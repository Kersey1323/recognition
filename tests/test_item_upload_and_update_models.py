from pydantic import ValidationError

from csrcqsf.biz.railwayparts.api_models import (
    CreateItemImagesReq,
    CreateItemImagesRes,
    UpdateItemReq,
)
from csrcqsf.biz.railwayparts.reconstruction_api_models import (
    ReconstructionResultUploadRes,
)


BIG_ITEM_ID = 1935558010375340032


def dump_model(model):
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model.dict()


def test_create_item_images_request_keeps_images_url_for_compatibility():
    req = CreateItemImagesReq(
        item_id=str(BIG_ITEM_ID),
        images_url=["bfr-ai-files/manual/demo-1.jpg"],
    )

    assert req.item_id == str(BIG_ITEM_ID)
    assert req.images_url == ["bfr-ai-files/manual/demo-1.jpg"]


def test_create_item_images_response_serializes_item_id_and_records():
    res = CreateItemImagesRes(
        item_id=BIG_ITEM_ID,
        uploaded_count=2,
        records=[
            {
                "image_id": BIG_ITEM_ID,
                "image_url": "bfr-ai-files/manual-upload/1/a.jpg",
                "filename": "a.jpg",
            }
        ],
        message="配件图片上传成功",
    )

    data = dump_model(res)

    assert data["item_id"] == str(BIG_ITEM_ID)
    assert data["uploaded_count"] == 2
    assert data["records"][0]["image_id"] == str(BIG_ITEM_ID)


def test_update_item_request_supports_partial_update_and_blank_parent_as_none():
    req = UpdateItemReq(
        id=str(BIG_ITEM_ID),
        height=0,
        parent_item_id="",
    )

    assert req.id == str(BIG_ITEM_ID)
    assert req.height == 0
    assert req.parent_item_id is None


def test_update_item_request_forbids_obj_url():
    try:
        UpdateItemReq(
            id=str(BIG_ITEM_ID),
            obj_url="bfr-reconstruction-files/results/demo/point_cloud.ply",
        )
    except ValidationError as exc:
        assert "obj_url" in str(exc)
    else:
        raise AssertionError("obj_url should not be accepted by item_put request model")


def test_reconstruction_result_upload_response_serializes_item_id_as_string():
    res = ReconstructionResultUploadRes(
        item_id=BIG_ITEM_ID,
        ply_url="bfr-reconstruction-files/results/manual/1935558010375340032/demo.ply",
        filename="demo.ply",
        size=1024,
        content_type="application/octet-stream",
        message="重构模型上传成功",
    )

    data = dump_model(res)

    assert data["item_id"] == str(BIG_ITEM_ID)
    assert data["ply_url"].endswith("demo.ply")
