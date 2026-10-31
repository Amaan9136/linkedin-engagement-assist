# LinkedIn Engagement Assistant

## About

LinkedIn Engagement Assistant is a personal tool that helps monitor LinkedIn posts, generate AI-powered comments, and manage post engagement from a single web dashboard.

It checks for new posts from your network, reads their available text, and uses AI to generate relevant comments that sound natural. You can review, edit, approve, or automate engagement based on your preferences.

The application runs on your own computer or server, with data stored locally.

## Features

- **Post Monitoring:** Automatically checks for new posts and keeps track of previously discovered ones.
- **AI Comments:** Generates relevant, natural-sounding comments using Ollama and `gpt-oss:20b-cloud`.
- **Text-Only AI:** Reads post descriptions, titles, extracted text, and accessible image alt text. Images and videos are never downloaded or sent to the AI.
- **Engagement Management:** Manage likes and comments with manual or automatic options.
- **Web Dashboard:** View posts, edit comment drafts, manage actions, and monitor application activity.
- **Persistent Storage:** Uses SQLite to save post details, comments, settings, and activity history.
- **Automatic Recovery:** Handles temporary errors, retries failed tasks, and resumes pending work after restarts.
- **Admin Access:** Protects the dashboard with credentials configured through environment variables.

## Technology

| Component | Technology |
|---|---|
| Backend | Python, Flask |
| Browser Automation | Playwright |
| Frontend | HTML, CSS, JavaScript |
| Database | SQLite |
| AI | Ollama (`gpt-oss:20b-cloud`) |

## Supported Platforms

- Windows
- Linux
- Android (Termux)

## How It Works

1. The application monitors accessible LinkedIn posts at regular intervals.
2. Post details and available text are extracted and saved locally.
3. AI generates a relevant comment based on the extracted text.
4. You can review and edit the comment or use the configured automation mode.
5. Likes, comments, and processing history are tracked in the dashboard.

## Project Goal

Keep LinkedIn post engagement simple and organized by bringing monitoring, AI comment generation, and engagement management together in one lightweight application.