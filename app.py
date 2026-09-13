import json
import os
import re
import smtplib
import urllib.parse
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from flask import Flask, render_template_string, request

load_dotenv()

app = Flask(__name__)
BASE_DIR = Path(__file__).resolve().parent
JOBS_FILE = BASE_DIR / "jobs.json"
RESUME_EXTENSIONS = {".pdf", ".txt", ".docx"}

DEFAULT_RESUME = ""

THOUGHTS = [
    "Success is built by small, consistent actions every day.",
    "Your next opportunity is closer than your last rejection.",
    "Keep refining your skills and the right role will find you.",
    "Confidence grows when you show up prepared and persistent.",
    "A focused plan beats a busy schedule every time."
]


def get_daily_thought():
    day_number = datetime.now().day
    return THOUGHTS[day_number % len(THOUGHTS)]


def extract_keywords(text):
    words = re.findall(r"[a-zA-Z][a-zA-Z+.#-]{2,}", text.lower())
    stop_words = {
        "the", "and", "for", "with", "from", "this", "that", "into", "your", "have",
        "will", "more", "than", "about", "been", "were", "they", "them", "their",
        "there", "also", "using", "skills", "experience", "work", "role", "team",
        "build", "built", "very", "years", "year", "developer", "engineer", "software"
    }
    cleaned = []
    for word in words:
        if word not in stop_words and len(word) > 2:
            cleaned.append(word)
    return set(cleaned)


def load_jobs():
    with JOBS_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_resume_from_file(file_path):
    if not file_path:
        return ""

    path = Path(file_path)
    if not path.exists():
        return ""

    if path.suffix.lower() == ".txt":
        try:
            return path.read_text(encoding="utf-8", errors="ignore") or ""
        except Exception:
            return ""

    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            return text.strip() or ""
        except Exception:
            return ""

    return ""


def detect_resume_file():
    resume_candidates = []
    for path in BASE_DIR.iterdir():
        if path.is_file() and path.suffix.lower() in RESUME_EXTENSIONS:
            resume_candidates.append(path)

    if not resume_candidates:
        return None

    resume_candidates.sort(key=lambda p: p.name.lower())
    named_matches = [p for p in resume_candidates if "resume" in p.name.lower() or "cv" in p.name.lower()]
    if named_matches:
        named_matches.sort(key=lambda p: (p.stat().st_mtime, p.name.lower()), reverse=True)
        return named_matches[0]

    resume_candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return resume_candidates[0]


def get_resume_text(file_storage=None):
    if file_storage and getattr(file_storage, "filename", None):
        return extract_text_from_resume(file_storage)

    configured_resume = os.getenv("RESUME_PATH")
    if configured_resume:
        return load_resume_from_file(configured_resume)

    detected_resume = detect_resume_file()
    if detected_resume:
        return load_resume_from_file(str(detected_resume))

    return ""


def preferred_location_bonus(job_location):
    preferred_terms = [
        "bengaluru", "bangalore", "chennai", "hyderabad", "kochi", "coimbatore",
        "mysuru", "mysore", "trivandrum", "thiruvananthapuram", "vizag", "visakhapatnam",
        "remote india", "india"
    ]
    location = (job_location or "").lower()
    if any(term in location for term in preferred_terms):
        return 20
    return 0


def score_job(resume_text, job):
    if not resume_text or not resume_text.strip():
        return 0, []

    resume_keywords = extract_keywords(resume_text)
    job_keywords = set(job.get("skills", [])) | extract_keywords(job.get("description", ""))
    overlap = resume_keywords & job_keywords
    base_score = round((len(overlap) / max(len(job_keywords), 1)) * 100, 2)
    location_bonus = preferred_location_bonus(job.get("location", ""))
    score = min(100.0, round(base_score + location_bonus, 2))
    return score, sorted(overlap)


def build_company_link(company, title, location, existing_url):
    clean_company = (company or "").strip()
    clean_title = (title or "").strip()
    clean_loc = (location or "Bengaluru, Karnataka").strip()
    
    # If the URL already contains the company name, use it
    if existing_url and (clean_company.lower() in existing_url.lower() or urllib.parse.quote(clean_company).lower() in existing_url.lower()):
        return existing_url

    encoded_keywords = urllib.parse.quote(f"{clean_company} {clean_title}".strip())
    encoded_loc = urllib.parse.quote(clean_loc)
    return f"https://www.linkedin.com/jobs/search/?keywords={encoded_keywords}&location={encoded_loc}"


def find_ranked_jobs(resume_text):
    if not resume_text or not resume_text.strip():
        return []

    jobs = load_jobs()
    ranked_jobs = []
    for job in jobs:
        score, overlap = score_job(resume_text, job)
        apply_url = build_company_link(job.get("company", ""), job.get("title", ""), job.get("location", ""), job.get("apply_url", ""))
        ranked_jobs.append({
            "company": job["company"],
            "title": job["title"],
            "location": job["location"],
            "type": job["type"],
            "apply_url": apply_url,
            "description": job["description"],
            "score": score,
            "match_keywords": overlap[:10]
        })
    ranked_jobs.sort(key=lambda x: x["score"], reverse=True)
    return ranked_jobs


def find_best_job(resume_text):
    ranked_jobs = find_ranked_jobs(resume_text)
    return ranked_jobs[0] if ranked_jobs else None


def build_email_body(ranked_jobs):
    if not ranked_jobs:
        return "No jobs matched your resume today."

    thought = get_daily_thought()
    lines = [
        "Subject: Daily Job Match Recommendation",
        "",
        "Hello,",
        "",
        "Here are the best job matches based on your resume:",
        ""
    ]

    for index, job in enumerate(ranked_jobs, start=1):
        lines.append(f"{index}. {job['title']} at {job['company']}")
        lines.append(f"   Location: {job['location']} | Type: {job['type']} | Match Score: {job['score']}%")
        lines.append(f"   Apply Link: {job['apply_url']}")
        lines.append(f"   Matching skills: {', '.join(job['match_keywords']) or 'core requirements'}")
        lines.append("")

    lines.extend([
        f"Daily Thought: {thought}",
        "",
        "Keep pushing forward. The right opportunity is on the way.",
        "",
        "Crafted for Anosha by Albi",
        "CareerBoost Assistant"
    ])
    return "\n".join(lines)


def send_email(subject, body, to_email=None):
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    sender_email = os.getenv("MAIL_USERNAME")
    sender_password = os.getenv("MAIL_PASSWORD")
    to_email = to_email or os.getenv("TO_EMAIL") or sender_email

    if not sender_email or not sender_password or not to_email:
        print("\n--- Email preview (SMTP not configured) ---")
        print(f"Subject: {subject}\n{body}\n")
        return True

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = to_email

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)
        print("Email sent successfully.")
        return True
    except Exception as exc:
        print(f"Email failed: {exc}")
        return False


def extract_text_from_resume(file_storage):
    if not file_storage or not file_storage.filename:
        return ""

    name = file_storage.filename.lower()
    raw = file_storage.read()

    if name.endswith(".txt"):
        return raw.decode("utf-8", errors="ignore") or ""

    if name.endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except ImportError:
            return raw.decode("utf-8", errors="ignore") or ""

        reader = PdfReader(file_storage)
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages) or ""

    if name.endswith(".docx"):
        try:
            import docx
        except ImportError:
            return ""

        document = docx.Document(file_storage)
        return "\n".join(paragraph.text for paragraph in document.paragraphs) or ""

    return raw.decode("utf-8", errors="ignore") or ""


def send_daily_job_email():
    resume_text = get_resume_text()
    ranked_jobs = find_ranked_jobs(resume_text)
    email_body = build_email_body(ranked_jobs)
    send_email("Your Daily Job Match", email_body)
    return ranked_jobs


@app.route("/", methods=["GET"])
def home():
    detected_resume = detect_resume_file()
    resume_path = os.getenv("RESUME_PATH") or (str(detected_resume) if detected_resume else "")
    resume_text = load_resume_from_file(resume_path) if resume_path else get_resume_text()
    ranked_jobs = find_ranked_jobs(resume_text)

    return render_template_string("""
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <title>CareerBoost Match</title>
      <style>
        body { font-family: Arial, sans-serif; background: #f4f6fb; margin: 0; padding: 30px; }
        .container { max-width: 1100px; margin: auto; background: white; border-radius: 16px; padding: 30px; box-shadow: 0 10px 25px rgba(0,0,0,.08); }
        h1, h2 { color: #1e3a8a; }
        .job-card { border: 1px solid #dbeafe; background: #eff6ff; padding: 18px; border-radius: 12px; margin-top: 18px; }
        .meta { color: #475569; }
        a { color: #1d4ed8; }
        textarea { width: 100%; min-height: 220px; padding: 12px; border: 1px solid #cbd5e1; border-radius: 8px; margin-top: 10px; }
      </style>
    </head>
    <body>
      <div class="container">
        <h1>CareerBoost Job Matcher</h1>
        <p>Using the resume file in the project folder: <strong>{{ resume_path }}</strong></p>

        <h2>Resume Used</h2>
        <textarea>{{ resume_text }}</textarea>

        {% if ranked_jobs %}
          {% for job in ranked_jobs %}
          <div class="job-card">
            <h2>{{ loop.index }}. {{ job.title }} at {{ job.company }}</h2>
            <p class="meta">{{ job.location }} | {{ job.type }} | Match score: {{ job.score }}%</p>
            <p>{{ job.description }}</p>
            <p>Matching keywords: {{ ', '.join(job.match_keywords) if job.match_keywords else 'N/A' }}</p>
            <p><a href="{{ job.apply_url }}" target="_blank">Apply Here</a></p>
          </div>
          {% endfor %}
        {% else %}
        <p>No job match was found for the provided resume.</p>
        {% endif %}

        <p style="text-align:center; color:#64748b; margin-top:30px; font-size:13px;">
          Crafted for Anosha by <strong>Albi</strong>
        </p>
      </div>
    </body>
    </html>
    """, resume_path=resume_path, resume_text=resume_text, ranked_jobs=ranked_jobs)


if __name__ == "__main__":
    time_str = os.getenv("DAILY_EMAIL_TIME", "09:00")
    hour, minute = [int(part) for part in time_str.split(":")[:2]]

    scheduler = BackgroundScheduler()
    scheduler.add_job(send_daily_job_email, "cron", hour=hour, minute=minute, id="daily_job_email")
    scheduler.start()
    send_daily_job_email()
    app.run(debug=True, host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
