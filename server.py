#!/usr/bin/env python3
"""CTI Radar: CTI blogs and security news feeds in one dashboard.

Standard library only. Run:  python3 server.py  ->  http://localhost:8080
"""
import argparse
import hashlib
import html
import json
import re
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
CACHE_FILE = BASE / "cache.json"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 CTI-Radar/1.0"
)

state_lock = threading.Lock()
state = {"items": {}, "feeds": {}, "last_refresh": None, "next_refresh": None, "refreshing": False}
refresh_now = threading.Event()


# ---------- parsing ----------

def local(tag):
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def child_text(el, *names):
    for c in el:
        if local(c.tag) in names and (c.text or "").strip():
            return c.text.strip()
    return ""


def parse_date(value):
    if not value:
        return None
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clean_summary(raw, limit=260):
    text = re.sub(r"<[^>]+>", " ", html.unescape(raw or ""))
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    text = re.sub(r"The post .* appeared first on .*$", "", text).strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def atom_link(entry):
    fallback = ""
    for c in entry:
        if local(c.tag) == "link":
            href = c.get("href") or (c.text or "").strip()
            if c.get("rel", "alternate") == "alternate" and href:
                return href
            fallback = fallback or href
    return fallback


def parse_feed(data):
    """Return a list of dicts (title, link, published, summary) from RSS/RDF/Atom bytes."""
    data = data.lstrip(b"\xef\xbb\xbf \t\r\n")
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return parse_feed_loose(data.decode("utf-8", "replace"))
    out = []
    for el in root.iter():
        name = local(el.tag)
        if name == "item":
            out.append({
                "title": child_text(el, "title"),
                "link": child_text(el, "link") or child_text(el, "guid"),
                "published": child_text(el, "pubdate", "date", "published", "updated"),
                "summary": child_text(el, "description", "summary", "encoded"),
            })
        elif name == "entry":
            out.append({
                "title": child_text(el, "title"),
                "link": atom_link(el),
                "published": child_text(el, "published", "updated", "issued"),
                "summary": child_text(el, "summary", "content"),
            })
    return out


def parse_feed_loose(text):
    """Regex fallback for feeds that are not well-formed XML."""
    def grab(block, tag):
        m = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}>", block, re.S | re.I)
        if not m:
            return ""
        return re.sub(r"^<!\[CDATA\[(.*)\]\]>$", r"\1", m.group(1).strip(), flags=re.S)

    out = []
    for block in re.findall(r"<(?:item|entry)\b.*?</(?:item|entry)>", text, re.S | re.I):
        link = grab(block, "link")
        if not link:
            m = re.search(r"<link\b[^>]*href=\"([^\"]+)\"", block, re.I)
            link = m.group(1) if m else ""
        out.append({
            "title": grab(block, "title"),
            "link": link,
            "published": grab(block, "pubDate") or grab(block, "published") or grab(block, "updated") or grab(block, "dc:date"),
            "summary": grab(block, "description") or grab(block, "summary"),
        })
    return out


# ---------- fetching ----------

def fetch_feed(feed, prev, max_items):
    url = feed["url"]
    info = {"name": feed["name"], "url": url, "category": feed.get("category", "cti"),
            "ok": False, "error": None, "count": 0, "checked": now_iso(),
            "etag": prev.get("etag"), "modified": prev.get("modified")}
    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"}
    if info["etag"]:
        headers["If-None-Match"] = info["etag"]
    if info["modified"]:
        headers["If-Modified-Since"] = info["modified"]
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as r:
            body = r.read()
            info["etag"] = r.headers.get("ETag")
            info["modified"] = r.headers.get("Last-Modified")
    except urllib.error.HTTPError as e:
        if e.code == 304:  # unchanged since last fetch
            info.update(ok=True, count=prev.get("count", 0))
            return info, None
        info["error"] = f"HTTP {e.code}"
        return info, None
    except Exception as e:  # network, TLS, timeout
        info["error"] = type(e).__name__ + (f": {e.reason}" if hasattr(e, "reason") else "")
        return info, None

    items = []
    for raw in parse_feed(body)[:max_items]:
        link = html.unescape(raw["link"].strip())
        title = clean_summary(raw["title"], 400)
        if not link or not title:
            continue
        dt = parse_date(raw["published"])
        items.append({
            "id": hashlib.sha1(link.encode()).hexdigest()[:16],
            "title": title,
            "link": link,
            "summary": clean_summary(raw["summary"]),
            "published": dt.isoformat() if dt else None,
            "source": feed["name"],
            "category": info["category"],
        })
    if not items:
        info["error"] = "No readable entries in feed"
        return info, None
    info.update(ok=True, count=len(items))
    return info, items


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_config():
    with open(BASE / "feeds.json", encoding="utf-8") as f:
        return json.load(f)


def refresh_all():
    cfg = load_config()
    max_items = cfg.get("max_items_per_feed", 40)
    with state_lock:
        state["refreshing"] = True
        prev_feeds = dict(state["feeds"])
    feeds = cfg["feeds"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda f: fetch_feed(f, prev_feeds.get(f["name"], {}), max_items), feeds))

    first_seen = now_iso()
    with state_lock:
        names = {f["name"] for f in feeds}
        state["feeds"] = {k: v for k, v in state["feeds"].items() if k in names}
        for info, items in results:
            state["feeds"][info["name"]] = info
            for it in items or []:
                old = state["items"].get(it["id"])
                it["first_seen"] = old["first_seen"] if old else first_seen
                if not it["published"]:
                    it["published"] = it["first_seen"]
                state["items"][it["id"]] = it
        # drop items of removed feeds, keep the newest 3000 overall
        kept = [i for i in state["items"].values() if i["source"] in names]
        kept.sort(key=lambda i: i["published"], reverse=True)
        state["items"] = {i["id"]: i for i in kept[:3000]}
        state["last_refresh"] = now_iso()
        state["refreshing"] = False
        snapshot = json.dumps(state, ensure_ascii=False)
    CACHE_FILE.write_text(snapshot, encoding="utf-8")
    ok = sum(1 for i, _ in results if i["ok"])
    print(f"[{datetime.now():%H:%M:%S}] refreshed: {ok}/{len(results)} sources, {len(state['items'])} items", flush=True)


def scheduler():
    while True:
        try:
            refresh_all()
        except Exception as e:
            print("refresh failed:", e, flush=True)
            with state_lock:
                state["refreshing"] = False
        minutes = max(1, float(load_config().get("refresh_minutes", 15)))
        with state_lock:
            state["next_refresh"] = datetime.fromtimestamp(time.time() + minutes * 60, timezone.utc).isoformat()
        refresh_now.wait(minutes * 60)
        refresh_now.clear()


# ---------- HTTP ----------

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(STATIC), **kw)

    def log_message(self, *a):
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/feed":
            with state_lock:
                items = sorted(state["items"].values(), key=lambda i: i["published"], reverse=True)
                feeds = [{k: v for k, v in f.items() if k not in ("etag", "modified")} for f in state["feeds"].values()]
                payload = {"items": items, "feeds": feeds, "last_refresh": state["last_refresh"],
                           "next_refresh": state["next_refresh"], "refreshing": state["refreshing"]}
            return self.send_json(payload)
        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/refresh":
            with state_lock:
                state["refreshing"] = True
            refresh_now.set()
            return self.send_json({"ok": True}, 202)
        self.send_json({"error": "not found"}, 404)


def main():
    ap = argparse.ArgumentParser(description="CTI Radar")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    if CACHE_FILE.exists():
        try:
            state.update(json.loads(CACHE_FILE.read_text(encoding="utf-8")))
            state["refreshing"] = False
        except (ValueError, OSError):
            pass
    threading.Thread(target=scheduler, daemon=True).start()
    print(f"CTI Radar: http://{args.host}:{args.port}", flush=True)
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
