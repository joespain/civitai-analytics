#!/usr/bin/env python3
"""
CivitAI Engagement Tracker
Tracks reactions per post over time, detects new comments, and surfaces engagement trends.
Run from a scheduler/cron or on-demand.

Usage:
    python tracker.py            # fetch + print summary
    python tracker.py --analyze  # also show engagement analysis by tag/character/theme
"""

import json
import os
import sys
from datetime import datetime, timezone

import requests

BASE = os.path.dirname(__file__)
STATE_FILE = os.path.join(BASE, "data", "civitai_state.json")
POSTS_META_FILE = os.path.join(BASE, "data", "civitai_posts.json")
CONFIG_FILE = os.path.join(BASE, "data", "config.json")
LIMIT = 100  # images per page


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {"api_key": "", "username": ""}


def fetch_images(api_key, username, stats_only=False):
    """Fetch images. stats_only=True fetches only first page (live stats).
    Full paginated fetch is used for post discovery; stats are unreliable past page 1."""
    all_items = []
    url = f"https://civitai.com/api/v1/images?username={username}&limit={LIMIT}&sort=Newest&nsfw=true"
    page = 0
    while url:
        resp = requests.get(url, headers={"Authorization": f"Bearer {api_key}"}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        items = data["items"]
        all_items.extend(items)
        page += 1
        # Only page 1 has reliable stats; stop there for stat tracking.
        # Continue paginating for post discovery (stats_only=False), cap at 20 pages.
        if stats_only or page >= 20:
            break
        url = data.get("metadata", {}).get("nextPage")
    return all_items, page == 1 or stats_only


def aggregate_posts(items):
    posts = {}
    for item in items:
        pid = str(item["postId"])
        if pid not in posts:
            posts[pid] = {
                "postId": pid,
                "date": item["createdAt"][:10],
                "imageCount": 0,
                "hearts": 0,
                "likes": 0,
                "laughs": 0,
                "cries": 0,
                "comments": 0,
                "nsfwLevels": set(),
            }
        s = item["stats"]
        posts[pid]["imageCount"] += 1
        posts[pid]["hearts"] += s.get("heartCount", 0)
        posts[pid]["likes"] += s.get("likeCount", 0)
        posts[pid]["laughs"] += s.get("laughCount", 0)
        posts[pid]["cries"] += s.get("cryCount", 0)
        posts[pid]["comments"] += s.get("commentCount", 0)
        posts[pid]["nsfwLevels"].add(item.get("nsfwLevel", "None"))

    for p in posts.values():
        p["nsfwLevels"] = sorted(p["nsfwLevels"])
    return posts


def load_post_meta():
    if os.path.exists(POSTS_META_FILE):
        with open(POSTS_META_FILE) as f:
            data = json.load(f)
            return data.get("posts", {})
    return {}


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"posts": {}, "history": [], "lastChecked": None}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def score(post):
    """Engagement score: hearts weighted higher than likes."""
    return post["hearts"] * 2 + post["likes"] + post["laughs"] * 0.5


def main(notify=False):
    config = load_config()
    api_key = config.get("api_key", "")
    username = config.get("username", "")

    if not api_key or not username:
        print(
            "[civitai_tracker] No API key or username configured. "
            "Copy config.example.json → data/config.json and fill in your credentials.",
            file=sys.stderr,
        )
        return None

    now = datetime.now(timezone.utc).isoformat()
    state = load_state()
    old_posts = state.get("posts", {})
    post_meta = load_post_meta()

    try:
        # Fetch first page only for live stats (subsequent pages return 0 stats from CivitAI)
        stat_items, _ = fetch_images(api_key, username, stats_only=True)
        # Also discover all posts via full pagination (for post count / history)
        all_items, _ = fetch_images(api_key, username, stats_only=False)
    except Exception as e:
        print(f"[civitai_tracker] Fetch failed: {e}", file=sys.stderr)
        return None

    # Aggregate: use stat_items for reaction counts, all_items for post discovery
    stat_posts = aggregate_posts(stat_items)
    all_posts_discovered = aggregate_posts(all_items)

    # Merge: start with all discovered posts, overlay live stats from page 1
    new_posts = all_posts_discovered
    for pid, stat_post in stat_posts.items():
        if pid in new_posts:
            new_posts[pid]["hearts"] = stat_post["hearts"]
            new_posts[pid]["likes"] = stat_post["likes"]
            new_posts[pid]["comments"] = stat_post["comments"]
            new_posts[pid]["laughs"] = stat_post["laughs"]
            new_posts[pid]["cries"] = stat_post["cries"]

    # For ALL posts: never overwrite good stats with zeros
    # (CivitAI API caches periodically and may return 0 for older pages)
    for pid, post in new_posts.items():
        old = old_posts.get(pid)
        if old:
            old_total = old.get("hearts", 0) + old.get("likes", 0)
            new_total = post.get("hearts", 0) + post.get("likes", 0)
            if new_total == 0 and old_total > 0:
                post["hearts"] = old.get("hearts", 0)
                post["likes"] = old.get("likes", 0)
                post["comments"] = old.get("comments", 0)
                post["laughs"] = old.get("laughs", 0)
                post["cries"] = old.get("cries", 0)

    alerts = []
    new_comments = []
    reaction_spikes = []
    new_post_ids = []

    for pid, post in new_posts.items():
        old = old_posts.get(pid)
        if old is None:
            new_post_ids.append(pid)
            continue

        comment_delta = post["comments"] - old.get("comments", 0)
        if comment_delta > 0:
            new_comments.append({
                "postId": pid,
                "date": post["date"],
                "newComments": comment_delta,
                "totalComments": post["comments"],
            })

        # Reaction spike: >10 new hearts or likes since last check
        heart_delta = post["hearts"] - old.get("hearts", 0)
        like_delta = post["likes"] - old.get("likes", 0)
        if heart_delta + like_delta >= 10:
            reaction_spikes.append({
                "postId": pid,
                "date": post["date"],
                "heartDelta": heart_delta,
                "likeDelta": like_delta,
            })

    # Merge post metadata into posts
    for pid, post in new_posts.items():
        meta = post_meta.get(pid, {})
        post["title"] = meta.get("title", "")
        post["characters"] = meta.get("characters", [])
        post["tags"] = meta.get("tags", [])
        post["theme"] = meta.get("theme", "")
        post["notes"] = meta.get("notes", "")

    # Build daily snapshot entry
    snapshot = {
        "timestamp": now,
        "totalPosts": len(new_posts),
        "totalImages": sum(p["imageCount"] for p in new_posts.values()),
        "totalHearts": sum(p["hearts"] for p in new_posts.values()),
        "totalLikes": sum(p["likes"] for p in new_posts.values()),
        "totalComments": sum(p["comments"] for p in new_posts.values()),
        "topPosts": sorted(
            [
                {
                    "postId": k,
                    "date": v["date"],
                    "score": score(v),
                    "hearts": v["hearts"],
                    "likes": v["likes"],
                    "nsfwLevels": v["nsfwLevels"],
                    "imageCount": v["imageCount"],
                    "title": v.get("title", ""),
                    "characters": v.get("characters", []),
                    "tags": v.get("tags", []),
                    "theme": v.get("theme", ""),
                }
                for k, v in new_posts.items()
            ],
            key=lambda x: x["score"],
            reverse=True,
        )[:5],
    }

    # Append to history (keep last 90 snapshots)
    history = state.get("history", [])
    history.append(snapshot)
    if len(history) > 90:
        history = history[-90:]

    state["posts"] = new_posts
    state["history"] = history
    state["lastChecked"] = now
    save_state(state)

    report = {
        "snapshot": snapshot,
        "alerts": {
            "newPosts": new_post_ids,
            "newComments": new_comments,
            "reactionSpikes": reaction_spikes,
        },
        "hasAlerts": bool(new_post_ids or new_comments or reaction_spikes),
    }

    return report


def analyze(state):
    """Cross-reference engagement with post metadata and surface patterns."""
    posts = state.get("posts", {})
    labeled = [p for p in posts.values() if p.get("tags") or p.get("characters") or p.get("theme")]
    if not labeled:
        print("\n[No labeled posts yet — use the Settings tab to configure, then label posts in the Posts tab]")
        return

    print(f"\n=== Engagement Analysis ({len(labeled)} labeled posts) ===")

    char_scores = {}
    for p in labeled:
        s = score(p)
        for c in p.get("characters", []):
            char_scores.setdefault(c, []).append(s)
    if char_scores:
        print("\nBy character (avg engagement score):")
        for c, scores in sorted(char_scores.items(), key=lambda x: sum(x[1]) / len(x[1]), reverse=True):
            print(f"  {c}: avg {sum(scores)/len(scores):.0f} over {len(scores)} posts")

    tag_scores = {}
    for p in labeled:
        s = score(p)
        for t in p.get("tags", []):
            tag_scores.setdefault(t, []).append(s)
    if tag_scores:
        print("\nBy tag (avg engagement score):")
        for t, scores in sorted(tag_scores.items(), key=lambda x: sum(x[1]) / len(x[1]), reverse=True)[:10]:
            print(f"  #{t}: avg {sum(scores)/len(scores):.0f} over {len(scores)} posts")

    theme_scores = {}
    for p in labeled:
        t = p.get("theme", "")
        if t:
            theme_scores.setdefault(t, []).append(score(p))
    if theme_scores:
        print("\nBy theme:")
        for t, scores in sorted(theme_scores.items(), key=lambda x: sum(x[1]) / len(x[1]), reverse=True):
            print(f"  {t}: avg {sum(scores)/len(scores):.0f} over {len(scores)} posts")

    level_scores = {}
    for p in posts.values():
        for lvl in p.get("nsfwLevels", []):
            level_scores.setdefault(lvl, []).append(score(p))
    if level_scores:
        print("\nBy NSFW level (all posts):")
        for lvl, scores in sorted(level_scores.items(), key=lambda x: sum(x[1]) / len(x[1]), reverse=True):
            print(f"  {lvl}: avg {sum(scores)/len(scores):.0f} over {len(scores)} posts")

    print("\nImage count vs avg score:")
    buckets = {"1": [], "2-5": [], "6-10": [], "11+": []}
    for p in posts.values():
        n = p["imageCount"]
        s = score(p)
        if n == 1:
            buckets["1"].append(s)
        elif n <= 5:
            buckets["2-5"].append(s)
        elif n <= 10:
            buckets["6-10"].append(s)
        else:
            buckets["11+"].append(s)
    for bucket, scores in buckets.items():
        if scores:
            print(f"  {bucket} images: avg {sum(scores)/len(scores):.0f} ({len(scores)} posts)")


def print_summary(report):
    if report is None:
        print("Failed to fetch data. Check data/config.json.")
        return

    s = report["snapshot"]
    print(f"\n=== CivitAI Snapshot — {s['timestamp'][:10]} ===")
    print(f"Posts tracked: {s['totalPosts']} | Images: {s['totalImages']}")
    print(f"Total hearts: {s['totalHearts']} | Likes: {s['totalLikes']} | Comments: {s['totalComments']}")
    print("\nTop 5 posts by engagement:")
    for p in s["topPosts"]:
        levels = "/".join(p["nsfwLevels"])
        label = p.get("title") or f"Post {p['postId']}"
        chars = ", ".join(p.get("characters", [])) or "—"
        print(
            f"  {label} ({p['date']}) | {p['imageCount']} imgs | "
            f"❤️{p['hearts']} 👍{p['likes']} | Score: {p['score']:.0f} | [{levels}] | {chars}"
        )

    alerts = report["alerts"]
    if alerts["newPosts"]:
        print(f"\n🆕 New posts detected: {alerts['newPosts']}")
    if alerts["newComments"]:
        print(f"\n💬 New comments!")
        for c in alerts["newComments"]:
            print(f"  Post {c['postId']} ({c['date']}): +{c['newComments']} (total {c['totalComments']})")
    if alerts["reactionSpikes"]:
        print(f"\n🔥 Reaction spikes!")
        for r in alerts["reactionSpikes"]:
            print(f"  Post {r['postId']} ({r['date']}): +{r['heartDelta']}❤️ +{r['likeDelta']}👍")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CivitAI engagement tracker")
    parser.add_argument("--analyze", action="store_true", help="Show engagement analysis by tag/character/theme")
    args = parser.parse_args()

    report = main()
    print_summary(report)

    if args.analyze:
        state = load_state()
        analyze(state)
