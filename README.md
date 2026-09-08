# aufe-yjs-rss

安徽财经大学研究生院官网（[yjs.aufe.edu.cn](https://yjs.aufe.edu.cn/)）没有 RSS，本项目定时抓取官网各栏目列表页，自动生成标准 RSS 2.0 订阅源。

## 订阅地址

| 栏目 | 订阅 URL |
| --- | --- |
| 新闻动态 | https://raw.githubusercontent.com/yanchou3/aufe-yjs-rss/main/rss/xwdt.xml |
| 教学工作通知 | https://raw.githubusercontent.com/yanchou3/aufe-yjs-rss/main/rss/jxgz.xml |
| 学位工作通知 | https://raw.githubusercontent.com/yanchou3/aufe-yjs-rss/main/rss/xwgz.xml |
| 学术看板 | https://raw.githubusercontent.com/yanchou3/aufe-yjs-rss/main/rss/xskb.xml |
| 学生管理 | https://raw.githubusercontent.com/yanchou3/aufe-yjs-rss/main/rss/xsgl.xml |
| 奖助学金 | https://raw.githubusercontent.com/yanchou3/aufe-yjs-rss/main/rss/jzxj.xml |
| **全部栏目合并** | https://raw.githubusercontent.com/yanchou3/aufe-yjs-rss/main/rss/all.xml |

一键导入全部订阅源（OPML，二选一）：

- `https://raw.githubusercontent.com/yanchou3/aufe-yjs-rss/main/rss/feeds.opml` —— 直连版，适合海外或可直连 GitHub 的网络
- `https://raw.githubusercontent.com/yanchou3/aufe-yjs-rss/main/rss/feeds-cn.opml` —— 国内镜像版，订阅地址走 ghproxy.net 代理（国内网络推荐用这份）

> **国内网络注意**：`raw.githubusercontent.com` 直连基本不可用，订阅和 OPML 导入都建议走镜像版；或把仓库发布到 Cloudflare Pages 后订阅镜像地址。上面镜像地址的手动替换规则是：在任意订阅 URL 前面加 `https://ghproxy.net/`。

## 工作方式

1. GitHub Actions 每 30 分钟运行一次 `fetch_rss.py`（也可在 Actions 页面手动触发）。
2. 脚本抓取各栏目 `list.htm` 第一页，解析 `li.news` 条目（标题、链接、日期），生成 RSS 写入 `rss/` 目录。
3. 有变化时自动提交回仓库，阅读器拉取到的始终是最新列表。

脚本只用 Python 标准库，无任何第三方依赖。

## 自定义栏目

编辑 `fetch_rss.py` 顶部的 `SECTIONS` 列表即可增删栏目：

```python
SECTIONS = [
    ("xwdt", "研究生院·新闻动态", "/2874/list.htm"),
    ("jxgz", "研究生院·教学工作通知", "/2879/list.htm"),
    ...
]
```

三项分别是输出文件名、订阅标题、栏目路径。栏目路径在官网导航"更多"链接里可以找到（形如 `/数字/list.htm`）。

## 本地运行

```bash
python3 fetch_rss.py          # 抓取并生成 rss/
python3 tests/test_parse.py   # 离线解析测试（不需要联网）
```

## 注意事项

- 官网启用了雷池 WAF，**高频访问会被临时封禁**（返回 403）。脚本已内置请求间隔（2~5 秒随机）和退避重试；每 30 分钟 6 个请求的频率是安全的，请勿调得太激进。
- GitHub 会在仓库 60 天无任何提交后自动停用定时任务，届时在 Actions 页面手动跑一次或随便推一个提交即可恢复。
