#!/usr/bin/env python3
"""
SQLite database module for CivitAI Analytics.
Replaces flat JSON storage (civitai_state.json + civitai_posts.json).
"""

import json
import os
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "data", "civitai.db")
STATE_FILE = os.path.join(BASE, "data", "civitai_state.json")
POSTS_META_FILE = os.path.join(BASE, "data", "civitai_posts.json")

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    total_posts INTEGER DEFAULT 0,
    total_images INTEGER DEFAULT 0,
    total_hearts INTEGER DEFAULT 0,
    total_likes INTEGER DEFAULT 0,
    total_comments INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS post_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER REFERENCES snapshots(id),
    post_id TEXT NOT NULL,
    post_date TEXT,
    hearts INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    laughs INTEGER DEFAULT 0,
    cries INTEGER DEFAULT 0,
    image_count INTEGER DEFAULT 0,
    nsfw_levels TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS post_meta (
    post_id TEXT PRIMARY KEY,
    title TEXT DEFAULT '',
    characters TEXT DEFAULT '[]',
    tags TEXT DEFAULT '[]',
    themes TEXT DEFAULT '[]',
    notes TEXT DEFAULT '',
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_post_stats_post_id ON post_stats(post_id);
CREATE INDEX IF NOT EXISTS idx_post_stats_snapshot_id ON post_stats(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_timestamp ON snapshots(timestamp);
"""


def get_conn():
    """Return sqlite3 connection with row_factory = sqlite3.Row."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if not exist; migrate from JSON if DB is empty."""
    conn = get_conn()
    conn.executescript(SCHEMA)
    conn.commit()

    # Check if DB is empty (no snapshots yet)
    row = conn.execute("SELECT COUNT(*) as cnt FROM snapshots").fetchone()
    if row["cnt"] == 0:
        # Try migrating from JSON files if they exist
        if os.path.exists(STATE_FILE) or os.path.exists(POSTS_META_FILE):
            migrate_from_json(STATE_FILE, POSTS_META_FILE, conn=conn)

    conn.close()


def migrate_from_json(state_path, posts_path, conn=None):
    """Import existing JSON data on first run. Renames originals to .bak after migration."""
    close_after = False
    if conn is None:
        conn = get_conn()
        close_after = True

    migrated_state = False
    migrated_meta = False

    # ── Migrate civitai_state.json ──────────────────────────────────────────
    if os.path.exists(state_path):
        try:
            with open(state_path) as f:
                state = json.load(f)

            history = state.get("history", [])
            posts_raw = state.get("posts", {})

            # Insert each history snapshot
            for snap in history:
                ts = snap.get("timestamp", "")
                cur = conn.execute(
                    "INSERT INTO snapshots (timestamp, total_posts, total_images, total_hearts, total_likes, total_comments) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        ts,
                        snap.get("totalPosts", 0),
                        snap.get("totalImages", 0),
                        snap.get("totalHearts", 0),
                        snap.get("totalLikes", 0),
                        snap.get("totalComments", 0),
                    ),
                )
                snap_id = cur.lastrowid

                # Pull per-post data from topPosts if available (limited to top 5)
                for tp in snap.get("topPosts", []):
                    pid = str(tp.get("postId", ""))
                    if not pid:
                        continue
                    # Try to get full post data from posts_raw if available
                    p = posts_raw.get(pid, tp)
                    conn.execute(
                        "INSERT INTO post_stats (snapshot_id, post_id, post_date, hearts, likes, comments, "
                        "laughs, cries, image_count, nsfw_levels) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            snap_id,
                            pid,
                            p.get("date", ""),
                            tp.get("hearts", p.get("hearts", 0)),
                            tp.get("likes", p.get("likes", 0)),
                            p.get("comments", 0),
                            p.get("laughs", 0),
                            p.get("cries", 0),
                            tp.get("imageCount", p.get("imageCount", 0)),
                            json.dumps(tp.get("nsfwLevels", p.get("nsfwLevels", []))),
                        ),
                    )

            # If no history, create a single snapshot from current posts
            if not history and posts_raw:
                total_hearts = sum(p.get("hearts", 0) for p in posts_raw.values())
                total_likes = sum(p.get("likes", 0) for p in posts_raw.values())
                total_comments = sum(p.get("comments", 0) for p in posts_raw.values())
                total_images = sum(p.get("imageCount", 0) for p in posts_raw.values())
                ts = state.get("lastChecked") or datetime.now(timezone.utc).isoformat()
                cur = conn.execute(
                    "INSERT INTO snapshots (timestamp, total_posts, total_images, total_hearts, total_likes, total_comments) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (ts, len(posts_raw), total_images, total_hearts, total_likes, total_comments),
                )
                snap_id = cur.lastrowid
                for pid, p in posts_raw.items():
                    conn.execute(
                        "INSERT INTO post_stats (snapshot_id, post_id, post_date, hearts, likes, comments, "
                        "laughs, cries, image_count, nsfw_levels) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            snap_id,
                            pid,
                            p.get("date", ""),
                            p.get("hearts", 0),
                            p.get("likes", 0),
                            p.get("comments", 0),
                            p.get("laughs", 0),
                            p.get("cries", 0),
                            p.get("imageCount", 0),
                            json.dumps(p.get("nsfwLevels", [])),
                        ),
                    )

            conn.commit()
            migrated_state = True
            os.rename(state_path, state_path + ".bak")
            print(f"[db] Migrated {state_path} → .bak ({len(history)} snapshots, {len(posts_raw)} posts)")
        except Exception as e:
            print(f"[db] Warning: could not migrate state JSON: {e}")

    # ── Migrate civitai_posts.json ──────────────────────────────────────────
    if os.path.exists(posts_path):
        try:
            with open(posts_path) as f:
                data = json.load(f)
            posts_meta = data.get("posts", {})
            now = datetime.now(timezone.utc).isoformat()
            for pid, m in posts_meta.items():
                themes = m.get("themes", [])
                if not themes and m.get("theme"):
                    themes = [m["theme"]]
                conn.execute(
                    "INSERT OR REPLACE INTO post_meta (post_id, title, characters, tags, themes, notes, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        pid,
                        m.get("title", ""),
                        json.dumps(m.get("characters", [])),
                        json.dumps(m.get("tags", [])),
                        json.dumps(themes),
                        m.get("notes", ""),
                        now,
                    ),
                )
            conn.commit()
            migrated_meta = True
            os.rename(posts_path, posts_path + ".bak")
            print(f"[db] Migrated {posts_path} → .bak ({len(posts_meta)} post meta entries)")
        except Exception as e:
            print(f"[db] Warning: could not migrate posts JSON: {e}")

    if close_after:
        conn.close()

    return migrated_state or migrated_meta


def get_latest_post_stats():
    """Return dict of {post_id: {hearts, likes, comments, laughs, cries, image_count, ...}}
    from the most recent snapshot."""
    conn = get_conn()
    try:
        snap = conn.execute(
            "SELECT id FROM snapshots ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if not snap:
            return {}
        rows = conn.execute(
            "SELECT * FROM post_stats WHERE snapshot_id = ?", (snap["id"],)
        ).fetchall()
        result = {}
        for r in rows:
            result[r["post_id"]] = {
                "hearts": r["hearts"],
                "likes": r["likes"],
                "comments": r["comments"],
                "laughs": r["laughs"],
                "cries": r["cries"],
                "image_count": r["image_count"],
                "post_date": r["post_date"],
                "nsfw_levels": json.loads(r["nsfw_levels"] or "[]"),
            }
        return result
    finally:
        conn.close()


def save_snapshot(posts_dict, timestamp):
    """Insert snapshot + post_stats rows. Applies zero-stat guard against latest snapshot."""
    conn = get_conn()
    try:
        # Get current latest stats for zero-stat guard
        latest = get_latest_post_stats()

        # Apply zero-stat guard: never overwrite known good stats with zeros
        guarded = {}
        for pid, post in posts_dict.items():
            p = dict(post)
            old = latest.get(pid)
            if old:
                old_total = old.get("hearts", 0) + old.get("likes", 0)
                new_total = p.get("hearts", 0) + p.get("likes", 0)
                if new_total == 0 and old_total > 0:
                    p["hearts"] = old["hearts"]
                    p["likes"] = old["likes"]
                    p["comments"] = old["comments"]
                    p["laughs"] = old["laughs"]
                    p["cries"] = old["cries"]
            guarded[pid] = p

        total_hearts = sum(p.get("hearts", 0) for p in guarded.values())
        total_likes = sum(p.get("likes", 0) for p in guarded.values())
        total_comments = sum(p.get("comments", 0) for p in guarded.values())
        total_images = sum(p.get("imageCount", p.get("image_count", 0)) for p in guarded.values())
        total_posts = len(guarded)

        cur = conn.execute(
            "INSERT INTO snapshots (timestamp, total_posts, total_images, total_hearts, total_likes, total_comments) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (timestamp, total_posts, total_images, total_hearts, total_likes, total_comments),
        )
        snap_id = cur.lastrowid

        for pid, p in guarded.items():
            nsfw = p.get("nsfwLevels", p.get("nsfw_levels", []))
            if isinstance(nsfw, set):
                nsfw = sorted(nsfw)
            conn.execute(
                "INSERT INTO post_stats (snapshot_id, post_id, post_date, hearts, likes, comments, "
                "laughs, cries, image_count, nsfw_levels) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    snap_id,
                    pid,
                    p.get("date", p.get("post_date", "")),
                    p.get("hearts", 0),
                    p.get("likes", 0),
                    p.get("comments", 0),
                    p.get("laughs", 0),
                    p.get("cries", 0),
                    p.get("imageCount", p.get("image_count", 0)),
                    json.dumps(nsfw),
                ),
            )

        conn.commit()
        return snap_id
    finally:
        conn.close()


def load_post_meta():
    """Return dict of {post_id: {title, characters, tags, themes, notes}}."""
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM post_meta").fetchall()
        result = {}
        for r in rows:
            result[r["post_id"]] = {
                "title": r["title"] or "",
                "characters": json.loads(r["characters"] or "[]"),
                "tags": json.loads(r["tags"] or "[]"),
                "themes": json.loads(r["themes"] or "[]"),
                "notes": r["notes"] or "",
            }
        return result
    finally:
        conn.close()


def save_post_meta(post_id, data):
    """Upsert into post_meta."""
    conn = get_conn()
    try:
        now = datetime.now(timezone.utc).isoformat()
        themes = data.get("themes", [])
        if not themes and data.get("theme"):
            themes = [data["theme"]]
        conn.execute(
            "INSERT OR REPLACE INTO post_meta (post_id, title, characters, tags, themes, notes, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                post_id,
                data.get("title", ""),
                json.dumps(data.get("characters", [])),
                json.dumps(data.get("tags", [])),
                json.dumps(themes),
                data.get("notes", ""),
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_all_post_meta():
    """Return all post_meta rows as dict."""
    return load_post_meta()


def get_known_values():
    """Scan post_meta, return {characters: [...], tags: [...], themes: [...]}."""
    meta = load_post_meta()
    characters, tags, themes = set(), set(), set()
    for m in meta.values():
        for c in m.get("characters", []):
            if c:
                characters.add(c)
        for t in m.get("tags", []):
            if t:
                tags.add(t)
        for th in m.get("themes", []):
            if th:
                themes.add(th)
    return {
        "characters": sorted(characters),
        "tags": sorted(tags),
        "themes": sorted(themes),
    }


def _score(hearts, likes, laughs=0):
    return hearts * 2 + likes + laughs * 0.5


def get_dashboard_data():
    """Return all data needed for the dashboard."""
    conn = get_conn()
    try:
        # Get latest snapshot
        latest_snap = conn.execute(
            "SELECT * FROM snapshots ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()

        if not latest_snap:
            return {
                "totals": {"hearts": 0, "likes": 0, "comments": 0, "posts": 0, "images": 0},
                "delta": None,
                "top_characters": [],
                "top_tags": [],
                "top_themes": [],
                "best_posts": [],
                "nsfw_breakdown": [],
                "image_buckets": [],
                "recent_posts": [],
            }

        totals = {
            "hearts": latest_snap["total_hearts"],
            "likes": latest_snap["total_likes"],
            "comments": latest_snap["total_comments"],
            "posts": latest_snap["total_posts"],
            "images": latest_snap["total_images"],
        }

        # Delta: compare last 2 snapshots
        delta = None
        prev_snap = conn.execute(
            "SELECT * FROM snapshots ORDER BY timestamp DESC LIMIT 1 OFFSET 1"
        ).fetchone()
        if prev_snap:
            delta = {
                "hearts": latest_snap["total_hearts"] - prev_snap["total_hearts"],
                "likes": latest_snap["total_likes"] - prev_snap["total_likes"],
                "comments": latest_snap["total_comments"] - prev_snap["total_comments"],
            }

        # Get latest post stats
        post_rows = conn.execute(
            "SELECT * FROM post_stats WHERE snapshot_id = ?", (latest_snap["id"],)
        ).fetchall()

        # Get all post meta
        meta = load_post_meta()

        char_scores = defaultdict(int)
        tag_scores = defaultdict(int)
        theme_scores = defaultdict(int)
        nsfw_buckets = defaultdict(list)
        img_buckets = {"1": [], "2-5": [], "6-10": [], "11+": []}
        all_posts = []

        for r in post_rows:
            pid = r["post_id"]
            hearts = r["hearts"]
            likes = r["likes"]
            laughs = r["laughs"]
            image_count = r["image_count"]
            s = _score(hearts, likes, laughs)
            nsfw_levels = json.loads(r["nsfw_levels"] or "[]")

            m = meta.get(pid, {})
            chars = m.get("characters", [])
            tags = m.get("tags", [])
            themes_list = m.get("themes", [])

            if chars or tags or themes_list:
                for c in chars:
                    if c:
                        char_scores[c] += s
                for t in tags:
                    if t:
                        tag_scores[t] += s
                for th in themes_list:
                    if th:
                        theme_scores[th] += s

            # NSFW buckets
            level = "X" if "X" in nsfw_levels else "Mature" if "Mature" in nsfw_levels else "None"
            nsfw_buckets[level].append(s)

            # Image buckets
            if image_count == 1:
                img_buckets["1"].append(s)
            elif image_count <= 5:
                img_buckets["2-5"].append(s)
            elif image_count <= 10:
                img_buckets["6-10"].append(s)
            else:
                img_buckets["11+"].append(s)

            all_posts.append({
                "postId": pid,
                "date": r["post_date"] or "",
                "hearts": hearts,
                "likes": likes,
                "comments": r["comments"],
                "imageCount": image_count,
                "nsfwLevels": nsfw_levels,
                "score": int(s),
                "title": m.get("title") or None,
                "characters": chars,
                "tags": tags,
                "themes": themes_list,
            })

        top_characters = [{"label": k, "value": int(v)} for k, v in sorted(char_scores.items(), key=lambda x: -x[1])[:8]]
        top_tags = [{"label": k, "value": int(v)} for k, v in sorted(tag_scores.items(), key=lambda x: -x[1])[:8]]
        top_themes = [{"label": k, "value": int(v)} for k, v in sorted(theme_scores.items(), key=lambda x: -x[1])[:6]]

        # Best posts top 10
        best_posts = sorted(all_posts, key=lambda p: p["score"], reverse=True)[:10]

        nsfw_breakdown = [
            {"level": lvl, "avg_score": round(sum(scores) / len(scores), 1), "count": len(scores)}
            for lvl in ["None", "Mature", "X"]
            if (scores := nsfw_buckets.get(lvl, []))
        ]

        image_buckets = [
            {"label": label, "avg_score": round(sum(scores) / len(scores), 1), "count": len(scores)}
            for label, scores in img_buckets.items() if scores
        ]

        recent_posts = sorted(all_posts, key=lambda p: p["date"], reverse=True)[:5]

        return {
            "totals": totals,
            "delta": delta,
            "top_characters": top_characters,
            "top_tags": top_tags,
            "top_themes": top_themes,
            "best_posts": best_posts,
            "nsfw_breakdown": nsfw_breakdown,
            "image_buckets": image_buckets,
            "recent_posts": recent_posts,
        }
    finally:
        conn.close()


def get_history(limit=90):
    """Return last N snapshots as list of dicts."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM snapshots ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        result = []
        for r in rows:
            result.append({
                "id": r["id"],
                "timestamp": r["timestamp"],
                "totalPosts": r["total_posts"],
                "totalImages": r["total_images"],
                "totalHearts": r["total_hearts"],
                "totalLikes": r["total_likes"],
                "totalComments": r["total_comments"],
            })
        return list(reversed(result))  # chronological order
    finally:
        conn.close()
