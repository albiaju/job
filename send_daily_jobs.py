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
    """Return a supplied HTTP(S) listing URL; never fabricate a job URL."""
    candidate = (url or "").strip()
    parsed = urllib.parse.urlparse(candidate)
    if (
        parsed.scheme in {"https", "http"}
        and bool(parsed.netloc)
        and "sample" not in candidate.lower()
        and "example" not in candidate.lower()
    ):
        return candidate
    return ""


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
        # Preserve the source location exactly; never relabel an unknown city as Chennai.
        "location": location,
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
                raw_company = company_tag.get_text(" ", strip=True) if company_tag else ""
                if not is_target_location(raw_location):
                    print(f"[INFO] Skipping non-Chennai/unknown LinkedIn result: {raw_title!r} — {raw_location!r}")
                    continue
                if not raw_company or not clean_apply_url(raw_link, raw_title, raw_company, raw_location):
                    print(f"[INFO] Skipping LinkedIn result missing company or direct URL: {raw_title!r}")
                    continue

                seen_links.add(raw_link)
                all_jobs.append({
                    "title": raw_title,
                    "company": raw_company,
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
    """Accept only listings explicitly located in Chennai or its nearby suburbs."""
    value = re.sub(r"\s+", " ", (location or "").strip().lower())
    if not value:
        return False

    # Remote, hybrid-with-unspecified-base, and explicit non-Chennai locations are not verified.
    if any(term in value for term in ("remote", "anywhere", "multiple locations", "multiple cities")):
        return False
    other_city_markers = (
        "bengaluru", "bangalore", "mumbai", "pune", "hyderabad",
        "delhi", "new delhi", "gurugram", "gurgaon", "noida",
        "kolkata", "kochi", "cochin", "thiruvananthapuram",
        "trivandrum", "coimbatore", "madurai", "mysuru", "mysore",
    )
    if any(city in value for city in other_city_markers):
        return False

    # Use whole-word/phrase matching to avoid broad false positives (e.g. "omr" in unrelated text).
    chennai_patterns = (
        r"\bchennai\b", r"\bmadras\b", r"\btambaram\b",
        r"\bsholinganallur\b", r"\bsiruseri\b", r"\bguindy\b",
        r"\bambattur\b", r"\bthoraipakkam\b", r"\bperungudi\b",
        r"\bold mahabalipuram road\b", r"\bomr\b",
    )
    return any(re.search(pattern, value) for pattern in chennai_patterns)


def is_valid_listing(job: dict) -> bool:
    """Require a real-looking source URL and explicit title, company, and Chennai location."""
    title = str(job.get("title") or "").strip()
    company = str(job.get("company") or "").strip()
    location = str(job.get("location") or "").strip()
    url = clean_apply_url(job.get("apply_url", ""), title, company, location)
    return bool(title and company and is_target_location(location) and url)


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
                    print(f"[INFO] Skipping non-Chennai/unknown Apify result: {title!r} — {location!r}")
                    continue
                if not is_relevant_role(title) or not title.strip() or not company.strip():
                    continue
                if not clean_apply_url(raw_url, title, company, location):
                    print(f"[INFO] Skipping Apify result without a direct source URL: {title!r}")
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
        )
        skills = "".join(
            '<span style="display:inline-block;background:#f1f5f9;color:#1e293b;'
            'border:1px solid #e2e8f0;font-size:11px;font-weight:600;'
            'padding:3px 8px;border-radius:6px;margin:2px 4px 2px 0;">'
            f'{html.escape(skill)}</span>'
            for skill in job["matched_skills"]
        ) or '<span style="color:#64748b;font-size:12px;">No specific skills verified</span>'

        description = (job.get("description") or "").strip()
        if not description:
            description = "Open the original listing to review the full responsibilities and requirements."
        elif len(description) > 260:
            description = description[:260].rstrip() + "…"

        safe_title = html.escape(job["title"])
        safe_company = html.escape(job["company"])
        safe_location = html.escape(job["location"])
        safe_type = html.escape(job["type"])
        safe_description = html.escape(description)
        safe_url = html.escape(job["apply_url"], quote=True)

        cards.append(f"""
        <div style="background:#fff;border:1px solid #e2e8f0;border-left:5px solid {color['border']};
        border-radius:14px;padding:20px;margin-bottom:18px;">
          <div style="margin-bottom:12px;">
            <span style="background:{color['badge_bg']};color:#fff;font-size:11px;font-weight:700;
            padding:4px 10px;border-radius:20px;">#{index} • {job['score']}% Match ({job['match_tier']})</span>
            {top_badge} {fresh_badge}
          </div>
          <div style="display:flex;align-items:center;margin-bottom:10px;">
            {get_company_avatar(job['company'])}
            <div>
              <h2 style="margin:0;font-size:18px;color:#0f172a;line-height:1.35;">{safe_title}</h2>
              <div style="color:#475569;font-size:13px;font-weight:600;margin-top:4px;">
                🏢 {safe_company} • 📍 {safe_location} • 💼 {safe_type}
              </div>
            </div>
          </div>
          <p style="color:#334155;font-size:13px;line-height:1.6;margin:10px 0 14px;">{safe_description}</p>
          <div style="margin-bottom:16px;">
            <div style="color:#64748b;font-size:11px;font-weight:700;margin-bottom:6px;">MATCHING SKILLS / KEYWORDS</div>
            {skills}
          </div>
          <div style="text-align:right;">
            <a href="{safe_url}" target="_blank" rel="noopener noreferrer"
            style="background:#17153a;color:#fff;text-decoration:none;padding:10px 18px;
            border-radius:8px;font-size:13px;font-weight:700;display:inline-block;">
            View listing / apply →</a>
          </div>
        </div>
        """)

    if not ranked_jobs:
        cards.append("""
        <div style="padding:22px;background:#fff7ed;border:1px solid #fed7aa;border-radius:12px;">
          <strong>No verified matching listings were retrieved today.</strong>
          <p style="margin-bottom:0;">The scraper may have been blocked or no matching Chennai postings were returned.
          No sample or invented vacancies have been included. Try again later or check LinkedIn directly.</p>
        </div>
        """)

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Daily Chennai Career Digest</title></head>
<body style="font-family:Arial,Helvetica,sans-serif;background:#f1f5f9;margin:0;padding:24px 10px;color:#1e293b;">
<div style="max-width:660px;margin:0 auto;background:#fff;border-radius:16px;overflow:hidden;">
<div style="height:5px;background:linear-gradient(90deg,#10b981,#6366f1,#ec4899);"></div>
<div style="background:#111827;padding:30px 22px;color:#fff;text-align:center;">
<div style="font-size:11px;font-weight:700;letter-spacing:.8px;margin-bottom:10px;">DAILY CAREER DIGEST • {DAILY_TIME_IST} IST</div>
<h1 style="margin:0 0 8px;font-size:25px;">🎯 Chennai Career Match Digest</h1>
<p style="margin:0;color:#cbd5e1;font-size:13px;">{html.escape(date_str)} • HR, Talent Acquisition & Business roles</p>
<p style="margin:12px 0 0;color:#e0e7ff;font-size:12px;">Tailored for Anosha Mariam Raji • BBA / HR Talent Acquisition</p>
</div>
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;text-align:center;border-bottom:1px solid #e2e8f0;">
<tr>
<td style="padding:15px 5px;width:33%;"><strong style="font-size:22px;">{total_scraped}</strong><br><span style="font-size:11px;color:#64748b;">ROLES EVALUATED</span></td>
<td style="padding:15px 5px;width:33%;"><strong style="font-size:22px;color:#059669;">{spam_count}</strong><br><span style="font-size:11px;color:#64748b;">SPAM FILTERED</span></td>
<td style="padding:15px 5px;width:33%;"><strong style="font-size:22px;color:#4f46e5;">{len(ranked_jobs)}</strong><br><span style="font-size:11px;color:#64748b;">MATCHES SHOWN</span></td>
</tr></table>
<div style="padding:22px;">
<div style="background:#eef2ff;border:1px solid #c7d2fe;border-radius:12px;padding:18px;margin-bottom:22px;">
<strong style="font-size:16px;color:#1e1b4b;">Hello Anosha! 👋</strong>
<p style="font-size:13px;line-height:1.65;color:#334155;margin-bottom:8px;">
Here are the retrieved matching HR, Talent Acquisition, Campus Hiring, HR Operations and Business Analytics listings for
<strong>Chennai, Tamil Nadu</strong>. Listings are ranked using keyword matches, posting recency, employer preference and location.
</p>
<p style="font-size:12px;color:#475569;margin:0;">Important: scores are heuristic estimates, not guarantees of qualification or employer quality.
Verify the job details and employer before applying.</p>
</div>
{''.join(cards)}
<div style="background:#f8fafc;border-left:4px solid #6366f1;padding:15px;border-radius:6px;font-size:13px;line-height:1.6;color:#475569;">
<strong>Recruiter tip:</strong> Highlight measurable hiring results, candidate response rates, time-to-hire,
campus hiring coordination, Naukri sourcing, LeadSquared CRM and Excel experience where applicable.
</div>
</div>
<div style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:20px;text-align:center;font-size:12px;color:#64748b;">
Automated Daily Career Digest • Chennai, Tamil Nadu<br>Prepared by Albi Aju
</div></div></body></html>"""


def generate_text_digest(ranked_jobs: list, spam_count: int, total_scraped: int) -> str:
    date_str = datetime.now(IST).strftime("%A, %B %d, %Y")
    lines = [
        f"DAILY CHENNAI CAREER DIGEST — {date_str}",
        "Tailored for Anosha Mariam Raji (BBA • HR Talent Acquisition)",
        "=" * 60,
        f"Roles evaluated: {total_scraped} | Spam filtered: {spam_count} | Matches: {len(ranked_jobs)}",
        "",
    ]
    if not ranked_jobs:
        lines.append(
            "No verified matching listings were retrieved today. "
            "The scraper may have been blocked or no matching Chennai postings were returned."
        )
    for index, job in enumerate(ranked_jobs, start=1):
        lines.extend([
            f"#{index}. {job['title']} — {job['company']}",
            f"Match: {job['score']}% ({job['match_tier']})",
            f"Location: {job['location']} | Type: {job['type']}",
            f"Posted: {job['recency_label']}",
            f"Matching skills: {', '.join(job['matched_skills']) or 'No specific skills verified'}",
            f"Apply/view: {job['apply_url']}",
            "-" * 60,
        ])
    lines.append("Verify the original listing and employer before applying.")
    return "\n".join(lines)

# =============================================================================
# EMAIL DELIVERY
# =============================================================================

def get_gmail_service():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        return None

    scopes = ["https://www.googleapis.com/auth/gmail.send"]
    creds = None
    env_token = os.getenv("GMAIL_TOKEN_JSON")

    if env_token:
        try:
            creds = Credentials.from_authorized_user_info(json.loads(env_token), scopes)
        except Exception as exc:
            print(f"[INFO] Could not parse GMAIL_TOKEN_JSON: {exc}")

    if not creds and os.path.exists(GMAIL_TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(GMAIL_TOKEN_FILE, scopes)
        except Exception as exc:
            print(f"[INFO] Could not read Gmail token file: {exc}")

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            Path(GMAIL_TOKEN_FILE).write_text(creds.to_json(), encoding="utf-8")
        except Exception as exc:
            print(f"[INFO] Gmail token refresh failed: {exc}")
            creds = None

    if not creds:
        if os.getenv("CI") or not sys.stdin.isatty():
            return None

        client_config = None
        env_creds = os.getenv("GMAIL_CREDENTIALS_JSON")
        if env_creds:
            try:
                client_config = json.loads(env_creds)
            except Exception:
                client_config = None

        try:
            if client_config:
                flow = InstalledAppFlow.from_client_config(client_config, scopes)
            elif os.path.exists(GMAIL_CREDENTIALS_FILE):
                flow = InstalledAppFlow.from_client_secrets_file(
                    GMAIL_CREDENTIALS_FILE, scopes
                )
            else:
                return None
            creds = flow.run_local_server(port=0)
            Path(GMAIL_TOKEN_FILE).write_text(creds.to_json(), encoding="utf-8")
        except Exception as exc:
            print(f"[INFO] Gmail OAuth setup failed: {exc}")
            return None

    return build("gmail", "v1", credentials=creds)


def send_via_gmail_api(service, sender: str, recipient: str, subject: str,
                       html_body: str, text_body: str) -> bool:
    message = MIMEMultipart("alternative")
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.attach(MIMEText(text_body, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    try:
        service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()
        print(f"[OK] Email sent via Gmail API to {recipient}")
        return True
    except Exception as exc:
        print(f"[ERROR] Gmail API send failed: {exc}")
        return False


def send_via_smtp(sender: str, recipient: str, subject: str,
                  html_body: str, text_body: str) -> bool:
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com").strip()
    try:
        smtp_port = int(os.getenv("SMTP_PORT", "587").strip())
    except ValueError:
        smtp_port = 587
    password = os.getenv("MAIL_PASSWORD", "").strip().replace(" ", "")
    if not password:
        print("[INFO] MAIL_PASSWORD is not configured.")
        return False

    message = MIMEMultipart("alternative")
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.attach(MIMEText(text_body, "plain", "utf-8"))
    message.attach(MIMEText(html_body, "html", "utf-8"))
    try:
        with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(sender, password)
            server.send_message(message)
        print(f"[OK] Email sent via SMTP to {recipient}")
        return True
    except Exception as exc:
        print(f"[ERROR] SMTP delivery failed: {exc}")
        return False


def dispatch_email(subject: str, html_body: str, text_body: str) -> bool:
    print(f"[INFO] Preparing email from {SENDER_EMAIL} to {RECIPIENT_EMAIL}")
    service = get_gmail_service()
    if service and send_via_gmail_api(
        service, SENDER_EMAIL, RECIPIENT_EMAIL, subject, html_body, text_body
    ):
        return True
    if os.getenv("MAIL_PASSWORD"):
        return send_via_smtp(
            SENDER_EMAIL, RECIPIENT_EMAIL, subject, html_body, text_body
        )
    print("[ERROR] No usable Gmail API credentials or SMTP password configured.")
    return False

# =============================================================================
# PIPELINE
# =============================================================================

def run_scraper_pipeline(dry_run: bool = False) -> list:
    print("=" * 65)
    print("DAILY CAREER DIGEST — CHENNAI, TAMIL NADU")
    print(f"Run time: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print("=" * 65)

    raw_jobs = fetch_jobs_from_apify()
    # Final location guard: no non-Chennai listing reaches the email.
    before_location_filter = len(raw_jobs)
    raw_jobs = [job for job in raw_jobs if is_valid_listing(job)]
    rejected_locations = before_location_filter - len(raw_jobs)
    if rejected_locations:
        print(
            f"[INFO] Final validation removed {rejected_locations} listing(s) with "
            "non-Chennai/unknown location or missing title, company, or direct URL."
        )

    total_scraped = len(raw_jobs)
    print(f"[INFO] Retrieved {total_scraped} Chennai candidate listings.")

    clean_jobs = []
    spam_jobs = []
    for job in raw_jobs:
        if is_blacklisted(job.get("company", "")):
            spam_jobs.append(job)
        else:
            clean_jobs.append(job)

    spam_count = len(spam_jobs)
    if spam_jobs:
        blocked = sorted({j.get("company", "") for j in spam_jobs if j.get("company")})
        print(f"[INFO] Filtered blacklisted companies: {', '.join(blocked)}")

    ranked_jobs = [score_job(job) for job in clean_jobs]
    ranked_jobs.sort(key=lambda job: job["score"], reverse=True)
    top_matches = ranked_jobs[:10]

    print(f"[INFO] Top matches selected: {len(top_matches)}")
    for index, job in enumerate(top_matches[:5], start=1):
        print(f"  {index}. {job['title']} at {job['company']} — {job['score']}%")

    date_for_subject = datetime.now(IST).strftime("%b %d")
    subject = f"Chennai Career Digest: {len(top_matches)} HR & Business Matches ({date_for_subject})"
    html_content = generate_html_digest(top_matches, spam_count, total_scraped)
    text_content = generate_text_digest(top_matches, spam_count, total_scraped)

    preview_file = BASE_DIR / "daily_jobs_preview.html"
    preview_file.write_text(html_content, encoding="utf-8")
    print(f"[INFO] HTML preview saved to: {preview_file}")

    if dry_run:
        print("[INFO] Dry run complete; no email was sent.")
        return top_matches

    if not dispatch_email(subject, html_content, text_content):
        print("[ERROR] Email delivery failed.")
    return top_matches


def main():
    parser = argparse.ArgumentParser(
        description="Daily Chennai HR, Talent Acquisition and Business Job Digest"
    )
    parser.add_argument("--now", action="store_true",
                        help="Run scraping and email immediately")
    parser.add_argument("--dry-run", action="store_true",
                        help="Scrape and generate preview without sending email")
    parser.add_argument("--schedule", action="store_true",
                        help="Run continuously at DAILY_TIME_IST every day")
    args = parser.parse_args()

    if args.now or args.dry_run:
        run_scraper_pipeline(dry_run=args.dry_run)
        return

    try:
        import schedule
    except ImportError:
        print("[INFO] 'schedule' package missing; running once.")
        run_scraper_pipeline()
        return

    print(f"[INFO] Scheduler active: daily at {DAILY_TIME_IST} IST.")
    print("Run once: python send_daily_jobs.py --now")
    print("Preview only: python send_daily_jobs.py --dry-run")
    print("Press Ctrl+C to stop.")
    schedule.every().day.at(DAILY_TIME_IST).do(run_scraper_pipeline)
    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        print("\n[INFO] Scheduler stopped.")


if __name__ == "__main__":
    main()
