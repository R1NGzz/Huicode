import unittest

from src.hello import greet


class HelloTests(unittest.TestCase):
    def test_greet(self) -> None:
        self.assertEqual(greet("HuiCode"), "Hello, HuiCode!")


if __name__ == "__main__":
    unittest.main()
