from csrcqsf.modules.railway_parts.utils.local_file_part_reader import LocalFilePartReader


def test_local_file_part_reader_lists_parts_and_reads_bytes(tmp_path):
    file_path = tmp_path / "demo.bin"
    file_path.write_bytes(b"abcdefghij")

    reader = LocalFilePartReader(str(file_path), 4)
    parts = reader.list_parts()

    assert [(part.part_number, part.start, part.end, part.size) for part in parts] == [
        (1, 0, 4, 4),
        (2, 4, 8, 4),
        (3, 8, 10, 2),
    ]
    assert reader.read_part(parts[1]) == b"efgh"
