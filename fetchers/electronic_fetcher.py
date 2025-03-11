import asyncio
import aiohttp
from bs4 import BeautifulSoup
from . import NewsFetcher

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

    async def fetch_news(self) -> list:
        news_list = []
        async with aiohttp.ClientSession() as session:
            for channel, identifier in self.categories.items():
                page = 1
                while True:
                    url = get_page_url(self.base_url, identifier, page)
                    try:
                        async with session.get(url, headers=HEADERS) as resp:
                            if resp.status != 200:
                                break
                            text = await resp.text()
                    except Exception:
                        break
                    soup = BeautifulSoup(text, "html.parser")
                    container = soup.find("div", id=self.container_id)
                    if not container:
                        break
                    ul = container.find("ul", class_="news_list")
                    if not ul:
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
                        break
                    news_list.extend(page_items)
                    page += 1
                    await asyncio.sleep(1)
        return news_list
