"""Public railway parts route aggregation package."""

from .asset_proxy_routes import asset_proxy_router
from .router import parts_router
from . import asset_proxy_routes, parts_routes, reconstruction_routes, review_ticket_routes, search_routes

RailwayPartsManager = parts_routes.RailwayPartsManager
SGOBiz = parts_routes.SGOBiz
MilvusStateManagerV2 = search_routes.MilvusStateManagerV2
ReconstructionManager = reconstruction_routes.ReconstructionManager

create_item = parts_routes.create_item
delete_item = parts_routes.delete_item
put_item = parts_routes.put_item
put_item_size_desc = parts_routes.put_item_size_desc
list_items = parts_routes.list_items
list_item_images = parts_routes.list_item_images
create_item_image = parts_routes.create_item_image
delete_item_image = parts_routes.delete_item_image
get_item_image_detail = parts_routes.get_item_image_detail
indexstatistics = parts_routes.indexstatistics
suggest_items = parts_routes.suggest_items

drop_v2_collections = search_routes.drop_v2_collections
init_v2_collections = search_routes.init_v2_collections
rebuild_v2_index = search_routes.rebuild_v2_index
get_v2_index_rebuild_status = search_routes.get_v2_index_rebuild_status
delete_v2_index = search_routes.delete_v2_index
search_v2_by_text = search_routes.search_v2_by_text
search_v2_by_image = search_routes.search_v2_by_image
list_v2_search_history = search_routes.list_v2_search_history
get_v2_search_history_detail = search_routes.get_v2_search_history_detail
summary_v2_search_history = search_routes.summary_v2_search_history
verify_v2_search_history = search_routes.verify_v2_search_history
submit_v2_search_feedback = search_routes.submit_v2_search_feedback
delete_v2_search_history = search_routes.delete_v2_search_history
get_v2_search_modes = search_routes.get_v2_search_modes

list_v2_search_review_tickets = review_ticket_routes.list_v2_search_review_tickets
get_v2_search_review_ticket_detail = review_ticket_routes.get_v2_search_review_ticket_detail
update_v2_search_review_ticket = review_ticket_routes.update_v2_search_review_ticket
delete_v2_search_review_ticket = review_ticket_routes.delete_v2_search_review_ticket
summary_v2_search_review_ticket = review_ticket_routes.summary_v2_search_review_ticket

reconstruct_v2_train = reconstruction_routes.reconstruct_v2_train
upload_reconstruct_v2_video = reconstruction_routes.upload_reconstruct_v2_video
init_reconstruct_v2_video_upload = reconstruction_routes.init_reconstruct_v2_video_upload
upload_reconstruct_v2_video_part = reconstruction_routes.upload_reconstruct_v2_video_part
get_reconstruct_v2_video_upload_progress = reconstruction_routes.get_reconstruct_v2_video_upload_progress
get_reconstruct_v2_video_upload_urls = reconstruction_routes.get_reconstruct_v2_video_upload_urls
complete_reconstruct_v2_video_upload = reconstruction_routes.complete_reconstruct_v2_video_upload
abort_reconstruct_v2_video_upload = reconstruction_routes.abort_reconstruct_v2_video_upload
health_reconstruct_v2_video_minio_and_sync = reconstruction_routes.health_reconstruct_v2_video_minio_and_sync
list_reconstruct_v2_source_videos = reconstruction_routes.list_reconstruct_v2_source_videos
get_reconstruct_v2_source_video = reconstruction_routes.get_reconstruct_v2_source_video
update_reconstruct_v2_source_video = reconstruction_routes.update_reconstruct_v2_source_video
delete_reconstruct_v2_source_video = reconstruction_routes.delete_reconstruct_v2_source_video
reconstruct_v2_video = reconstruction_routes.reconstruct_v2_video
get_reconstruct_v2_status = reconstruction_routes.get_reconstruct_v2_status
delete_reconstruct_v2_result = reconstruction_routes.delete_reconstruct_v2_result
upload_reconstruct_v2_result = reconstruction_routes.upload_reconstruct_v2_result
list_item_reconstruct_tasks = reconstruction_routes.list_item_reconstruct_tasks
list_all_reconstruct_tasks = reconstruction_routes.list_all_reconstruct_tasks
get_reconstruct_v2_task_item_details = reconstruction_routes.get_reconstruct_v2_task_item_details
reconstruct_v2_statistics = reconstruction_routes.reconstruct_v2_statistics
cancel_reconstruct_task = reconstruction_routes.cancel_reconstruct_task
list_reconstruction_scenes = reconstruction_routes.list_reconstruction_scenes

__all__ = [
    "asset_proxy_router",
    "asset_proxy_routes",
    "parts_router",
    "parts_routes",
    "search_routes",
    "review_ticket_routes",
    "reconstruction_routes",
    "RailwayPartsManager",
    "SGOBiz",
    "MilvusStateManagerV2",
    "ReconstructionManager",
    "create_item",
    "delete_item",
    "put_item",
    "put_item_size_desc",
    "list_items",
    "list_item_images",
    "create_item_image",
    "delete_item_image",
    "get_item_image_detail",
    "indexstatistics",
    "suggest_items",
    "drop_v2_collections",
    "init_v2_collections",
    "rebuild_v2_index",
    "get_v2_index_rebuild_status",
    "delete_v2_index",
    "search_v2_by_text",
    "search_v2_by_image",
    "list_v2_search_history",
    "get_v2_search_history_detail",
    "summary_v2_search_history",
    "verify_v2_search_history",
    "submit_v2_search_feedback",
    "delete_v2_search_history",
    "get_v2_search_modes",
    "list_v2_search_review_tickets",
    "get_v2_search_review_ticket_detail",
    "update_v2_search_review_ticket",
    "delete_v2_search_review_ticket",
    "summary_v2_search_review_ticket",
    "reconstruct_v2_train",
    "upload_reconstruct_v2_video",
    "init_reconstruct_v2_video_upload",
    "upload_reconstruct_v2_video_part",
    "get_reconstruct_v2_video_upload_progress",
    "get_reconstruct_v2_video_upload_urls",
    "complete_reconstruct_v2_video_upload",
    "abort_reconstruct_v2_video_upload",
    "health_reconstruct_v2_video_minio_and_sync",
    "list_reconstruct_v2_source_videos",
    "get_reconstruct_v2_source_video",
    "update_reconstruct_v2_source_video",
    "delete_reconstruct_v2_source_video",
    "reconstruct_v2_video",
    "get_reconstruct_v2_status",
    "delete_reconstruct_v2_result",
    "upload_reconstruct_v2_result",
    "list_item_reconstruct_tasks",
    "list_all_reconstruct_tasks",
    "get_reconstruct_v2_task_item_details",
    "reconstruct_v2_statistics",
    "cancel_reconstruct_task",
    "list_reconstruction_scenes",
]
