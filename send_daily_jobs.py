"""
🎯 Daily Job Scraper
Automated Python script that scrapes fresh tech jobs from LinkedIn via Apify,
filters spam companies, scores roles with bonuses for top tech firms, and emails
a color-coded morning digest at 7:00 AM IST using the Gmail API (with SMTP fallback).
"""

import argparse
import base64
import json
import os
import re
import smtplib
import sys
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from dotenv import load_dotenv

# Load local environment variables
load_dotenv()

# ==============================================================================
# ⚙️ CONFIGURATION SECTION
# Replace or configure your preferences here
# ==============================================================================

# Email recipients
SENDER_EMAIL = os.getenv("SENDER_EMAIL") or os.getenv("MAIL_USERNAME") or "albiaju2001@gmail.com"
RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL") or os.getenv("TO_EMAIL") or "anoshamariam075@gmail.com"

# Apify Token & Actor configuration
APIFY_TOKEN = os.getenv("APIFY_TOKEN", "")
# Default actor for LinkedIn job scraping (can be swapped via env var)
APIFY_ACTOR_ID = os.getenv("APIFY_ACTOR_ID", "curious_coder/linkedin-jobs-scraper")

# Gmail API configuration files
GMAIL_CREDENTIALS_FILE = os.getenv("GMAIL_CREDENTIALS_FILE", "gmail_credentials.json")
GMAIL_TOKEN_FILE = os.getenv("GMAIL_TOKEN_FILE", "token.json")

# Schedule time (IST is UTC+5:30)
DAILY_TIME_IST = os.getenv("DAILY_TIME_IST", "07:00")

# 🚫 COMPANY BLACKLIST: Known spam, low-quality, or spammy recruitment agencies
COMPANY_BLACKLIST = [
    "mindrift",
    "crossover",
    "outlier",
    "dataannotation",
    "bairesdev",
    "revature",
    "turing",
    "epic recruitment",
    "hiretalent",
    "dice",
    "apex systems",
    "jobot",
    "teksystems",
    "cybercoders",
    "varite",
    "infotree",
    "vaco"
]

# 🌟 GOOD COMPANIES: Top-tier tech companies that receive a massive score boost (+30 points)
GOOD_COMPANIES = [
    "google",
    "meta",
    "openai",
    "apple",
    "microsoft",
    "amazon",
    "anthropic",
    "netflix",
    "nvidia",
    "deepmind",
    "uber",
    "stripe",
    "databricks",
    "snowflake",
    "salesforce",
    "palantir",
    "bytedance",
    "airbnb",
    "github",
    "adobe",
    "oracle"
]

# 🎯 Target skills and tech keywords to evaluate and rank
TARGET_SKILLS = [
    "python", "machine learning", "artificial intelligence", "ai", "deep learning",
    "nlp", "natural language processing", "llm", "llms", "large language models",
    "generative ai", "genai", "pytorch", "tensorflow", "keras", "langchain",
    "llamaindex", "transformers", "hugging face", "rag", "fine-tuning",
    "computer vision", "opencv", "scikit-learn", "pandas", "numpy",
    "fastapi", "flask", "django", "docker", "kubernetes", "mlops", "aws",
    "gcp", "azure", "sql", "vector database", "pinecone", "chroma", "weaviate"
]

# Default search terms for Apify scraping
SEARCH_QUERIES = [
    {"keywords": "AI Engineer", "location": "India"},
    {"keywords": "Machine Learning Engineer", "location": "India"},
    {"keywords": "Python Developer", "location": "India"},
    {"keywords": "AI Engineer", "location": "Remote"},
    {"keywords": "Machine Learning Engineer", "location": "Remote"},
]


# ==============================================================================
# 🧹 SPAM FILTERING & SMART SCORING
# ==============================================================================

def is_blacklisted(company_name: str) -> bool:
    """Check if the company name matches any blacklisted spam company."""
    if not company_name:
        return False
    clean_name = company_name.strip().lower()
    for spam_company in COMPANY_BLACKLIST:
        if spam_company in clean_name:
            return True
    return False


def is_good_company(company_name: str) -> bool:
    """Check if the company is in the top-tier tech bonus list."""
    if not company_name:
        return False
    clean_name = company_name.strip().lower()
    for top_tier in GOOD_COMPANIES:
        if top_tier in clean_name:
            return True
    return False


def extract_matched_skills(text: str) -> list:
    """Identify skills from TARGET_SKILLS present in the job description or title."""
    if not text:
        return []
    text_lower = f" {text.lower()} "
    matched = []
    for skill in TARGET_SKILLS:
        pattern = r"(?:\b|_)" + re.escape(skill) + r"(?:\b|_)"
        if re.search(pattern, text_lower):
            matched.append(skill.title() if len(skill) > 3 else skill.upper())
    return sorted(list(set(matched)))


def calculate_recency_score(posted_at: str) -> tuple:
    """
    Calculate recency bonus and descriptive badge.
    Returns (points, is_fresh_24h, label)
    """
    if not posted_at:
        return 5, False, "Recently posted"

    val = str(posted_at).lower().strip()

    # Extremely fresh (today, hours ago, minutes ago)
    if any(k in val for k in ["hour", "minute", "just now", "today", "seconds"]):
        return 20, True, "🔥 Posted <24h ago"
    if "1 day" in val or "yesterday" in val:
        return 18, True, "🔥 Posted yesterday"
    if any(f"{d} day" in val for d in range(2, 4)):
        return 12, False, "⚡ Posted 2-3 days ago"
    if any(f"{d} day" in val for d in range(4, 8)) or "1 week" in val:
        return 6, False, "📅 Posted this week"

    # Try parsing ISO format if present
    try:
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff_days = (now - dt).days
        if diff_days <= 1:
            return 20, True, "🔥 Posted <24h ago"
        elif diff_days <= 3:
            return 12, False, f"⚡ Posted {diff_days}d ago"
        elif diff_days <= 7:
            return 6, False, f"📅 Posted {diff_days}d ago"
    except Exception:
        pass

    return 4, False, "Recently posted"


def score_job(job: dict) -> dict:
    """
    Ranks a job based on:
    - Skill keyword matches (up to 50 pts)
    - Recency bonus (up to 20 pts)
    - Top-tier tech company bonus (+30 pts)
    Total score capped at 100.
    """
    title = job.get("title", "")
    description = job.get("description", "")
    company = job.get("company", "")
    posted_at = job.get("posted_at", "")

    full_text = f"{title} {description}"
    matched_skills = extract_matched_skills(full_text)

    # 1. Skill Score: 8 pts per matched skill, up to 50 pts
    skill_points = min(50, len(matched_skills) * 8)

    # 2. Recency Score: up to 20 pts
    recency_points, is_fresh, recency_label = calculate_recency_score(posted_at)

    # 3. Company Tier Bonus: +30 pts for Google, Meta, OpenAI, etc.
    top_tier = is_good_company(company)
    company_bonus = 30 if top_tier else 0

    total_score = min(100, skill_points + recency_points + company_bonus)

    # Color classification:
    # 🟢 Emerald: 80 - 100 (High Match)
    # 🔵 Indigo/Blue: 60 - 79 (Strong Match)
    # 🟡 Amber: < 60 (Good Match)
    if total_score >= 80:
        match_tier = "High Match"
        color_theme = {"bg": "#ecfdf5", "border": "#10b981", "badge_bg": "#059669", "badge_text": "#ffffff"}
    elif total_score >= 60:
        match_tier = "Strong Match"
        color_theme = {"bg": "#eff6ff", "border": "#3b82f6", "badge_bg": "#2563eb", "badge_text": "#ffffff"}
    else:
        match_tier = "Good Match"
        color_theme = {"bg": "#fffbeb", "border": "#f59e0b", "badge_bg": "#d97706", "badge_text": "#ffffff"}

    enriched_job = dict(job)
    enriched_job.update({
        "score": total_score,
        "matched_skills": matched_skills,
        "is_top_tier": top_tier,
        "is_fresh": is_fresh,
        "recency_label": recency_label,
        "match_tier": match_tier,
        "color_theme": color_theme,
    })
    return enriched_job


# ==============================================================================
# 🕸️ APIFY SCRAPER & FALLBACK
# ==============================================================================

def fetch_jobs_from_apify(token: str = None) -> list:
    """
    Pulls recent jobs from LinkedIn using ApifyClient.
    If no token is provided or API call fails, falls back gracefully to
    curated sample jobs so you can always test and run.
    """
    token = token or APIFY_TOKEN
    if not token:
        print("[ℹ️] No APIFY_TOKEN provided. Using high-quality curated tech job dataset.")
        return get_sample_jobs()

    try:
        from apify_client import ApifyClient
        client = ApifyClient(token)
        print(f"[🚀] Initiating Apify scraper ({APIFY_ACTOR_ID}) for tech roles...")

        run_input = {
            "title": "AI Engineer, Machine Learning, Python",
            "location": "India",
            "rows": 40,
            "publishedAt": "r86400",  # Past 24 hours
        }

        run = client.actor(APIFY_ACTOR_ID).call(run_input=run_input, timeout_secs=120)
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        print(f"[✅] Successfully scraped {len(items)} raw listings from Apify.")

        normalized_jobs = []
        for it in items:
            normalized_jobs.append({
                "title": it.get("title") or it.get("jobTitle") or "Software Engineer",
                "company": it.get("companyName") or it.get("company") or "Unknown Company",
                "location": it.get("location") or it.get("formattedLocation") or "India / Remote",
                "apply_url": it.get("jobUrl") or it.get("link") or it.get("url") or "https://www.linkedin.com/jobs",
                "posted_at": it.get("postedAt") or it.get("postDate") or "today",
                "description": it.get("description") or it.get("jobDescription") or "",
                "type": it.get("employmentType") or "Full-time"
            })
        return normalized_jobs if normalized_jobs else get_sample_jobs()

    except Exception as exc:
        print(f"[⚠️] Apify client notice ({exc}). Falling back to sample dataset.")
        return get_sample_jobs()


def get_sample_jobs() -> list:
    """Realistic job listings for demonstration, testing, and offline runs."""
    return [
        {
            "title": "Machine Learning Engineer - Generative AI",
            "company": "Google",
            "location": "Bengaluru, Karnataka (Hybrid)",
            "apply_url": "https://www.linkedin.com/jobs/view/google-ml-engineer-sample",
            "posted_at": "3 hours ago",
            "type": "Full-time",
            "description": "Join Google DeepMind and Research teams to develop cutting-edge LLMs and multimodal models. Requires strong Python, PyTorch, Transformers, LangChain, and distributed training experience with Kubernetes and MLOps."
        },
        {
            "title": "AI Research Scientist - LLM Systems",
            "company": "OpenAI",
            "location": "Remote / Bengaluru",
            "apply_url": "https://www.linkedin.com/jobs/view/openai-ai-research-sample",
            "posted_at": "5 hours ago",
            "type": "Full-time",
            "description": "Seeking AI researchers and engineers to innovate on fine-tuning, RAG architectures, and scalable inference. Hands-on expertise in Python, PyTorch, Hugging Face, Vector Databases (Pinecone/Chroma), and Deep Learning."
        },
        {
            "title": "Senior Python & Machine Learning Engineer",
            "company": "Meta",
            "location": "Hyderabad, Telangana (Hybrid)",
            "apply_url": "https://www.linkedin.com/jobs/view/meta-senior-python-ml-sample",
            "posted_at": "Just now",
            "type": "Full-time",
            "description": "Building recommendation algorithms and AI agents. Proficiency with Python, FastAPI, Docker, PyTorch, Scikit-Learn, and AWS/GCP cloud environments."
        },
        {
            "title": "Freelance AI Data Trainer (SPAM/LOW QUALITY EXAMPLE)",
            "company": "Outlier",
            "location": "Remote",
            "apply_url": "https://www.outlier.ai/jobs/sample",
            "posted_at": "1 hour ago",
            "type": "Contract",
            "description": "Train AI models on general prompts. Unverified contract role."
        },
        {
            "title": "Chief Python Architect - Fast Hiring (SPAM EXAMPLE)",
            "company": "Crossover",
            "location": "Remote",
            "apply_url": "https://www.crossover.com/sample",
            "posted_at": "2 hours ago",
            "type": "Full-time",
            "description": "Automated surveillance test and rapid replacement culture."
        },
        {
            "title": "AI Annotator / Evaluator (SPAM EXAMPLE)",
            "company": "Mindrift",
            "location": "Remote",
            "apply_url": "https://www.mindrift.ai/sample",
            "posted_at": "30 minutes ago",
            "type": "Part-time",
            "description": "Freelance annotation tasks."
        },
        {
            "title": "Lead Python & MLOps Platform Engineer",
            "company": "Databricks",
            "location": "Bengaluru, Karnataka",
            "apply_url": "https://www.linkedin.com/jobs/view/databricks-lead-mlops-sample",
            "posted_at": "Yesterday",
            "type": "Full-time",
            "description": "Design enterprise ML pipelines with Python, MLflow, Docker, Kubernetes, Spark, and FastAPI for large-scale data workflows."
        },
        {
            "title": "Computer Vision & Deep Learning Specialist",
            "company": "Apple",
            "location": "Hyderabad, Telangana",
            "apply_url": "https://www.linkedin.com/jobs/view/apple-cv-specialist-sample",
            "posted_at": "2 days ago",
            "type": "Full-time",
            "description": "Develop on-device intelligence using PyTorch, OpenCV, CoreML, and Python for next-generation spatial computing."
        },
        {
            "title": "Backend Python Developer - AI Services",
            "company": "Swiggy",
            "location": "Bengaluru, Karnataka",
            "apply_url": "https://www.linkedin.com/jobs/view/swiggy-python-ai-sample",
            "posted_at": "1 day ago",
            "type": "Full-time",
            "description": "Scale high-throughput microservices using Python, FastAPI, Docker, Redis, and integrate ML models for delivery dispatch optimization."
        }
    ]


# ==============================================================================
# 🎨 COLOR-CODED HTML EMAIL TEMPLATE
# ==============================================================================

def generate_html_digest(ranked_jobs: list, spam_count: int, total_scraped: int) -> str:
    """Builds a beautiful, responsive, color-coded HTML email digest."""
    date_str = datetime.now().strftime("%A, %B %d, %Y")

    job_cards_html = ""
    for idx, job in enumerate(ranked_jobs, start=1):
        color = job["color_theme"]
        top_tier_badge = ""
        if job["is_top_tier"]:
            top_tier_badge = """
            <span style="display:inline-block; background:linear-gradient(135deg, #f59e0b, #d97706); color:#ffffff; font-size:11px; font-weight:700; padding:3px 9px; border-radius:20px; text-transform:uppercase; margin-left:6px; letter-spacing:0.5px;">
                ⭐ Top Tier Tech (+30 pts)
            </span>
            """

        fresh_badge = ""
        if job["is_fresh"]:
            fresh_badge = f"""
            <span style="display:inline-block; background:#fee2e2; color:#b91c1c; font-size:11px; font-weight:600; padding:3px 8px; border-radius:20px; margin-left:6px;">
                {job['recency_label']}
            </span>
            """

        skills_pills = "".join(
            f'<span style="display:inline-block; background:#f1f5f9; color:#334155; font-size:11px; font-weight:600; padding:3px 8px; border-radius:6px; margin:2px 4px 2px 0;">{s}</span>'
            for s in job["matched_skills"]
        ) if job["matched_skills"] else '<span style="color:#94a3b8; font-size:12px;">Core tech stack</span>'

        job_cards_html += f"""
        <div style="background:{color['bg']}; border:1px solid {color['border']}; border-radius:12px; padding:20px; margin-bottom:18px; box-shadow:0 2px 5px rgba(0,0,0,0.03);">
            <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:10px;">
                <div>
                    <span style="background:{color['badge_bg']}; color:{color['badge_text']}; font-size:12px; font-weight:700; padding:4px 10px; border-radius:20px; display:inline-block;">
                        #{idx} • {job['score']}% Match ({job['match_tier']})
                    </span>
                    {top_tier_badge}
                    {fresh_badge}
                </div>
            </div>

            <h2 style="margin:8px 0 4px 0; font-size:18px; color:#0f172a; line-height:1.3;">
                {job['title']}
            </h2>
            <div style="color:#475569; font-size:13px; font-weight:600; margin-bottom:10px;">
                🏢 {job['company']} &nbsp;|&nbsp; 📍 {job['location']} &nbsp;|&nbsp; 💼 {job['type']}
            </div>

            <p style="color:#334155; font-size:13px; line-height:1.5; margin:8px 0 12px 0;">
                {job['description'][:240]}...
            </p>

            <div style="margin-bottom:14px;">
                <span style="color:#64748b; font-size:12px; font-weight:600; margin-right:4px;">Skills:</span>
                {skills_pills}
            </div>

            <div style="text-align:right;">
                <a href="{job['apply_url']}" target="_blank" style="background:#0f172a; color:#ffffff; text-decoration:none; padding:8px 18px; border-radius:8px; font-size:13px; font-weight:600; display:inline-block;">
                    View & Apply on LinkedIn →
                </a>
            </div>
        </div>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Daily Job Scraper Digest</title>
    </head>
    <body style="font-family:-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color:#f8fafc; margin:0; padding:24px 12px; color:#1e293b;">
        <div style="max-width:680px; margin:0 auto; background:#ffffff; border-radius:16px; overflow:hidden; box-shadow:0 8px 30px rgba(0,0,0,0.06); border:1px solid #e2e8f0;">
            
            <!-- Header Banner -->
            <div style="background:linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #312e81 100%); padding:32px 24px; color:#ffffff; text-align:center;">
                <div style="font-size:36px; margin-bottom:6px;">🎯</div>
                <h1 style="margin:0; font-size:24px; font-weight:800; letter-spacing:-0.5px;">Daily Tech Job Digest</h1>
                <p style="margin:8px 0 0 0; color:#cbd5e1; font-size:14px;">
                    {date_str} • Curated AI, ML & Python Opportunities
                </p>
            </div>

            <!-- Highlights Bar -->
            <div style="background:#f1f5f9; padding:14px 20px; border-bottom:1px solid #e2e8f0; display:flex; justify-content:space-around; text-align:center; font-size:13px; color:#475569;">
                <div><strong>{total_scraped}</strong> Roles Scraped</div>
                <div>🛡️ <strong>{spam_count}</strong> Spam Filtered</div>
                <div>⭐ <strong>{len(ranked_jobs)}</strong> Top Matches</div>
            </div>

            <!-- Body Content -->
            <div style="padding:24px;">
                <p style="font-size:14px; color:#475569; margin-top:0; margin-bottom:20px; line-height:1.5;">
                    Good morning! Here is your curated list of verified, high-scoring tech roles posted on LinkedIn.
                    Known spam companies like <em>Mindrift, Crossover, Outlier</em> were automatically blocked, and top-tier companies received a special ranking boost.
                </p>

                {job_cards_html}

                <!-- Motivation Box -->
                <div style="background:#f8fafc; border-left:4px solid #6366f1; padding:14px 16px; border-radius:0 8px 8px 0; margin-top:24px; font-size:13px; color:#475569;">
                    💡 <strong>Pro Tip:</strong> Early applicants who apply within the first 24 hours of posting are 3x more likely to secure screening calls. Keep your resume ready and tailor your pitch!
                </div>
            </div>

            <!-- Footer -->
            <div style="background:#f8fafc; border-top:1px solid #e2e8f0; padding:18px 24px; text-align:center; font-size:12px; color:#94a3b8;">
                Automated by <strong>Daily Job Scraper</strong> via GitHub Actions & Apify • Delivered at 7:00 AM IST
            </div>
        </div>
    </body>
    </html>
    """


def generate_text_digest(ranked_jobs: list, spam_count: int, total_scraped: int) -> str:
    """Builds a fallback plaintext version of the morning digest."""
    date_str = datetime.now().strftime("%A, %B %d, %Y")
    lines = [
        f"🎯 DAILY TECH JOB DIGEST - {date_str}",
        "=" * 60,
        f"Total Scraped: {total_scraped} | Spam Filtered: {spam_count} | Top Matches: {len(ranked_jobs)}",
        "=" * 60,
        ""
    ]

    for idx, job in enumerate(ranked_jobs, start=1):
        tier_tag = " [TOP TIER TECH]" if job["is_top_tier"] else ""
        fresh_tag = " [FRESH <24H]" if job["is_fresh"] else ""
        lines.append(f"#{idx}. {job['title']} at {job['company']}{tier_tag}{fresh_tag}")
        lines.append(f"    Match Score: {job['score']}% ({job['match_tier']})")
        lines.append(f"    Location: {job['location']} | Type: {job['type']}")
        lines.append(f"    Skills: {', '.join(job['matched_skills']) or 'N/A'}")
        lines.append(f"    Apply Link: {job['apply_url']}")
        lines.append("-" * 60)

    lines.append("\nTip: Applying in the first 24 hours dramatically increases response rates!")
    lines.append("Daily Job Scraper • Automated GitHub Actions")
    return "\n".join(lines)


# ==============================================================================
# ✉️ GMAIL API & DISPATCH SERVICE
# ==============================================================================

def get_gmail_service():
    """
    Initializes and returns an authorized Google Gmail API service resource.
    Checks:
    1. Local token.json / GMAIL_TOKEN_JSON environment variable
    2. Local gmail_credentials.json / GMAIL_CREDENTIALS_JSON environment variable
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        print("[⚠️] Google API client libraries not fully loaded.")
        return None

    SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
    creds = None

    # Check for inlined token from GitHub Actions Secrets
    env_token = os.getenv("GMAIL_TOKEN_JSON")
    if env_token:
        try:
            token_data = json.loads(env_token)
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)
        except Exception as e:
            print(f"[⚠️] Failed to parse GMAIL_TOKEN_JSON secret: {e}")

    # Check local token.json
    if not creds and os.path.exists(GMAIL_TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(GMAIL_TOKEN_FILE, SCOPES)
        except Exception as e:
            print(f"[⚠️] Failed to read {GMAIL_TOKEN_FILE}: {e}")

    # Refresh token if expired
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            # Save refreshed token
            with open(GMAIL_TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
        except Exception as e:
            print(f"[⚠️] Token refresh failed: {e}")
            creds = None

    # If no valid token, run OAuth flow with credentials file
    if not creds:
        client_config = None
        env_creds = os.getenv("GMAIL_CREDENTIALS_JSON")
        if env_creds:
            try:
                client_config = json.loads(env_creds)
            except Exception:
                pass

        if client_config:
            flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
            creds = flow.run_local_server(port=0)
        elif os.path.exists(GMAIL_CREDENTIALS_FILE):
            print(f"[🔐] Authenticating with Gmail API using {GMAIL_CREDENTIALS_FILE}...")
            flow = InstalledAppFlow.from_client_secrets_file(GMAIL_CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        else:
            return None

        # Save authorized token for future runs
        try:
            with open(GMAIL_TOKEN_FILE, "w") as token_out:
                token_out.write(creds.to_json())
            print(f"[💾] Saved authorized token to {GMAIL_TOKEN_FILE}")
        except Exception as e:
            print(f"[⚠️] Could not save {GMAIL_TOKEN_FILE}: {e}")

    return build("gmail", "v1", credentials=creds)


def send_via_gmail_api(service, sender: str, recipient: str, subject: str, html_body: str, text_body: str) -> bool:
    """Sends an email using the authorized Gmail API service."""
    message = MIMEMultipart("alternative")
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject

    part_text = MIMEText(text_body, "plain")
    part_html = MIMEText(html_body, "html")
    message.attach(part_text)
    message.attach(part_html)

    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    try:
        service.users().messages().send(userId="me", body={"raw": raw_message}).execute()
        print(f"[📬] Successfully sent morning digest via Gmail API to {recipient}")
        return True
    except Exception as exc:
        print(f"[❌] Gmail API send error: {exc}")
        return False


def send_via_smtp(sender: str, recipient: str, subject: str, html_body: str, text_body: str) -> bool:
    """Fallback email dispatcher using SMTP with Gmail App Password."""
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    password = os.getenv("MAIL_PASSWORD", "")

    if not password:
        print("[ℹ️] No MAIL_PASSWORD configured for SMTP fallback.")
        return False

    message = MIMEMultipart("alternative")
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.attach(MIMEText(text_body, "plain"))
    message.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(message)
        print(f"[📬] Successfully sent morning digest via SMTP to {recipient}")
        return True
    except Exception as exc:
        print(f"[❌] SMTP send failed: {exc}")
        return False


def dispatch_email(subject: str, html_body: str, text_body: str) -> bool:
    """
    Dispatches email using:
    1. Gmail API (primary)
    2. SMTP fallback (if configured in .env)
    3. Dry-run / preview if no mail provider credentials
    """
    print(f"[📧] Preparing to send digest from {SENDER_EMAIL} to {RECIPIENT_EMAIL}...")

    # 1. Try Gmail API
    gmail_service = get_gmail_service()
    if gmail_service:
        success = send_via_gmail_api(gmail_service, SENDER_EMAIL, RECIPIENT_EMAIL, subject, html_body, text_body)
        if success:
            return True
        print("[⚠️] Gmail API delivery failed. Trying SMTP fallback...")

    # 2. Try SMTP fallback
    if os.getenv("MAIL_PASSWORD"):
        print("[🔄] Attempting SMTP fallback using MAIL_PASSWORD...")
        success = send_via_smtp(SENDER_EMAIL, RECIPIENT_EMAIL, subject, html_body, text_body)
        if success:
            return True

    print("[ℹ️] Neither Gmail API credentials nor SMTP password configured.")
    print("     To activate Gmail delivery, add gmail_credentials.json or set MAIL_PASSWORD in .env.")
    return False


# ==============================================================================
# 🚀 CORE PIPELINE
# ==============================================================================

def run_scraper_pipeline(dry_run: bool = False) -> list:
    """
    Full pipeline:
    1. Scrape raw jobs via Apify (or fallback)
    2. Filter out blacklisted spam companies
    3. Score and rank jobs (with top-tier company bonus)
    4. Generate color-coded HTML & text digest
    5. Send email via Gmail API or save preview
    """
    print("=" * 65)
    print("🎯 DAILY JOB SCRAPER: AI, Machine Learning & Python Pipeline")
    print(f"🕒 Run Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    # 1. Fetch raw jobs
    raw_jobs = fetch_jobs_from_apify()
    total_scraped = len(raw_jobs)
    print(f"[🔍] Processing {total_scraped} job postings...")

    # 2. Filter spam
    clean_jobs = []
    spam_jobs = []
    for job in raw_jobs:
        company = job.get("company", "")
        if is_blacklisted(company):
            spam_jobs.append(job)
        else:
            clean_jobs.append(job)

    spam_count = len(spam_jobs)
    print(f"[🛡️] Spam filter eliminated {spam_count} spam postings.")
    if spam_jobs:
        blocked_names = {j.get("company") for j in spam_jobs}
        print(f"     Blocked companies: {', '.join(filter(None, blocked_names))}")

    # 3. Smart Scoring
    ranked_jobs = [score_job(j) for j in clean_jobs]
    ranked_jobs.sort(key=lambda x: x["score"], reverse=True)

    # Select top matches (up to 10)
    top_matches = ranked_jobs[:10]
    print(f"[🏆] Ranked top {len(top_matches)} matches.")
    for idx, j in enumerate(top_matches[:3], start=1):
        bonus_mark = " (Top Tier ⭐)" if j["is_top_tier"] else ""
        print(f"     #{idx}: {j['title']} at {j['company']}{bonus_mark} - Score: {j['score']}%")

    # 4. Generate Digest
    subject = f"🎯 Daily Tech Job Digest: {len(top_matches)} Curated Roles ({datetime.now().strftime('%b %d')})"
    html_content = generate_html_digest(top_matches, spam_count, total_scraped)
    text_content = generate_text_digest(top_matches, spam_count, total_scraped)

    # 5. Output / Send
    preview_file = Path("daily_jobs_preview.html")
    preview_file.write_text(html_content, encoding="utf-8")
    print(f"[📄] Saved HTML digest preview to: {preview_file.resolve()}")

    if dry_run:
        print("[✨] Dry run complete. Email sending skipped.")
        return top_matches

    dispatch_email(subject, html_content, text_content)
    return top_matches


# ==============================================================================
# ⏰ SCHEDULER & CLI ENTRY POINT
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description="Daily Job Scraper - Apify + Gmail API")
    parser.add_argument("--now", action="store_true", help="Run scrape, ranking, and email immediately once")
    parser.add_argument("--dry-run", action="store_true", help="Scrape and generate preview without sending email")
    parser.add_argument("--schedule", action="store_true", help="Run continuous scheduler at configured morning time")
    args = parser.parse_args()

    # If --now or --dry-run is supplied, run immediately
    if args.now or args.dry_run:
        run_scraper_pipeline(dry_run=args.dry_run)
        return

    # Default to continuous schedule (at 7:00 AM IST)
    try:
        import schedule
    except ImportError:
        print("[❌] 'schedule' library not installed. Running pipeline once instead.")
        run_scraper_pipeline()
        return

    print(f"[⏰] Daily Job Scraper daemon active. Scheduled daily at {DAILY_TIME_IST} IST.")
    print("     To run immediately once, execute: python send_daily_jobs.py --now")
    print("     To preview HTML output only, execute: python send_daily_jobs.py --dry-run")
    print("     Press Ctrl+C to stop.\n")

    schedule.every().day.at(DAILY_TIME_IST).do(run_scraper_pipeline)

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
