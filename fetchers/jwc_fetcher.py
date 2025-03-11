import asyncio
import aiohttp
from bs4 import BeautifulSoup
from . import NewsFetcher

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

def get_page_url(base_url, identifier, page):
    return f"{base_url}/{identifier}/list.htm" if page == 1 else f"{base_url}/{identifier}/list{page}.htm"

class JwcFetcher(NewsFetcher):
    def __init__(self):
        self.source = "教务处"
        self.base_url = "https://jwc.seu.edu.cn"
        # 定义多个栏目
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

    async def fetch_news(self) -> list:
        new_news = []
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
                    news_div = soup.find("div", id=self.container_id)
                    if not news_div:
                        break
                    # 这里以表格结构为例解析
                    page_news = []
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
                        # 注意：这里可以增加对日期格式的统一处理
                        page_news.append((self.source, channel, title, full_url, date_str))
                    if not page_news:
                        break
                    new_news.extend(page_news)
                    page += 1
                    await asyncio.sleep(1)
        return new_news
