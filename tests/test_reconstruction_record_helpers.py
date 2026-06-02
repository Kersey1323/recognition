def test_build_clear_current_result_values_clears_urls_but_keeps_output_path():
    from csrcqsf.models.orm.reconstruction import ReconstructionRecord

    values = ReconstructionRecord.build_clear_current_result_values()

    assert values == {
        "ply_url": None,
        "obj_url": None,
        "glb_url": None,
    }
    assert "output_path" not in values
