from abc import ABC, abstractmethod

class NewsFetcher(ABC):
    @abstractmethod
    async def fetch_news(self) -> list:
        """
        抓取新闻数据，返回列表，每条记录格式为 (source, channel, title, url, pub_date)
        """
        pass
