from pattern_explorer.orchestration.tsv import format_tsv_table, tsv_diff, tsv_equal


def test_format_tsv_table_aligns_columns():
    assert format_tsv_table("short\t1\nx\t200") == "short  1\nx      200"


def test_format_tsv_table_limits_output():
    text = "\n".join(f"row-{index}\t{index}" for index in range(4))

    assert format_tsv_table(text, max_rows=2) == (
        "row-0  0\n"
        "row-1  1\n"
        "... 2 more row(s)"
    )


def test_format_tsv_table_handles_empty_results():
    assert format_tsv_table("") == "(no rows)"


def test_tsv_equal_ignores_comment_lines():
    got = "200001\t2\tcold_s3"
    want = "# partition\trows\tdisk\n200001\t2\tcold_s3"

    assert tsv_equal(got, want)


def test_tsv_equal_still_compares_data_rows():
    assert not tsv_equal("200001\t3", "# header\n200001\t2")


def test_tsv_diff_ignores_comment_lines():
    assert "(results differ only in trailing whitespace)" == tsv_diff(
        "a\t1", "# comment\na\t1"
    )
