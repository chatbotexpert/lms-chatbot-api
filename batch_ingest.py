"""
Batch ingest all published posts from wp_posts.json into the FastAPI vector database.
Run: venv\Scripts\python.exe batch_ingest.py
"""
import sys
import json
import re
import requests
import time

# Fix Windows console encoding
sys.stdout.reconfigure(encoding="utf-8")

# ── Config ────────────────────────────────────────────────────────────────────
JSON_FILE   = "wp_posts.json"
API_URL     = "https://lms-chatbot-api.vercel.app/api/ingest"
API_KEY     = "test_key_123"
DELAY_SEC   = 1.5   # pause between requests to avoid rate limits
# ─────────────────────────────────────────────────────────────────────────────

def extract_image_urls(html: str) -> list:
    return re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)

def clean_text(html: str) -> str:
    # Strip HTML tags and shortcodes
    text = re.sub(r'\[embed\].*?\[/embed\]', '', html, flags=re.DOTALL)
    text = re.sub(r'\[[^\]]+\]', '', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'\r\n|\r', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def load_posts(path: str) -> list:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    # Find the table entry with wp_posts data
    for entry in raw:
        if entry.get("type") == "table" and entry.get("name") == "wp_posts":
            return entry.get("data", [])
    return []

def ingest_post(post: dict) -> bool:
    post_id      = post["ID"]
    post_status  = post.get("post_status", "")
    post_type    = post.get("post_type", "")
    post_content = post.get("post_content", "")
    post_title   = post.get("post_title", "")

    if post_status != "publish" or post_type != "post":
        return False
    if not post_content.strip():
        return False

    content    = f"{post_title}\n\n{clean_text(post_content)}"
    image_urls = extract_image_urls(post_content)

    payload = {
        "lesson_id":  str(post_id),
        "content":    content,
        "image_urls": image_urls
    }

    try:
        resp = requests.post(
            API_URL,
            json=payload,
            headers={"X-API-Key": API_KEY, "Content-Type": "application/json"},
            timeout=60
        )
        if resp.status_code == 200:
            data = resp.json()
            print(f"  ✅ [{post_id}] {post_title[:60]} → {data.get('chunks_created', '?')} chunks")
            return True
        else:
            print(f"  ❌ [{post_id}] HTTP {resp.status_code}: {resp.text[:120]}")
            return False
    except Exception as e:
        print(f"  ❌ [{post_id}] Error: {e}")
        return False

def main():
    posts = load_posts(JSON_FILE)
    published = [p for p in posts if p.get("post_status") == "publish" and p.get("post_type") == "post"]

    print(f"Found {len(published)} published posts to ingest.\n")

    success = 0
    failed  = 0

    for i, post in enumerate(published, 1):
        print(f"[{i}/{len(published)}] Ingesting post {post['ID']}...")
        ok = ingest_post(post)
        if ok:
            success += 1
        else:
            failed += 1
        time.sleep(DELAY_SEC)

    print(f"\n─── Done ───────────────────────────────")
    print(f"  ✅ Success: {success}")
    print(f"  ❌ Failed:  {failed}")
    print(f"  Total:     {len(published)}")

if __name__ == "__main__":
    main()
