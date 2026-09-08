#!/usr/bin/env python3
"""抓取安徽财经大学研究生院官网（yjs.aufe.edu.cn）栏目列表，生成 RSS 2.0 订阅源。

只用 Python 标准库，无第三方依赖。运行后在 rss/ 目录生成：
- rss/<slug>.xml   每个栏目一条订阅源（含正文）
- rss/all.xml      全部栏目合并去重，按日期倒序，最多 100 条
- rss/feeds.opml   直连版订阅源一键导入文件
- rss/feeds-cn.opml  国内镜像版（订阅地址走 ghproxy.net 代理）

正文抓取策略：官网文章页只有正文和日期（没有具体时刻）。为避免每轮
抓取几十个文章页触发 WAF，用 state/seen.json 记录已处理的文章链接，
只对首次出现的文章抓正文；首轮预算 40 篇，之后每轮 15 篇，抓完为止。

注意：官网启用了雷池 WAF，高频访问会被临时封禁。脚本自带请求间隔、
浏览器请求头和被拦退避重试；GitHub Actions 每 30 分钟抓一次，频率安全。
"""

from __future__ import annotations

import email.utils
import json
import os
import random
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin
from xml.sax.saxutils import escape

BASE = "https://yjs.aufe.edu.cn"
OUT_DIR = Path(__file__).resolve().parent / "rss"
STATE_PATH = Path(__file__).resolve().parent / "state" / "seen.json"
TIMEOUT = 30
DELAY_RANGE = (2.0, 5.0)  # 栏目列表页之间的随机间隔（秒），避免触发 WAF
ARTICLE_DELAY_RANGE = (1.5, 3.0)  # 文章页之间的随机间隔（秒）
RETRY_DELAYS = (8, 20)  # 被拦截后的退避等待（秒）
MAX_MERGED = 100
MAX_CONTENT_CHARS = 15000  # 单篇正文截断长度
BUDGET_FIRST_RUN = 40  # 首轮（无状态文件时）抓正文的篇数预算
BUDGET_NORMAL = 15  # 常规轮次补抓篇数预算
MIRROR_PREFIX = "https://ghproxy.net/"  # 国内镜像代理前缀，用于 feeds-cn.opml

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# 要生成订阅源的栏目：(文件名 slug, 订阅标题, 栏目路径)。增删栏目只改这里。
SECTIONS = [
    ("xwdt", "研究生院·新闻动态", "/2874/list.htm"),
    ("jxgz", "研究生院·教学工作通知", "/2879/list.htm"),
    ("xwgz", "研究生院·学位工作通知", "/2895/list.htm"),
    ("xskb", "研究生院·学术看板", "/2884/list.htm"),
    ("xsgl", "研究生院·学生管理", "/2927/list.htm"),
    ("jzxj", "研究生院·奖助学金", "/2928/list.htm"),
]

LI_RE = re.compile(r"<li\b[^>]*>(.*?)</li>", re.S)
A_WITH_TITLE_RE = re.compile(
    r"<a\b[^>]*?href=(['\"])(?P<href>[^'\"]+)\1[^>]*?title=(['\"])(?P<title>[^'\"]*)\3", re.S
)
A_RE = re.compile(r"<a\b[^>]*?href=(['\"])(?P<href>[^'\"]+)\1[^>]*>(?P<title>.*?)</a>", re.S)
TAG_RE = re.compile(r"<[^>]+>")
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
TZ = timezone(timedelta(hours=8))


def attr_escape(text: str) -> str:
    return escape(text, {'"': "&quot;"})


def parse_items(html: str) -> list[dict]:
    """解析列表页里的文章条目（博达 CMS 的 li.news 结构）。"""
    items: list[dict] = []
    seen: set[str] = set()
    for body in LI_RE.findall(html):
        m = A_WITH_TITLE_RE.search(body)
        if m:
            title = m.group("title").strip()
        else:
            m = A_RE.search(body)
            if not m:
                continue
            title = TAG_RE.sub("", m.group("title")).strip()
        date_match = DATE_RE.search(body)
        if not (title and m and date_match):
            continue
        link = urljoin(BASE, m.group("href").strip())
        if link in seen:
            continue
        seen.add(link)
        dt = datetime.strptime(date_match.group(1), "%Y-%m-%d").replace(tzinfo=TZ)
        items.append(
            {
                "title": title,
                "link": link,
                "dt": dt,
                "pubdate": email.utils.format_datetime(dt),
            }
        )
    return items


def fetch(url: str) -> str:
    """抓取页面；遇到 WAF 拦截（403/挑战页）按 RETRY_DELAYS 退避重试。"""
    last_err: Exception | None = None
    for delay in (0,) + RETRY_DELAYS:
        if delay:
            print(f"    被拦截，{delay}s 后重试…", file=sys.stderr)
            time.sleep(delay)
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = resp.read().decode("utf-8", "replace")
            if "/.safeline/" in data:
                raise RuntimeError("雷池 WAF 拦截页")
            return data
        except Exception as e:  # 网络类异常统一走退避重试
            last_err = e
    raise RuntimeError(f"重试 {len(RETRY_DELAYS)} 次后仍失败：{url}（{last_err}）")


def extract_div(html: str, class_keyword: str) -> str | None:
    """按 class 关键字定位 div，用配对计数取完整内层 HTML。"""
    m = re.search(r'<div\b[^>]*class="[^"]*' + class_keyword + r'[^"]*"[^>]*>', html, re.I)
    if not m:
        return None
    depth = 1
    start = m.end()
    for t in re.finditer(r"<(/?)div\b[^>]*>", html[start:], re.I):
        depth += -1 if t.group(1) else 1
        if depth == 0:
            return html[start : start + t.start()]
    return html[start:]


def clean_content(raw: str) -> str:
    """清理正文 HTML：去脚本/样式/注释和内联样式，相对地址转绝对。"""
    raw = re.sub(r"<script\b.*?</script>", "", raw, flags=re.S | re.I)
    raw = re.sub(r"<style\b.*?</style>", "", raw, flags=re.S | re.I)
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.S)

    def absolutize(m: re.Match) -> str:
        attr, quote, url = m.group(1), m.group(2), m.group(3)
        if url.startswith(("http://", "https://", "data:", "#", "mailto:")):
            return m.group(0)
        return f"{attr}={quote}{urljoin(BASE, url)}{quote}"

    raw = re.sub(r"\b(src|href)=(['\"])([^'\"]+)\2", absolutize, raw)
    raw = re.sub(
        r'\s+(?:style|class|id|sudyfile-attr|data-layer|original-src|frag|portletmode)="[^"]*"',
        "",
        raw,
    )
    raw = re.sub(r"<p\b[^>]*>", "<p>", raw)
    raw = re.sub(r"<img\b[^>]*>", lambda m: m.group(0).replace(" />", ">"), raw)
    if len(raw) > MAX_CONTENT_CHARS:
        raw = re.sub(r"<[^>]*$", "", raw[:MAX_CONTENT_CHARS]) + "…（内容过长，已截断）"
    return raw.strip()


def fetch_article_content(url: str) -> str | None:
    """抓文章页并提取正文 HTML；提取失败返回 None。"""
    html = fetch(url)
    for kw in ("wp_articlecontent", "v_news_content", "vsb_content"):
        raw = extract_div(html, kw)
        if raw:
            return clean_content(raw)
    return None


def build_rss(title: str, link: str, description: str, items: list[dict]) -> str:
    now = email.utils.format_datetime(datetime.now(TZ))
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<rss version="2.0">',
        "<channel>",
        f"    <title>{escape(title)}</title>",
        f"    <link>{escape(link)}</link>",
        f"    <description>{escape(description)}</description>",
        f"    <lastBuildDate>{now}</lastBuildDate>",
        "    <generator>aufe-yjs-rss</generator>",
    ]
    for it in items:
        parts.append("    <item>")
        parts.append(f"        <title>{escape(it['title'])}</title>")
        parts.append(f"        <link>{escape(it['link'])}</link>")
        parts.append(f'        <guid isPermaLink="true">{escape(it["link"])}</guid>')
        parts.append(f"        <pubDate>{it['pubdate']}</pubDate>")
        if it.get("description"):
            parts.append(f"        <description>{escape(it['description'])}</description>")
        parts.append("    </item>")
    parts += ["</channel>", "</rss>", ""]
    return "\n".join(parts)


def build_opml(public_base: str, mirror_prefix: str = "") -> str:
    """生成扁平结构的 OPML（部分阅读器不兼容嵌套文件夹）。

    mirror_prefix 传代理前缀（如 https://ghproxy.net/）时，
    订阅地址会变成镜像地址，供直连 raw.githubusercontent.com 困难的网络使用。
    """
    now = email.utils.format_datetime(datetime.now(TZ))
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<opml version="2.0">',
        "  <head>",
        "    <title>安徽财经大学研究生院 RSS</title>",
        f"    <dateCreated>{now}</dateCreated>",
        "    <ownerName>aufe-yjs-rss</ownerName>",
        "  </head>",
        "  <body>",
    ]
    feeds = [(name, f"{public_base}/{slug}.xml", BASE + path) for slug, name, path in SECTIONS]
    feeds.append(("研究生院·全部更新", f"{public_base}/all.xml", BASE + "/"))
    for name, xml_url, html_url in feeds:
        parts.append(
            f'    <outline type="rss" text="{attr_escape(name)}" title="{attr_escape(name)}" '
            f'xmlUrl="{attr_escape(mirror_prefix + xml_url)}" htmlUrl="{attr_escape(html_url)}"/>'
        )
    parts += ["  </body>", "</opml>", ""]
    return "\n".join(parts)


def write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    print(f"    写出 {path.relative_to(OUT_DIR.parent)}")


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    repo = os.environ.get("GITHUB_REPOSITORY", "yanchou3/aufe-yjs-rss")
    public_base = f"https://raw.githubusercontent.com/{repo}/main/rss"

    sections: list[tuple[str, str, str, list[dict]]] = []
    all_items: list[dict] = []
    ok = 0
    for idx, (slug, name, path) in enumerate(SECTIONS):
        url = BASE + path
        print(f"[{idx + 1}/{len(SECTIONS)}] {name}  {url}")
        if idx:
            time.sleep(random.uniform(*DELAY_RANGE))
        try:
            items = parse_items(fetch(url))
        except Exception as e:  # 单个栏目失败不影响其余栏目
            print(f"    [FAIL] {e}", file=sys.stderr)
            continue
        if not items:
            print("    [WARN] 解析到 0 条，页面结构可能变化", file=sys.stderr)
        ok += 1
        sections.append((slug, name, url, items))
        all_items.extend(items)
        print(f"    [OK] {len(items)} 条")

    if ok == 0:
        print("所有栏目均抓取失败", file=sys.stderr)
        return 1

    # 为首次出现的文章抓正文（按日期倒序处理，优先最新的）
    all_items.sort(key=lambda x: x["dt"], reverse=True)
    state = load_state()
    budget = BUDGET_FIRST_RUN if not state else BUDGET_NORMAL
    pending = [it for it in all_items if it["link"] not in state]
    print(f"正文抓取：未处理 {len(pending)} 篇，本轮预算 {budget} 篇")
    fetched = 0
    for it in pending:
        if fetched >= budget:
            break  # 剩下的留给下一轮
        if fetched:
            time.sleep(random.uniform(*ARTICLE_DELAY_RANGE))
        try:
            it["description"] = fetch_article_content(it["link"])
        except Exception as e:  # 单篇失败不阻塞，标记已处理避免反复重试
            print(f"    [WARN] 正文抓取失败 {it['link']}：{e}", file=sys.stderr)
        state[it["link"]] = 1
        fetched += 1
    if fetched:
        save_state(state)
        print(f"    已抓正文 {fetched} 篇，state/seen.json 共 {len(state)} 条")

    names = "、".join(name for _, name, _, _ in sections)
    for slug, name, url, items in sections:
        write(
            OUT_DIR / f"{slug}.xml",
            build_rss(name, url, f"安徽财经大学研究生院「{name}」栏目（自动抓取生成）", items),
        )

    seen_links: set[str] = set()
    merged: list[dict] = []
    for it in all_items:
        if it["link"] not in seen_links:
            seen_links.add(it["link"])
            merged.append(it)
    write(
        OUT_DIR / "all.xml",
        build_rss(
            "安徽财经大学研究生院·全部更新",
            BASE + "/",
            f"研究生院官网全部栏目合并：{names}",
            merged[:MAX_MERGED],
        ),
    )
    write(OUT_DIR / "feeds.opml", build_opml(public_base))
    write(OUT_DIR / "feeds-cn.opml", build_opml(public_base, MIRROR_PREFIX))
    print(f"完成：{ok}/{len(SECTIONS)} 个栏目，合并去重后 {len(merged[:MAX_MERGED])} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
