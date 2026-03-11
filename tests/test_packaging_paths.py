import os
import sys
import unittest
from unittest.mock import patch

from core.agent_tools_base import get_executable_root, get_ide_root


class TestPackagingPaths(unittest.TestCase):
    def test_get_ide_root_prefers_bundle_root_when_frozen(self):
        with patch.object(sys, "_MEIPASS", "C:/bundle-root", create=True):
            self.assertEqual(get_ide_root(), os.path.realpath("C:/bundle-root"))

    def test_get_executable_root_prefers_executable_directory_when_frozen(self):
        with patch.object(sys, "frozen", True, create=True), patch.object(
            sys, "executable", r"C:\Apps\VoxAI_IDE\VoxAI_IDE.exe", create=True
        ):
            self.assertEqual(get_executable_root(), os.path.realpath(r"C:\Apps\VoxAI_IDE"))


if __name__ == "__main__":
    unittest.main()