# Email Assistant — A local-first, privacy-focused AI email triage system

[![Python](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Local-First](https://img.shields.io/badge/Architecture-Local--First%20%28SQLite%29-0A84FF.svg)](#privacy--local-first-design)
[![No OAuth Required](https://img.shields.io/badge/Auth-No%20OAuth%20Required-success.svg)](#getting-started)

**Email Assistant** is an autonomous, privacy-first desktop email companion that connects directly to your standard IMAP/SMTP inbox to summarize, prioritize, extract calendar events, and draft contextual replies using Google Gemini. Built for developers and busy professionals who want AI email superpowers without exposing their inbox data to multi-tenant cloud SaaS platforms, paying recurring subscriptions, or dealing with complex Google Cloud OAuth consent screens. Everything runs locally on your machine with a fast SQLite database and a lightweight, Apple-inspired dark UI.

---

## ✨ Features

### 🧠 Smart Inbox Triage & Classification
- **Automated Priority Scoring**: Assigns an objective **1–10 priority score** to incoming emails based on urgency, sender context, and required action.
- **Category Segmentation**: Automatically classifies threads into 5 operational buckets: `Urgent`, `Business`, `Meeting`, `Newsletter`, and `Spam`.
- **Executive Summaries**: Produces crisp, one-sentence summaries (under 15 words) for zero-click inbox scanning.
- **On-Demand Re-Classification**: Allows manual re-triggering of classification on any individual thread via `POST /emails/{id}/classify`.

### 📅 Meeting Detection & RFC 5545 Calendar Sync
- **Intelligent Meeting Parsing**: Scans meeting-tagged emails for dates, time ranges, timezones, physical locations, or virtual meeting URLs (Google Meet, Zoom, Teams).
- **Standard `.ics` File Generation**: Generates clean, RFC 5545 compliant `.ics` calendar files stored locally in `calendar_events/`.
- **Direct 1-Click Import**: Download `.ics` files directly from the UI or API (`GET /calendar-events/{id}/download`) for instant addition to Apple Calendar, Google Calendar, or Microsoft Outlook.
- **Idempotency Guard**: Prevents duplicate event records and duplicate `.ics` file generation when re-scanning existing meeting threads.

### ✍️ AI Ghostwriter
Generates context-aware response drafts matching the thread history across **5 distinct tones**:
1. **Professional**: Structured, polite, and business-appropriate.
2. **Friendly**: Warm, conversational, and collegial.
3. **Short & Direct**: Concise and actionable for fast executive replies.
4. **Polite Decline**: Respectfully says no to sales pitches, invites, or requests while maintaining positive goodwill.
5. **Meeting Confirmation**: Acknowledges proposed dates and times, confirms attendance, and confirms agenda details.
- **In-Place Manual Editing**: Full editing capabilities before dispatching.
- **Direct SMTP Dispatch**: Sends approved drafts directly through your authenticated SMTP connection via `POST /drafts/{id}/send` and tracks dispatch status.

### 💬 Chat With Inbox (RAG-Lite)
- **Natural Language Search**: Ask factual questions about your email archive (*"What was the approved Q3 cloud infrastructure budget?"*, *"Did Sarah confirm the Tuesday demo?"*).
- **Grounded Answers with Citations**: Responses are strictly synthesized from retrieved inbox records and cite valid email IDs to eliminate hallucinations.
- **English & Roman Urdu Support**: Full multilingual understanding for code-mixed English and Urdu/Roman Urdu queries (*"Q3 cloud budget kitna approve hua hai?"*).

### 🔒 Privacy & Local-First Architecture
- **Zero Cloud Middleman**: Connects straight from your computer to your email provider via TLS-encrypted IMAP/SMTP.
- **Local SQLite Persistence**: All thread metadata, full sanitized bodies, drafts, and event records stay in a local SQLite file (`email_assistant.db`).
- **No Complex OAuth / Cloud Console**: Connect using standard IMAP credentials or a 16-character Gmail App Password without creating Google Cloud Projects or waiting for OAuth app verification.
- **Sanitized HTML Rendering**: Email HTML bodies are sanitized with `bleach` and `BeautifulSoup`, stripping script and style execution while preserving layout and clickable outbound links (`target="_blank"`, `rel="noopener noreferrer"`).
- **Muted Senders Filter**: Mute high-volume senders at the IMAP fetch level to conserve Gemini API quota and keep your database clean.

### 🔄 Background Sync Service
- Asynchronous background polling worker running on a configurable timer (`SYNC_INTERVAL_MINUTES`).
- Live settings reloader: update polling intervals in the UI without restarting the server.
- Detailed file-rotated diagnostics in `logs/app.log`.

---

## 🛠 Tech Stack

| Layer | Technologies / Libraries |
| :--- | :--- |
| **Backend Framework** | [FastAPI](https://fastapi.tiangolo.com/) (Async REST API), [Uvicorn](https://www.uvicorn.org/) (ASGI Server), [Pydantic v2](https://docs.pydantic.dev/) |
| **AI & LLM Engine** | [Google GenAI SDK](https://github.com/googleapis/python-genai) (`google-genai`), Gemini 2.5 Flash (`gemini-2.5-flash`), Gemini 1.5 Flash fallback |
| **Database & Storage** | [SQLite3](https://sqlite.org/) (Local file storage with WAL mode), Standard Schema Migrations |
| **Email Protocol** | [IMAPClient](https://imapclient.readthedocs.io/), Python standard `smtplib`, `email.message` |
| **Calendar Engine** | [ics.py](https://icspy.readthedocs.io/) (RFC 5545 compliant `.ics` calendar generator) |
| **Sanitization & Parsing** | [Bleach](https://bleach.readthedocs.io/) (HTML sanitizer), [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) (DOM parser) |
| **Frontend UI** | [Alpine.js](https://alpinejs.dev/) (Reactivity), [Tailwind CSS](https://tailwindcss.com/) (Styling), [Lucide Icons](https://lucide.dev/) |

---

## 💡 Why I Built This

I wanted the productivity of modern AI-powered email agents without handing over my entire communication history to a third-party SaaS cloud or navigating the maze of Google Cloud OAuth verification. Most commercial email tools either lock your inbox into their proprietary cloud databases or require complex developer setups just to read your own messages. 

Inspired by autonomous agent architectures, I built Email Assistant as a lean, local-first system. It connects directly over standard IMAP/SMTP, saves everything to a local SQLite database on your machine, and uses lightweight Gemini models for fast, cost-effective classification, drafting, and chat. It gives you a private, intelligent email workspace that you completely control.

---

## 🚀 Getting Started

### 1. Prerequisites
- **Python 3.11 or newer** ([Download Python](https://www.python.org/downloads/))
- A **Google Gemini API Key** (Free tier available at [Google AI Studio](https://aistudio.google.com/apikey))
- A **Gmail App Password** or standard IMAP/SMTP credentials for your mail provider

---

### 2. Quick Setup

#### Windows (1-Click Launch)
Double-click `run.bat` or run:
```bash
run.bat
```
*The script automatically sets up a Python virtual environment (`venv`), installs all required packages from `requirements.txt`, creates `.env` if missing, and boots the application.*

#### Linux / macOS / Manual Setup
```bash
# 1. Clone the repository
git clone https://github.com/RaiFarhan0/Email-Assistant.git
cd Email-Assistant

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows PowerShell: .\venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Create your .env file
cp .env.example .env

# 5. Start the server
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

Open your browser and navigate to:
👉 **[http://localhost:8000](http://localhost:8000)**

---

### 3. Credential Setup Guide

#### How to generate a Gmail App Password
1. Navigate to your [Google Account Security Settings](https://myaccount.google.com/security).
2. Ensure **2-Step Verification** is enabled on your Google account.
3. Open [Google App Passwords](https://myaccount.google.com/apppasswords).
4. Enter an app name (e.g., `Email Assistant`) and click **Create**.
5. Copy the generated 16-character code (e.g., `abcd efgh ijkl mnop`).

#### How to get a Google Gemini API Key
1. Visit [Google AI Studio](https://aistudio.google.com/apikey).
2. Click **Create API Key** and copy your key.

#### Configure `.env`
Edit your `.env` file (or use the in-app **Settings & Onboarding** interface):
```env
# Email Assistant Configuration
EMAIL_ADDRESS=your.email@gmail.com
APP_PASSWORD=abcdefghijklmnop
IMAP_SERVER=imap.gmail.com
SMTP_SERVER=smtp.gmail.com
IMAP_PORT=993
SMTP_PORT=465

# AI Configuration
GEMINI_API_KEY=AIzaSy...YourGeminiKey
GEMINI_MODEL=gemini-2.5-flash
GEMINI_FALLBACK_MODEL=gemini-1.5-flash

# Background Sync
SYNC_INTERVAL_MINUTES=5
```

---

## 📂 Project Structure

```
Email Assistant/
├── backend/
│   ├── api/
│   │   ├── routes_ai.py          # Ghostwriter, Chat With Inbox, Reclassify endpoints
│   │   ├── routes_emails.py      # Email listing, sync, read toggle, detail routes
│   │   └── routes_settings.py    # Settings, mute management, test connection
│   ├── services/
│   │   ├── background_sync.py    # Async periodic sync worker
│   │   ├── calendar_service.py   # RFC 5545 .ics generation and event queries
│   │   ├── email_client.py       # IMAP/SMTP transport, MIME parsing, sanitization
│   │   └── gemini_agent.py       # Gemini API client, triage prompts, chat RAG
│   ├── config.py                 # Pydantic Settings & environment manager
│   ├── database.py               # SQLite connection manager & schema migrations
│   ├── main.py                   # FastAPI application factory & lifespan
│   └── models.py                 # Pydantic request/response schemas
├── calendar_events/              # Generated .ics calendar event storage
├── frontend/
│   ├── css/
│   │   └── style.css             # Apple-inspired dark aesthetic stylesheet
│   ├── js/
│   │   ├── app.js                # Alpine.js state controller & API integration
│   │   └── components.js         # UI helpers (markdown parser, priority chips)
│   └── index.html                # Single-page interface
├── tests/
│   └── test_comprehensive_suite.py # Complete 19-point integration test suite
├── .env.example                  # Environment configuration template
├── LICENSE                       # MIT License
├── README.md                     # Documentation
├── requirements.txt              # Production dependencies
└── run.bat                       # 1-click Windows runner
```

---

## 📡 API Reference

Interactive Swagger documentation is available locally at **[http://localhost:8000/docs](http://localhost:8000/docs)**.

### Core Endpoints

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/emails` | Query emails with filtering (`category`, `min_priority`, `search`, `sort`) |
| `GET` | `/emails/{id}` | Retrieve full email content, thread siblings, and draft history |
| `POST` | `/emails/sync` | Manually trigger IMAP fetch, AI triage, and meeting extraction |
| `PATCH`| `/emails/{id}/read` | Toggle email read/unread state |
| `POST` | `/emails/{id}/classify`| Force AI re-classification of a specific email |
| `POST` | `/emails/{id}/create-event`| Extract meeting metadata and generate an `.ics` file |
| `GET` | `/calendar-events` | List all extracted calendar events chronologically |
| `GET` | `/calendar-events/{id}/download` | Download `.ics` calendar file for calendar import |
| `POST` | `/emails/{id}/draft` | Generate an AI reply draft with a selected tone |
| `POST` | `/drafts/{id}/send` | Send an approved/edited draft response via SMTP |
| `POST` | `/chat` | RAG-lite natural language inquiry over your inbox (English & Urdu) |
| `GET` | `/settings` | Retrieve active connection status and configuration |
| `POST` | `/settings` | Update settings and restart sync worker dynamically |
| `POST` | `/settings/test-connection` | Validate IMAP and SMTP credentials independently |
| `POST` | `/settings/mute` | Add an email address to the muted senders list |
| `DELETE`| `/settings/mute/{email}` | Remove an email address from the muted list |

---

## 🗺 Roadmap

- [ ] **Multi-Account Support**: Manage multiple personal and work inboxes in a unified view.
- [ ] **Expanded Provider Presets**: One-click configuration templates for Outlook/Office365, Fastmail, Proton Bridge, and custom IMAP/SMTP hosts.
- [ ] **Local Vector Search**: Optional offline vector embeddings using `chromadb` / `sqlite-vec` for local semantic indexing.
- [ ] **Mobile-Optimized PWA**: Responsive progressive web application view for mobile tablet and smartphone browsers.

---

## 🤝 Contributing

Contributions, bug reports, and feature requests are welcome!

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📄 License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for more information.

---

## 👤 Author & Contact

- **GitHub**: [@RaiFarhan0](https://github.com/RaiFarhan0)
- **Repository**: [RaiFarhan0/Email-Assistant](https://github.com/RaiFarhan0/Email-Assistant)
