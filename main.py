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
            logger.error(f"加载自动通知列表失败：{str(e)}")
    return set()

def save_auto_notify_origins(origins: set):
    try:
        with open(AUTO_NOTIFY_FILE, "w", encoding="utf-8") as f:
            json.dump(list(origins), f, ensure_ascii=False, indent=2)
        logger.info(f"保存自动通知列表成功：{list(origins)}")
    except Exception as e:
        logger.error(f"保存自动通知列表失败：{str(e)}")

@register("astrbot_plugin_seu_news", "YourName", "新闻订阅与查询插件，模块化抓取多个来源", "1.0.0", "https://github.com/yourrepo/astrbot_plugin_seu_news")
class NewsPlugin(Star):
    def __init__(self, context: Context, config: dict):
        """
        插件初始化时接收配置文件（_conf_schema.json），支持配置项：
          - check_interval: 定时检查新闻更新的间隔（秒），默认 3600 秒
        """
        super().__init__(context)
        self.config = config
        self.db = NewsDB()
        # 初始化各个新闻抓取器
        self.fetchers = [JwcFetcher(), SflFetcher(), ElectronicFetcher()]
        # 自动通知订阅列表（使用 unified_msg_origin 作为标识）
        self.auto_notify_origins = load_auto_notify_origins()
        interval = self.config.get("check_interval", 3600)
        logger.info(f"新闻插件启动，定时检查间隔设置为 {interval} 秒")
        asyncio.create_task(self.scheduled_check(interval=interval))
    
    async def scheduled_check(self, interval: int):
        """
        定时任务：定期调用所有抓取器进行增量更新，
        每个抓取器将接收一个最新日期字典（键为频道，值为最新日期，格式 "YYYY-MM-DD"），
        仅返回发布时间严格大于对应最新日期的新闻，然后写入数据库，
        并向所有自动订阅会话推送新新闻。
        """
        while True:
            logger.info("【定时任务】开始增量更新检查")
            new_news = []
            for fetcher in self.fetchers:
                try:
                    # 为当前抓取器构建最新日期字典
                    latest_dates = {}
                    for channel in fetcher.categories.keys():
                        key = f"{fetcher.source}:{channel}"
                        ld = self.db.get_latest_date(key)
                        if ld:
                            try:
                                ld_str = ld.strip()[:10]
                                latest_dates[channel] = ld_str
                            except Exception as e:
                                logger.error(f"【定时任务】解析数据库最新日期失败：{ld} 错误：{str(e)}")
                    logger.info(f"【定时任务】{fetcher.__class__.__name__} 最新日期字典：{latest_dates}")
                    # 调用 fetch_news 时传入最新日期字典
                    news = await fetcher.fetch_news(force_update=False, latest_dates=latest_dates)
                    logger.info(f"{fetcher.__class__.__name__} 获取到 {len(news)} 条新闻")
                    new_news.extend(news)
                except Exception as e:
                    logger.error(f"【定时任务】{fetcher.__class__.__name__} 抓取新闻失败：{str(e)}")
            # 写入数据库
            for record in new_news:
                source, channel, title, url, pub_date = record
                key = f"{source}:{channel}"
                try:
                    self.db.insert_news([record], key=key)
                    logger.info(f"【定时任务】插入新新闻：{title} ({url})")
                except Exception as e:
                    logger.error(f"【定时任务】插入失败：{title} ({url}) 错误：{str(e)}")
            logger.info(f"【定时任务】增量更新共检测到 {len(new_news)} 条新新闻")
            # 自动通知
            if new_news and self.auto_notify_origins:
                msg_text = f"检测到 {len(new_news)} 条新新闻：\n\n"
                for src, cat, title, url, date_str in new_news:
                    msg_text += f"【{src} - {cat}】 {title}\n链接：{url}\n发布日期：{date_str}\n\n"
                chain = MessageChain().message(msg_text)
                for origin in self.auto_notify_origins:
                    try:
                        await self.context.send_message(origin, chain)
                        logger.info(f"【自动通知】已向 {origin} 推送新新闻")
                    except Exception as e:
                        logger.error(f"【自动通知】发送消息到 {origin} 失败：{str(e)}")
            else:
                logger.info("【定时任务】无新新闻或无自动订阅会话")
            logger.info(f"【定时任务】等待 {interval} 秒后进行下一次更新检查")
            await asyncio.sleep(interval)
    
    @filter.command("news update")
    async def news_update(self, event: AstrMessageEvent):
        """
        指令: /news update
        强制全量抓取新闻（不进行增量过滤），并反馈抓取数量。
        """
        logger.info("【全量更新】开始全量抓取新闻任务")
        all_news = []
        for fetcher in self.fetchers:
            try:
                news = await fetcher.fetch_news(force_update=True)
                logger.info(f"{fetcher.__class__.__name__} 获取到 {len(news)} 条新闻")
                all_news.extend(news)
            except Exception as e:
                logger.error(f"{fetcher.__class__.__name__} 抓取新闻失败：{str(e)}")
        inserted_count = 0
        for record in all_news:
            source, channel, title, url, pub_date = record
            key = f"{source}:{channel}"
            try:
                self.db.insert_news([record], key=key)
                inserted_count += 1
                logger.info(f"【全量更新】插入新闻成功：{title} ({url})")
            except Exception as e:
                logger.error(f"【全量更新】插入新闻失败：{title} ({url}) 错误：{str(e)}")
        msg = f"全量更新完成，共更新 {inserted_count} 条新闻。"
        logger.info(f"【全量更新】{msg}")
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
            logger.info(f"【自动订阅】会话 {origin} 加入自动更新通知列表")
            yield event.plain_result("已将当前会话加入自动更新通知列表。")
    
    @filter.command("news auto off")
    async def news_auto_unsubscribe(self, event: AstrMessageEvent):
        """
        指令: /news auto off
        将当前会话从自动更新通知列表中移除（持久化）。
        """
        origin = event.unified_msg_origin
        # 注意：这里如果出现拼写错误，请确保使用 unified_msg_origin
        origin = event.unified_msg_origin
        if origin in self.auto_notify_origins:
            self.auto_notify_origins.remove(origin)
            save_auto_notify_origins(self.auto_notify_origins)
            logger.info(f"【自动订阅】会话 {origin} 从自动更新通知列表中移除")
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
        查询新闻记录，并先执行一次增量更新检查（仅检测新数据），然后从数据库查询最新结果。

        参数（顺序依次为）：source, channel, page, keyword, start_date, end_date
          - source: 可选，新闻来源（例如 "教务处"）
          - channel: 可选，栏目（例如 "zxdt"）
          - page: 页码，默认为 1，每页显示 5 条新闻
          - keyword: 可选，标题关键词过滤
          - start_date: 可选，起始发布日期（格式 YYYY-MM-DD）
          - end_date: 可选，结束发布日期（格式 YYYY-MM-DD）
        """
        logger.info("【查询】执行 /news 指令前进行增量更新检查")
        # 执行一次增量更新检查：对于所有抓取器，传入 force_update=False
        for fetcher in self.fetchers:
            try:
                # 构建最新日期字典
                latest_dates = {}
                for ch in fetcher.categories.keys():
                    key = f"{fetcher.source}:{ch}"
                    ld = self.db.get_latest_date(key)
                    if ld:
                        try:
                            ld_str = ld.strip()[:10]
                            latest_dates[ch] = ld_str
                        except Exception as e:
                            logger.error(f"【查询】解析最新日期失败：{ld} 错误：{str(e)}")
                logger.info(f"【查询】{fetcher.__class__.__name__} 最新日期字典：{latest_dates}")
                news = await fetcher.fetch_news(force_update=False, latest_dates=latest_dates)
                for record in news:
                    source_, channel_, title, url, pub_date = record
                    key = f"{source_}:{channel_}"
                    latest_date = self.db.get_latest_date(key)
                    latest_dt = None
                    if latest_date:
                        try:
                            latest_dt = datetime.strptime(latest_date.strip()[:10], "%Y-%m-%d")
                        except Exception as e:
                            logger.error(f"【查询】最新日期解析失败：{latest_date} 错误：{str(e)}")
                    try:
                        record_dt = datetime.strptime(pub_date.strip()[:10], "%Y-%m-%d")
                    except Exception as e:
                        logger.error(f"【查询】新闻日期解析失败：{pub_date} 错误：{str(e)}")
                        record_dt = None
                    if latest_dt is None or (record_dt is not None and record_dt > latest_dt):
                        try:
                            self.db.insert_news([record], key=key)
                            logger.info(f"【查询】插入新新闻：{title} ({url})")
                        except Exception as e:
                            logger.error(f"【查询】插入失败：{title} ({url}) 错误：{str(e)}")
            except Exception as e:
                logger.error(f"【查询】{fetcher.__class__.__name__} 抓取新闻失败：{str(e)}")
        per_page = 5
        results = self.db.get_news(source=source, channel=channel, page=page, per_page=per_page, 
                                   keyword=keyword, start_date=start_date, end_date=end_date)
        logger.info(f"【查询】查询新闻: source={source}, channel={channel}, page={page}, keyword={keyword}, start_date={start_date}, end_date={end_date} -> {len(results)} 条记录")
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
