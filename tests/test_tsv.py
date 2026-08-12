from pattern_explorer.orchestration.tsv import format_tsv_table


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
