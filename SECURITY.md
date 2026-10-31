# Security
The browser profile in `data/browser_profile` contains a logged-in session, and `.env` contains the admin password and secret key. Never commit `.env`, `data/` or `logs/`. Protect the dashboard with a strong `ADMIN_PASSWORD`, keep `HOST=127.0.0.1`, and use a VPN or an HTTPS reverse proxy for remote access.
Report vulnerabilities privately via GitHub's "Report a vulnerability" (Security tab) on the repository, or by contacting [@Amaan9136](https://github.com/Amaan9136). Please do not open public issues for them.
