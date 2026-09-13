# 🎯 Daily Career Scraper

A lightweight, automated Python script that scrapes fresh **HR, Talent Acquisition, and Business** roles from LinkedIn and emails a beautifully formatted digest every morning tailored for **Anosha Mariam** (BBA • Talent Acquisition).

---

## 🌟 What It Does

- **Scrapes Roles**: Uses Apify to pull recently posted **Talent Acquisition, HR Recruiter, Campus Hiring, and Business Operations** roles in Bengaluru.
- **Filters Spam**: Automatically blocks known spam companies (like Mindrift, Crossover, Outlier, etc.) so you only see genuine, high-quality career roles.
- **Smart Scoring**: Ranks roles based on resume skills (Naukri, LeadSquared CRM, Advanced Excel, Sourcing, Campus Hiring, BBA Analytics), recency, and gives a bonus boost to top employers (Google, Amazon, Deloitte, Flipkart, Swiggy, Kalvium, etc.).
- **Morning Digest**: Sends a clean, color-coded HTML email summarizing the best matches with working LinkedIn direct-apply links every day at 7:00 AM IST.

---

## 🚀 How It Works

- **GitHub Actions**: The entire script runs automatically in the cloud using GitHub Actions. You don't need to keep your computer on!
- **Apify**: Grabs the job data efficiently.
- **Gmail API**: Securely emails the final digest straight to your inbox.

---

## 🛠️ Setup (If you want to run it locally)

1. **Clone this repository to your computer**:
   ```bash
   git clone <your-repo-url>
   cd "job project"
   ```

2. **Install the required Python libraries**:
   ```bash
   pip install google-auth google-auth-oauthlib google-api-python-client apify-client schedule python-dotenv
   ```
   *(Or simply run `pip install -r requirements.txt`)*

3. **Add your `gmail_credentials.json` (from Google Cloud Console) into the folder**:
   - Go to [Google Cloud Console](https://console.cloud.google.com/).
   - Create a project and enable the **Gmail API**.
   - Go to **Credentials** > **Create Credentials** > **OAuth client ID** (Application type: *Desktop App*).
   - Download the client secrets file and rename it to `gmail_credentials.json` in this root directory (see `gmail_credentials.example.json` for reference).
   - *(Optional Fallback)*: You can also use a standard Gmail App Password with SMTP by configuring `MAIL_PASSWORD` in `.env`.

4. **Replace the email addresses in the configuration section of `send_daily_jobs.py`** (or set `SENDER_EMAIL` and `RECIPIENT_EMAIL` in `.env`).

5. **Run the script**:
   ```bash
   python send_daily_jobs.py
   ```

   **Helpful CLI flags**:
   - Run immediately once: `python send_daily_jobs.py --now`
   - Preview the HTML digest in your browser without sending an email: `python send_daily_jobs.py --dry-run`

> [!TIP]
> To update the companies you want to block or boost, just edit the `COMPANY_BLACKLIST` or `GOOD_COMPANIES` lists inside `send_daily_jobs.py`!

---

## ☁️ GitHub Actions Setup (Automated Cloud Run)

To let it run every morning at **7:00 AM IST** without keeping your computer on:

1. Push this repository to GitHub.
2. In your GitHub repository, navigate to **Settings** > **Secrets and variables** > **Actions**.
3. Add the following **Repository secrets**:
   - `APIFY_TOKEN`: Your API token from [Apify Console](https://console.apify.com/account/integrations).
   - `SENDER_EMAIL`: The Gmail address sending the digest.
   - `RECIPIENT_EMAIL`: The destination email address.
   - `GMAIL_CREDENTIALS_JSON`: The full text content of your `gmail_credentials.json`.
   - `GMAIL_TOKEN_JSON`: The generated token content from `token.json` after your first local run.
   - *(Optional fallback)*: `MAIL_PASSWORD`: Your 16-character Gmail App Password.
4. The workflow in `.github/workflows/daily_jobs.yml` is scheduled to execute daily at 01:30 UTC (**7:00 AM IST**). You can also click **Run workflow** in the Actions tab at any time to test immediately!
