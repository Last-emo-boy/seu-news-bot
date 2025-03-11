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

class SflFetcher(NewsFetcher):
    def __init__(self):
        # 新闻来源名称
        self.source = "外国语学院"
        self.base_url = "https://sfl.seu.edu.cn"
        # 定义栏目：键为显示名称，值为对应的标识
        self.categories = {
            "学院公告": "9827",
            "学生公告": "9828",
            "学术活动": "24046"
        }
        # 该网站的新闻容器ID（列表结构）
        self.container_id = "wp_news_w6"

    async def fetch_news(self, force_update: bool = False, latest_dates: dict = None) -> list:
        """
        抓取外国语学院新闻数据。

        参数:
          - force_update: 是否全量抓取。如果为 True，则不进行增量过滤；
                          否则仅返回发布时间严格大于对应最新日期的新闻记录。
          - latest_dates: 字典，键为栏目名称，值为最新新闻日期字符串（格式 "YYYY-MM-DD"），仅在 force_update 为 False 时使用。

        返回:
          新闻列表，每条记录格式为 (source, channel, title, url, pub_date)
        """
        news_list = []
        async with aiohttp.ClientSession() as session:
            for channel, identifier in self.categories.items():
                # 针对当前栏目，从 latest_dates 字典中获取最新日期
                latest_dt = None
                if not force_update and latest_dates is not None:
                    current_latest = latest_dates.get(channel)
                    if current_latest:
                        try:
                            latest_dt = datetime.strptime(current_latest.strip()[:10], "%Y-%m-%d")
                            logger.info(f"SflFetcher: 栏目 {channel} 使用最新日期 {latest_dt} 进行增量过滤")
                        except Exception as e:
                            logger.error(f"SflFetcher: 解析最新日期 {current_latest} 失败：{str(e)}")
                else:
                    logger.info(f"SflFetcher: 栏目 {channel} 无最新日期信息，进行全量抓取")

                logger.info(f"SflFetcher: 抓取栏目 {channel}（标识：{identifier}）")
                page = 1
                while True:
                    url = get_page_url(self.base_url, identifier, page)
                    logger.info(f"SflFetcher: 正在抓取第 {page} 页：{url}")
                    try:
                        async with session.get(url, headers=HEADERS) as resp:
                            if resp.status != 200:
                                logger.error(f"SflFetcher: 第 {page} 页请求失败，状态码：{resp.status}")
                                break
                            text = await resp.text()
                    except Exception as e:
                        logger.error(f"SflFetcher: 请求第 {page} 页出错：{str(e)}")
                        break

                    soup = BeautifulSoup(text, "html.parser")
                    container = soup.find("div", id=self.container_id)
                    if not container:
                        logger.error(f"SflFetcher: 未找到 id='{self.container_id}'，跳出第 {page} 页")
                        break
                    ul = container.find("ul", class_="news_list")
                    if not ul:
                        logger.info(f"SflFetcher: 第 {page} 页未找到 ul.news_list，跳出")
                        break

                    page_items = []
                    stop_category = False
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
                        include_item = True
                        if not force_update and latest_dt and date_str != "日期未知":
                            try:
                                item_dt = datetime.strptime(date_str.strip()[:10], "%Y-%m-%d")
                                logger.debug(f"SflFetcher: 比较新闻日期 {item_dt} 与最新日期 {latest_dt}")
                                if item_dt <= latest_dt:
                                    include_item = False
                                    stop_category = True
                            except Exception as e:
                                logger.error(f"SflFetcher: 日期解析失败：{date_str} 错误：{str(e)}")
                        if include_item:
                            page_items.append((self.source, channel, title, full_url, date_str))
                    
                    if not page_items:
                        logger.info(f"SflFetcher: 第 {page} 页无新闻或全部为旧新闻，跳出")
                        break

                    news_list.extend(page_items)
                    logger.info(f"SflFetcher: 第 {page} 页抓取 {len(page_items)} 条新闻")
                    if not force_update and latest_dt and stop_category:
                        logger.info(f"SflFetcher: 栏目 {channel} 第 {page} 页检测到旧新闻，终止分页抓取")
                        break
                    page += 1
                    await asyncio.sleep(1)
        logger.info(f"SflFetcher: 总共抓取 {len(news_list)} 条新闻")
        return news_list
