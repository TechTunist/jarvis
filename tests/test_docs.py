"""Local markdown/PDF writer. No Grok."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from memory.docs import looks_like_guide, save_guide, write_pdf


class DocsTests(unittest.TestCase):
    def test_write_pdf_header_and_save_guide(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dest = Path(tmp.name) / "note.pdf"
        write_pdf("# Title\n\nHello from Jarvis.\n", dest)
        raw = dest.read_bytes()
        self.assertTrue(raw.startswith(b"%PDF"))
        self.assertIn(b"%%EOF", raw)
        import os

        os.environ["JARVIS_DOCUMENTS"] = str(Path(tmp.name) / "Documents" / "jarvis")
        self.addCleanup(os.environ.pop, "JARVIS_DOCUMENTS", None)
        md, pdf = save_guide(
            "# Wireless mic\n\n1. Flash firmware.\n",
            slug="room-mic",
        )
        self.assertTrue(md.is_file())
        self.assertTrue(pdf.is_file())
        self.assertIn("Flash firmware", md.read_text(encoding="utf-8"))

    def test_rejects_workspace_stall(self) -> None:
        self.assertFalse(
            looks_like_guide(
                "I need the hardware details Matt already described so the "
                "guide freezes one repeatable recipe. Searching the workspace "
                "for that context."
            )
        )
        self.assertTrue(
            looks_like_guide(
                "# Room mic\n\n## Parts\n- ESP32-S3\n- MEMS mic\n- BMS USB-C\n\n"
                "## Assembly\n1. Solder the capsule.\n2. Fit the pack.\n"
                "## Flash\nSame firmware on every node.\n## Test\nMute LED, MQTT ping.\n"
                + ("more detail\n" * 20)
            )
        )


if __name__ == "__main__":
    unittest.main()
