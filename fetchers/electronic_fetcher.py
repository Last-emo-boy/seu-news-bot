import asyncio
import aiohttp
from bs4 import BeautifulSoup
from datetime import datetime
from . import NewsFetcher
from astrbot.api import logger

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

def get_page_url(base_url, identifier, page):
    return f"{base_url}/{identifier}/list.htm" if page == 1 else f"{base_url}/{identifier}/list{page}.htm"

class ElectronicFetcher(NewsFetcher):
    def __init__(self):
        self.source = "电子科学与工程学院"
        self.base_url = "https://electronic.seu.edu.cn"
        # 定义栏目：键为显示名称，值为对应的标识
        self.categories = {
            "通知公告": "11484",
            "学生工作": "sywxsgz",
            "本科生培养": "bkswsy"
        }
        self.container_id = "wp_news_w6"  # 列表结构

    async def fetch_news(self, force_update: bool = False, latest_dates: dict = None) -> list:
        """
        抓取电子科学与工程学院新闻数据。

        参数:
          - force_update: 若为 True，则全量抓取（不进行增量过滤）；否则仅返回发布时间严格大于对应最新日期的新闻记录。
          - latest_dates: 字典，键为栏目名称，值为最新日期字符串（格式 "YYYY-MM-DD"），仅在 force_update 为 False 时使用。

        返回:
          返回新闻列表，每条记录格式为 (source, channel, title, url, pub_date)
        """
        news_list = []
        async with aiohttp.ClientSession() as session:
            for channel, identifier in self.categories.items():
                # 如果传入了 latest_dates 并且存在当前栏目，则取出最新日期
                current_latest = None
                if not force_update and latest_dates and channel in latest_dates:
                    current_latest = latest_dates[channel].strip()[:10]
                    try:
                        latest_dt = datetime.strptime(current_latest, "%Y-%m-%d")
                        logger.info(f"ElectronicFetcher: 栏目 {channel} 使用最新日期 {latest_dt} 进行增量过滤")
                    except Exception as e:
                        logger.error(f"ElectronicFetcher: 解析最新日期 {current_latest} 失败：{str(e)}")
                        latest_dt = None
                else:
                    latest_dt = None

                logger.info(f"ElectronicFetcher: 抓取栏目 {channel}（标识：{identifier}）")
                page = 1
                while True:
                    url = get_page_url(self.base_url, identifier, page)
                    logger.info(f"ElectronicFetcher: 正在抓取第 {page} 页：{url}")
                    try:
                        async with session.get(url, headers=HEADERS) as resp:
                            if resp.status != 200:
                                logger.error(f"ElectronicFetcher: 第 {page} 页请求失败，状态码：{resp.status}")
                                break
                            text = await resp.text()
                    except Exception as e:
                        logger.error(f"ElectronicFetcher: 请求第 {page} 页出错：{str(e)}")
                        break

                    soup = BeautifulSoup(text, "html.parser")
                    container = soup.find("div", id=self.container_id)
                    if not container:
                        logger.error(f"ElectronicFetcher: 未找到 id='{self.container_id}'，跳出第 {page} 页")
                        break
                    ul = container.find("ul", class_="news_list")
                    if not ul:
                        logger.info(f"ElectronicFetcher: 第 {page} 页未找到 ul.news_list，跳出")
                        break

                    page_items = []
                    for li in ul.find_all("li"):
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
                        full_url = href if href.startswith("http") else f"{self.base_url}{href}"
                        page_items.append((self.source, channel, title, full_url, date_str))
                    
                    if not page_items:
                        logger.info(f"ElectronicFetcher: 第 {page} 页无新闻，跳出")
                        break

                    if not force_update and latest_dt:
                        filtered_items = []
                        for item in page_items:
                            item_date_str = item[4].strip()
                            if item_date_str == "日期未知":
                                logger.debug("ElectronicFetcher: 跳过日期未知的新闻")
                                continue
                            try:
                                item_dt = datetime.strptime(item_date_str[:10], "%Y-%m-%d")
                            except Exception as e:
                                logger.error(f"ElectronicFetcher: 日期解析失败：{item_date_str} 错误：{str(e)}")
                                continue
                            logger.info(f"ElectronicFetcher: 比较新闻日期 {item_dt} 与最新日期 {latest_dt}")
                            if item_dt > latest_dt:
                                filtered_items.append(item)
                        if filtered_items:
                            logger.info(f"ElectronicFetcher: 第 {page} 页过滤后保留 {len(filtered_items)} 条新新闻")
                            # 如果过滤后数量少于原始数量，则认为后续页均为旧新闻，终止该栏目抓取
                            if len(filtered_items) < len(page_items):
                                logger.info(f"ElectronicFetcher: 栏目 {channel} 第 {page} 页部分为旧新闻，终止分页抓取")
                                news_list.extend(filtered_items)
                                break
                            page_items = filtered_items
                        else:
                            logger.info(f"ElectronicFetcher: 第 {page} 页无新新闻，跳出")
                            break

                    news_list.extend(page_items)
                    logger.info(f"ElectronicFetcher: 第 {page} 页抓取 {len(page_items)} 条新闻")
                    page += 1
                    await asyncio.sleep(1)
        logger.info(f"ElectronicFetcher: 总共抓取 {len(news_list)} 条新闻")
        return news_list
