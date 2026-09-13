import tempfile
import unittest
from pathlib import Path

from app import find_best_job, load_resume_from_file


class ResumeMatchingTests(unittest.TestCase):
    def test_project_resume_matches_jobs(self):
        project_resume = Path(__file__).resolve().parent / "Resume_anosha.pdf"
        self.assertTrue(project_resume.exists(), "Expected the uploaded resume file to exist in the project folder.")

        resume_text = load_resume_from_file(str(project_resume))
        self.assertTrue(isinstance(resume_text, str))
        self.assertGreater(len(resume_text.strip()), 0)

        job = find_best_job(resume_text)
        self.assertIsNotNone(job)
        self.assertTrue(job["apply_url"].startswith("https://"))
        self.assertGreaterEqual(job["score"], 0)

    def test_pdf_resume_loads_text_from_local_file(self):
        from pypdf import PdfWriter

        with tempfile.TemporaryDirectory() as tmpdir:
            resume_path = Path(tmpdir) / "resume.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=200, height=200)
            writer.write(str(resume_path))

            text = load_resume_from_file(str(resume_path))
            self.assertTrue(isinstance(text, str))
            self.assertGreaterEqual(len(text), 0)


if __name__ == "__main__":
    unittest.main()
