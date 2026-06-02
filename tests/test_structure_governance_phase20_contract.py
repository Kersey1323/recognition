from pathlib import Path


def test_phase_twenty_models_orm_are_real_implementations():
    target_paths = [
        "csrcqsf/models/orm/files.py",
        "csrcqsf/models/orm/item.py",
        "csrcqsf/models/orm/search_history.py",
        "csrcqsf/models/orm/reconstruction.py",
        "csrcqsf/models/orm/reconstruction_upload.py",
        "csrcqsf/models/orm/sgo.py",
        "csrcqsf/models/orm/sgo_external.py",
    ]

    forbidden_fragments = (
        '_import_module("csrcqsf.models.',
        "_sys.modules[__name__] = _impl",
    )

    for relative_path in target_paths:
        text = Path(relative_path).read_text(encoding="utf-8")
        for fragment in forbidden_fragments:
            assert fragment not in text, f"{relative_path} still uses compat indirection"


def test_phase_twenty_legacy_models_are_removed_after_orm_cutover():
    removed_paths = [
        "csrcqsf/models/files.py",
        "csrcqsf/models/item.py",
        "csrcqsf/models/search_history.py",
        "csrcqsf/models/reconstruction.py",
        "csrcqsf/models/reconstruction_upload.py",
        "csrcqsf/models/sgo.py",
        "csrcqsf/models/sgo_models.py",
    ]

    for relative_path in removed_paths:
        assert not Path(relative_path).exists(), relative_path
