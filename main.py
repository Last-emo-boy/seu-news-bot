import asyncio
import aiohttp
import json
from pathlib import Path
from astrbot.api.all import *
from bs4 import BeautifulSoup
from datetime import datetime
from .news_db import NewsDB

BASE_URL = "https://jwc.seu.edu.cn"
# 待爬取的各个栏目
PATHS = ["zxdt", "jwxx", "jxgl", "gjjl", "sjjx", "cbxx", "jxyj"]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# 定义持久化自动通知列表的 JSON 文件路径
AUTO_NOTIFY_FILE = Path(__file__).parent / "auto_notify.json"

def load_auto_notify_origins():
    if AUTO_NOTIFY_FILE.exists():
        try:
            with open(AUTO_NOTIFY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(data)
        except Exception:
            return set()
    return set()

def save_auto_notify_origins(origins: set):
    with open(AUTO_NOTIFY_FILE, "w", encoding="utf-8") as f:
        json.dump(list(origins), f, ensure_ascii=False, indent=2)

@register("SEU助手", "教务处新闻订阅与查询插件，新版支持关键词和日期查询，自动输出最新新闻及全量更新", "1.0.1", "https://github.com/Last-emo-boy/seu-news-bot")
class NewsPlugin(Star):
    def __init__(self, context: Context, config: dict):
        """
        初始化时接收配置文件（通过 _conf_schema.json），配置项包括：
          - check_interval: 检查更新的间隔（秒），默认 3600 秒
        """
        super().__init__(context)
        self.config = config
        self.db = NewsDB()
        # 加载持久化的自动通知会话列表
        self.auto_notify_origins = load_auto_notify_origins()
        interval = self.config.get("check_interval", 3600)
        asyncio.create_task(self.scheduled_check(interval=interval))
    
    async def scheduled_check(self, interval: int):
        """
        定时任务：每次检查更新后，
          若检测到新新闻且存在自动更新订阅会话，
          则向所有订阅会话推送最新新闻。
        """
        while True:
            new_news = await self.check_updates(force_update=False)
            if new_news and self.auto_notify_origins:
                msg_text = f"检测到 {len(new_news)} 条新新闻：\n\n"
                for channel, title, url, pub_date in new_news:
                    msg_text += f"【{channel}】 {title}\n链接：{url}\n发布日期：{pub_date}\n\n"
                for origin in self.auto_notify_origins:
                    await self.context.send_message(origin, [Plain(msg_text)])
            await asyncio.sleep(interval)
    
    async def check_updates(self, force_update: bool = False):
        """
        更新新闻数据。
        
        参数:
          - force_update: 若为 True，则全量更新（忽略已存在新闻判断）；否则遇到已有新闻时停止翻页更新。
        
        返回:
          返回本次更新中新插入的新闻列表，每条记录格式为 (频道, 标题, 链接, 发布日期)。
        """
        new_news_all = []
        async with aiohttp.ClientSession() as session:
            for path in PATHS:
                latest_date = None if force_update else self.db.get_latest_date(path)
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
                                if not force_update and latest_date not in (None, "日期未知") and pub_date_iso != "日期未知":
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
                            new_news_all.extend(news_list)
                            if not force_update and latest_date is not None:
                                break
                            else:
                                page += 1
                        else:
                            break
        return new_news_all

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
          - channel: 可选，指定栏目名称（如 zxdt、jwxx 等，支持模糊匹配）。
          - page: 页码，默认 1，每页显示 5 条新闻。
          - keyword: 可选，新闻标题关键词过滤。
          - start_date: 可选，起始发布日期，格式 YYYY-MM-DD。
          - end_date: 可选，结束发布日期，格式 YYYY-MM-DD。
        """
        per_page = 5
        news = self.db.get_news(channel=channel, page=page, per_page=per_page, 
                                keyword=keyword, start_date=start_date, end_date=end_date)
        if not news:
            yield event.plain_result("暂无更多新闻")
            return
        
        result = event.make_result().message(f"📰 新闻查询结果（第 {page} 页）\n")
        for idx, item in enumerate(news, 1):
            result = result.message(f"{idx}. 【{item[0]}】{item[1]}\n链接：{item[2]}\n发布日期：{item[3]}\n\n")
        if len(news) == per_page:
            next_cmd = f"/news {channel or ''} {page+1} {keyword or ''} {start_date or ''} {end_date or ''}"
            result = result.message(f"发送 {next_cmd.strip()} 查看下一页")
        yield result

    @filter.command("news auto")
    async def news_auto_subscribe(self, event: AstrMessageEvent):
        """
        指令: /news auto
        将当前会话加入到自动更新通知列表（持久化）。
        """
        origin = event.unified_msg_origin
        if origin in self.auto_notify_origins:
            yield event.plain_result("当前会话已在自动更新列表中。")
        else:
            self.auto_notify_origins.add(origin)
            save_auto_notify_origins(self.auto_notify_origins)
            yield event.plain_result("已将当前会话加入自动更新通知列表。")

    @filter.command("news auto off")
    async def news_auto_unsubscribe(self, event: AstrMessageEvent):
        """
        指令: /news auto off
        将当前会话从自动更新通知列表中移除（并更新持久化存储）。
        """
        origin = event.unified_msg_origin
        if origin in self.auto_notify_origins:
            self.auto_notify_origins.remove(origin)
            save_auto_notify_origins(self.auto_notify_origins)
            yield event.plain_result("已将当前会话移除自动更新通知列表。")
        else:
            yield event.plain_result("当前会话不在自动更新列表中。")

    @filter.command("news update")
    async def news_update(self, event: AstrMessageEvent):
        """
        指令: /news update
        强制全量更新新闻，无论数据库中是否已是最新，然后反馈更新数量。
        """
        new_news = await self.check_updates(force_update=True)
        msg = f"全量更新完成，共更新 {len(new_news)} 条新闻。"
        yield event.plain_result(msg)
    
    async def terminate(self):
        self.db.close()
