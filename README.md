# Repo structure

This repo contains two projects, one Messenger-price-analyzer and one Messenger-price-analyzer-ASP. The ASP is a prepared, ready and deployed ADK agent to Vertex AI.
The "Messenger-price-analyzer" is the project what it looks like before applying the Agent Starter Pack enhancement. Below you will find a installation and deployment guide for the clean Messenger-price-analyzer project.


# Installation & Deployment Guide

This guide walks you from a fresh clone to a working local run and a deployment to **Vertex AI Agent Engine**, using the **Agent Starter Pack** on Windows (Anaconda Prompt). A `venv` alternative is also included.

---

## 1) Prerequisites
- Windows with **Anaconda Prompt** (recommended)
- Python **3.10–3.12**
- Git
- Make
- UV
- Google Cloud SDK (`gcloud`) and `gsutil` (for deployment)
- A Google Cloud project with billing enabled
- Mock data (a couple of .emls for testing)

> Tip: Keep a terminal open with your active environment so installs and runs go into the same place.

---

## 2) Clone the repository
```bat
cd \path\to\where\you\want\the\repo
git clone https://example.com/your-repo.git
cd your-repo
```

---

## 3) Create and activate an environment

### Option A — **conda** (recommended with Anaconda)
```bat
conda create -n sms-agent python=3.11 -y
conda activate sms-agent
python -m pip install --upgrade pip
```

### Option B — **venv** (works inside Anaconda Prompt)
```bat
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
```

> You should see `(sms-agent)` or `(.venv)` at the beginning of your prompt before installs/runs.

---

## 4) Install project requirements
If you have a `requirements.txt`:
```bat
pip install -r requirements.txt
```

If you *don’t* have one yet, install the essentials used by the project:
```bat
pip install pandas lxml openpyxl xlrd beautifulsoup4 html5lib python-dotenv
```

---

## 5) Install the Agent Starter Pack CLI
```bat
pip install --upgrade agent-starter-pack
```

---

## 6) Enhance your existing project (scaffold production bits)
From your project root, run:
```bat
agent-starter-pack enhance
```
During the interactive prompts, use the following guidance:

1. **Proceed?** → `Y`
2. **Template** → `1` (Base template)
3. **Project directory to enhance** → select your **adk_agent** (or your agent app) directory
4. **Deployment target** → **Vertex AI** (Agent Engine)
5. **CI/CD runner** → choose your preference (e.g., **GCP**)
6. **Region** → confirm a supported region (e.g., `us-central1`)
7. **Account/Project** → confirm your Google Cloud account & project

This step:
- Adds deployment/infra/observability/CI scaffolding alongside your code
- Leaves your existing files intact

> Recommended safety step:
```bat
git init
git add .
git commit -m "baseline before agent-starter-pack enhance"
```
Run `agent-starter-pack enhance` on a feature branch if you prefer:
```bat
git checkout -b asp/enhance
```
---

## 7) Add mock data (local eml's)

Add a couple of messenging supplier emls in \data\email_memory for test runs

---

## 8) Align dependencies for Agent Engine
Update your dependency list (e.g., in `pyproject.toml` or your dependencies file) to include the following set commonly used with Agent Engine + ADK:

```toml
# Example for pyproject.toml (poetry/pdm)
# Adjust to your tool; version pins are illustrative.
dependencies = [
  "google-adk>=1.15.0,<2.0.0",
  "opentelemetry-exporter-gcp-trace>=1.9.0,<2.0.0",
  "google-cloud-logging>=3.12.0,<4.0.0",
  "google-cloud-aiplatform[evaluation,agent-engines]>=1.118.0,<2.0.0",
  "protobuf>=6.31.1,<7.0.0",
  "pandas>=2.2",
  "beautifulsoup4>=4.12",
  "lxml>=4.9",
  "openpyxl>=3.1",
  "xlrd>=2.0",
  "python-dotenv>=1.0",
]
```

Then install (example using pip):
```bat
pip install "google-cloud-aiplatform[adk,agent_engines]>=1.111"
```

---

## 9) Agent Engine app path configuration
If your Agent Engine application package needs to import local modules from `utils` (and/or `llm`), ensure those paths are included. For example, in `agent_engine_app` config where a list of import roots is defined, add:

```python
default = ["./adk_agent", "./utils", "./llm"]
```

---

Adjust to match your repo layout.

## 10) Post‑enhance: quick local sanity check

Use the enhance added Make targets:
```bat
cd . && make install && make playground
```

---

Try running daily pipeline in the local web server

## 10.1) Post‑enhance: quick local sanity check

Chat with the agent in the playground / web server.
try: Hi
try: run daily pipeline

check logs after

---

## 11) Google Cloud setup (one‑time)
1. Authenticate and select your project:
```bat
gcloud auth application-default login
gcloud config set project YOUR_DEV_PROJECT_ID
```
2. Create a staging bucket (match your region):
```bat
set REGION=us-central1
gsutil mb -l %REGION% gs://YOUR-STAGING-BUCKET
```

> You can confirm your active project anytime:
```bat
gcloud config get-value project
```

---

## 12) Deploy to Vertex AI Agent Engine
Most enhanced repos include a Make target:
```bat
make backend
```
This builds, stages, and deploys your agent to Agent Engine in the configured project/region.

After deployment, you can also explicitly re‑set your gcloud project if needed:
```bat
gcloud config set project YOUR_DEV_PROJECT_ID
```

---

## 13) Verify & test
- In Google Cloud Console → **Vertex AI → Agent Engine**, confirm your agent appears.
- Use the **Query URL** or SDK to send a simple test request.
- Re‑deploy by rerunning `make backend` after code changes.

---


## 14) Quick command reference
```bat
:: env
conda create -n sms-agent python=3.11 -y
conda activate sms-agent

:: install project deps
pip install -r requirements.txt

:: install starter pack CLI
pip install --upgrade agent-starter-pack

:: enhance (interactive)
agent-starter-pack enhance

:: optional: make targets added by enhance
make install
make playground
make backend

:: GCP basics
gcloud auth application-default login
gcloud config set project YOUR_DEV_PROJECT_ID
set REGION=us-central1
gsutil mb -l %REGION% gs://YOUR-STAGING-BUCKET
```

---

**You’re set.** Run locally with your active env, enhance to add production scaffolding, then deploy to Agent Engine with `make backend`. Iterate and redeploy as needed.

