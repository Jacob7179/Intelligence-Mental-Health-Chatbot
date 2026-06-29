<div align="center">

# 🧠 Intelligent Mental Health Chatbot

### An emotion-aware conversational support prototype built with Flask, Transformers, Gemini, and MongoDB.

[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white)](#-getting-started)
[![Flask](https://img.shields.io/badge/Flask-2.3.3-000000?style=for-the-badge&logo=flask&logoColor=white)](#-technology-stack)
[![MongoDB](https://img.shields.io/badge/MongoDB-Optional-47A248?style=for-the-badge&logo=mongodb&logoColor=white)](#-configuration)
[![Google Gemini](https://img.shields.io/badge/Google_Gemini-Optional-4285F4?style=for-the-badge&logo=google&logoColor=white)](#-configuration)
[![License: GPL v3](https://img.shields.io/badge/License-GPL--3.0-blue?style=for-the-badge)](LICENSE)

[Features](#-key-features) · [Getting Started](#-getting-started)
 · [Windows Quick Start](#-windows-quick-start)
</div>

---

## 📖 About the Project

**Intelligent Mental Health Chatbot** is a web-based final-year-project prototype designed to provide supportive, emotion-aware conversations. It analyses a user's text, identifies an emotional signal, and generates an empathetic response through Google Gemini when an API key is available. A local template-based response system remains available as a fallback.

The application supports registered accounts and guest access, conversation history, ratings, editable user profiles, and an admin dashboard for managing users and reviewing conversations.

> [!WARNING]
> This project is an **academic prototype**, not a medical device, diagnostic tool, therapy service, or replacement for qualified professional care. Do not rely on it for emergencies or clinical decisions.

---

## ✨ Key Features

| Area | Included capabilities |
| --- | --- |
| 🎭 **Emotion awareness** | Uses `cardiffnlp/twitter-roberta-base-emotion` with rule-based keyword detection as a fallback. |
| 💬 **Supportive chat** | Generates empathetic responses using Google Gemini, with local fallback responses when the API is unavailable. |
| 🚨 **Basic crisis detection** | Detects a limited set of self-harm or suicide-related keywords and returns an urgent-support message. |
| 👤 **Accounts and guest access** | Users can register, sign in, update their profile, or start as a guest. |
| 🗂️ **Conversation management** | Creates, loads, deletes, and rates conversation sessions. |
| 🛡️ **Admin dashboard** | Allows administrators to review conversations and manage registered users. |
| 💾 **Flexible data storage** | Uses MongoDB when connected, with a non-persistent in-memory fallback for local development. |

---

## 🛠️ Technology Stack

| Category | Technologies |
| --- | --- |
| **Backend** | Python 3.11, Flask, Flask-CORS |
| **AI / NLP** | PyTorch, Hugging Face Transformers, Cardiff NLP RoBERTa emotion model |
| **Generative AI** | Google Generative AI (Gemini) |
| **Database** | MongoDB / PyMongo |
| **Frontend** | HTML, CSS, JavaScript |

---

## 📁 Project Structure

```text
Intelligence-Mental-Health-Chatbot/
├── app.py                     # Flask application, AI logic, API routes, and database logic
├── requirements.txt           # Python dependencies
├── run.bat                    # Automated setup script for Windows
├── Dockerfile                 # Docker configuration
├── templates/
│   ├── chat.html              # Main chatbot interface
│   ├── login.html             # User login page
│   ├── register.html          # User registration page
│   ├── admin_login.html       # Administrator login page
│   └── admin_dashboard.html   # Administrator dashboard
└── static/
    └── icon/                  # Application icon assets
```

---

## 🚀 Getting Started

### Prerequisites

Install the following before running the application:

- **Python 3.11**
- **pip**
- **MongoDB** *(recommended for persistent accounts and conversations)*
- A **Google Gemini API key** *(optional; local fallback replies still work without it)*

> [!NOTE]
> On the first successful run with internet access, the application downloads the Hugging Face emotion-classification model. This may take a few minutes depending on your connection.

### 1. Clone the repository

```bash
git clone https://github.com/Jacob7179/Intelligence-Mental-Health-Chatbot.git
cd Intelligence-Mental-Health-Chatbot
```

### 2. Download python version 3.11.0
```bash
curl -o python-3.11.0.exe https://www.python.org/ftp/python/3.11.0/python-3.11.0-amd64.exe
```

### 3. Install python version 3.11.0
```bash
./python-3.11.0.exe /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
```

### 4. Create virtual environment
```bash
python -m venv venv
```

### 5. Activate virtual environment
```bash
.\venv\Scripts\Activate.ps1
```

### 6. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 7. Configure environment variables

Create a file named `.env` in the project root:

```dotenv
# MongoDB is recommended for persistent data.
MONGODB_URI=mongodb://localhost:27017/
MONGODB_DB=mental_health_chatbot

SECRET_KEY=replace-this-with-a-long-random-secret

GEMINI_API_KEY=your_gemini_api_key_here
```

### 8. Start the application

```bash
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

---

## ⚡ Windows Quick Start

For Windows users, the included script can install Python 3.11 when needed, create the virtual environment, install dependencies, and start the application:

```bat
run.bat
```

Run it from the project folder. An internet connection is required if Python or packages need to be downloaded.

---

## 📦 Dockerfile Note

A `Dockerfile` is included to define a Python 3.11 environment and install the project dependencies. It should not be treated as a complete Docker deployment setup because it does not configure a database service, persistent storage, production server, or deployment-specific security settings.

---

## 🔐 Administrator Access

When MongoDB is available and no administrator record exists, the application creates a development-only admin account:

```text
Admin ID: admin001
Password: admin123
```

The admin panel is available at:

```text
http://127.0.0.1:5000/admin/login
```

---

## 🧠 Emotion and Response Flow

1. A user submits a message through the chat interface.
2. The application checks for basic crisis-related keywords.
3. It preprocesses the message and predicts an emotion using the RoBERTa model when available.
4. It combines model output with rule-based logic to improve resilience when a model or network service is unavailable.
5. Gemini generates an empathetic response when configured; otherwise, a local response template is used.
6. The message, detected emotion, response, and conversation metadata are stored in MongoDB when connected.

---

## 📜 License

This project is licensed under the **GNU General Public License v3.0**. See [LICENSE](LICENSE) for details.

---

<div align="center">

Built as a Final Year Project · Use responsibly

</div>
