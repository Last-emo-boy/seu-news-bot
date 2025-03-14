import asyncio
import aiohttp
import json
from pathlib import Path
from datetime import datetime
from astrbot.api.all import *
from astrbot.api import logger
from bs4 import BeautifulSoup
from .news_db import NewsDB

from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain

# 请求头，防止被封
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

# 定义各组信息（新闻来源及栏目）
GROUPS = [
    {
        "source": "教务处",
        "base_url": "https://jwc.seu.edu.cn",
        "categories": {
            "zxdt": "zxdt",
            "jwxx": "jwxx",
            "xjgl": "xjgl",
            "gjjl": "gjjl",
            "sjjx": "sjjx",
            "cbxx": "cbxx",
            "jxyj": "jxyj"
        },
        "container_id": "wp_news_w8"  # 表格结构
    },
    {
        "source": "外国语学院",
        "base_url": "https://sfl.seu.edu.cn",
        "categories": {
            "学院公告": "9827",
            "学生公告": "9828",
            "学术活动": "24046"
        },
        "container_id": "wp_news_w6"  # 列表结构
    },
    {
        "source": "电子科学与工程学院",
        "base_url": "https://electronic.seu.edu.cn",
        "categories": {
            "通知公告": "11484",
            "学生工作": "sywxsgz",
            "本科生培养": "bkswsy"
        },
        "container_id": "wp_news_w6"  # 列表结构
    }
]

# 持久化自动更新通知列表的 JSON 文件路径
AUTO_NOTIFY_FILE = Path(__file__).parent / "auto_notify.json"

def load_auto_notify_origins():
    if AUTO_NOTIFY_FILE.exists():
        try:
            with open(AUTO_NOTIFY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return set(data)
        except Exception as e:
            logger.error(f"加载自动通知列表失败：{str(e)}")
    return set()

def save_auto_notify_origins(origins: set):
    try:
        with open(AUTO_NOTIFY_FILE, "w", encoding="utf-8") as f:
            json.dump(list(origins), f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存自动通知列表失败：{str(e)}")

def get_page_url(base_url, identifier, page):
    """
    构造页面 URL：
      - 第一页为 {base_url}/{identifier}/list.htm
      - 其它页为 {base_url}/{identifier}/list{page}.htm
    """
    return f"{base_url}/{identifier}/list.htm" if page == 1 else f"{base_url}/{identifier}/list{page}.htm"

@register("SEU助手", "新闻订阅与查询插件，支持多来源查询、自动输出最新新闻及全量更新", "1.0.2", "https://github.com/Last-emo-boy/seu-news-bot")
class NewsPlugin(Star):
    def __init__(self, context: Context, config: dict):
        """
        初始化时接收配置文件（通过 _conf_schema.json），配置项包括：
          - check_interval: 检查更新的间隔（秒），默认 3600 秒
          - notify_origin: （可选）补充的通知目标，会话标识（不影响自动订阅）
        """
        super().__init__(context)
        self.config = config
        self.db = NewsDB()
        self.auto_notify_origins = load_auto_notify_origins()
        interval = self.config.get("check_interval", 3600)
        logger.info(f"新闻插件启动，更新间隔为 {interval} 秒")
        asyncio.create_task(self.scheduled_check(interval=interval))
    
    async def scheduled_check(self, interval: int):
        """
        定时任务：每次检查更新后，
          若检测到新新闻且存在自动订阅会话，则向所有订阅会话推送最新新闻。
        """
        while True:
            new_news = await self.check_updates(force_update=False)
            if new_news and self.auto_notify_origins:
                msg_text = f"检测到 {len(new_news)} 条新新闻：\n\n"
                for src, cat, title, url, date_str in new_news:
                    msg_text += f"【{src} - {cat}】 {title}\n链接：{url}\n发布日期：{date_str}\n\n"
                chain = MessageChain().message(msg_text)
                for origin in self.auto_notify_origins:
                    try:
                        await self.context.send_message(origin, chain)
                        logger.info(f"已向 {origin} 推送新新闻")
                    except Exception as e:
                        logger.error(f"发送消息到 {origin} 失败：{str(e)}")
            else:
                logger.info("本次检查未发现新新闻或无自动订阅会话")
            await asyncio.sleep(interval)
    
    async def check_updates(self, force_update: bool = False):
        """
        更新新闻数据。

        参数:
          - force_update: 若为 True，则全量更新（忽略数据库判断）；否则仅获取发布时间晚于或等于数据库中最新记录的新闻。

        返回:
          返回本次更新中新插入的新闻列表，每条记录格式为 (来源, 栏目, 标题, 链接, 发布日期)。
        """
        new_news_all = []
        async with aiohttp.ClientSession() as session:
            for group in GROUPS:
                source = group["source"]
                base_url = group["base_url"]
                container_id = group["container_id"]
                logger.info(f"【{source}】开始爬取...")
                for cat_name, identifier in group["categories"].items():
                    logger.info(f"  开始处理栏目：{cat_name} (标识：{identifier})")
                    key = f"{source}:{cat_name}"
                    latest_date = None
                    if not force_update:
                        latest_date = self.db.get_latest_date(key)
                        if latest_date:
                            latest_date = latest_date.strip()
                        logger.info(f"    数据库中最新日期为：{latest_date}")
                    # 解析最新日期
                    latest_dt = None
                    if latest_date:
                        try:
                            latest_dt = datetime.strptime(latest_date[:10], "%Y-%m-%d")
                            logger.info(f"    解析后的最新日期：{latest_dt}")
                        except Exception as e:
                            logger.error(f"    最新日期解析失败：{str(e)}")
                    # 获取第一页以确定总页数
                    first_page_url = get_page_url(base_url, identifier, 1)
                    try:
                        async with session.get(first_page_url, headers=HEADERS) as resp:
                            if resp.status != 200:
                                logger.error(f"    请求失败：{first_page_url} 状态码：{resp.status}")
                                continue
                            first_text = await resp.text()
                    except Exception as e:
                        logger.error(f"    请求 {first_page_url} 出错：{str(e)}")
                        continue
                    soup = BeautifulSoup(first_text, "html.parser")
                    page_span = soup.find("span", class_="pages")
                    total_pages = 1
                    if page_span:
                        ems = page_span.find_all("em")
                        try:
                            total_pages = int(ems[-1].text.strip())
                        except Exception as e:
                            logger.error(f"    解析总页数失败：{str(e)}")
                    logger.info(f"    共 {total_pages} 页")
                    page = 1
                    while page <= total_pages:
                        page_url = get_page_url(base_url, identifier, page)
                        logger.info(f"    爬取第 {page} 页：{page_url}")
                        try:
                            async with session.get(page_url, headers=HEADERS) as resp:
                                if resp.status != 200:
                                    logger.error(f"      第 {page} 页请求失败，状态码：{resp.status}")
                                    break
                                page_text = await resp.text()
                        except Exception as e:
                            logger.error(f"      请求第 {page} 页出错：{str(e)}")
                            break
                        soup = BeautifulSoup(page_text, "html.parser")
                        news_div = soup.find("div", id=container_id)
                        if not news_div:
                            logger.error(f"      未找到 id='{container_id}'，跳过第 {page} 页")
                            break
                        # 解析新闻项，支持列表结构和表格结构
                        page_news = []
                        news_ul = news_div.find("ul", class_="news_list")
                        if news_ul:
                            for li in news_ul.find_all("li"):
                                title_span = li.find("span", class_="news_title") or li.find("span", class_="news_title5")
                                if not title_span:
                                    continue
                                a_tag = title_span.find("a")
                                if not a_tag:
                                    continue
                                title = (a_tag.get("title") or a_tag.text).strip()
                                href = a_tag.get("href", "").strip()
                                if not href:
                                    continue
                                date_span = li.find("span", class_="news_meta") or li.find("span", class_="news_meta1")
                                date_str = date_span.text.strip() if date_span else "日期未知"
                                full_url = href if href.startswith("http") else f"{base_url}{href}"
                                page_news.append((source, cat_name, title, full_url, date_str))
                        else:
                            for tr in news_div.find_all("tr"):
                                tds = tr.find_all("td", class_="main")
                                if len(tds) < 2:
                                    continue
                                title_tag = tds[0].find("a", title=True)
                                if not title_tag:
                                    links = tds[0].find_all("a")
                                    if len(links) >= 2:
                                        title_tag = links[1]
                                    else:
                                        continue
                                title = (title_tag.get("title") or title_tag.text).strip()
                                relative_url = title_tag.get("href", "").strip()
                                if not relative_url:
                                    continue
                                date_td = tds[-1]
                                div_date = date_td.find("div")
                                date_str = (div_date.text if div_date else date_td.text).strip()
                                full_url = relative_url if relative_url.startswith("http") else f"{base_url}{relative_url}"
                                page_news.append((source, cat_name, title, full_url, date_str))
                        if not page_news:
                            logger.info(f"      第 {page} 页无新闻，跳出")
                            break

                        logger.info(f"      第 {page} 页抓取到 {len(page_news)} 条新闻")
                        # 过滤新新闻
                        if not force_update and latest_dt:
                            new_page_news = []
                            for item in page_news:
                                item_date_str = item[4].strip()
                                logger.info(f"        处理新闻《{item[2]}》，日期字符串：'{item_date_str}'")
                                if item_date_str == "日期未知":
                                    logger.info("        日期未知，跳过过滤")
                                    continue
                                try:
                                    item_dt = datetime.strptime(item_date_str[:10], "%Y-%m-%d")
                                    logger.info(f"        解析后的新闻日期：{item_dt}")
                                except Exception as e:
                                    logger.error(f"        日期解析失败：{item_date_str}，错误：{str(e)}")
                                    continue
                                if item_dt > latest_dt:
                                    logger.info(f"        新闻日期 {item_dt} >= 最新日期 {latest_dt}，认为是新新闻")
                                    new_page_news.append(item)
                                else:
                                    logger.info(f"        新闻日期 {item_dt} < 最新日期 {latest_dt}，忽略")
                            if new_page_news:
                                try:
                                    self.db.insert_news(new_page_news, key=f"{source}:{cat_name}")
                                    logger.info(f"      成功写入 {len(new_page_news)} 条新新闻到数据库，Key: {source}:{cat_name}")
                                except Exception as e:
                                    logger.error(f"      写入数据库失败：{str(e)}")
                                new_news_all.extend(new_page_news)
                            else:
                                logger.info(f"      第 {page} 页无新新闻，跳出")
                                break
                            # 若本页部分为旧新闻，则终止后续页抓取
                            if len(new_page_news) < len(page_news):
                                logger.info(f"      {cat_name} 第 {page} 页部分为旧新闻，终止分页抓取")
                                break
                        else:
                            try:
                                self.db.insert_news(page_news, key=f"{source}:{cat_name}")
                                logger.info(f"      写入 {len(page_news)} 条新闻到数据库，Key: {source}:{cat_name}")
                            except Exception as e:
                                logger.error(f"      写入数据库失败：{str(e)}")
                            new_news_all.extend(page_news)
                        page += 1
                        await asyncio.sleep(1)
        logger.info(f"本次更新共获取 {len(new_news_all)} 条新闻")
        return new_news_all




    @filter.command("news")
    async def get_news(self, event: AstrMessageEvent, 
                       source: str = None, 
                       channel: str = None, 
                       page: int = 1, 
                       keyword: str = None, 
                       start_date: str = None, 
                       end_date: str = None):
        """
        获取新闻查询结果。
        
        参数:
          - source: 可选，指定新闻来源（如 教务处、外国语学院、电子科学与工程学院）。
          - channel: 可选，指定栏目（如 zxdt、学院公告、通知公告）。
          - page: 页码，默认 1，每页显示 5 条新闻。
          - keyword: 可选，标题关键词过滤。
          - start_date: 可选，起始发布日期，格式 YYYY-MM-DD。
          - end_date: 可选，结束发布日期，格式 YYYY-MM-DD。
        """
        per_page = 5
        news = self.db.get_news(source=source, channel=channel, page=page, per_page=per_page, 
                                keyword=keyword, start_date=start_date, end_date=end_date)
        if not news:
            yield event.plain_result("暂无更多新闻")
            return
        
        result = event.make_result().message(f"📰 新闻查询结果（第 {page} 页）\n")
        for idx, item in enumerate(news, 1):
            result = result.message(f"{idx}. 【{item[0]} - {item[1]}】{item[2]}\n链接：{item[3]}\n发布日期：{item[4]}\n\n")
        if len(news) == per_page:
            next_cmd = f"/news {source or ''} {channel or ''} {page+1} {keyword or ''} {start_date or ''} {end_date or ''}"
            result = result.message(f"发送 {next_cmd.strip()} 查看下一页")
        yield result

    @filter.command("news auto")
    async def news_auto_subscribe(self, event: AstrMessageEvent):
        """
        指令: /news auto
        将当前会话加入自动更新通知列表（持久化）。
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
        将当前会话从自动更新通知列表中移除（并持久化）。
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
        强制全量更新新闻，无论数据库中是否最新，然后反馈更新数量。
        """
        new_news = await self.check_updates(force_update=True)
        msg = f"全量更新完成，共更新 {len(new_news)} 条新闻。"
        yield event.plain_result(msg)
    
    async def terminate(self):
        self.db.close()
