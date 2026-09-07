"""离线解析测试：不需要联网，直接运行 `python tests/test_parse.py`。"""

import sys
import unittest
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fetch_rss import parse_items  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "news_list_2874.html"

# 服务器原始 HTML 用单引号包属性，与浏览器渲染的双引号不同，两种都要能解析
RAW_SINGLE_QUOTE = (
    "<li class='news n1 clearfix'>"
    "<span class='news_title'><a href='/2026/0717/c2874a253649/page.htm' "
    "target='_blank' title='测试标题'>测试标题</a></span>"
    "<span class='news_meta'>2026-07-17</span></li>"
)


class TestParse(unittest.TestCase):
    def test_fixture_items(self):
        items = parse_items(FIXTURE.read_text(encoding="utf-8"))
        self.assertEqual(len(items), 14)
        first = items[0]
        self.assertEqual(
            first["link"],
            "https://yjs.aufe.edu.cn/2026/0717/c2874a253649/page.htm",
        )
        self.assertIn("暑期学术训练营", first["title"])
        self.assertEqual(
            parsedate_to_datetime(first["pubdate"]).strftime("%Y-%m-%d"), "2026-07-17"
        )
        last = items[-1]
        self.assertEqual(
            parsedate_to_datetime(last["pubdate"]).strftime("%Y-%m-%d"), "2025-12-31"
        )

    def test_absolute_link_kept(self):
        items = parse_items(FIXTURE.read_text(encoding="utf-8"))
        links = [it["link"] for it in items]
        self.assertIn(
            "https://www.aufe.edu.cn/2026/0531/c408a248861/page.htm", links
        )

    def test_single_quoted_attributes(self):
        items = parse_items(RAW_SINGLE_QUOTE)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "测试标题")
        self.assertEqual(
            items[0]["link"],
            "https://yjs.aufe.edu.cn/2026/0717/c2874a253649/page.htm",
        )

    def test_dates_sorted_input_not_required(self):
        items = parse_items(RAW_SINGLE_QUOTE + RAW_SINGLE_QUOTE)
        # 同一链接去重后只剩 1 条
        self.assertEqual(len(items), 1)


if __name__ == "__main__":
    unittest.main()
