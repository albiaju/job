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
    clean_apply_url,
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
            "Crossover for Work",
            "Outlier",
            "DataAnnotation Tech",
            "BairesDev Inc.",
            "Turing Enterprises"
        ]
        for company in spam_companies:
            self.assertTrue(is_blacklisted(company), f"Expected {company} to be blacklisted as spam.")

        legit_companies = ["Google", "Amazon", "Deloitte", "Swiggy", "Kalvium", "Infosys"]
        for company in legit_companies:
            self.assertFalse(is_blacklisted(company), f"Expected {company} NOT to be blacklisted.")

    def test_good_company_bonus(self):
        """Test that top employers in Bengaluru are recognized."""
        for company in ["Google", "Amazon", "Deloitte", "Swiggy", "Kalvium", "Flipkart", "Infosys"]:
            self.assertTrue(is_good_company(company), f"Expected {company} to be recognized as a top employer.")

        self.assertFalse(is_good_company("Generic Staffing Agency"))

    def test_recency_scoring(self):
        """Test recency scoring and freshness badges."""
        pts, fresh, label = calculate_recency_score("2 hours ago")
        self.assertEqual(pts, 20)
        self.assertTrue(fresh)
        self.assertIn("24h", label)

        pts, fresh, label = calculate_recency_score("1 day ago")
        self.assertEqual(pts, 18)
        self.assertTrue(fresh)

    def test_working_url_cleaning(self):
        """Test that sample or broken URLs are converted to live LinkedIn search links."""
        broken_url = "https://www.linkedin.com/jobs/view/sample-slug"
        cleaned = clean_apply_url(broken_url, "Talent Acquisition Associate", "Kalvium", "Bengaluru")
        self.assertTrue(cleaned.startswith("https://www.linkedin.com/jobs/search/?keywords="))
        self.assertIn("Talent%20Acquisition%20Associate", cleaned)
        self.assertIn("Kalvium", cleaned)

        live_url = "https://www.linkedin.com/jobs/view/123456789"
        self.assertEqual(clean_apply_url(live_url, "HR Recruiter", "Amazon"), live_url)

    def test_skill_extraction_for_anosha(self):
        """Test extracting skills relevant to Anosha's BBA & HR recruitment background."""
        text = "Seeking a Talent Acquisition Associate skilled in campus hiring, resume screening, LeadSquared CRM, and advanced excel."
        skills = extract_matched_skills(text)
        self.assertIn("Talent Acquisition", skills)
        self.assertIn("Campus Hiring", skills)
        self.assertIn("Resume Screening", skills)
        self.assertIn("LeadSquared CRM", skills)
        self.assertIn("Advanced Excel", skills)

    def test_score_job_calculation_for_hr(self):
        """Test scoring for HR Talent Acquisition in Bengaluru."""
        hr_job = {
            "title": "Talent Acquisition Associate",
            "company": "Deloitte",
            "description": "End to end recruitment, campus hiring, Naukri, LeadSquared CRM, Excel, BBA",
            "posted_at": "Just now",
            "location": "Bengaluru, Karnataka",
            "apply_url": "https://www.linkedin.com/jobs/view/sample",
            "type": "Full-time"
        }
        scored = score_job(hr_job)
        self.assertTrue(scored["is_top_tier"])
        self.assertTrue(scored["is_fresh"])
        self.assertGreaterEqual(scored["score"], 80)
        self.assertEqual(scored["match_tier"], "High Match")
        self.assertTrue(scored["apply_url"].startswith("https://www.linkedin.com/jobs/"))

    def test_digest_generation_for_anosha(self):
        """Test generating HTML and plaintext digests customized for Anosha."""
        sample_ranked = [
            score_job({
                "title": "Talent Acquisition Associate",
                "company": "Kalvium",
                "description": "Campus hiring, screening, LeadSquared CRM, Excel",
                "posted_at": "today",
                "location": "Bengaluru, Karnataka",
                "apply_url": "https://www.linkedin.com/jobs/search/?keywords=Talent%20Acquisition",
                "type": "Full-time"
            })
        ]
        html = generate_html_digest(sample_ranked, spam_count=2, total_scraped=8)
        self.assertIn("Anosha Mariam Raji", html)
        self.assertIn("Talent Acquisition", html)
        self.assertIn("Kalvium", html)
        self.assertIn("View & Apply on LinkedIn", html)

    def test_pipeline_dry_run(self):
        """Test running the full pipeline in dry-run mode."""
        ranked = run_scraper_pipeline(dry_run=True)
        self.assertIsInstance(ranked, list)
        self.assertGreater(len(ranked), 0)

        preview_file = Path("daily_jobs_preview.html")
        self.assertTrue(preview_file.exists())
        content = preview_file.read_text(encoding="utf-8")
        self.assertIn("Anosha Mariam Raji", content)


if __name__ == "__main__":
    unittest.main()
