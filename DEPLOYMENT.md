# Deploying & Testing RecoverAI

This guide details how to deploy **RecoverAI** to production with a public URL, and explains exactly how judges/evaluators will test the agent.

---

## 1. Where is it Deployed Right Now?

Currently, the project code is stored and fully functional **locally on your machine**. It is configured to be a **Fintech-Grade, Production-Oriented Prototype Deployable** via:
- 🌐 **Flagship Web App & REST API** (`server.py` on port `8000`, built with StitchMCP design system)
- 📖 **Interactive Swagger / OpenAPI Explorer** (`/docs` endpoint for judges to test individual endpoints)
- 🐳 **Docker & Docker Compose** (Containerized production deployment serving both Web App and API)
- ☁️ **Vercel / Render / Railway / PaaS** (`vercel.json`, `Procfile`, & `render.yaml`)
- ⚡ **Streamlit Backup Dashboard** (`app.py` on port `8501`)
- 🛡️ **GitHub Actions CI/CD** (Automated testing on every push)

---

## 2. How Will Hackathon Judges Test This Project?

Hackathon judges typically evaluate submissions using three tiers:

| Evaluation Tier | What the Judges Do | What RecoverAI Provides |
|---|---|---|
| **Tier 1: Live Web Demo (Highest Priority)** | Open your live URL on their browser (no installation needed) and click through the features. | Flagship SaaS web app with animated KPI counters, 5-stage live pipeline stepper, interactive 80/20 AI split charts, filterable audit trail, and an interactive **Judge Sandbox Mode** with smartphone Hinglish message preview. |
| **Tier 2: Interactive Swagger API Explorer** | Open `/docs` to test raw endpoints. | Auto-generated OpenAPI / Swagger documentation allowing judges to test detection, diagnosis, and sandbox endpoints interactively. |
| **Tier 3: Code Quality & Automated Tests** | Clone the repository and run automated test suites to ensure edge-case safety. | `pytest -v tests/` runs 9 automated unit tests verifying deterministic rules, opt-out hard stops, attempt caps, and idempotency. |
| **Tier 4: CLI & Headless Execution** | Test batch processing via CLI to verify backend pipeline stability. | `python run_pipeline.py` runs a full 200-transaction simulation, prints headline financial results, and exports `report.json`. |

---

## 3. How to Deploy to Streamlit Community Cloud (Recommended — 2 Minutes, Free)

Streamlit Community Cloud is the industry standard for deploying Streamlit apps with a free public HTTPS URL (`https://<your-app-name>.streamlit.app`).

### Step 1: Push Code to GitHub

Open terminal in the project directory:

```bash
# 1. Initialize git (if not already done)
git init

# 2. Stage all files
git add .

# 3. Commit
git commit -m "feat: production ready RecoverAI agent"

# 4. Rename branch to main
git branch -M main

# 5. Link to your GitHub repository (create an empty repo on github.com first)
git remote add origin https://github.com/<YOUR_GITHUB_USERNAME>/<YOUR_REPOSITORY_NAME>.git

# 6. Push to GitHub
git push -u origin main
```

### Step 2: Deploy on Streamlit Cloud

1. Go to **[share.streamlit.io](https://share.streamlit.io)** and log in with your GitHub account.
2. Click **"New app"** (or "Create app").
3. Configure deployment:
   - **Repository:** `<YOUR_GITHUB_USERNAME>/<YOUR_REPOSITORY_NAME>`
   - **Branch:** `main`
   - **Main file path:** `app.py`
   - **App URL:** (Choose a custom subdomain, e.g., `recoverai-razorpay`)
4. *(Optional — for live Claude LLM calls)*:
   - Click **Advanced settings...** -> **Secrets**.
   - Paste:
     ```toml
     ANTHROPIC_API_KEY = "your-api-key-here"
     ```
   *(Note: If omitted, the app will seamlessly run in its high-discipline deterministic fallback mode without crashing!)*
5. Click **"Deploy!"**.
6. Within 60 seconds, your app will be live at `https://<your-app-name>.streamlit.app`! You can copy-paste this link directly into the hackathon submission form.

---

## 4. Alternative Deployment Options

### Option A: Docker / Docker Compose (Local or Cloud VPS)

To run the containerized production build locally or on an EC2/Droplet/GCP VM:

```bash
# Build and run with Docker Compose
docker-compose up --build -d

# View live app
# Open http://localhost:8501 in your browser
```

Or using standard Docker:
```bash
docker build -t recoverai:latest .
docker run -p 8501:8501 recoverai:latest
```

### Option B: Render.com (Free Web Service)

1. Create a free account at [render.com](https://render.com).
2. Click **New +** -> **Web Service** -> Connect your GitHub repo.
3. Render will automatically detect `render.yaml` or use:
   - **Environment:** `Python`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn server:app --host 0.0.0.0 --port $PORT`
4. Deploy!

---

## 5. Judge Testing Guide (Step-by-Step for Submission)

Include these exact instructions in your submission for judges to test:

### For Judges Testing Online (Live Demo URL)
1. Navigate to your live deployed URL (e.g. `https://recoverai.onrender.com` or `http://localhost:8000`).
2. Observe the top KPI cards: **Revenue At Risk**, **Revenue Recovered**, **Recovery Rate**, and **AI Discipline Split**.
3. In the top bar:
   - Adjust the **Batch Size** slider (150–300) and **Random Seed**.
   - Click **"Run Live Recovery"**.
   - Observe live 5-step pipeline stepper (Deterministic Detect → 80/20 Diagnosis → Bounded Execution → PTP Tracking → Financial Metrics).
4. Review the **AI Discipline Split Donut Chart** (confirms 80% Rule / 20% LLM target).
5. Open the **Judge Sandbox** on the right:
   - Select or type any failure code (e.g. `insufficient_funds`, `card_expired`, or an unknown anomaly).
   - Click **"Evaluate Scenario Live"** to watch the Rule Engine and LLM classify it in real-time.
   - Toggle customer opt-out or attempts cap to verify the compliance firewall.
   - Toggle between **Hinglish** and **English** on the smartphone preview.
6. Inspect the **Real-Time Audit Trail** table and search/filter by status.
7. Open `/docs` to test raw REST API endpoints in Swagger.

### For Judges Testing Locally via Terminal
```bash
# 1. Clone & install
git clone <REPO_URL>
cd "Razorpay Project"
pip install -r requirements.txt

# 2. Run automated test suite (verifies all guardrails & rules)
pytest -v tests/

# 3. Launch Flagship Web App & REST API (Port 8000)
python server.py
# Open http://localhost:8000 in browser
# Open http://localhost:8000/docs for Swagger API Docs

# 4. Alternative: Run Headless CLI Pipeline
python run_pipeline.py

# 5. Alternative: Run Streamlit Backup UI (Port 8501)
streamlit run app.py
```
