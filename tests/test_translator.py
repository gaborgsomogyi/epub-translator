import unittest

from epub_translator.xml_translator.translator import _count_blocks, _parse_numbered_blocks


class CountBlocksTest(unittest.TestCase):
    def test_single_block(self) -> None:
        self.assertEqual(_count_blocks("just one block of text"), 1)

    def test_blank_line_separated_blocks(self) -> None:
        self.assertEqual(_count_blocks("block one\n\nblock two\n\nblock three"), 3)

    def test_single_newline_separated_blocks(self) -> None:
        # Consecutive newlines collapse to one separator; single newlines still split.
        self.assertEqual(_count_blocks("block one\nblock two"), 2)

    def test_merged_block_counts_as_one(self) -> None:
        # The bug signature: two source blocks fused into one line by the translator.
        self.assertEqual(_count_blocks("leading on rock; and holly beck"), 1)

    def test_surrounding_whitespace_ignored(self) -> None:
        self.assertEqual(_count_blocks("\n\n  block one\n\nblock two  \n\n"), 2)

    def test_empty(self) -> None:
        self.assertEqual(_count_blocks(""), 0)
        self.assertEqual(_count_blocks("   \n\n  "), 0)


class ParseNumberedBlocksTest(unittest.TestCase):
    def test_clean_response(self) -> None:
        response = "[[1]] first translated\n[[2]] second translated"
        self.assertEqual(
            _parse_numbered_blocks(response, 2, fallback=["a", "b"]),
            ["first translated", "second translated"],
        )

    def test_marker_whitespace_variants(self) -> None:
        response = "[[ 1 ]] alpha\n\n[[2]]beta"
        self.assertEqual(
            _parse_numbered_blocks(response, 2, fallback=["a", "b"]),
            ["alpha", "beta"],
        )

    def test_multiline_block_content_preserved(self) -> None:
        response = "[[1]] line one\nstill block one\n[[2]] block two"
        self.assertEqual(
            _parse_numbered_blocks(response, 2, fallback=["a", "b"]),
            ["line one\nstill block one", "block two"],
        )

    def test_missing_marker_falls_back_to_source(self) -> None:
        response = "[[1]] only the first came back"
        self.assertEqual(
            _parse_numbered_blocks(response, 2, fallback=["src-a", "src-b"]),
            ["only the first came back", "src-b"],
        )

    def test_empty_block_falls_back_to_source(self) -> None:
        response = "[[1]] \n[[2]] second"
        self.assertEqual(
            _parse_numbered_blocks(response, 2, fallback=["src-a", "src-b"]),
            ["src-a", "second"],
        )

    def test_out_of_order_markers_realigned_by_number(self) -> None:
        response = "[[2]] second\n[[1]] first"
        self.assertEqual(
            _parse_numbered_blocks(response, 2, fallback=["a", "b"]),
            ["first", "second"],
        )


if __name__ == "__main__":
    unittest.main()
