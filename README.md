# LetsBeBio AI Advisor — Intelligent Conversational Recommender for WooCommerce

[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://www.docker.com/)
[![WooCommerce](https://img.shields.io/badge/WooCommerce-Compatible-96588A?logo=woocommerce&logoColor=white)](https://woocommerce.com/)
[![License: GPL v2](https://img.shields.io/badge/License-GPL_v2-blue.svg)](https://www.gnu.org/licenses/old-licenses/gpl-2.0.en.html)

An end-to-end, privacy-respecting recommendation engine and conversational AI advisor designed for online beauty and parapharmacy stores. Built on top of a live WooCommerce catalogue, it extracts structured clinical attributes from unstructured descriptions and delivers personalized skincare and haircare routines through an interactive storefront chat widget.

Supports **French**, **Tunisian Arabic (الدارجة)**, and **Arabizi (e.g. *3andi 7boub fi wajhi*)**.

---

## 🌟 Key Features

### 1. 🛡️ Deterministic Clinical Scoring (Zero Hallucination)
- **Hard Rule**: The Language Model parses shopper intent and crafts warm prose, but **never invents products or prices**.
- **Transparent Logic**: Every recommended product and routine sequence is computed using deterministic matching rules against stock status, target concerns, skin/hair types, and budget.
- **Live Sync**: Prices and availability are verified in real time against the WooCommerce database (`postmeta`).

### 2. 💬 Interactive Diagnostic Form & Stepper
- When intent is broad, the agent presents structured, multi-question diagnostic cards with pill options (e.g., `① Type de peau` + `② Budget`).
- Shoppers can select options with a single tap and validate them together without manual typing.

### 3. 🛍️ One-Click Routine Bundle Checkout
- Recommending a multi-step routine automatically displays an **« Ajouter toute la routine au panier »** CTA.
- Adds all items to the WooCommerce cart simultaneously via background dispatch, directing the shopper immediately to checkout.

### 4. 🔄 Catalog Filter Relaxation (Zero Dead-Ends)
- If an ultra-specific combination yields 0 matches (e.g., *Chute de cheveux* + *Bouclés*), the engine automatically falls back to universal treatments with a reassuring explanation, ensuring no customer is left empty-handed.

### 5. ⚡ Quick-Starter Topics on Welcome Screen
- Immediate mobile engagement with 5 one-click diagnostic chips on greeting:
  - 🌿 *Boutons & Acné*
  - 💆‍♀️ *Chute de cheveux*
  - ✨ *Taches & Teint terne*
  - 💧 *Peau sèche qui tiraille*
  - 🌸 *Soins anti-âge & rides*

### 6. 🇹🇳 Native Tunisian Arabic & Arabizi Lexicon
- Custom rule-based NLP normalizer (`derja.py`) resolves transliterated numeral-letters (`3` = ع, `7` = ح, `9` = ق) and colloquial idioms into standard clinical attributes before reaching the engine.

---

## 🏛️ System Architecture

```
  Shopper (Browser / Mobile)
        │
        ▼
  Storefront Widget (reco-engine WordPress Plugin)
        │
   (HTTPS Proxy — no direct client API exposure)
        │
        ▼
  FastAPI Service (Docker Container on Port 8000)
        ├── agent.py ......... ReAct Tool-Calling Execution Loop
        ├── scoring.py ....... Multi-Criteria Clinical Matching Engine
        ├── catalogue.py ..... Dynamic Cache & Background Rebuilder
        ├── derja.py ......... Trilingual Normalizer (FR / AR / Arabizi)
        └── semantic.py ...... Local Sentence-Transformer Embeddings
        │
        ▼
  WooCommerce Database (Read-Only MySQL / MariaDB)
```

---

## 📁 Repository Structure

```
letsbebio-reco/
├── service/                  # Production FastAPI backend
│   ├── app/                  # Application modules (agent, scoring, catalogue, etc.)
│   ├── Dockerfile            # Production multi-stage container build
│   ├── docker-compose.yml    # Container orchestration
│   ├── requirements.txt      # Python dependencies
│   ├── .env.example          # Clean configuration template
│   └── run.sh                # Local launcher script
├── wordpress-plugin/         # Storefront WordPress plugin
│   └── reco-engine/          # Plugin source (reco-engine.php, chat.js, reco.css)
├── pipeline/                 # Data exploration & SQL extraction pipeline
│   ├── 0_explore.sql         # DB inspection scripts
│   ├── 1_export.sql          # Clean export queries
│   └── 2_extract.py          # Attribute normalization
├── validation/               # Clinical benchmark profiles & test suite
│   ├── baseline.json         # Reference benchmark snapshot
│   └── validate.py           # Regression testing script
├── demo/                     # Standalone HTML/JS testing interface
├── docs/                     # Technical specifications & architecture documentation
├── scripts/                  # Developer automation (make_plugin.py, list_models.py)
├── Makefile                  # Developer CLI command suite
├── setup.sh                  # One-shot local environment setup
└── test.sh                   # Comprehensive test suite
```

---

## 🚀 Getting Started

### Method 1: Running with Docker (Recommended for Production)

1. Navigate to the service folder:
   ```bash
   cd service
   ```

2. Copy the environment configuration template:
   ```bash
   cp .env.example .env
   ```

3. Configure your database and LLM credentials in `.env`:
   ```env
   DB_HOST=your_mysql_host       # use 'host.docker.internal' if MySQL is on your local machine
   DB_PORT=3306
   DB_NAME=your_wordpress_db
   DB_USER=reco_read
   DB_PASSWORD=your_secure_password
   WP_PREFIX=wp_

   ENABLE_INTERPRET=true
   LLM_BASE_URL=https://api.groq.com/openai/v1
   LLM_API_KEY=gsk_your_api_key
   LLM_MODEL=llama-3.3-70b-versatile
   ```

4. Launch the container:
   ```bash
   docker compose up -d --build
   ```

5. Verify health:
   ```bash
   curl http://localhost:8000/health
   ```

---

### Method 2: Running Locally with Python / Make

1. Run the one-shot setup script:
   ```bash
   make setup
   ```
   *(Installs dependencies, detects the WordPress database prefix, and builds `service/.env`)*.

2. Start the API:
   ```bash
   make run
   # or with live reload:
   make dev
   ```

3. Interactive Swagger documentation will be available at:
   👉 **`http://localhost:8000/docs`**

---

## 🔌 WordPress Storefront Installation

1. Package the plugin archive:
   ```bash
   make plugin
   ```
   *(Creates `reco-engine.zip`)*.

2. In WordPress Admin:
   - Go to **Plugins → Add New → Upload Plugin**.
   - Select `reco-engine.zip` and click **Install Now** → **Activate**.

3. In **Settings → Moteur de recommandation**:
   - Set **API URL** to your backend URL (`http://localhost:8000` or `https://api.yourdomain.com`).
   - Enable **« Recherche en langage naturel »** *(enables conversational AI)*.
   - Enable **« Conseiller flottant »** *(enables the floating advisor bubble across the entire shop)*.
   - Click **Save Changes**.

---

## 📡 API Endpoints Overview

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | Live operational status, product counts, and cache state |
| `GET` | `/options` | Diagnostic options for guided questionnaires |
| `POST` | `/recommend` | Deterministic recommendation engine (routine assembly) |
| `POST` | `/chat` | Conversational AI advisor with interactive options & card dispatch |
| `POST` | `/search` | Semantic retrieval by clinical intent / similarity |
| `POST` | `/admin/refresh` | Force an atomic rebuild of the product catalog snapshot |

---

## 🧪 Validation & Quality Assurance

The engine includes 22 clinical customer profiles covering acne, pregnancy-safe hyperpigmentation, sensitive skin, and hair thinning:

```bash
make validate    # Executes all 22 benchmark profiles
make compare     # Compares results against the verified baseline to prevent regressions
```

---

## 🎓 Academic Context

Developed as an End-of-Studies Project (PFE) for the **National Engineering Diploma in Artificial Intelligence and Data Science** at **EPI Digital School** (Academic Year 2025/2026).

- **Author**: Montassar Bagané
- **Academic Supervisor**: Dr. Sawssen Guerbej
- **Host Company**: WebDesign (`letsbebio.tn`)

---

## 📄 License

This project is licensed under the terms of the **GNU General Public License v2.0** (GPL-2.0).
