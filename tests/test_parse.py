"""离线解析测试：不需要联网，直接运行 `python tests/test_parse.py`。"""

import sys
import unittest
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fetch_rss import clean_content, extract_div, parse_items  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "news_list_2874.html"
ARTICLE = Path(__file__).resolve().parent / "article_sample.html"

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

    def test_duplicate_links_deduped(self):
        items = parse_items(RAW_SINGLE_QUOTE + RAW_SINGLE_QUOTE)
        # 同一链接去重后只剩 1 条
        self.assertEqual(len(items), 1)

    def test_jwc_list_item_template(self):
        # 教务处的 wp_article_list 模板（Article_Title / Article_PublishDate）
        raw = (
            '<ul class="wp_article_list">'
            '<li class="list_item i1 clearfix">'
            '<div class="fields pr_fields"><span class="Article_Title">'
            '<a href="/2025/0224/c10355a228918/page.htm" target="_blank" '
            'title="【学科竞赛】关于举办计算机设计大赛校内选拔赛的通知">标题文本</a></span></div>'
            '<div class="fields ex_fields"><span class="Article_PublishDate">2025-02-24</span></div>'
            "</li></ul>"
        )
        items = parse_items(raw, "https://jwc.aufe.edu.cn")
        self.assertEqual(len(items), 1)
        # 链接必须按教务处站点解析，而不是默认的研究生院
        self.assertEqual(
            items[0]["link"],
            "https://jwc.aufe.edu.cn/2025/0224/c10355a228918/page.htm",
        )
        self.assertIn("计算机设计大赛", items[0]["title"])


class TestArticleContent(unittest.TestCase):
    def test_extract_div_balanced(self):
        raw = extract_div(ARTICLE.read_text(encoding="utf-8"), "wp_articlecontent")
        self.assertIsNotNone(raw)
        self.assertIn("暑期学术训练营", raw)
        self.assertIn("（文/图：兰轲轲；审核：张超）", raw)
        # 嵌套 div 配对正确：不应包含外层 article 的标题和 meta
        self.assertNotIn("arti_title", raw)

    def test_clean_content(self):
        raw = extract_div(ARTICLE.read_text(encoding="utf-8"), "wp_articlecontent")
        cleaned = clean_content(raw)
        # 相对图片地址转绝对
        self.assertIn('src="https://yjs.aufe.edu.cn/_upload/article/images/', cleaned)
        # 内联样式被去除
        self.assertNotIn("style=", cleaned)
        self.assertNotIn("sudyfile-attr", cleaned)
        # 保留段落和文本
        self.assertIn("<p>", cleaned)
        self.assertIn("人工智能对经济学研究范式的重构", cleaned)

    def test_single_quoted_content_div(self):
        # 服务器原始 HTML 的 class 属性是单引号（浏览器会规范成双引号，离线样本易漏）
        raw_html = (
            "<div class='read'><div class='wp_articlecontent'>"
            "<p class='MsoNormal' style='text-indent:32px;'>正文第一段。</p>"
            "<p><img src='/__local/abc.png' style='width:600px;'></p>"
            "</div></div>"
        )
        raw = extract_div(raw_html, "wp_articlecontent")
        self.assertIsNotNone(raw)
        cleaned = clean_content(raw)
        self.assertIn("正文第一段", cleaned)
        self.assertIn('src="https://yjs.aufe.edu.cn/__local/abc.png"', cleaned)
        self.assertNotIn("style=", cleaned)


if __name__ == "__main__":
    unittest.main()
