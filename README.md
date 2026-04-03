# 📊 CivitAI Analytics

A self-hosted post analytics dashboard and metadata editor for Stable Diffusion artists publishing on [CivitAI](https://civitai.com).

Track engagement across all your posts, tag them with characters and themes, and discover what content resonates most with your audience — all from a clean dark-themed web UI running locally on your machine or home server.

---

## Screenshots

> _Screenshots coming soon. Run it yourself to see it in action!_

---

## Features

- **📊 Dashboard** — at-a-glance totals for hearts, likes, comments, posts, and images across your entire CivitAI account, with 24-hour deltas
- **✏️ Post Editor** — label every post with a title, characters, tags, themes, and notes; autocompletes from your existing labels
- **🏷️ Tag & Character Tracking** — discover which characters and tags drive the most engagement with ranked bar charts
- **🔥 Engagement Analytics** — best performing posts table, NSFW level breakdown, and image count sweet-spot analysis
- **⚙️ Settings Tab** — enter your CivitAI API key and username in the UI; no config file editing needed; test connection with one click
- **🔒 Local-first** — your API key lives in `data/config.json` on your machine; nothing is sent anywhere except directly to the CivitAI API
- **🕒 Tracker script** — run `tracker.py` on a schedule to snapshot engagement over time and detect spikes and new comments

---

## Requirements

- Python 3.9+
- A [CivitAI](https://civitai.com) account with at least one post
- A CivitAI API key (free, generated in Account Settings)

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/civitai-analytics.git
cd civitai-analytics
```

### 2. Create a virtual environment and install dependencies

```bash
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Run the app

```bash
python app.py
```

Then open **http://localhost:5757** in your browser.

### 4. Configure your API key

- Click the **⚙️ Settings** tab
- Enter your CivitAI username
- Paste your API key (generate one at **civitai.com → Profile → Settings → API Keys → Add API Key**)
- Click **Save Settings**, then **Test Connection** to verify

Your credentials are saved to `data/config.json` (gitignored — never committed).

---

## Syncing Post Data

The app reads from `data/civitai_state.json`, which is populated by the tracker script. Run it manually or on a schedule:

```bash
# One-shot sync
python tracker.py

# With engagement analysis
python tracker.py --analyze
```

### Schedule with cron (Linux/macOS)

```bash
crontab -e
```

Add a line to run every 6 hours:

```
0 */6 * * * /path/to/civitai-analytics/venv/bin/python /path/to/civitai-analytics/tracker.py
```

---

## Home Server / Proxmox LXC Deployment

These steps work for any Debian/Ubuntu-based LXC container or VM.

### 1. Copy files to your server

```bash
scp -r civitai-analytics/ root@YOUR_SERVER_IP:/opt/civitai-analytics/
```

### 2. Set up the environment on the server

```bash
ssh root@YOUR_SERVER_IP
cd /opt/civitai-analytics
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

### 3. Seed your config

```bash
cp config.example.json data/config.json
nano data/config.json   # fill in your real API key and username
```

### 4. Create a systemd service

```bash
cat > /etc/systemd/system/civitai-analytics.service << 'EOF'
[Unit]
Description=CivitAI Analytics
After=network.target

[Service]
WorkingDirectory=/opt/civitai-analytics
ExecStart=/opt/civitai-analytics/venv/bin/python app.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now civitai-analytics
```

The dashboard will be available at **http://YOUR_SERVER_IP:5757**.

### 5. Schedule the tracker

```bash
crontab -e
# Add:
0 */6 * * * /opt/civitai-analytics/venv/bin/python /opt/civitai-analytics/tracker.py
```

---

## Data Files

| File | Purpose | Committed? |
|---|---|---|
| `data/config.json` | Your API key and username | ❌ No (gitignored) |
| `data/civitai_state.json` | Cached post stats and history | ❌ No (gitignored) |
| `data/civitai_posts.json` | Your post metadata/labels | ❌ No (gitignored) |
| `config.example.json` | Template for config setup | ✅ Yes |

---

## License

MIT — do whatever you want with it. Attribution appreciated but not required.

---

## Contributing

PRs welcome. This started as a personal tool for a specific CivitAI creator workflow, so feature requests tied to real use cases are especially appreciated.
