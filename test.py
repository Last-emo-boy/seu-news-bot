import requests
from bs4 import BeautifulSoup
import pandas as pd
import time

def get_page_url(base_url, identifier, page):
    """
    构造页面 URL：
    - 第一页为 {base_url}/{identifier}/list.htm
    - 其它页为 {base_url}/{identifier}/list{page}.htm
    """
    if page == 1:
        return f"{base_url}/{identifier}/list.htm"
    else:
        return f"{base_url}/{identifier}/list{page}.htm"

# 定义各组信息
groups = [
    {
        "source": "教务处",
        "base_url": "https://jwc.seu.edu.cn",
        "categories": {
            "zxdt": "zxdt"
            # "jwxx": "jwxx",
            # "xjgl": "xjgl",
            # "gjjl": "gjjl",
            # "sjjx": "sjjx",
            # "cbxx": "cbxx",
            # "jxyj": "jxyj"
        },
        "container_id": "wp_news_w8"  # 表格结构
    },
    {
        "source": "外国语学院",
        "base_url": "https://sfl.seu.edu.cn",
        "categories": {
            "学院公告": "9827"
            # "学生公告": "9828",
            # "学术活动": "24046"
        },
        "container_id": "wp_news_w6"  # 列表结构
    },
    {
        "source": "电子科学与工程学院",
        "base_url": "https://electronic.seu.edu.cn",
        "categories": {
            "通知公告": "11484"
            # "学生工作": "sywxsgz",
            # "本科生培养": "bkswsy"
        },
        "container_id": "wp_news_w6"  # 列表结构
    }
]

# 请求头（防止被封）
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

# 存储所有新闻数据
all_news = []

for group in groups:
    source = group["source"]
    base_url = group["base_url"]
    container_id = group["container_id"]
    print(f"正在爬取【{source}】...")
    
    for cat_name, identifier in group["categories"].items():
        print(f"  栏目：{cat_name}（标识：{identifier}）")
        # 构造第一页 URL
        first_page_url = get_page_url(base_url, identifier, 1)
        resp = requests.get(first_page_url, headers=headers)
        if resp.status_code != 200:
            print(f"    请求失败：{first_page_url} 状态码：{resp.status_code}")
            continue
        
        soup = BeautifulSoup(resp.text, "html.parser")
        # 获取总页数（若存在 span.pages，则取最后一个 em，否则默认为 1）
        page_span = soup.find("span", class_="pages")
        if page_span:
            ems = page_span.find_all("em")
            try:
                total_pages = int(ems[-1].text.strip())
            except Exception:
                total_pages = 1
        else:
            total_pages = 1
        print(f"    共 {total_pages} 页")
        
        for page in range(1, total_pages + 1):
            page_url = get_page_url(base_url, identifier, page)
            print(f"    正在爬取第 {page} 页：{page_url}")
            resp = requests.get(page_url, headers=headers)
            if resp.status_code != 200:
                print(f"      第 {page} 页请求失败，跳过")
                continue
            soup = BeautifulSoup(resp.text, "html.parser")
            news_div = soup.find("div", id=container_id)
            if not news_div:
                print(f"      未找到 id='{container_id}'，跳过第 {page} 页")
                continue
            
            # 判断是否采用列表结构（ul.news_list）解析
            news_ul = news_div.find("ul", class_="news_list")
            if news_ul:
                # 列表结构解析：遍历所有 li 元素
                for li in news_ul.find_all("li"):
                    # 尝试查找标题所在的 span（可能是 news_title 或 news_title5）
                    title_span = li.find("span", class_="news_title")
                    if not title_span:
                        title_span = li.find("span", class_="news_title5")
                    if not title_span:
                        continue
                    a_tag = title_span.find("a")
                    if not a_tag:
                        continue
                    # 获取标题：优先取 a 标签 title 属性，否则取文本
                    title = a_tag.get("title", "").strip() or a_tag.text.strip()
                    href = a_tag.get("href", "").strip()
                    if not href:
                        continue
                    # 日期：尝试查找 span.news_meta 或 span.news_meta1
                    date_span = li.find("span", class_="news_meta")
                    if not date_span:
                        date_span = li.find("span", class_="news_meta1")
                    date = date_span.text.strip() if date_span else "日期未知"
                    full_url = href if href.startswith("http") else f"{base_url}{href}"
                    all_news.append([source, cat_name, title, full_url, date])
            else:
                # 表格结构解析（如教务处）：遍历 table 中的 tr
                for tr in news_div.find_all("tr"):
                    tds = tr.find_all("td", class_="main")
                    if len(tds) < 2:
                        continue
                    # 标题从第一个 td 提取：查找带 title 属性的 <a> 标签
                    title_tag = tds[0].find("a", title=True)
                    if not title_tag:
                        links = tds[0].find_all("a")
                        if len(links) >= 2:
                            title_tag = links[1]
                        else:
                            continue
                    title = title_tag.get("title", "").strip() or title_tag.text.strip()
                    relative_url = title_tag.get("href", "").strip()
                    if not relative_url:
                        continue
                    # 日期取最后一个 td 中的 <div> 文本；若不存在则直接取 td 文本
                    date_td = tds[-1]
                    div_date = date_td.find("div")
                    date = div_date.text.strip() if div_date else date_td.text.strip()
                    full_url = relative_url if relative_url.startswith("http") else f"{base_url}{relative_url}"
                    all_news.append([source, cat_name, title, full_url, date])
                    
            # 每页暂停 1 秒，防止请求过快
            time.sleep(1)

print(f"\n爬取完成，共爬取 {len(all_news)} 条新闻。")
df = pd.DataFrame(all_news, columns=["来源", "栏目", "标题", "链接", "发布日期"])
df.to_csv("seu_news.csv", index=False, encoding="utf-8-sig")
print("数据已保存到 seu_news.csv")
