import unittest
from unittest.mock import Mock
from PIL import Image
from anchored import focused_code


class FocusedCodeTests(unittest.TestCase):
    def check(self, readings):
        recognize = Mock(
            side_effect=[
                [{"text": text, "confidence": confidence}] for text, confidence in readings
            ]
        )
        return focused_code(Image.new("RGB", (120, 90), "white"), recognize)[0]

    def test_requires_agreement(self):
        self.assertEqual(self.check([("25", 0.99), ("25", 0.98)]), "25")
        self.assertIsNone(self.check([("25", 0.99), ("85", 0.99)]))

    def test_no_guessing_from_labels_or_low_confidence(self):
        self.assertIsNone(self.check([("118a 25", 0.99), ("25", 0.99)]))
        self.assertIsNone(self.check([("25", 0.60), ("25", 0.99)]))
        self.assertIsNone(self.check([("--", 0.99), ("--", 0.99)]))


if __name__ == "__main__":
    unittest.main()
