#!/usr/bin/env python3
"""
CivitAI Post Metadata Editor & Analytics Dashboard
Run: python app.py
Then open: http://localhost:5757
"""

import json
import os
from collections import defaultdict

import requests
from flask import Flask, render_template_string, request, jsonify

BASE = os.path.dirname(__file__)
DATA_DIR = os.path.join(BASE, "data")
STATE_FILE = os.path.join(DATA_DIR, "civitai_state.json")
POSTS_META_FILE = os.path.join(DATA_DIR, "civitai_posts.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")

os.makedirs(DATA_DIR, exist_ok=True)

app = Flask(__name__)

# ── Config helpers ──────────────────────────────────────────────────────────

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {"api_key": "", "username": ""}


def save_config(cfg):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


# ── State / meta helpers ────────────────────────────────────────────────────

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"posts": {}, "history": []}


def load_meta():
    if os.path.exists(POSTS_META_FILE):
        with open(POSTS_META_FILE) as f:
            data = json.load(f)
            return data.get("posts", {})
    return {}


def save_meta(meta):
    existing = {}
    if os.path.exists(POSTS_META_FILE):
        with open(POSTS_META_FILE) as f:
            existing = json.load(f)
    existing["posts"] = meta
    with open(POSTS_META_FILE, "w") as f:
        json.dump(existing, f, indent=2)


def get_known(meta):
    characters, tags, themes = set(), set(), set()
    for m in meta.values():
        for c in m.get("characters", []):
            if c:
                characters.add(c)
        for t in m.get("tags", []):
            if t:
                tags.add(t)
        for t in m.get("themes", []):
            if t:
                themes.add(t)
        th = m.get("theme", "")
        if th:
            themes.add(th)
    return {
        "characters": sorted(characters),
        "tags": sorted(tags),
        "themes": sorted(themes),
    }


# ── HTML ────────────────────────────────────────────────────────────────────

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>CivitAI Analytics</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: #0f0f13;
      color: #e0e0e0;
      min-height: 100vh;
    }
    header {
      background: #1a1a24;
      border-bottom: 1px solid #2a2a3a;
      padding: 0 24px;
      display: flex;
      align-items: stretch;
      gap: 0;
    }
    .header-brand {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 14px 0;
      margin-right: 20px;
    }
    header h1 { font-size: 1.2rem; font-weight: 600; color: #fff; white-space: nowrap; }

    /* Nav tabs */
    .nav-tabs { display: flex; align-items: stretch; gap: 0; flex: 1; }
    .nav-tab {
      padding: 0 22px;
      display: flex;
      align-items: center;
      cursor: pointer;
      font-size: 0.9rem;
      font-weight: 500;
      color: #888;
      border-bottom: 3px solid transparent;
      transition: all 0.15s;
      user-select: none;
      white-space: nowrap;
    }
    .nav-tab:hover { color: #ccc; background: rgba(255,255,255,0.03); }
    .nav-tab.active { color: #7c6fff; border-bottom-color: #7c6fff; }
    .header-right {
      display: flex;
      align-items: center;
      margin-left: auto;
      padding: 14px 0;
    }

    /* Tab content */
    .tab-content { display: none; }
    .tab-content.active { display: block; }

    /* ── Posts layout ── */
    .layout { display: grid; grid-template-columns: 280px 1fr; height: calc(100vh - 57px); }
    .sidebar {
      background: #141420;
      border-right: 1px solid #2a2a3a;
      overflow-y: auto;
      padding: 12px 0;
    }
    .sidebar-filter {
      padding: 8px 12px 12px;
      border-bottom: 1px solid #2a2a3a;
      margin-bottom: 8px;
    }
    .sidebar-filter input {
      width: 100%;
      background: #0f0f18;
      border: 1px solid #333;
      border-radius: 6px;
      color: #e0e0e0;
      padding: 6px 10px;
      font-size: 0.82rem;
    }
    .post-item {
      padding: 10px 14px;
      cursor: pointer;
      border-left: 3px solid transparent;
      transition: all 0.15s;
    }
    .post-item:hover { background: #1e1e2e; }
    .post-item.active { background: #1e1e2e; border-left-color: #7c6fff; }
    .post-item.labeled { border-left-color: #3a8f5a; }
    .post-item.active.labeled { border-left-color: #7c6fff; }
    .post-date { font-size: 0.75rem; color: #888; margin-bottom: 2px; }
    .post-title { font-size: 0.88rem; font-weight: 500; color: #ccc; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .post-stats { font-size: 0.72rem; color: #666; margin-top: 3px; }
    .post-chars { font-size: 0.72rem; color: #7c6fff; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .nsfw-badge {
      display: inline-block;
      font-size: 0.65rem;
      padding: 1px 5px;
      border-radius: 3px;
      margin-left: 4px;
      vertical-align: middle;
    }
    .badge-X { background: #5a1a2a; color: #ff7a8a; }
    .badge-Mature { background: #3a2a1a; color: #ffaa60; }
    .badge-None { background: #1a2a1a; color: #60cc80; }

    /* Main editor */
    .editor { overflow-y: auto; padding: 24px 32px; }
    .editor-empty {
      display: flex; align-items: center; justify-content: center;
      height: 100%; color: #555; font-size: 1rem;
    }
    .editor-header {
      margin-bottom: 24px;
      padding-bottom: 16px;
      border-bottom: 1px solid #2a2a3a;
    }
    .editor-header h2 { font-size: 1.1rem; color: #fff; margin-bottom: 4px; }
    .editor-meta { font-size: 0.8rem; color: #666; }

    .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
    .form-group { display: flex; flex-direction: column; gap: 6px; }
    .form-group.full { grid-column: 1 / -1; }
    label { font-size: 0.8rem; color: #aaa; font-weight: 500; text-transform: uppercase; letter-spacing: 0.04em; }
    input[type="text"], input[type="password"], textarea, select {
      background: #1a1a24;
      border: 1px solid #333;
      border-radius: 8px;
      color: #e0e0e0;
      padding: 9px 12px;
      font-size: 0.9rem;
      font-family: inherit;
      transition: border-color 0.15s;
      width: 100%;
    }
    input[type="text"]:focus, input[type="password"]:focus, textarea:focus {
      outline: none;
      border-color: #7c6fff;
    }
    textarea { resize: vertical; min-height: 70px; }

    /* Pill inputs */
    .pill-input-wrap {
      background: #1a1a24;
      border: 1px solid #333;
      border-radius: 8px;
      padding: 6px 8px;
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: flex-start;
      min-height: 42px;
      cursor: text;
    }
    .pill-input-wrap:focus-within { border-color: #7c6fff; }
    .pill {
      display: inline-flex; align-items: center; gap: 4px;
      background: #2a2a3e; border: 1px solid #444; border-radius: 20px;
      padding: 3px 10px; font-size: 0.82rem; color: #c0b8ff; white-space: nowrap;
    }
    .pill.char-pill { background: #1e2a3e; color: #80b8ff; border-color: #335; }
    .pill.theme-pill { background: #2a1e3e; color: #c080ff; border-color: #533; }
    .pill-remove { cursor: pointer; color: #888; font-size: 0.9rem; line-height: 1; margin-left: 2px; }
    .pill-remove:hover { color: #ff7a8a; }
    .pill-text-input {
      border: none; background: transparent; color: #e0e0e0; font-size: 0.88rem;
      outline: none; min-width: 100px; flex: 1; padding: 2px 4px;
    }

    /* Dropdown suggestions */
    .suggest-wrap { position: relative; }
    .suggestions {
      position: absolute; top: 100%; left: 0; right: 0;
      background: #1e1e2e; border: 1px solid #444; border-radius: 8px;
      z-index: 100; max-height: 180px; overflow-y: auto;
      margin-top: 2px; box-shadow: 0 8px 24px rgba(0,0,0,0.5);
    }
    .suggestion-item { padding: 8px 12px; cursor: pointer; font-size: 0.88rem; color: #ccc; }
    .suggestion-item:hover, .suggestion-item.highlighted { background: #2a2a3e; color: #fff; }

    /* Theme chips */
    .theme-chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 4px; }
    .theme-chip {
      padding: 5px 14px; border-radius: 20px; font-size: 0.82rem; cursor: pointer;
      border: 1px solid #333; background: #1a1a24; color: #aaa; transition: all 0.15s;
    }
    .theme-chip:hover { border-color: #7c6fff; color: #c0b8ff; }
    .theme-chip.active { background: #2a2a4e; border-color: #7c6fff; color: #c0b8ff; }

    /* Actions */
    .actions { margin-top: 28px; display: flex; gap: 12px; align-items: center; }
    .btn {
      padding: 10px 22px; border-radius: 8px; font-size: 0.9rem; font-weight: 600;
      border: none; cursor: pointer; transition: all 0.15s;
    }
    .btn-primary { background: #7c6fff; color: #fff; }
    .btn-primary:hover { background: #9b8fff; }
    .btn-secondary { background: #2a2a3a; color: #aaa; border: 1px solid #333; }
    .btn-secondary:hover { background: #333; color: #ddd; }
    .btn-danger { background: #3a1a1a; color: #ff7a8a; border: 1px solid #5a2a2a; }
    .btn-danger:hover { background: #4a2020; }
    .save-status { font-size: 0.85rem; color: #60cc80; display: none; }
    .save-status.error { color: #ff7a8a; }

    /* Stats panel */
    .stats-row { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; }
    .stat-box {
      background: #1a1a24; border: 1px solid #2a2a3a; border-radius: 10px;
      padding: 12px 18px; min-width: 100px; text-align: center;
    }
    .stat-val { font-size: 1.4rem; font-weight: 700; color: #fff; }
    .stat-lbl { font-size: 0.72rem; color: #777; margin-top: 2px; }
    .stat-hearts .stat-val { color: #ff7aaa; }
    .stat-likes .stat-val { color: #7aaeff; }

    /* ── Dashboard ── */
    .dashboard { height: calc(100vh - 57px); overflow-y: auto; padding: 28px 32px; }
    .dash-section { margin-bottom: 32px; }
    .dash-section h2 {
      font-size: 0.78rem; font-weight: 700; text-transform: uppercase;
      letter-spacing: 0.08em; color: #666; margin-bottom: 14px;
    }
    .dash-grid { display: grid; gap: 14px; }
    .dash-grid-5 { grid-template-columns: repeat(5, 1fr); }
    .dash-grid-3 { grid-template-columns: repeat(3, 1fr); }
    .dash-grid-4 { grid-template-columns: repeat(4, 1fr); }
    .dash-grid-2 { grid-template-columns: 1fr 1fr; }
    @media (max-width: 900px) {
      .dash-grid-5 { grid-template-columns: repeat(3, 1fr); }
      .dash-grid-3 { grid-template-columns: 1fr 1fr; }
      .dash-grid-4 { grid-template-columns: 1fr 1fr; }
      .dash-grid-2 { grid-template-columns: 1fr; }
    }
    .dash-card {
      background: #1a1a24; border: 1px solid #2a2a3a; border-radius: 12px; padding: 18px 20px;
    }
    .dash-stat-card {
      background: #1a1a24; border: 1px solid #2a2a3a; border-radius: 12px;
      padding: 16px 20px; text-align: center;
    }
    .dash-stat-card .dsc-val { font-size: 2rem; font-weight: 700; color: #fff; line-height: 1.1; }
    .dash-stat-card .dsc-lbl { font-size: 0.75rem; color: #666; margin-top: 4px; }
    .dash-stat-card .dsc-delta { font-size: 0.78rem; margin-top: 6px; font-weight: 600; }
    .delta-pos { color: #60cc80; }
    .delta-neg { color: #ff7a8a; }
    .delta-neu { color: #666; }

    .bar-list { display: flex; flex-direction: column; gap: 8px; }
    .bar-row { display: flex; align-items: center; gap: 10px; }
    .bar-label { font-size: 0.82rem; color: #bbb; width: 110px; flex-shrink: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .bar-track { flex: 1; background: #0f0f18; border-radius: 4px; height: 14px; overflow: hidden; }
    .bar-fill { height: 100%; border-radius: 4px; background: linear-gradient(90deg, #7c6fff, #a08fff); transition: width 0.6s ease; min-width: 2px; }
    .bar-val { font-size: 0.78rem; color: #888; width: 50px; text-align: right; flex-shrink: 0; }

    .posts-table { width: 100%; border-collapse: collapse; font-size: 0.83rem; }
    .posts-table th { text-align: left; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.06em; color: #555; padding: 0 10px 10px 0; border-bottom: 1px solid #2a2a3a; }
    .posts-table td { padding: 9px 10px 9px 0; border-bottom: 1px solid #1e1e2a; vertical-align: middle; color: #ccc; }
    .posts-table tr:last-child td { border-bottom: none; }
    .posts-table a { color: #7c6fff; text-decoration: none; }
    .posts-table a:hover { text-decoration: underline; }
    .posts-table .score-val { color: #fff; font-weight: 700; }
    .char-tag { display: inline-block; font-size: 0.7rem; padding: 2px 7px; border-radius: 10px; background: #1e2a3e; color: #80b8ff; margin: 1px 2px; }

    .recent-list { display: flex; flex-direction: column; gap: 10px; }
    .recent-item { background: #141420; border: 1px solid #2a2a3a; border-radius: 8px; padding: 12px 16px; display: flex; align-items: center; gap: 16px; }
    .recent-date { font-size: 0.75rem; color: #666; width: 80px; flex-shrink: 0; }
    .recent-title { font-size: 0.88rem; color: #ccc; flex: 1; }
    .recent-title a { color: #7c6fff; text-decoration: none; }
    .recent-title a:hover { text-decoration: underline; }
    .recent-stats { font-size: 0.78rem; color: #888; white-space: nowrap; }

    .empty-hint { color: #555; font-size: 0.88rem; padding: 20px; text-align: center; font-style: italic; }

    .nsfw-card { background: #1a1a24; border: 1px solid #2a2a3a; border-radius: 12px; padding: 16px 20px; text-align: center; }
    .nsfw-card .nc-level { font-size: 0.75rem; color: #888; margin-bottom: 8px; }
    .nsfw-card .nc-score { font-size: 1.6rem; font-weight: 700; color: #fff; }
    .nsfw-card .nc-count { font-size: 0.72rem; color: #555; margin-top: 4px; }

    .bucket-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }
    @media (max-width: 700px) { .bucket-grid { grid-template-columns: 1fr 1fr; } }
    .bucket-card { background: #1a1a24; border: 1px solid #2a2a3a; border-radius: 12px; padding: 16px 20px; text-align: center; }
    .bucket-card .bc-label { font-size: 0.75rem; color: #888; margin-bottom: 8px; }
    .bucket-card .bc-score { font-size: 1.6rem; font-weight: 700; color: #fff; }
    .bucket-card .bc-count { font-size: 0.72rem; color: #555; margin-top: 4px; }

    /* ── Settings tab ── */
    .settings-page {
      height: calc(100vh - 57px);
      overflow-y: auto;
      padding: 36px 40px;
      max-width: 680px;
    }
    .settings-page h2 {
      font-size: 1.1rem;
      font-weight: 600;
      color: #fff;
      margin-bottom: 6px;
    }
    .settings-page .settings-desc {
      font-size: 0.85rem;
      color: #666;
      margin-bottom: 32px;
      line-height: 1.5;
    }
    .settings-page .settings-desc a {
      color: #7c6fff;
      text-decoration: none;
    }
    .settings-page .settings-desc a:hover { text-decoration: underline; }
    .settings-section {
      background: #1a1a24;
      border: 1px solid #2a2a3a;
      border-radius: 12px;
      padding: 24px 28px;
      margin-bottom: 20px;
    }
    .settings-section h3 {
      font-size: 0.78rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #555;
      margin-bottom: 18px;
    }
    .settings-field {
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin-bottom: 18px;
    }
    .settings-field:last-child { margin-bottom: 0; }
    .settings-field label { font-size: 0.8rem; color: #aaa; font-weight: 500; text-transform: uppercase; letter-spacing: 0.04em; }
    .settings-field .field-hint { font-size: 0.78rem; color: #555; margin-top: 3px; }
    .api-key-wrap { position: relative; display: flex; align-items: center; }
    .api-key-wrap input { padding-right: 44px; }
    .toggle-visible {
      position: absolute; right: 12px; cursor: pointer; font-size: 1rem;
      color: #555; user-select: none; transition: color 0.15s;
    }
    .toggle-visible:hover { color: #bbb; }
    .settings-actions {
      display: flex;
      gap: 12px;
      align-items: center;
      margin-top: 24px;
    }
    .conn-status {
      font-size: 0.85rem;
      display: none;
      padding: 6px 12px;
      border-radius: 6px;
      font-weight: 500;
    }
    .conn-ok { background: #1a2e1a; color: #60cc80; border: 1px solid #2a4a2a; }
    .conn-fail { background: #2e1a1a; color: #ff7a8a; border: 1px solid #4a2a2a; }
    .conn-loading { background: #1a1a2e; color: #7c6fff; border: 1px solid #2a2a4a; }
  </style>
</head>
<body>
  <header>
    <div class="header-brand">
      <h1>📊 CivitAI Analytics</h1>
    </div>
    <div class="nav-tabs">
      <div class="nav-tab" id="tab-dashboard" onclick="switchTab('dashboard')">📊 Dashboard</div>
      <div class="nav-tab active" id="tab-posts" onclick="switchTab('posts')">✏️ Posts</div>
      <div class="nav-tab" id="tab-settings" onclick="switchTab('settings')">⚙️ Settings</div>
    </div>
    <div class="header-right">
      <span id="header-status" style="font-size:0.85rem;color:#888;">Loading...</span>
    </div>
  </header>

  <!-- Dashboard tab -->
  <div class="tab-content" id="content-dashboard">
    <div class="dashboard" id="dashboard-content">
      <div class="empty-hint">Loading dashboard...</div>
    </div>
  </div>

  <!-- Posts tab -->
  <div class="tab-content active" id="content-posts">
    <div class="layout">
      <div class="sidebar">
        <div class="sidebar-filter">
          <input type="text" id="search" placeholder="Search posts..." oninput="filterPosts()" />
        </div>
        <div id="post-list"></div>
      </div>
      <div class="editor" id="editor">
        <div class="editor-empty">← Select a post to edit</div>
      </div>
    </div>
  </div>

  <!-- Settings tab -->
  <div class="tab-content" id="content-settings">
    <div class="settings-page">
      <h2>Settings</h2>
      <p class="settings-desc">
        Configure your CivitAI credentials to enable data syncing.<br>
        Get your API key from
        <a href="https://civitai.com/user/account" target="_blank">civitai.com → Account Settings → API Keys</a>.
        Your key is stored locally in <code>data/config.json</code> and never transmitted anywhere except directly to the CivitAI API.
      </p>

      <div class="settings-section">
        <h3>CivitAI Credentials</h3>

        <div class="settings-field">
          <label>CivitAI Username</label>
          <input type="text" id="cfg-username" placeholder="your-civitai-username" autocomplete="off" />
          <div class="field-hint">Your public CivitAI username (visible in your profile URL).</div>
        </div>

        <div class="settings-field">
          <label>API Key</label>
          <div class="api-key-wrap">
            <input type="password" id="cfg-apikey" placeholder="Paste your API key here" autocomplete="off" />
            <span class="toggle-visible" onclick="toggleApiKeyVisibility()" id="eye-icon">👁</span>
          </div>
          <div class="field-hint">
            Generate at: <strong>civitai.com → Profile → Settings → API Keys → Add API Key</strong>
          </div>
        </div>
      </div>

      <div class="settings-actions">
        <button class="btn btn-primary" onclick="saveSettings()">💾 Save Settings</button>
        <button class="btn btn-secondary" onclick="testConnection()">🔌 Test Connection</button>
        <span class="conn-status" id="conn-status"></span>
      </div>
    </div>
  </div>

<script>
let allPosts = [];
let allMeta = {};
let known = { characters: [], tags: [], themes: [] };
let currentPostId = null;
let dashLoaded = false;

// ── Tab switching ──────────────────────────────────────────────────────────
function switchTab(tab) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.nav-tab').forEach(el => el.classList.remove('active'));
  document.getElementById('content-' + tab).classList.add('active');
  document.getElementById('tab-' + tab).classList.add('active');
  if (tab === 'dashboard' && !dashLoaded) loadDashboard();
  if (tab === 'settings') loadSettings();
}

// ── Init ──────────────────────────────────────────────────────────────────
async function init() {
  try {
    const r = await fetch('/api/data');
    const d = await r.json();
    if (d.unconfigured) {
      document.getElementById('header-status').textContent = '⚠️ Not configured — see Settings';
      document.getElementById('post-list').innerHTML =
        '<div class="empty-hint">Configure your API key in ⚙️ Settings to load posts.</div>';
      document.getElementById('editor').innerHTML =
        '<div class="editor-empty">Configure your CivitAI credentials in the Settings tab to get started.</div>';
      return;
    }
    allPosts = d.posts;
    allMeta = d.meta;
    known = d.known;
    document.getElementById('header-status').textContent =
      `${allPosts.length} posts · ${allPosts.filter(p => allMeta[p.postId]?.title).length} labeled`;
    renderList(allPosts);
  } catch(e) {
    document.getElementById('header-status').textContent = 'Error loading data';
  }
}

// ── Post list ──────────────────────────────────────────────────────────────
function filterPosts() {
  const q = document.getElementById('search').value.toLowerCase();
  const filtered = q
    ? allPosts.filter(p => {
        const m = allMeta[p.postId] || {};
        return p.postId.includes(q)
          || (m.title || '').toLowerCase().includes(q)
          || (m.characters || []).join(' ').toLowerCase().includes(q)
          || (m.tags || []).join(' ').toLowerCase().includes(q)
          || (m.theme || '').toLowerCase().includes(q);
      })
    : allPosts;
  renderList(filtered);
}

function renderList(posts) {
  const el = document.getElementById('post-list');
  el.innerHTML = posts.map(p => {
    const m = allMeta[p.postId] || {};
    const labeled = m.title || (m.characters||[]).length || (m.tags||[]).length;
    const levels = [...new Set(p.nsfwLevels)].map(l =>
      `<span class="nsfw-badge badge-${l}">${l}</span>`).join('');
    const chars = (m.characters||[]).join(', ');
    const title = m.title || `Post ${p.postId}`;
    return `<div class="post-item ${labeled ? 'labeled' : ''} ${p.postId === currentPostId ? 'active' : ''}"
      onclick="selectPost('${p.postId}')">
      <div class="post-date">${p.date} ${levels}</div>
      <div class="post-title">${title}</div>
      <div class="post-stats">❤️${p.hearts} 👍${p.likes} · ${p.imageCount} imgs</div>
      ${chars ? `<div class="post-chars">${chars}</div>` : ''}
    </div>`;
  }).join('');
}

function selectPost(postId) {
  currentPostId = postId;
  const post = allPosts.find(p => p.postId === postId);
  const meta = allMeta[postId] || {};
  filterPosts();

  const editor = document.getElementById('editor');
  const levels = [...new Set(post.nsfwLevels)].map(l =>
    `<span class="nsfw-badge badge-${l}">${l}</span>`).join(' ');

  editor.innerHTML = `
    <div class="editor-header">
      <h2>${meta.title || 'Untitled Post'} &nbsp;${levels}</h2>
      <div class="editor-meta">
        Post ID: ${postId} &nbsp;·&nbsp; ${post.date} &nbsp;·&nbsp;
        ${post.imageCount} images &nbsp;·&nbsp;
        <a href="https://civitai.com/posts/${postId}" target="_blank" style="color:#7c6fff">View on CivitAI ↗</a>
      </div>
    </div>

    <div class="stats-row">
      <div class="stat-box stat-hearts"><div class="stat-val">❤️${post.hearts}</div><div class="stat-lbl">Hearts</div></div>
      <div class="stat-box stat-likes"><div class="stat-val">👍${post.likes}</div><div class="stat-lbl">Likes</div></div>
      <div class="stat-box"><div class="stat-val">💬${post.comments}</div><div class="stat-lbl">Comments</div></div>
      <div class="stat-box"><div class="stat-val">${post.imageCount}</div><div class="stat-lbl">Images</div></div>
      <div class="stat-box"><div class="stat-val">${Math.round(post.hearts * 2 + post.likes)}</div><div class="stat-lbl">Score</div></div>
    </div>

    <div class="form-grid">
      <div class="form-group full">
        <label>Title / Set Name</label>
        <input type="text" id="f-title" value="${meta.title || ''}" placeholder="e.g. Beach Set Vol 1" />
      </div>

      <div class="form-group">
        <label>Characters</label>
        <div class="suggest-wrap">
          <div class="pill-input-wrap" id="char-wrap" onclick="focusInput('char-input')">
            ${(meta.characters||[]).map(c => pillHtml(c, 'char')).join('')}
            <input class="pill-text-input" id="char-input" placeholder="Add character..."
              oninput="showSuggest(this, 'char-suggest', known.characters)"
              onkeydown="pillKeydown(event, 'char-wrap', 'char-input', 'characters')"
              onfocus="showSuggest(this, 'char-suggest', known.characters)"
              onblur="hideSuggest('char-suggest')" />
          </div>
          <div class="suggestions" id="char-suggest" style="display:none"></div>
        </div>
      </div>

      <div class="form-group">
        <label>Tags</label>
        <div class="suggest-wrap">
          <div class="pill-input-wrap" id="tag-wrap" onclick="focusInput('tag-input')">
            ${(meta.tags||[]).map(t => pillHtml(t, 'tag')).join('')}
            <input class="pill-text-input" id="tag-input" placeholder="Add tag..."
              oninput="showSuggest(this, 'tag-suggest', known.tags)"
              onkeydown="pillKeydown(event, 'tag-wrap', 'tag-input', 'tags')"
              onfocus="showSuggest(this, 'tag-suggest', known.tags)"
              onblur="hideSuggest('tag-suggest')" />
          </div>
          <div class="suggestions" id="tag-suggest" style="display:none"></div>
        </div>
      </div>

      <div class="form-group full">
        <label>Themes <span style="color:#555;font-size:0.75em;text-transform:none;letter-spacing:0">(select multiple or type custom)</span></label>
        <div class="theme-chips" id="theme-chips">
          ${['pinup','holiday','explicit','SFW','outdoor','indoor','fantasy','seasonal','beach','studio','closeup','portrait','action'].map(t =>
            `<div class="theme-chip ${(meta.themes||[]).includes(t)?'active':''}" onclick="toggleTheme('${t}')">${t}</div>`
          ).join('')}
        </div>
        <div class="suggest-wrap" style="margin-top:8px">
          <div class="pill-input-wrap" id="theme-wrap" onclick="focusInput('theme-input')">
            ${(meta.themes||[]).map(t => pillHtml(t, 'theme')).join('')}
            <input class="pill-text-input" id="theme-input" placeholder="Add custom theme..."
              oninput="showSuggest(this, 'theme-suggest', known.themes)"
              onkeydown="pillKeydown(event, 'theme-wrap', 'theme-input', 'themes')"
              onfocus="showSuggest(this, 'theme-suggest', known.themes)"
              onblur="hideSuggest('theme-suggest')" />
          </div>
          <div class="suggestions" id="theme-suggest" style="display:none"></div>
        </div>
      </div>

      <div class="form-group full">
        <label>Notes</label>
        <textarea id="f-notes" placeholder="Checkpoint used, workflow notes, etc.">${meta.notes || ''}</textarea>
      </div>
    </div>

    <div class="actions">
      <button class="btn btn-primary" onclick="savePost()">Save</button>
      <button class="btn btn-secondary" onclick="clearPost()">Clear</button>
      <span class="save-status" id="save-status"></span>
    </div>
  `;
}

function pillHtml(val, type) {
  return `<span class="pill ${type}-pill" data-val="${val}">${val}<span class="pill-remove" onclick="removePill(this)">✕</span></span>`;
}
function focusInput(id) { document.getElementById(id)?.focus(); }
function removePill(el) { el.parentElement.remove(); }
function getPillValues(wrapId) {
  return [...document.querySelectorAll(`#${wrapId} .pill`)].map(p => p.dataset.val);
}
function addPill(wrapId, inputId, type, val) {
  val = val.trim();
  if (!val) return;
  const wrap = document.getElementById(wrapId);
  const existing = getPillValues(wrapId);
  if (existing.includes(val)) return;
  const input = document.getElementById(inputId);
  const pill = document.createElement('span');
  pill.className = `pill ${type}-pill`;
  pill.dataset.val = val;
  pill.innerHTML = `${val}<span class="pill-remove" onclick="removePill(this)">✕</span>`;
  wrap.insertBefore(pill, input);
  input.value = '';
}
function pillKeydown(e, wrapId, inputId, type) {
  const input = document.getElementById(inputId);
  const suggestId = type === 'characters' ? 'char-suggest' : type === 'tags' ? 'tag-suggest' : 'theme-suggest';
  const pillType = type === 'characters' ? 'char' : type === 'tags' ? 'tag' : 'theme';
  if ((e.key === 'Enter' || e.key === ',') && input.value.trim()) {
    e.preventDefault();
    addPill(wrapId, inputId, pillType, input.value);
    hideSuggest(suggestId);
  } else if (e.key === 'Backspace' && !input.value) {
    const pills = document.querySelectorAll(`#${wrapId} .pill`);
    if (pills.length) pills[pills.length - 1].remove();
  }
}
function showSuggest(input, suggestId, list) {
  const q = input.value.toLowerCase();
  const suggest = document.getElementById(suggestId);
  const matches = list.filter(v => v.toLowerCase().includes(q) && v !== input.value).slice(0, 8);
  if (!matches.length) { suggest.style.display = 'none'; return; }
  suggest.innerHTML = matches.map(m =>
    `<div class="suggestion-item" onmousedown="pickSuggest(event, '${suggestId}', '${m}')">${m}</div>`
  ).join('');
  suggest.style.display = 'block';
}
function pickSuggest(e, suggestId, val) {
  e.preventDefault();
  const map = {
    'char-suggest':  ['char-wrap',  'char-input',  'char'],
    'tag-suggest':   ['tag-wrap',   'tag-input',   'tag'],
    'theme-suggest': ['theme-wrap', 'theme-input', 'theme'],
  };
  const [wrapId, inputId, pillType] = map[suggestId] || [];
  if (wrapId) {
    addPill(wrapId, inputId, pillType, val);
    if (suggestId === 'theme-suggest') syncThemeChips();
  }
  hideSuggest(suggestId);
}
function hideSuggest(id) {
  setTimeout(() => { const el = document.getElementById(id); if (el) el.style.display = 'none'; }, 150);
}
function toggleTheme(val) {
  const wrap = document.getElementById('theme-wrap');
  const existing = getPillValues('theme-wrap');
  if (existing.includes(val)) {
    wrap.querySelectorAll('.pill').forEach(p => { if (p.dataset.val === val) p.remove(); });
  } else {
    addPill('theme-wrap', 'theme-input', 'theme', val);
  }
  syncThemeChips();
}
function syncThemeChips() {
  const active = getPillValues('theme-wrap');
  document.querySelectorAll('.theme-chip').forEach(c => {
    c.classList.toggle('active', active.includes(c.textContent));
  });
}

async function savePost() {
  const payload = {
    postId: currentPostId,
    title: document.getElementById('f-title').value.trim(),
    characters: getPillValues('char-wrap'),
    tags: getPillValues('tag-wrap'),
    themes: getPillValues('theme-wrap'),
    notes: document.getElementById('f-notes').value.trim(),
  };
  const r = await fetch('/api/save', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const d = await r.json();
  const status = document.getElementById('save-status');
  status.style.display = 'inline';
  if (d.ok) {
    allMeta[currentPostId] = payload;
    payload.characters.forEach(c => { if (!known.characters.includes(c)) known.characters.push(c); });
    payload.tags.forEach(t => { if (!known.tags.includes(t)) known.tags.push(t); });
    payload.themes.forEach(t => { if (!known.themes.includes(t)) known.themes.push(t); });
    status.className = 'save-status';
    status.textContent = '✓ Saved';
    filterPosts();
    dashLoaded = false;
    setTimeout(() => { status.style.display = 'none'; }, 2000);
  } else {
    status.className = 'save-status error';
    status.textContent = '✗ Error saving';
  }
}

function clearPost() {
  if (!confirm('Clear all metadata for this post?')) return;
  document.getElementById('f-title').value = '';
  document.getElementById('f-notes').value = '';
  ['char-wrap', 'tag-wrap', 'theme-wrap'].forEach(wrapId => {
    document.querySelectorAll(`#${wrapId} .pill`).forEach(p => p.remove());
  });
  syncThemeChips();
}

// ── Dashboard ──────────────────────────────────────────────────────────────
async function loadDashboard() {
  const container = document.getElementById('dashboard-content');
  container.innerHTML = '<div class="empty-hint">Loading dashboard...</div>';
  try {
    const r = await fetch('/api/dashboard');
    const d = await r.json();
    if (d.unconfigured) {
      container.innerHTML = `<div class="empty-hint">
        ⚙️ Please configure your API key in the <a href="#" onclick="switchTab('settings');return false;" style="color:#7c6fff">Settings tab</a> to load dashboard data.
      </div>`;
      return;
    }
    dashLoaded = true;
    renderDashboard(d, container);
  } catch(e) {
    container.innerHTML = `<div class="empty-hint">Failed to load dashboard: ${e.message}</div>`;
  }
}

function deltaHtml(val) {
  if (val === null || val === undefined) return '<span class="delta-neu">—</span>';
  if (val > 0) return `<span class="delta-pos">+${val}</span>`;
  if (val < 0) return `<span class="delta-neg">${val}</span>`;
  return '<span class="delta-neu">±0</span>';
}

function barChart(items) {
  if (!items || items.length === 0) return '<div class="empty-hint">Label some posts to see this</div>';
  const top = Math.max(...items.map(i => i.value), 1);
  return '<div class="bar-list">' + items.map(item => `
    <div class="bar-row">
      <div class="bar-label" title="${item.label}">${item.label}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${Math.max(2, Math.round(item.value / top * 100))}%"></div></div>
      <div class="bar-val">${item.value}</div>
    </div>
  `).join('') + '</div>';
}

function renderDashboard(d, container) {
  const t = d.totals;
  const delta = d.delta;

  const statCards = [
    { val: t.hearts,   lbl: 'Total Hearts',   emoji: '❤️', delta: delta?.hearts },
    { val: t.likes,    lbl: 'Total Likes',    emoji: '👍', delta: delta?.likes },
    { val: t.comments, lbl: 'Total Comments', emoji: '💬', delta: delta?.comments },
    { val: t.posts,    lbl: 'Total Posts',    emoji: '📝', delta: null },
    { val: t.images,   lbl: 'Total Images',   emoji: '🖼️', delta: null },
  ].map(s => `
    <div class="dash-stat-card">
      <div class="dsc-val">${s.emoji} ${s.val.toLocaleString()}</div>
      <div class="dsc-lbl">${s.lbl}</div>
      ${s.delta !== null ? `<div class="dsc-delta">Last 24h: ${deltaHtml(s.delta)}</div>` : ''}
    </div>
  `).join('');

  let bestPostsHtml = '';
  if (d.best_posts && d.best_posts.length > 0) {
    bestPostsHtml = `<table class="posts-table">
      <thead><tr><th>Post</th><th>Date</th><th>Characters</th><th>NSFW</th><th>❤️</th><th>👍</th><th>Score</th></tr></thead>
      <tbody>${d.best_posts.map(p => `
        <tr>
          <td><a href="https://civitai.com/posts/${p.postId}" target="_blank">${p.title || p.postId}</a></td>
          <td>${p.date}</td>
          <td>${(p.characters||[]).map(c => `<span class="char-tag">${c}</span>`).join('')}</td>
          <td>${(p.nsfwLevels||[]).map(l => `<span class="nsfw-badge badge-${l}">${l}</span>`).join('')}</td>
          <td>${p.hearts}</td><td>${p.likes}</td>
          <td class="score-val">${p.score}</td>
        </tr>`).join('')}
      </tbody></table>`;
  } else {
    bestPostsHtml = '<div class="empty-hint">No posts with engagement data yet.</div>';
  }

  let nsfwHtml = d.nsfw_breakdown && d.nsfw_breakdown.length > 0
    ? '<div class="dash-grid dash-grid-3">' + d.nsfw_breakdown.map(n => `
        <div class="nsfw-card">
          <div class="nc-level"><span class="nsfw-badge badge-${n.level}">${n.level}</span></div>
          <div class="nc-score">${n.avg_score}</div>
          <div class="nc-count">${n.count} posts · avg score</div>
        </div>`).join('') + '</div>'
    : '<div class="empty-hint">No data yet.</div>';

  let bucketHtml = d.image_buckets && d.image_buckets.length > 0
    ? '<div class="bucket-grid">' + d.image_buckets.map(b => `
        <div class="bucket-card">
          <div class="bc-label">${b.label} images</div>
          <div class="bc-score">${b.avg_score}</div>
          <div class="bc-count">${b.count} posts · avg score</div>
        </div>`).join('') + '</div>'
    : '<div class="empty-hint">No data yet.</div>';

  let recentHtml = d.recent_posts && d.recent_posts.length > 0
    ? '<div class="recent-list">' + d.recent_posts.map(p => `
        <div class="recent-item">
          <div class="recent-date">${p.date}</div>
          <div class="recent-title">
            <a href="https://civitai.com/posts/${p.postId}" target="_blank">${p.title || 'Post ' + p.postId}</a>
            ${(p.characters||[]).map(c => `<span class="char-tag">${c}</span>`).join('')}
          </div>
          <div class="recent-stats">❤️${p.hearts} &nbsp;👍${p.likes} &nbsp;💬${p.comments}</div>
        </div>`).join('') + '</div>'
    : '<div class="empty-hint">No recent posts.</div>';

  container.innerHTML = `
    <div class="dash-section">
      <h2>All-Time Totals</h2>
      <div class="dash-grid dash-grid-5">${statCards}</div>
    </div>
    <div class="dash-grid dash-grid-2" style="margin-bottom:32px">
      <div class="dash-section" style="margin-bottom:0">
        <h2>Top Characters (by engagement)</h2>
        <div class="dash-card">${barChart(d.top_characters)}</div>
      </div>
      <div class="dash-section" style="margin-bottom:0">
        <h2>Top Tags (by engagement)</h2>
        <div class="dash-card">${barChart(d.top_tags)}</div>
      </div>
    </div>
    <div class="dash-section">
      <h2>Top Themes (by engagement)</h2>
      <div class="dash-card">${barChart(d.top_themes)}</div>
    </div>
    <div class="dash-section">
      <h2>Best Performing Posts (Top 10)</h2>
      <div class="dash-card">${bestPostsHtml}</div>
    </div>
    <div class="dash-grid dash-grid-2" style="margin-bottom:32px">
      <div class="dash-section" style="margin-bottom:0">
        <h2>NSFW Level Breakdown</h2>${nsfwHtml}
      </div>
      <div class="dash-section" style="margin-bottom:0">
        <h2>Image Count Sweet Spot</h2>${bucketHtml}
      </div>
    </div>
    <div class="dash-section">
      <h2>Recent Activity (Last 5 Posts)</h2>${recentHtml}
    </div>
  `;
}

// ── Settings ──────────────────────────────────────────────────────────────
async function loadSettings() {
  try {
    const r = await fetch('/api/config');
    const d = await r.json();
    document.getElementById('cfg-username').value = d.username || '';
    document.getElementById('cfg-apikey').value = d.has_api_key ? '••••••••••••••••••••••••••••••••' : '';
    document.getElementById('cfg-apikey').dataset.placeholder = d.has_api_key ? 'true' : '';
  } catch(e) { /* silently fail */ }
}

function toggleApiKeyVisibility() {
  const input = document.getElementById('cfg-apikey');
  const icon = document.getElementById('eye-icon');
  if (input.type === 'password') {
    input.type = 'text';
    icon.textContent = '🙈';
  } else {
    input.type = 'password';
    icon.textContent = '👁';
  }
}

async function saveSettings() {
  const apiKey = document.getElementById('cfg-apikey').value;
  const username = document.getElementById('cfg-username').value.trim();
  const payload = { username };

  // Only send api_key if it's not the placeholder mask
  if (apiKey && !apiKey.startsWith('••')) payload.api_key = apiKey;

  const r = await fetch('/api/config', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const d = await r.json();
  const status = document.getElementById('conn-status');
  status.className = d.ok ? 'conn-status conn-ok' : 'conn-status conn-fail';
  status.textContent = d.ok ? '✓ Settings saved' : '✗ Failed to save';
  status.style.display = 'inline-block';
  if (d.ok) {
    // Refresh post data with new config
    init();
    dashLoaded = false;
  }
  setTimeout(() => { status.style.display = 'none'; }, 3000);
}

async function testConnection() {
  const status = document.getElementById('conn-status');
  status.className = 'conn-status conn-loading';
  status.textContent = '⟳ Testing…';
  status.style.display = 'inline-block';
  try {
    const r = await fetch('/api/test-connection');
    const d = await r.json();
    status.className = d.ok ? 'conn-status conn-ok' : 'conn-status conn-fail';
    status.textContent = d.ok ? `✓ ${d.message}` : `✗ ${d.message}`;
  } catch(e) {
    status.className = 'conn-status conn-fail';
    status.textContent = '✗ Request failed';
  }
  setTimeout(() => { status.style.display = 'none'; }, 5000);
}

init();
</script>
</body>
</html>
"""


# ── Flask routes ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/data")
def api_data():
    cfg = load_config()
    if not cfg.get("api_key") or not cfg.get("username"):
        return jsonify({"unconfigured": True, "posts": [], "meta": {}, "known": {}})

    state = load_state()
    meta = load_meta()
    posts_raw = state.get("posts", {})

    posts = []
    for pid, p in sorted(posts_raw.items(), key=lambda x: x[1]["date"], reverse=True):
        posts.append({
            "postId": pid,
            "date": p["date"],
            "hearts": p["hearts"],
            "likes": p["likes"],
            "comments": p["comments"],
            "imageCount": p["imageCount"],
            "nsfwLevels": p.get("nsfwLevels", []),
            "score": p["hearts"] * 2 + p["likes"],
        })

    return jsonify({"posts": posts, "meta": meta, "known": get_known(meta)})


@app.route("/api/save", methods=["POST"])
def api_save():
    data = request.json
    post_id = data.get("postId")
    if not post_id:
        return jsonify({"ok": False, "error": "No postId"})

    meta = load_meta()
    meta[post_id] = {
        "title": data.get("title", ""),
        "characters": data.get("characters", []),
        "tags": data.get("tags", []),
        "themes": data.get("themes", []),
        "notes": data.get("notes", ""),
    }
    save_meta(meta)
    return jsonify({"ok": True})


@app.route("/api/dashboard")
def api_dashboard():
    cfg = load_config()
    if not cfg.get("api_key") or not cfg.get("username"):
        return jsonify({"unconfigured": True})

    state = load_state()
    meta = load_meta()
    posts_raw = state.get("posts", {})
    history = state.get("history", [])

    total_hearts = sum(p.get("hearts", 0) for p in posts_raw.values())
    total_likes = sum(p.get("likes", 0) for p in posts_raw.values())
    total_comments = sum(p.get("comments", 0) for p in posts_raw.values())
    total_images = sum(p.get("imageCount", 0) for p in posts_raw.values())
    total_posts = len(posts_raw)

    delta = None
    if len(history) >= 2:
        curr, prev = history[-1], history[-2]
        delta = {
            "hearts": curr.get("totalHearts", 0) - prev.get("totalHearts", 0),
            "likes": curr.get("totalLikes", 0) - prev.get("totalLikes", 0),
            "comments": curr.get("totalComments", 0) - prev.get("totalComments", 0),
        }

    def get_post_labels(pid):
        if pid in meta:
            m = meta[pid]
            chars = m.get("characters", [])
            tags = m.get("tags", [])
            themes_list = m.get("themes", [])
            if not themes_list and m.get("theme"):
                themes_list = [m["theme"]]
            return chars, tags, themes_list
        p = posts_raw.get(pid, {})
        chars = p.get("characters", [])
        tags = p.get("tags", [])
        theme = p.get("theme", "")
        return chars, tags, [theme] if theme else []

    char_scores = defaultdict(int)
    tag_scores = defaultdict(int)
    theme_scores = defaultdict(int)

    for pid, p in posts_raw.items():
        s = p.get("hearts", 0) * 2 + p.get("likes", 0)
        chars, tags, themes_list = get_post_labels(pid)
        if chars or tags or themes_list:
            for c in chars:
                if c: char_scores[c] += s
            for t in tags:
                if t: tag_scores[t] += s
            for th in themes_list:
                if th: theme_scores[th] += s

    top_characters = [{"label": k, "value": v} for k, v in sorted(char_scores.items(), key=lambda x: -x[1])[:8]]
    top_tags = [{"label": k, "value": v} for k, v in sorted(tag_scores.items(), key=lambda x: -x[1])[:8]]
    top_themes = [{"label": k, "value": v} for k, v in sorted(theme_scores.items(), key=lambda x: -x[1])[:6]]

    def post_score(pid):
        p = posts_raw[pid]
        return p.get("hearts", 0) * 2 + p.get("likes", 0)

    sorted_pids = sorted(posts_raw.keys(), key=post_score, reverse=True)[:10]
    best_posts = []
    for pid in sorted_pids:
        p = posts_raw[pid]
        chars, tags, themes_list = get_post_labels(pid)
        title = (meta.get(pid) or {}).get("title") or p.get("title") or None
        best_posts.append({
            "postId": pid, "title": title, "date": p.get("date", ""),
            "characters": chars, "nsfwLevels": list(set(p.get("nsfwLevels", []))),
            "hearts": p.get("hearts", 0), "likes": p.get("likes", 0),
            "score": post_score(pid),
        })

    nsfw_buckets = defaultdict(list)
    for pid, p in posts_raw.items():
        levels = list(set(p.get("nsfwLevels", [])))
        s = post_score(pid)
        level = "X" if "X" in levels else "Mature" if "Mature" in levels else "None"
        nsfw_buckets[level].append(s)

    nsfw_breakdown = [
        {"level": lvl, "avg_score": round(sum(scores) / len(scores), 1), "count": len(scores)}
        for lvl in ["None", "Mature", "X"]
        if (scores := nsfw_buckets.get(lvl, []))
    ]

    img_buckets = {"1": [], "2-5": [], "6-10": [], "11+": []}
    for pid, p in posts_raw.items():
        n = p.get("imageCount", 0)
        s = post_score(pid)
        if n == 1: img_buckets["1"].append(s)
        elif n <= 5: img_buckets["2-5"].append(s)
        elif n <= 10: img_buckets["6-10"].append(s)
        else: img_buckets["11+"].append(s)

    image_buckets = [
        {"label": label, "avg_score": round(sum(scores) / len(scores), 1), "count": len(scores)}
        for label, scores in img_buckets.items() if scores
    ]

    recent_sorted = sorted(posts_raw.items(), key=lambda x: x[1].get("date", ""), reverse=True)[:5]
    recent_posts = []
    for pid, p in recent_sorted:
        chars, _, _ = get_post_labels(pid)
        title = (meta.get(pid) or {}).get("title") or p.get("title") or None
        recent_posts.append({
            "postId": pid, "title": title, "date": p.get("date", ""),
            "characters": chars, "hearts": p.get("hearts", 0),
            "likes": p.get("likes", 0), "comments": p.get("comments", 0),
        })

    return jsonify({
        "totals": {
            "hearts": total_hearts, "likes": total_likes, "comments": total_comments,
            "posts": total_posts, "images": total_images,
        },
        "delta": delta,
        "top_characters": top_characters,
        "top_tags": top_tags,
        "top_themes": top_themes,
        "best_posts": best_posts,
        "nsfw_breakdown": nsfw_breakdown,
        "image_buckets": image_buckets,
        "recent_posts": recent_posts,
    })


@app.route("/api/config", methods=["GET"])
def api_config_get():
    cfg = load_config()
    return jsonify({
        "username": cfg.get("username", ""),
        "has_api_key": bool(cfg.get("api_key", "").strip()),
    })


@app.route("/api/config", methods=["POST"])
def api_config_post():
    data = request.json or {}
    cfg = load_config()
    if "username" in data:
        cfg["username"] = data["username"].strip()
    if "api_key" in data and data["api_key"].strip():
        cfg["api_key"] = data["api_key"].strip()
    try:
        save_config(cfg)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@app.route("/api/test-connection")
def api_test_connection():
    cfg = load_config()
    api_key = cfg.get("api_key", "").strip()
    username = cfg.get("username", "").strip()

    if not api_key or not username:
        return jsonify({"ok": False, "message": "No credentials configured — check Settings"})

    try:
        url = f"https://civitai.com/api/v1/images?username={username}&limit=1&sort=Newest"
        r = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=10)
        if r.status_code == 401:
            return jsonify({"ok": False, "message": "Invalid API key (401 Unauthorized)"})
        if r.status_code == 404:
            return jsonify({"ok": False, "message": f"Username '{username}' not found (404)"})
        r.raise_for_status()
        data = r.json()
        count = data.get("metadata", {}).get("totalItems", "?")
        return jsonify({"ok": True, "message": f"Connected! {count} images found for @{username}"})
    except requests.exceptions.Timeout:
        return jsonify({"ok": False, "message": "Request timed out — CivitAI may be slow"})
    except requests.exceptions.ConnectionError:
        return jsonify({"ok": False, "message": "Could not reach civitai.com — check network"})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)})


if __name__ == "__main__":
    print("📊 CivitAI Analytics running at http://localhost:5757")
    print("   Open Settings tab to configure your API key.")
    print("   Press Ctrl+C to stop.")
    app.run(host="0.0.0.0", port=5757, debug=False)
