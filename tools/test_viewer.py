import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ViewerContractTests(unittest.TestCase):
    def test_gallery_links_open_the_viewer(self):
        index = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn(
            'link.href = "./view.html#/" + encodeURIComponent(s.slug)',
            index,
        )
        self.assertIn('document.getElementById("cta-submissions").href = "./view.html"', index)

    def test_viewer_handles_every_protocol_kind(self):
        viewer = (ROOT / "view.html").read_text(encoding="utf-8")
        self.assertIn('row.kind === "svg"', viewer)
        self.assertIn('|| row.kind === "png"', viewer)
        self.assertIn('row.kind === "json"', viewer)
        self.assertIn('pre.textContent = body', viewer)
        self.assertIn('raw.textContent = JSON.stringify(doc, null, 2)', viewer)
        self.assertIn('const image = document.createElement("img")', viewer)
        self.assertIn('image.src = pathURL(row.piece_path)', viewer)
        self.assertIn('stage.appendChild(image)', viewer)

    def test_untrusted_art_is_inserted_as_text_not_html(self):
        gallery = (ROOT / "index.html").read_text(encoding="utf-8")
        viewer = (ROOT / "view.html").read_text(encoding="utf-8")
        self.assertNotIn("innerHTML", gallery)
        self.assertNotIn("innerHTML", viewer)
        self.assertIn("title.textContent = s.title || s.slug", gallery)
        self.assertIn("kind.textContent =", gallery)
        self.assertIn('document.createTextNode(" by @" + (s.contributor || "?") + " ")', gallery)
        self.assertIn('link.href = "./view.html#/" + encodeURIComponent(s.slug)', gallery)

    def test_recent_submissions_success_clears_loading_placeholder_before_rows_append(self):
        gallery = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn(
            '<div id="submissions" class="submissions-empty">Loading…</div>',
            gallery,
        )
        self.assertIn("function renderSubmissions(target, submissions) {", gallery)
        self.assertIn("target.replaceChildren();", gallery)
        self.assertLess(
            gallery.index("target.replaceChildren();"),
            gallery.index("for (const s of submissions.slice(0, 12)) {"),
        )

    def test_recent_submissions_empty_and_error_paths_use_safe_text_messages(self):
        gallery = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('const NO_SUBMISSIONS_MESSAGE = "No submissions yet — be the first.";', gallery)
        self.assertIn("function setSubmissionsMessage(target, message) {", gallery)
        self.assertIn('target.classList.add("submissions-empty");', gallery)
        self.assertIn("target.textContent = message;", gallery)
        self.assertGreaterEqual(
            gallery.count("setSubmissionsMessage(target, NO_SUBMISSIONS_MESSAGE);"),
            2,
        )

    def test_workflow_runs_viewer_contracts(self):
        workflow = (ROOT / ".github/workflows/submissions-index.yml").read_text(
            encoding="utf-8")
        self.assertIn('- "view.html"', workflow)
        self.assertIn('-p "test_*.py"', workflow)


if __name__ == "__main__":
    unittest.main()
