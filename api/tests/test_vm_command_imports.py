"""Host controllers retain VM execution without importing the file controller."""

import subprocess
import sys
import unittest


class HostVmCommandImportsTest(unittest.TestCase):
    def test_note_git_and_link_import_without_file_controller(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "import api.controller.note; "
                    "import api.controller.git; "
                    "import api.controller.link; "
                    "assert 'api.controller.file' not in sys.modules"
                ),
            ],
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
