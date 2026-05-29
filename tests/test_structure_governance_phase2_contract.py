from pathlib import Path


def test_phase_two_route_modules_exist():
    expected_paths = [
        "csrcqsf/modules/__init__.py",
        "csrcqsf/modules/railway_parts/__init__.py",
        "csrcqsf/modules/railway_parts/routes/__init__.py",
        "csrcqsf/modules/railway_parts/routes/router.py",
        "csrcqsf/modules/railway_parts/routes/parts_routes.py",
        "csrcqsf/modules/railway_parts/routes/search_routes.py",
        "csrcqsf/modules/railway_parts/routes/review_ticket_routes.py",
        "csrcqsf/modules/railway_parts/routes/reconstruction_routes.py",
    ]

    for relative_path in expected_paths:
        assert Path(relative_path).exists(), relative_path


def test_route_aggregation_package_references_split_route_modules():
    text = Path("csrcqsf/modules/railway_parts/routes/__init__.py").read_text(encoding="utf-8")

    expected_fragments = [
        "from .router import parts_router",
        "parts_routes",
        "search_routes",
        "review_ticket_routes",
        "reconstruction_routes",
    ]

    for fragment in expected_fragments:
        assert fragment in text


def test_split_route_files_keep_domain_boundaries():
    expected_fragments = {
        "csrcqsf/modules/railway_parts/routes/parts_routes.py": [
            "@parts_router.post('/item'",
            "@parts_router.post('/list_item_images'",
            "@parts_router.post('/item/suggest'",
        ],
        "csrcqsf/modules/railway_parts/routes/search_routes.py": [
            "@parts_router.post('/v2/index/rebuild'",
            "@parts_router.post('/v2/search/history/list'",
            "@parts_router.get('/v2/search/modes'",
        ],
        "csrcqsf/modules/railway_parts/routes/review_ticket_routes.py": [
            "@parts_router.post('/v2/search/reviewTicket/list'",
            "@parts_router.post('/v2/search/reviewTicket/update'",
        ],
        "csrcqsf/modules/railway_parts/routes/reconstruction_routes.py": [
            "@parts_router.post('/v2/reconstruct/video/upload/init'",
            "@parts_router.post('/v2/reconstruct/tasks/video'",
        ],
    }

    for relative_path, fragments in expected_fragments.items():
        text = Path(relative_path).read_text(encoding="utf-8")
        for fragment in fragments:
            assert fragment in text, f"{relative_path}: missing {fragment}"
