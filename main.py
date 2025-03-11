import asyncio
import json
from pathlib import Path
from datetime import datetime

from astrbot.api.all import *
from astrbot.api import logger
from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain

from .news_db import NewsDB
from .fetchers.jwc_fetcher import JwcFetcher
from .fetchers.sfl_fetcher import SflFetcher
from .fetchers.electronic_fetcher import ElectronicFetcher

# 自动通知持久化文件路径
AUTO_NOTIFY_FILE = Path(__file__).parent / "auto_notify.json"

def load_auto_notify_origins():
    if AUTO_NOTIFY_FILE.exists():
        try:
            with open(AUTO_NOTIFY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    logger.info(f"加载自动通知列表：{data}")
                    return set(data)
        except Exception as e:
            logger.exception(f"加载自动通知列表失败：{e}")
    return set()

def save_auto_notify_origins(origins: set):
    try:
        with open(AUTO_NOTIFY_FILE, "w", encoding="utf-8") as f:
            json.dump(list(origins), f, ensure_ascii=False, indent=2)
        logger.info(f"保存自动通知列表成功：{list(origins)}")
    except Exception as e:
        logger.exception(f"保存自动通知列表失败：{e}")

@register("astrbot_plugin_seu_news", "YourName", "新闻订阅与查询插件，模块化抓取多个来源", "1.0.0", "https://github.com/yourrepo/astrbot_plugin_seu_news")
class NewsPlugin(Star):
    def __init__(self, context: Context, config: dict):
        """
        插件初始化时接收配置文件（通过 _conf_schema.json），支持配置项：
          - check_interval: 检查更新的间隔（秒），默认 3600 秒
        """
        super().__init__(context)
        self.config = config
        self.db = NewsDB()
        # 初始化抓取器列表
        self.fetchers = [JwcFetcher(), SflFetcher(), ElectronicFetcher()]
        # 自动通知订阅列表（以 unified_msg_origin 作为标识）
        self.auto_notify_origins = load_auto_notify_origins()
        self.check_interval = self.config.get("check_interval", 3600)
        logger.info(f"新闻插件启动，更新间隔设置为 {self.check_interval} 秒")
        asyncio.create_task(self.scheduled_check())

    async def scheduled_check(self):
        """
        定时任务：定期调用所有抓取器抓取新闻，
        并发写入数据库、并发推送通知，同时记录详细日志便于监控和调试。
        """
        while True:
            logger.info("开始定时抓取新闻任务")
            all_news = []
            try:
                # 并发调用所有抓取器
                fetch_tasks = [asyncio.create_task(fetcher.fetch_news()) for fetcher in self.fetchers]
                results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
                for idx, result in enumerate(results):
                    fetcher = self.fetchers[idx]
                    if isinstance(result, Exception):
                        logger.exception(f"{fetcher.__class__.__name__} 抓取新闻失败：{result}")
                    else:
                        logger.info(f"{fetcher.__class__.__name__} 获取到 {len(result)} 条新闻")
                        all_news.extend(result)
            except Exception as e:
                logger.exception(f"定时抓取任务出错：{e}")
            
            # 数据库插入新闻记录
            inserted_count = 0
            for record in all_news:
                source, channel, title, url, pub_date = record
                key = f"{source}:{channel}"
                try:
                    self.db.insert_news([record], key=key)
                    inserted_count += 1
                    logger.debug(f"插入新闻成功：{title} ({url})")
                except Exception as e:
                    logger.exception(f"插入新闻失败：{title} ({url})，错误：{e}")
            logger.info(f"本次定时抓取处理 {len(all_news)} 条新闻，成功插入 {inserted_count} 条新记录")
            
            # 自动通知订阅会话（并发推送）
            if all_news and self.auto_notify_origins:
                msg_text = f"检测到 {len(all_news)} 条最新新闻：\n\n"
                for src, cat, title, url, date_str in all_news:
                    msg_text += f"【{src} - {cat}】 {title}\n链接：{url}\n发布日期：{date_str}\n\n"
                chain = MessageChain().message(msg_text)
                notify_tasks = [self.send_notification(origin, chain) for origin in self.auto_notify_origins]
                await asyncio.gather(*notify_tasks)
            else:
                logger.info("本次抓取未发现新新闻或无自动订阅会话")
            
            logger.info(f"等待 {self.check_interval} 秒后进行下一次抓取")
            await asyncio.sleep(self.check_interval)
    
    async def send_notification(self, origin, chain):
        try:
            await self.context.send_message(origin, chain)
            logger.info(f"已向 {origin} 推送新新闻")
        except Exception as e:
            logger.exception(f"发送消息到 {origin} 失败：{e}")
    
    @filter.command("news update")
    async def news_update(self, event: AstrMessageEvent):
        """
        指令: /news update
        强制全量抓取新闻（忽略数据库最新记录），并反馈抓取数量。
        """
        all_news = []
        logger.info("开始全量更新新闻任务")
        try:
            fetch_tasks = [asyncio.create_task(fetcher.fetch_news()) for fetcher in self.fetchers]
            results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
            for idx, result in enumerate(results):
                fetcher = self.fetchers[idx]
                if isinstance(result, Exception):
                    logger.exception(f"{fetcher.__class__.__name__} 抓取新闻失败：{result}")
                else:
                    logger.info(f"{fetcher.__class__.__name__} 获取到 {len(result)} 条新闻")
                    all_news.extend(result)
        except Exception as e:
            logger.exception(f"全量更新任务出错：{e}")
        
        inserted_count = 0
        for record in all_news:
            source, channel, title, url, pub_date = record
            key = f"{source}:{channel}"
            try:
                self.db.insert_news([record], key=key)
                inserted_count += 1
                logger.debug(f"插入新闻成功：{title} ({url})")
            except Exception as e:
                logger.exception(f"插入新闻失败：{title} ({url})，错误：{e}")
        msg = f"全量更新完成，共更新 {len(all_news)} 条新闻，成功插入 {inserted_count} 条记录。"
        logger.info(msg)
        yield event.plain_result(msg)
    
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
            logger.info(f"会话 {origin} 加入自动更新通知列表")
            yield event.plain_result("已将当前会话加入自动更新通知列表。")
    
    @filter.command("news auto off")
    async def news_auto_unsubscribe(self, event: AstrMessageEvent):
        """
        指令: /news auto off
        将当前会话从自动更新通知列表中移除（持久化）。
        """
        origin = event.unified_msg_origin
        if origin in self.auto_notify_origins:
            self.auto_notify_origins.remove(origin)
            save_auto_notify_origins(self.auto_notify_origins)
            logger.info(f"会话 {origin} 从自动更新通知列表中移除")
            yield event.plain_result("已将当前会话移除自动更新通知列表。")
        else:
            yield event.plain_result("当前会话不在自动更新列表中。")
    
    @filter.command("news")
    async def get_news(self, event: AstrMessageEvent, 
                       source: str = None, 
                       channel: str = None, 
                       page: int = 1, 
                       keyword: str = None, 
                       start_date: str = None, 
                       end_date: str = None):
        """
        指令: /news
        查询新闻记录。

        参数（顺序依次为）：source, channel, page, keyword, start_date, end_date
          - source: 可选，新闻来源（例如 "教务处"）
          - channel: 可选，栏目（例如 "zxdt"）
          - page: 页码，默认为 1，每页显示 5 条新闻
          - keyword: 可选，标题关键词过滤
          - start_date: 可选，起始发布日期（格式 YYYY-MM-DD）
          - end_date: 可选，结束发布日期（格式 YYYY-MM-DD）
        """
        per_page = 5
        results = self.db.get_news(source=source, channel=channel, page=page, per_page=per_page, 
                                   keyword=keyword, start_date=start_date, end_date=end_date)
        logger.info(f"查询新闻: source={source}, channel={channel}, page={page}, keyword={keyword}, start_date={start_date}, end_date={end_date} -> {len(results)} 条记录")
        if not results:
            yield event.plain_result("暂无更多新闻")
            return
        
        response = event.make_result().message(f"📰 新闻查询结果（第 {page} 页）\n")
        for idx, item in enumerate(results, 1):
            response = response.message(f"{idx}. 【{item[0]} - {item[1]}】{item[2]}\n链接：{item[3]}\n发布日期：{item[4]}\n\n")
        if len(results) == per_page:
            next_cmd = f"/news {source or ''} {channel or ''} {page+1} {keyword or ''} {start_date or ''} {end_date or ''}"
            response = response.message(f"发送 {next_cmd.strip()} 查看下一页")
        yield response

    async def terminate(self):
        self.db.close()
