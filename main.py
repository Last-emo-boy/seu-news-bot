import asyncio
import aiohttp
from astrbot.api.all import *

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain

from bs4 import BeautifulSoup
from datetime import datetime
from .news_db import NewsDB

BASE_URL = "https://jwc.seu.edu.cn"
# 待爬取的各个栏目
PATHS = ["zxdt", "jwxx", "xjgl", "gjjl", "sjjx", "cbxx", "jxyj"]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

@register("SEU助手", "教务处新闻订阅与查询插件，新版支持关键词和日期查询", "1.0.1", "https://github.com/Last-emo-boy/seu-news-bot")
class NewsPlugin(Star):
    def __init__(self, context: Context, config: dict):
        """
        初始化时接收配置文件（通过 _conf_schema.json），可配置项例如：
            - check_interval: 检查更新的时间间隔（秒），默认 3600 秒
        """
        super().__init__(context)
        self.config = config  # 启用 schema 配置
        self.db = NewsDB()
        interval = self.config.get("check_interval", 3600)
        # 启动定时任务，每隔 interval 秒检查一次新闻更新
        asyncio.create_task(self.scheduled_check(interval=interval))
    
    async def scheduled_check(self, interval: int):
        while True:
            await self.check_updates()
            await asyncio.sleep(interval)
    
    async def check_updates(self):
        """
        更新新闻数据：
          - 遍历各个新闻栏目
          - 爬取当前页面新闻，若检测到新闻发布日期早于数据库中最新的记录则停止继续翻页
        """
        async with aiohttp.ClientSession() as session:
            for path in PATHS:
                latest_date = self.db.get_latest_date(path)
                page = 1
                has_new = True
                while has_new:
                    url = f"{BASE_URL}/{path}/list{page}.htm"
                    async with session.get(url, headers=HEADERS) as resp:
                        if resp.status != 200:
                            break
                        html = await resp.text()
                        soup = BeautifulSoup(html, "html.parser")
                        news_div = soup.find("div", id="wp_news_w8")
                        if not news_div:
                            break
                        news_list = []
                        for tr in news_div.find_all("tr"):
                            title_tag = tr.find("a", title=True)
                            tds = tr.find_all("td", class_="main")
                            if title_tag and tds and len(tds) >= 2 and tds[1].find("div"):
                                pub_date_str = tds[1].find("div").text.strip()
                                try:
                                    pub_date = datetime.strptime(pub_date_str, "%Y-%m-%d")
                                    pub_date_iso = pub_date.isoformat()
                                except Exception:
                                    pub_date_iso = "日期未知"
                                # 若能正确解析日期，则判断是否需要停止翻页更新
                                if latest_date not in (None, "日期未知") and pub_date_iso != "日期未知":
                                    try:
                                        latest_dt = datetime.fromisoformat(latest_date)
                                        if pub_date <= latest_dt:
                                            has_new = False
                                            break
                                    except Exception:
                                        pass
                                relative_url = title_tag.get("href", "")
                                full_url = relative_url if relative_url.startswith("http") else f"{BASE_URL}{relative_url}"
                                news_list.append((path, title_tag["title"].strip(), full_url, pub_date_iso))
                        if news_list:
                            self.db.insert_news(news_list)
                            # 首次运行时数据库为空，则翻页继续爬取全部数据；否则只更新最新页面
                            if latest_date is None:
                                page += 1
                            else:
                                break
                        else:
                            break

    @filter.command("news")
    async def get_news(self, event: AstrMessageEvent, 
                       channel: str = None, 
                       page: int = 1, 
                       keyword: str = None, 
                       start_date: str = None, 
                       end_date: str = None):
        """
        获取教务处新闻。
        
        参数:
            channel (str): 可选，指定栏目名称（例如 zxdt、jwxx 等，支持模糊匹配）。
            page (int): 页码，默认 1，每页显示 5 条新闻。
            keyword (str): 可选，新闻标题关键词过滤。
            start_date (str): 可选，起始发布日期，格式 YYYY-MM-DD。
            end_date (str): 可选，结束发布日期，格式 YYYY-MM-DD。
        """
        per_page = 5
        # 注意：NewsDB.get_news 方法需支持上述额外过滤条件
        news = self.db.get_news(channel=channel, page=page, per_page=per_page, 
                                keyword=keyword, start_date=start_date, end_date=end_date)
        if not news:
            yield event.plain_result("暂无更多新闻")
            return
        
        # 使用 event.make_result() 构造消息链
        result = event.make_result().message(f"📰 新闻查询结果（第 {page} 页）\n")
        for idx, item in enumerate(news, 1):
            # 假设新闻记录结构为 (频道, 标题, 链接, 发布日期)
            result = result.message(f"{idx}. 【{item[0]}】{item[1]}\n链接：{item[2]}\n发布日期：{item[3]}\n\n")
        if len(news) == per_page:
            next_cmd = f"/news {channel or ''} {page+1} {keyword or ''} {start_date or ''} {end_date or ''}"
            result = result.message(f"发送 {next_cmd.strip()} 查看下一页")
        yield result  # 自动发送构造好的消息
    
    async def terminate(self):
        self.db.close()
