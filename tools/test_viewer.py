import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ViewerContractTests(unittest.TestCase):
    def test_gallery_links_open_the_viewer(self):
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="./view.html#/${encodeURIComponent(s.slug)}"', index)
        self.assertIn('document.getElementById("cta-submissions").href = "./view.html"', index)

    def test_viewer_handles_every_protocol_kind(self):
        viewer = (ROOT / "view.html").read_text(encoding="utf-8")
        self.assertIn('row.kind === "svg"', viewer)
        self.assertIn('|| row.kind === "png"', viewer)
        self.assertIn('row.kind === "json"', viewer)
        self.assertIn('pre.textContent = body', viewer)
        self.assertIn('raw.textContent = JSON.stringify(doc, null, 2)', viewer)

    def test_untrusted_art_is_inserted_as_text_not_html(self):
        viewer = (ROOT / "view.html").read_text(encoding="utf-8")
        self.assertNotIn("stage.innerHTML", viewer)
        self.assertNotIn("raw.innerHTML", viewer)
        self.assertNotIn("pre.innerHTML", viewer)

    def test_workflow_runs_viewer_contracts(self):
        workflow = (ROOT / ".github/workflows/submissions-index.yml").read_text(
            encoding="utf-8")
        self.assertIn('- "view.html"', workflow)
        self.assertIn('-p "test_*.py"', workflow)


if __name__ == "__main__":
    unittest.main()
