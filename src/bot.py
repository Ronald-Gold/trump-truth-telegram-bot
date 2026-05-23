"""Trump Truth Social -> Telegram bridge.

Polls https://trumpstruth.org/feed (a public archive of @realDonaldTrump posts on
Truth Social), finds posts not yet relayed, scrapes the per-status detail page
to recover full text and media URLs, translates English -> Simplified Chinese,
and pushes a bilingual message (with images/videos when present) to one or more
Telegram chats via a regular Bot API token.

Designed to be safe to run repeatedly under GitHub Actions every 5 minutes.
State (already-sent IDs) is kept in `state.json` next to this script's parent.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import feedparser
import requests
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator

FEED_URL = "https://trumpstruth.org/feed?per_page=50"
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
HTTP_TIMEOUT = 30
TG_CAPTION_MAX = 1024
TG_TEXT_MAX = 4096
MAX_NEW_PER_RUN = int(os.environ.get("MAX_NEW_PER_RUN", "8"))
TRANSLATE_MAX_CHARS = 4500

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "state.json"
DEFAULT_STATE = {"sent_ids": [], "last_run": None}
STATE_KEEP = 600

log = logging.getLogger("trump-bot")


@dataclass
class Attachment:
    url: str
    type: str
    description: str = ""


@dataclass
class Post:
    status_id: str
    status_url: str
    truth_url: str
    pub_date: str
    body: str = ""
    attachments: list[Attachment] = field(default_factory=list)


def configure_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def load_state() -> dict:
    if not STATE_PATH.exists():
        return dict(DEFAULT_STATE)
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("state.json corrupt, starting from empty state")
        return dict(DEFAULT_STATE)
    data.setdefault("sent_ids", [])
    data.setdefault("last_run", None)
    return data


def save_state(state: dict) -> None:
    state["sent_ids"] = state["sent_ids"][-STATE_KEEP:]
    state["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def http_get(url: str, *, retries: int = 3) -> requests.Response:
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(
                url,
                timeout=HTTP_TIMEOUT,
                headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
            )
            r.raise_for_status()
            return r
        except requests.RequestException as exc:
            last_exc = exc
            wait = min(2 ** attempt, 10)
            log.warning("GET %s failed (attempt %d/%d): %s; sleep %ds",
                        url, attempt, retries, exc, wait)
            time.sleep(wait)
    raise RuntimeError(f"GET {url} failed after {retries} attempts: {last_exc}")


def parse_feed() -> list[tuple[str, str, str, str]]:
    """Return list of (status_id, status_url, truth_url, pub_date) sorted oldest-first."""
    raw = http_get(FEED_URL).content
    feed = feedparser.parse(raw)
    items: list[tuple[str, str, str, str]] = []
    for entry in feed.entries:
        link = entry.get("link") or entry.get("guid", "")
        m = re.search(r"/statuses/(\d+)", link)
        if not m:
            continue
        status_id = m.group(1)
        truth_url = ""
        for key in ("source", "comments"):
            cand = entry.get(key)
            if isinstance(cand, str) and "truthsocial.com" in cand:
                truth_url = cand
                break
        if not truth_url:
            for value in entry.values():
                if isinstance(value, str) and "truthsocial.com/" in value:
                    truth_url = value.strip()
                    break
        items.append((status_id, link, truth_url, entry.get("published", "")))
    items.sort(key=lambda t: t[0])
    log.info("RSS: %d entries", len(items))
    return items


_VIDEO_EXT = (".mp4", ".mov", ".webm", ".m4v")
_GIF_EXT = (".gif",)


def _classify_media(url: str) -> str:
    lower = url.lower().split("?", 1)[0]
    if lower.endswith(_VIDEO_EXT):
        return "video"
    if lower.endswith(_GIF_EXT):
        return "animation"
    return "photo"


def fetch_post_detail(status_id: str, status_url: str, truth_url: str, pub_date: str) -> Post:
    soup = BeautifulSoup(http_get(status_url).text, "html.parser")

    body_el = soup.select_one(".status__body__text") or soup.select_one(".status__content")
    body = body_el.get_text("\n", strip=True) if body_el else ""

    attachments: list[Attachment] = []
    for att in soup.select(".status-details-attachment"):
        media_link = att.select_one("a[data-fancybox]") or att.select_one("a[download]")
        media_url = media_link["href"] if media_link and media_link.get("href") else ""
        if not media_url:
            img = att.select_one(".status-details-attachment__media img")
            if img and img.get("src"):
                media_url = img["src"]
        if not media_url:
            continue
        desc_el = att.select_one(".status-details-attachment__text")
        description = desc_el.get_text(" ", strip=True) if desc_el else ""
        if "no information available" in description.lower():
            description = ""
        attachments.append(
            Attachment(url=media_url, type=_classify_media(media_url), description=description)
        )

    if not truth_url:
        og = soup.find("meta", attrs={"property": "og:url"})
        if og and og.get("content"):
            truth_url = og["content"]

    return Post(
        status_id=status_id,
        status_url=status_url,
        truth_url=truth_url,
        pub_date=pub_date,
        body=body,
        attachments=attachments,
    )


_TRANSLATOR_CACHE: GoogleTranslator | None = None


def translate_to_zh(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    global _TRANSLATOR_CACHE
    if _TRANSLATOR_CACHE is None:
        _TRANSLATOR_CACHE = GoogleTranslator(source="auto", target="zh-CN")
    chunks: list[str] = []
    for i in range(0, len(text), TRANSLATE_MAX_CHARS):
        piece = text[i:i + TRANSLATE_MAX_CHARS]
        for attempt in range(1, 4):
            try:
                out = _TRANSLATOR_CACHE.translate(piece) or ""
                chunks.append(out)
                break
            except Exception as exc:  # noqa: BLE001
                wait = 2 ** attempt
                log.warning("translation attempt %d failed: %s; retry in %ds",
                            attempt, exc, wait)
                time.sleep(wait)
        else:
            log.error("translation gave up; falling back to source text")
            return ""
    return "\n".join(chunks).strip()


_HTML_ESCAPE = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}


def _esc(s: str) -> str:
    return "".join(_HTML_ESCAPE.get(c, c) for c in s)


def render_message(post: Post, body_zh: str, media_descs_zh: list[str]) -> str:
    parts: list[str] = []
    parts.append(f"<b>Donald J. Trump</b> on Truth Social")
    if post.pub_date:
        parts.append(f"<i>{_esc(post.pub_date)}</i>")
    parts.append("")
    if post.body:
        parts.append("<b>EN</b>")
        parts.append(_esc(post.body))
        if body_zh:
            parts.append("")
            parts.append("<b>中文</b>")
            parts.append(_esc(body_zh))
    elif post.attachments:
        parts.append("<i>(图片/视频帖, 无文字)</i>")

    for idx, (att, zh) in enumerate(zip(post.attachments, media_descs_zh), start=1):
        if not att.description and not zh:
            continue
        parts.append("")
        label = {"photo": "图片", "video": "视频", "animation": "GIF"}.get(att.type, "媒体")
        parts.append(f"<b>{label} {idx} 描述</b>")
        if att.description:
            parts.append(f"EN: {_esc(att.description)}")
        if zh:
            parts.append(f"中文: {_esc(zh)}")

    parts.append("")
    parts.append(f'<a href="{_esc(post.status_url)}">📖 trumpstruth.org</a>')
    if post.truth_url:
        parts.append(f'<a href="{_esc(post.truth_url)}">🔗 Truth Social 原帖</a>')

    return "\n".join(parts)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cutoff = text.rfind("\n", 0, limit - 20)
    if cutoff < limit // 2:
        cutoff = limit - 20
    return text[:cutoff].rstrip() + "\n…(truncated)"


def telegram_call(token: str, method: str, **payload) -> dict:
    url = TELEGRAM_API.format(token=token, method=method)
    last_exc: Exception | None = None
    for attempt in range(1, 5):
        try:
            r = requests.post(url, json=payload, timeout=HTTP_TIMEOUT)
            data = r.json() if r.content else {}
            if r.ok and data.get("ok"):
                return data
            if r.status_code == 429:
                retry_after = int((data.get("parameters") or {}).get("retry_after", 5))
                log.warning("Telegram 429 rate-limited, sleeping %ds", retry_after)
                time.sleep(retry_after + 1)
                continue
            raise RuntimeError(f"Telegram {method} -> {r.status_code} {data}")
        except requests.RequestException as exc:
            last_exc = exc
            wait = 2 ** attempt
            log.warning("Telegram %s attempt %d failed: %s; sleep %ds",
                        method, attempt, exc, wait)
            time.sleep(wait)
    raise RuntimeError(f"Telegram {method} failed: {last_exc}")


def _short_caption(post: Post) -> str:
    parts = [
        f"<b>Donald J. Trump</b> on Truth Social",
        f"<i>{_esc(post.pub_date)}</i>" if post.pub_date else "",
        f'<a href="{_esc(post.status_url)}">📖 trumpstruth.org</a>',
    ]
    if post.truth_url:
        parts.append(f'<a href="{_esc(post.truth_url)}">🔗 Truth Social</a>')
    return "\n".join(p for p in parts if p)


def send_post(token: str, chat_ids: Iterable[str], post: Post,
              body_zh: str, media_descs_zh: list[str]) -> None:
    full_html = render_message(post, body_zh, media_descs_zh)
    media = post.attachments
    needs_extra_text = bool(media) and len(full_html) > TG_CAPTION_MAX

    for chat_id in chat_ids:
        try:
            if not media:
                telegram_call(
                    token, "sendMessage",
                    chat_id=chat_id,
                    text=_truncate(full_html, TG_TEXT_MAX),
                    parse_mode="HTML",
                    disable_web_page_preview=False,
                )
            elif len(media) == 1:
                m = media[0]
                method = {"photo": "sendPhoto", "video": "sendVideo",
                          "animation": "sendAnimation"}[m.type]
                key = {"photo": "photo", "video": "video", "animation": "animation"}[m.type]
                caption = _short_caption(post) if needs_extra_text else _truncate(full_html, TG_CAPTION_MAX)
                try:
                    telegram_call(token, method, **{
                        "chat_id": chat_id,
                        key: m.url,
                        "caption": caption,
                        "parse_mode": "HTML",
                    })
                except RuntimeError as exc:
                    log.warning("media send failed (%s), falling back to text+link: %s",
                                method, exc)
                    text = _truncate(full_html + f"\n\n📎 媒体: {m.url}", TG_TEXT_MAX)
                    telegram_call(token, "sendMessage",
                                  chat_id=chat_id, text=text,
                                  parse_mode="HTML", disable_web_page_preview=False)
            else:
                group = []
                first_caption = _short_caption(post) if needs_extra_text else _truncate(full_html, TG_CAPTION_MAX)
                for i, m in enumerate(media[:10]):
                    item = {
                        "type": "video" if m.type in ("video", "animation") else "photo",
                        "media": m.url,
                    }
                    if i == 0:
                        item["caption"] = first_caption
                        item["parse_mode"] = "HTML"
                    group.append(item)
                try:
                    telegram_call(token, "sendMediaGroup",
                                  chat_id=chat_id, media=group)
                except RuntimeError as exc:
                    log.warning("sendMediaGroup failed, fallback to text: %s", exc)
                    extras = "\n".join(f"📎 {m.url}" for m in media)
                    text = _truncate(full_html + "\n\n" + extras, TG_TEXT_MAX)
                    telegram_call(token, "sendMessage",
                                  chat_id=chat_id, text=text,
                                  parse_mode="HTML", disable_web_page_preview=False)

            if needs_extra_text:
                telegram_call(
                    token, "sendMessage",
                    chat_id=chat_id,
                    text=_truncate(full_html, TG_TEXT_MAX),
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                )

            log.info("Posted %s -> chat %s", post.status_id, chat_id)
        except Exception as exc:  # noqa: BLE001
            log.exception("Failed to send post %s to chat %s: %s",
                          post.status_id, chat_id, exc)
            raise


def main() -> int:
    configure_logging()

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    raw_ids = os.environ.get("TELEGRAM_CHAT_IDS", "").strip()
    if not token:
        log.error("TELEGRAM_BOT_TOKEN env var is missing")
        return 2
    if not raw_ids:
        log.error("TELEGRAM_CHAT_IDS env var is missing (comma-separated chat ids)")
        return 2
    chat_ids = [c.strip() for c in raw_ids.split(",") if c.strip()]

    state = load_state()
    sent = set(state["sent_ids"])
    log.info("State: %d ids known, last_run=%s", len(sent), state["last_run"])

    try:
        feed_items = parse_feed()
    except Exception as exc:  # noqa: BLE001
        log.exception("Failed to read RSS feed: %s", exc)
        return 1

    new_items = [it for it in feed_items if it[0] not in sent]
    if not new_items:
        log.info("Nothing new.")
        save_state(state)
        return 0

    is_first_run = len(sent) == 0
    if is_first_run:
        new_items = new_items[-min(2, len(new_items)):]
        log.info("First run: only relaying the latest %d (avoiding flood).", len(new_items))
    else:
        new_items = new_items[:MAX_NEW_PER_RUN]
        log.info("Will process %d new posts this run.", len(new_items))

    for status_id, status_url, truth_url, pub_date in new_items:
        try:
            log.info("Fetching %s", status_url)
            post = fetch_post_detail(status_id, status_url, truth_url, pub_date)

            body_zh = translate_to_zh(post.body) if post.body else ""
            media_descs_zh = [
                translate_to_zh(a.description) if a.description else ""
                for a in post.attachments
            ]

            send_post(token, chat_ids, post, body_zh, media_descs_zh)
            sent.add(status_id)
            state["sent_ids"].append(status_id)
            save_state(state)
            time.sleep(1)
        except Exception as exc:  # noqa: BLE001
            log.exception("Skipping %s after error: %s", status_id, exc)
            save_state(state)

    save_state(state)
    log.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
