"""
Daily Career Scraper — Chennai Edition
Fetches HR, Talent Acquisition, Campus Hiring, HR Operations, and Business
Analytics roles for Anosha's profile, scores and filters listings, then
creates an HTML/text email digest.

Important:
- LinkedIn guest-page scraping can be blocked or change without notice.
- Apify actor input/output fields may vary by actor version.
- No fabricated sample vacancies are sent if live scraping fails.
- Default schedule: 8:00 PM IST (set DAILY_TIME_IST=07:00 for 7 AM).
"""

import argparse
import base64
import html
import json
import os
import re
import smtplib
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

load_dotenv()
BASE_DIR = Path(__file__).resolve().parent
IST = ZoneInfo("Asia/Kolkata")

# =============================================================================
# CONFIGURATION
# =============================================================================

SENDER_EMAIL = (
    os.getenv("SENDER_EMAIL")
    or os.getenv("MAIL_USERNAME")
    or "albiaju2001@gmail.com"
)
RECIPIENT_EMAIL = (
    os.getenv("RECIPIENT_EMAIL")
    or os.getenv("TO_EMAIL")
    or "anoshamariam075@gmail.com"
)

APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")
APIFY_ACTOR_ID = os.getenv(
    "APIFY_ACTOR_ID", "curious_coder/linkedin-jobs-scraper"
)

DEFAULT_RESUME_PATH = BASE_DIR / "Resume_anosha.pdf"
RESUME_PATH = os.getenv("RESUME_PATH") or (
    str(DEFAULT_RESUME_PATH) if DEFAULT_RESUME_PATH.exists() else ""
)

GMAIL_CREDENTIALS_FILE = os.getenv(
    "GMAIL_CREDENTIALS_FILE", "gmail_credentials.json"
)
GMAIL_TOKEN_FILE = os.getenv("GMAIL_TOKEN_FILE", "token.json")

# 24-hour format in Asia/Kolkata. Set DAILY_TIME_IST=07:00 for 7 AM.
DAILY_TIME_IST = os.getenv("DAILY_TIME_IST", "20:00")
CITY = "Chennai"
STATE = "Tamil Nadu"
LOCATION = f"{CITY}, {STATE}"

COMPANY_BLACKLIST = [
    "mindrift", "crossover", "outlier", "dataannotation", "bairesdev",
    "revature", "turing", "epic recruitment", "hiretalent", "dice",
    "apex systems", "jobot", "teksystems", "cybercoders", "varite",
    "infotree", "vaco",
]

GOOD_COMPANIES = [
    "google", "amazon", "microsoft", "flipkart", "deloitte", "swiggy",
    "zomato", "pwc", "ey", "kpmg", "accenture", "kalvium", "infosys",
    "wipro", "tcs", "phonepe", "razorpay", "cred", "meesho", "uber",
    "target", "walmart", "cisco", "linkedin", "goldman sachs",
    "morgan stanley", "apple", "meta",
]

TARGET_SKILLS = [
    "talent acquisition", "recruitment", "sourcing", "screening",
    "resume screening", "interview coordination", "hr screening",
    "onboarding", "campus hiring", "hr operations", "candidate experience",
    "job description", "job posting", "talent sourcing", "hiring",
    "headhunting", "people operations", "hr recruiter", "recruiter",
    "talent partner", "hr associate", "naukri", "linkedin", "leadsquared",
    "crm", "excel", "advanced excel", "power bi", "ms excel", "ats",
    "workday", "spreadsheets", "bba", "business administration",
    "business analytics", "data visualization", "analytics", "finance",
    "communication", "stakeholder management",
]

SEARCH_QUERIES = [
    {"keywords": "Talent Acquisition Associate", "location": LOCATION},
    {"keywords": "HR Recruiter", "location": LOCATION},
    {"keywords": "Campus Hiring Coordinator", "location": LOCATION},
    {"keywords": "HR Operations Specialist", "location": LOCATION},
    {"keywords": "Junior Business Analyst", "location": LOCATION},
]

# =============================================================================
# RESUME
# =============================================================================

def load_resume_text(file_path: str = None) -> str:
    """Extract text from a PDF resume if present."""
    path = Path(file_path) if file_path else (
        Path(RESUME_PATH) if RESUME_PATH else DEFAULT_RESUME_PATH
    )
    if not path.exists():
        return ""
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception as exc:
        print(f"[INFO] Could not read resume ({exc}); using configured keywords.")
        return ""

# =============================================================================
# FILTERING AND SCORING
# =============================================================================

def is_blacklisted(company_name: str) -> bool:
    clean_name = (company_name or "").strip().lower()
    return any(spam in clean_name for spam in COMPANY_BLACKLIST)


def is_good_company(company_name: str) -> bool:
    clean_name = (company_name or "").strip().lower()
    return any(name in clean_name for name in GOOD_COMPANIES)


def extract_matched_skills(text: str) -> list:
    if not text:
        return []
    text_lower = f" {text.lower()} "
    matched = []
    for skill in TARGET_SKILLS:
        pattern = r"(?:\b|_)" + re.escape(skill) + r"(?:\b|_)"
        if re.search(pattern, text_lower):
            if skill in {"bba", "crm", "ats", "hr"}:
                display = skill.upper()
            elif skill == "power bi":
                display = "Power BI"
            elif skill == "leadsquared":
                display = "LeadSquared CRM"
            else:
                display = skill.title()
            matched.append(display)
    return sorted(set(matched))


def calculate_recency_score(posted_at: str) -> tuple:
    """Return (points, is_fresh_24h, label)."""
    if not posted_at:
        return 6, False, "Posting date unavailable"

    value = str(posted_at).lower().strip()
    if any(word in value for word in (
        "hour", "minute", "just now", "today", "seconds", "1d"
    )):
        return 20, True, "Posted within about 24 hours"
    if "yesterday" in value or "1 day" in value:
        return 18, True, "Posted yesterday"
    if any(f"{day} day" in value for day in (2, 3)):
        return 12, False, "Posted 2–3 days ago"
    if any(f"{day} day" in value for day in range(4, 8)) or "1 week" in value:
        return 6, False, "Posted this week"

    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 3600
        if 0 <= age_hours <= 24:
            return 20, True, "Posted within about 24 hours"
        if 24 < age_hours <= 72:
            return 12, False, "Posted 1–3 days ago"
        if 72 < age_hours <= 168:
            return 6, False, "Posted this week"
    except (ValueError, TypeError):
        pass
    return 6, False, "Posting date unavailable"


def clean_apply_url(url: str, title: str, company: str,
                    location: str = LOCATION) -> str:
    """Use a supplied HTTP(S) link, or construct a LinkedIn search link."""
    candidate = (url or "").strip()
    if (
        candidate.startswith(("https://", "http://"))
        and "sample" not in candidate.lower()
        and "example" not in candidate.lower()
    ):
        return candidate

    keywords = " ".join(part for part in (title, company) if part)
    return (
        "https://www.linkedin.com/jobs/search/?"
        + urllib.parse.urlencode({
            "keywords": keywords or "Talent Acquisition Associate",
            "location": location or LOCATION,
            "f_TPR": "r86400",
        })
    )


def score_job(job: dict) -> dict:
    title = str(job.get("title") or "")
    description = str(job.get("description") or "")
    company = str(job.get("company") or "")
    location = str(job.get("location") or "")
    posted_at = str(job.get("posted_at") or "")
    full_text = f"{title} {description} {location}"
    matched_skills = extract_matched_skills(full_text)

    skill_points = min(50, len(matched_skills) * 9)
    recency_points, is_fresh, recency_label = calculate_recency_score(posted_at)
    top_tier = is_good_company(company)
    company_bonus = 30 if top_tier else 0
    location_bonus = 10 if CITY.lower() in location.lower() else 0
    total_score = min(100, skill_points + recency_points + company_bonus + location_bonus)

    if total_score >= 80:
        tier = "High Match"
        color = {"bg": "#ecfdf5", "border": "#10b981",
                 "badge_bg": "#059669", "badge_text": "#ffffff"}
    elif total_score >= 60:
        tier = "Strong Match"
        color = {"bg": "#eff6ff", "border": "#3b82f6",
                 "badge_bg": "#2563eb", "badge_text": "#ffffff"}
    else:
        tier = "Good Match"
        color = {"bg": "#fffbeb", "border": "#f59e0b",
                 "badge_bg": "#d97706", "badge_text": "#ffffff"}

    result = dict(job)
    result.update({
        "title": title or "Untitled role",
        "company": company or "Company not specified",
        "location": location or LOCATION,
        "description": description,
        "type": job.get("type") or "Not specified",
        "score": total_score,
        "apply_url": clean_apply_url(job.get("apply_url", ""), title, company, location),
        "matched_skills": matched_skills,
        "is_top_tier": top_tier,
        "is_fresh": is_fresh,
        "recency_label": recency_label,
        "match_tier": tier,
        "color_theme": color,
    })
    return result

# =============================================================================
# LIVE SCRAPING
# =============================================================================

def is_relevant_role(title: str) -> bool:
    title_lower = (title or "").lower()
    hr_terms = [
        "hr", "human resource", "talent", "recruiter", "recruitment",
        "hiring", "sourcing", "people", "staffing", "onboarding",
        "campus", "business analyst", "analytics", "operations associate",
        "talent partner", "hr associate",
    ]
    exclude_terms = [
        "exchange", "o365", "software engineer", "devops", "cloud engineer",
        "java", ".net", "technician", "electrician", "hardware", "civil",
    ]
    return not any(term in title_lower for term in exclude_terms) and any(
        term in title_lower for term in hr_terms
    )


def scrape_live_linkedin_jobs() -> list:
    """Fetch public LinkedIn guest-search results; may be blocked by LinkedIn."""
    import requests

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    all_jobs = []
    seen_links = set()

    for query in SEARCH_QUERIES:
        params = {
            "keywords": query["keywords"],
            "location": query["location"],
            "f_TPR": "r86400",
        }
        url = (
            "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
            + urllib.parse.urlencode(params)
        )
        try:
            response = requests.get(url, headers=headers, timeout=20)
            if response.status_code != 200:
                print(f"[INFO] LinkedIn query returned HTTP {response.status_code}: {query['keywords']}")
                continue

            # Parse cards with BeautifulSoup to avoid fragile parallel regex arrays.
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.text, "html.parser")
            cards = soup.select("li")
            for card in cards:
                link_tag = card.select_one("a.base-card__full-link")
                title_tag = card.select_one("h3.base-search-card__title")
                company_tag = card.select_one("h4.base-search-card__subtitle")
                location_tag = card.select_one("span.job-search-card__location")
                time_tag = card.select_one("time")

                if not link_tag or not title_tag:
                    continue
                raw_link = (link_tag.get("href") or "").split("?")[0]
                raw_title = title_tag.get_text(" ", strip=True)
                if not raw_link or raw_link in seen_links or not is_relevant_role(raw_title):
                    continue

                raw_location = (
                    location_tag.get_text(" ", strip=True)
                    if location_tag else ""
                )
                if not is_target_location(raw_location):
                    print(f"[INFO] Skipping non-Chennai LinkedIn result: {raw_title!r} — {raw_location!r}")
                    continue

                seen_links.add(raw_link)
                all_jobs.append({
                    "title": raw_title,
                    "company": company_tag.get_text(" ", strip=True) if company_tag else "",
                    "location": raw_location,
                    "apply_url": raw_link,
                    "posted_at": (
                        time_tag.get("datetime") or time_tag.get_text(" ", strip=True)
                        if time_tag else ""
                    ),
                    # Do not invent job-description skills when the description is unavailable.
                    "description": "",
                    "type": "Not specified",
                })
        except Exception as exc:
            print(f"[INFO] LinkedIn query failed ({query['keywords']}): {exc}")

    return all_jobs


def is_target_location(location: str) -> bool:
    """Accept Chennai-area listings only; reject other cities explicitly."""
    value = (location or "").strip().lower()
    if not value:
        return False

    # Explicitly reject common non-Chennai locations, especially Bengaluru.
    other_city_markers = (
        "bengaluru", "bangalore", "mumbai", "pune", "hyderabad",
        "delhi", "new delhi", "gurugram", "gurgaon", "noida",
        "kolkata", "kochi", "cochin", "thiruvananthapuram",
        "trivandrum", "coimbatore", "madurai", "mysuru", "mysore",
    )
    if any(city in value for city in other_city_markers):
        return False

    # Chennai and common Chennai-area location labels.
    chennai_markers = (
        "chennai", "madras", "tambaram", "sholinganallur",
        "siruseri", "guindy", "ambattur", "thoraipakkam",
        "perungudi", "omr", "old mahabalipuram road",
    )
    return any(place in value for place in chennai_markers)


def fetch_jobs_from_apify(token: str = None) -> list:
    """Try Apify first, then LinkedIn guest search. No fabricated fallback listings."""
    token = token or APIFY_TOKEN
    jobs = []

    if token.strip():
        try:
            from apify_client import ApifyClient
            client = ApifyClient(token)
            print("[INFO] Starting Apify job scraper for Chennai...")
            search_urls = [
                "https://www.linkedin.com/jobs/search/?"
                + urllib.parse.urlencode({
                    "keywords": q["keywords"],
                    "location": q["location"],
                    "f_TPR": "r86400",
                })
                for q in SEARCH_QUERIES
            ]
            run_input = {
                "urls": search_urls,
                "keywords": "Talent Acquisition Associate",
                "location": f"{CITY}, {STATE}, India",
                "datePosted": "past24Hours",
                "limitPerSource": 15,
            }
            run = client.actor(APIFY_ACTOR_ID).call(
                run_input=run_input, timeout_secs=120
            )
            items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            for item in items:
                title = item.get("title") or item.get("jobTitle") or ""
                company = item.get("companyName") or item.get("company") or ""
                location = item.get("location") or item.get("formattedLocation") or ""
                raw_url = (
                    item.get("link") or item.get("jobUrl")
                    or item.get("applyUrl") or item.get("url") or ""
                )
                # Do not trust a scraper result from a different city.
                if not is_target_location(location):
                    print(f"[INFO] Skipping non-Chennai Apify result: {title!r} — {location!r}")
                    continue
                if not is_relevant_role(title):
                    continue
                jobs.append({
                    "title": title,
                    "company": company,
                    "location": location,
                    "apply_url": raw_url,
                    "posted_at": item.get("postedAt") or item.get("postDate") or "",
                    "description": (
                        item.get("descriptionText") or item.get("description")
                        or item.get("jobDescription") or ""
                    ),
                    "type": item.get("employmentType") or "Not specified",
                })
            print(f"[INFO] Apify returned {len(jobs)} matching Chennai listings.")
        except Exception as exc:
            print(f"[INFO] Apify failed; switching to LinkedIn guest search: {exc}")

    if not jobs:
        print("[INFO] Fetching Chennai listings from LinkedIn guest search...")
        jobs = scrape_live_linkedin_jobs()

    # De-duplicate by URL and title/company/location.
    deduplicated = []
    seen = set()
    for job in jobs:
        key = (
            job.get("apply_url") or "",
            job.get("title", "").lower(),
            job.get("company", "").lower(),
            job.get("location", "").lower(),
        )
        if key not in seen:
            seen.add(key)
            deduplicated.append(job)
    return deduplicated

# =============================================================================
# HTML AND TEXT DIGEST
# =============================================================================

def get_company_initials(company: str) -> str:
    words = re.sub(r"[^a-zA-Z0-9\s]", "", company or "").strip().split()
    if len(words) >= 2:
        return (words[0][0] + words[1][0]).upper()
    if words:
        return words[0][:2].upper()
    return "HR"


def get_company_avatar(company: str) -> str:
    palette = [
        ("#0284c7", "#ffffff"), ("#7c3aed", "#ffffff"),
        ("#059669", "#ffffff"), ("#db2777", "#ffffff"),
        ("#ea580c", "#ffffff"), ("#334155", "#ffffff"),
    ]
    # Stable color assignment between runs.
    idx = sum((i + 1) * ord(char) for i, char in enumerate(company.lower())) % len(palette)
    bg, fg = palette[idx]
    initials = html.escape(get_company_initials(company))
    return (
        f'<div style="width:42px;height:42px;border-radius:10px;background:{bg};'
        f'color:{fg};font-size:14px;font-weight:800;text-align:center;'
        f'line-height:42px;display:inline-block;vertical-align:middle;'
        f'margin-right:12px;">{initials}</div>'
    )


def generate_html_digest(ranked_jobs: list, spam_count: int, total_scraped: int) -> str:
    date_str = datetime.now(IST).strftime("%A, %B %d, %Y")
    cards = []

    for index, job in enumerate(ranked_jobs, start=1):
        color = job["color_theme"]
        top_badge = (
            '<span style="display:inline-block;background:#d97706;color:#fff;'
            'font-size:11px;font-weight:700;padding:4px 9px;border-radius:20px;">'
            '⭐ Top Employer</span>'
            if job["is_top_tier"] else ""
        )
        fresh_badge = (
            '<span style="display:inline-block;background:#fee2e2;color:#b91c1c;'
            'font-size:11px;font-weight:700;padding:4px 9px;border-radius:20px;">'
            f'{html.escape(job["recency_label"])}</span>'
            if job["is_fresh"] else ""
    