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

class JwcFetcher(NewsFetcher):
    def __init__(self):
        self.source = "教务处"
        self.base_url = "https://jwc.seu.edu.cn"
        # 定义多个栏目：键为栏目名称，值为对应页面标识
        self.categories = {
            "zxdt": "zxdt",
            "jwxx": "jwxx",
            "xjgl": "xjgl",
            "gjjl": "gjjl",
            "sjjx": "sjjx",
            "cbxx": "cbxx",
            "jxyj": "jxyj"
        }
        self.container_id = "wp_news_w8"  # 表格结构

    async def fetch_news(self, force_update: bool = False, latest_dates: dict = None) -> list:
        """
        抓取教务处新闻数据。

        参数:
          - force_update: 若为 True，则全量抓取（不进行增量过滤）；否则仅返回发布时间严格大于对应最新日期的新闻记录。
          - latest_dates: 字典类型，键为栏目名称，值为最新日期字符串（格式 "YYYY-MM-DD"），仅在 force_update 为 False 时使用。

        返回:
          返回新闻列表，每条记录格式为 (source, channel, title, url, pub_date)
        """
        new_news = []
        async with aiohttp.ClientSession() as session:
            for channel, identifier in self.categories.items():
                # 针对当前栏目，从最新日期字典中取出对应值（如果有的话）
                latest_dt = None
                if not force_update and latest_dates and channel in latest_dates:
                    ld_str = latest_dates[channel]
                    try:
                        latest_dt = datetime.strptime(ld_str.strip()[:10], "%Y-%m-%d")
                        logger.info(f"JwcFetcher: 栏目 {channel} 使用最新日期 {latest_dt} 进行增量过滤")
                    except Exception as e:
                        logger.error(f"JwcFetcher: 解析最新日期 {ld_str} 失败：{str(e)}")
                        latest_dt = None
                else:
                    logger.info(f"JwcFetcher: 栏目 {channel} 无最新日期信息，进行全量抓取")
                
                logger.info(f"JwcFetcher: 开始抓取栏目 {channel}（标识：{identifier}）")
                page = 1
                while True:
                    url = get_page_url(self.base_url, identifier, page)
                    logger.info(f"JwcFetcher: 正在抓取第 {page} 页：{url}")
                    try:
                        async with session.get(url, headers=HEADERS) as resp:
                            if resp.status != 200:
                                logger.error(f"JwcFetcher: 第 {page} 页请求失败，状态码：{resp.status}")
                                break
                            text = await resp.text()
                    except Exception as e:
                        logger.error(f"JwcFetcher: 请求第 {page} 页出错：{str(e)}")
                        break

                    soup = BeautifulSoup(text, "html.parser")
                    news_div = soup.find("div", id=self.container_id)
                    if not news_div:
                        logger.error(f"JwcFetcher: 未找到 id='{self.container_id}'，跳出第 {page} 页")
                        break

                    page_news = []
                    # 采用表格结构解析
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
                        full_url = relative_url if relative_url.startswith("http") else f"{self.base_url}{relative_url}"
                        page_news.append((self.source, channel, title, full_url, date_str))
                    
                    if not page_news:
                        logger.info(f"JwcFetcher: 第 {page} 页无新闻，跳出")
                        break

                    # 保存原始抓取数量用于比较
                    original_count = len(page_news)
                    
                    if not force_update and latest_dt:
                        filtered_news = []
                        for item in page_news:
                            item_date_str = item[4].strip()
                            if item_date_str == "日期未知":
                                logger.debug("JwcFetcher: 跳过日期未知的新闻")
                                continue
                            try:
                                item_dt = datetime.strptime(item_date_str[:10], "%Y-%m-%d")
                            except Exception as e:
                                logger.error(f"JwcFetcher: 日期解析失败：{item_date_str} 错误：{str(e)}")
                                continue
                            logger.info(f"JwcFetcher: 比较新闻日期 {item_dt} 与最新日期 {latest_dt}")
                            if item_dt > latest_dt:
                                filtered_news.append(item)
                        if filtered_news:
                            logger.info(f"JwcFetcher: 第 {page} 页过滤后保留 {len(filtered_news)} 条新新闻")
                            # 如果过滤后数量少于原始数量，则认为部分新闻已存在，终止该栏目的分页抓取
                            if len(filtered_news) < original_count:
                                logger.info(f"JwcFetcher: 栏目 {channel} 第 {page} 页部分为旧新闻，终止分页抓取")
                                new_news.extend(filtered_news)
                                break
                            page_news = filtered_news
                        else:
                            logger.info(f"JwcFetcher: 第 {page} 页无新新闻，跳出")
                            break
                    new_news.extend(page_news)
                    logger.info(f"JwcFetcher: 第 {page} 页抓取 {len(page_news)} 条新闻")
                    page += 1
                    await asyncio.sleep(1)
        logger.info(f"JwcFetcher: 总共抓取 {len(new_news)} 条新闻")
        return new_news
