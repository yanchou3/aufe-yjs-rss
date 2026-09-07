#!/usr/bin/env python3
"""抓取安徽财经大学研究生院官网（yjs.aufe.edu.cn）栏目列表，生成 RSS 2.0 订阅源。

只用 Python 标准库，无第三方依赖。运行后在 rss/ 目录生成：
- rss/<slug>.xml   每个栏目一条订阅源
- rss/all.xml      全部栏目合并去重，按日期倒序，最多 100 条
- rss/feeds.opml   全部订阅源的一键导入文件

注意：官网启用了雷池 WAF，高频访问会被临时封禁。脚本自带请求间隔、
浏览器请求头和被拦退避重试；GitHub Actions 每 30 分钟抓一次，频率安全。
"""

from __future__ import annotations

import email.utils
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
TIMEOUT = 30
DELAY_RANGE = (2.0, 5.0)  # 栏目之间的随机间隔（秒），避免触发 WAF
RETRY_DELAYS = (8, 20)  # 被拦截后的退避等待（秒）
MAX_MERGED = 100

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
        parts += [
            "    <item>",
            f"        <title>{escape(it['title'])}</title>",
            f"        <link>{escape(it['link'])}</link>",
            f'        <guid isPermaLink="true">{escape(it["link"])}</guid>',
            f"        <pubDate>{it['pubdate']}</pubDate>",
            "    </item>",
        ]
    parts += ["</channel>", "</rss>", ""]
    return "\n".join(parts)


def build_opml(public_base: str) -> str:
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<opml version="2.0">',
        "  <head><title>安徽财经大学研究生院 RSS</title></head>",
        "  <body>",
        '    <outline text="安徽财经大学研究生院">',
    ]
    feeds = [(name, f"{public_base}/{slug}.xml", BASE + path) for slug, name, path in SECTIONS]
    feeds.append(("研究生院·全部更新", f"{public_base}/all.xml", BASE + "/"))
    for name, xml_url, html_url in feeds:
        parts.append(
            f'      <outline type="rss" text="{attr_escape(name)}" title="{attr_escape(name)}" '
            f'xmlUrl="{attr_escape(xml_url)}" htmlUrl="{attr_escape(html_url)}"/>'
        )
    parts += ["    </outline>", "  </body>", "</opml>", ""]
    return "\n".join(parts)


def write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    print(f"    写出 {path.relative_to(OUT_DIR.parent)}")


def main() -> int:
    OUT_DIR.mkdir(exist_ok=True)
    repo = os.environ.get("GITHUB_REPOSITORY", "yanchou3/aufe-yjs-rss")
    public_base = f"https://raw.githubusercontent.com/{repo}/main/rss"

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
        all_items.extend(items)
        write(
            OUT_DIR / f"{slug}.xml",
            build_rss(name, url, f"安徽财经大学研究生院「{name}」栏目（自动抓取生成）", items),
        )
        print(f"    [OK] {len(items)} 条")

    if ok == 0:
        print("所有栏目均抓取失败", file=sys.stderr)
        return 1

    seen: set[str] = set()
    merged: list[dict] = []
    for it in sorted(all_items, key=lambda x: x["dt"], reverse=True):
        if it["link"] not in seen:
            seen.add(it["link"])
            merged.append(it)
    names = "、".join(name for _, name, _ in SECTIONS)
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
    print(f"完成：{ok}/{len(SECTIONS)} 个栏目，合并去重后 {len(merged[:MAX_MERGED])} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
