import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
sys.path.insert(0, str(Path(__file__).parent / "src"))
from visual_parse import extract_messages

class AvatarFallbackTests(unittest.TestCase):
    def test_sidebar_candidate_does_not_block_valid_avatar_column(self):
        image = Image.new("RGB", (1021, 740), (237,237,237))
        def rows(image, x):
            return [(78,570)] if x == 305 else [(100,135)] if x == 340 else []
        with patch("visual_parse.avatar_rows", side_effect=rows):
            self.assertEqual(extract_messages(image), [])

    def test_all_ambiguous_columns_fail_closed(self):
        image = Image.new("RGB", (1021, 740), (237,237,237))
        with patch("visual_parse.avatar_rows", return_value=[(78,570)]):
            with self.assertRaises(ValueError):
                extract_messages(image)

    def test_real_widened_sidebar_frame(self):
        path = Path(__file__).parent / "shots/discovery-before.png"
        if not path.exists():
            self.skipTest("实机截图未随仓库分发")
        result = extract_messages(Image.open(path).convert("RGB"))
        self.assertGreater(len(result), 0)

if __name__ == "__main__":
    unittest.main()
