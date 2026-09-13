import os
import sys
import unittest
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from send_daily_jobs import (
    COMPANY_BLACKLIST,
    GOOD_COMPANIES,
    calculate_recency_score,
    extract_matched_skills,
    generate_html_digest,
    generate_text_digest,
    is_blacklisted,
    is_good_company,
    run_scraper_pipeline,
    score_job,
)


class TestDailyJobScraper(unittest.TestCase):
    def test_blacklist_filtering(self):
        """Test that spam companies are correctly identified and normal companies pass."""
        spam_companies = [
            "Mindrift",
            "Mindrift AI",
            "Crossover for Work",
            "Outlier",
            "Outlier.ai",
            "DataAnnotation Tech",
            "BairesDev Inc.",
            "Turing Enterprises"
        ]
        for company in spam_companies:
            self.assertTrue(is_blacklisted(company), f"Expected {company} to be blacklisted as spam.")

        legit_companies = ["Google", "OpenAI", "Meta", "Swiggy", "Infosys", "Microsoft"]
        for company in legit_companies:
            self.assertFalse(is_blacklisted(company), f"Expected {company} NOT to be blacklisted.")

    def test_good_company_bonus(self):
        """Test that top-tier tech companies are correctly recognized."""
        for company in ["Google", "Google DeepMind", "Meta", "OpenAI", "Apple", "Microsoft", "NVIDIA", "Anthropic"]:
            self.assertTrue(is_good_company(company), f"Expected {company} to be recognized as a top-tier company.")

        self.assertFalse(is_good_company("Generic Tech Staffing"))
        self.assertFalse(is_good_company("Local Agency LLC"))

    def test_recency_scoring(self):
        """Test recency scoring and freshness badges."""
        pts, fresh, label = calculate_recency_score("2 hours ago")
        self.assertEqual(pts, 20)
        self.assertTrue(fresh)
        self.assertIn("24h", label)

        pts, fresh, label = calculate_recency_score("1 day ago")
        self.assertEqual(pts, 18)
        self.assertTrue(fresh)

        pts, fresh, label = calculate_recency_score("3 days ago")
        self.assertEqual(pts, 12)
        self.assertFalse(fresh)

    def test_skill_extraction(self):
        """Test extracting skills from job descriptions."""
        text = "Seeking an AI Engineer skilled in Python, PyTorch, LangChain, and Docker with LLM fine-tuning."
        skills = extract_matched_skills(text)
        self.assertIn("Python", skills)
        self.assertIn("Pytorch", skills)
        self.assertIn("Langchain", skills)
        self.assertIn("Docker", skills)
        self.assertIn("LLM", skills)

    def test_score_job_calculation_and_boost(self):
        """Test overall scoring including the 30-point top-tier tech bonus."""
        top_tier_job = {
            "title": "Machine Learning Engineer",
            "company": "Google",
            "description": "Python, PyTorch, LangChain, Transformers, Kubernetes",
            "posted_at": "Just now",
            "location": "Bengaluru",
            "apply_url": "https://linkedin.com/test",
            "type": "Full-time"
        }
        scored_top = score_job(top_tier_job)
        self.assertTrue(scored_top["is_top_tier"])
        self.assertTrue(scored_top["is_fresh"])
        self.assertGreaterEqual(scored_top["score"], 80)
        self.assertEqual(scored_top["match_tier"], "High Match")

        standard_job = {
            "title": "Junior Python Assistant",
            "company": "RegularCorp",
            "description": "Basic Python script maintenance.",
            "posted_at": "6 days ago",
            "location": "Remote",
            "apply_url": "https://linkedin.com/test2",
            "type": "Part-time"
        }
        scored_std = score_job(standard_job)
        self.assertFalse(scored_std["is_top_tier"])
        self.assertLess(scored_std["score"], scored_top["score"])

    def test_digest_generation(self):
        """Test generating HTML and plaintext digests."""
        sample_ranked = [
            score_job({
                "title": "AI Engineer",
                "company": "OpenAI",
                "description": "Python, LLM, PyTorch",
                "posted_at": "today",
                "location": "Remote",
                "apply_url": "https://linkedin.com/jobs/view/123",
                "type": "Full-time"
            })
        ]
        html = generate_html_digest(sample_ranked, spam_count=3, total_scraped=10)
        self.assertIn("Daily Tech Job Digest", html)
        self.assertIn("OpenAI", html)
        self.assertIn("https://linkedin.com/jobs/view/123", html)
        self.assertIn("Spam Filtered", html)

        text = generate_text_digest(sample_ranked, spam_count=3, total_scraped=10)
        self.assertIn("DAILY TECH JOB DIGEST", text)
        self.assertIn("OpenAI", text)

    def test_pipeline_dry_run(self):
        """Test running the full pipeline in dry-run mode."""
        ranked = run_scraper_pipeline(dry_run=True)
        self.assertIsInstance(ranked, list)
        self.assertGreater(len(ranked), 0)

        preview_file = Path("daily_jobs_preview.html")
        self.assertTrue(preview_file.exists())
        content = preview_file.read_text(encoding="utf-8")
        self.assertIn("Daily Tech Job Digest", content)


if __name__ == "__main__":
    unittest.main()
