import requests
from bs4 import BeautifulSoup
import pandas as pd
import time

# 基础 URL
base_url = "https://jwc.seu.edu.cn"
# paths = ["zxdt", "jwxx", "xjgl", "gjjl", "sjjx", "cbxx", "jxyj"]  # 要爬取的不同栏目
paths = ["zxdt"]  # 要爬取的不同栏目
list_url_template = base_url + "/{}/list{}.htm"  # {} 处替换路径和页码

# 请求头，防止被封
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

# 存储所有新闻数据
all_news_list = []

# 遍历多个栏目
for path in paths:
    print(f"正在爬取栏目: {path}")
    
    # 爬取第一页，获取总页数
    first_page_url = list_url_template.format(path, 1)
    response = requests.get(first_page_url, headers=headers)

    if response.status_code == 200:
        soup = BeautifulSoup(response.text, "html.parser")

        # 获取总页数
        page_span = soup.find("span", class_="pages")
        total_pages = int(page_span.find_all("em")[-1].text.strip()) if page_span else 1

        print(f"栏目 {path} 总页数: {total_pages}")

        # 遍历所有页面
        for page in range(1, total_pages + 1):
            print(f"正在爬取 {path} 栏目，第 {page} 页...")
            page_url = list_url_template.format(path, page)
            response = requests.get(page_url, headers=headers)
            if response.status_code != 200:
                print(f"第 {page} 页请求失败，跳过...")
                continue
            
            soup = BeautifulSoup(response.text, "html.parser")
            news_div = soup.find("div", id="wp_news_w8")  # 确保找到正确的 div
            if not news_div:
                print(f"未找到 id='wp_news_w8'，跳过 {path} 栏目第 {page} 页...")
                continue

            # 解析新闻列表
            for tr in news_div.find_all("tr"):
                title_tag = tr.find("a", title=True)  # `title` 属性包含完整标题
                date_tag = tr.find("td", class_="main")
                
                

                if title_tag:
                    title = title_tag["title"].strip()  # 获取 title 属性作为标题
                    relative_url = title_tag["href"]
                    # date = date_tag.find("div").text.strip() if date_tag and date_tag.find("div") else "日期未知"
                    tds = tr.find_all("td", class_="main")
                    if len(tds) >= 2 and tds[1].find("div"):
                        date = tds[1].find("div").text.strip()
                    else:
                        date = "日期未知"


                    # 处理相对 URL
                    full_url = relative_url if relative_url.startswith("http") else f"{base_url}{relative_url}"

                    # 存储数据
                    all_news_list.append([path, title, full_url, date])

            # 避免短时间内大量请求，休眠 1 秒
            time.sleep(1)

    else:
        print(f"请求失败，状态码: {response.status_code}")

# 保存到 CSV
df = pd.DataFrame(all_news_list, columns=["栏目", "标题", "链接", "发布日期"])
df.to_csv("seu_news.csv", index=False, encoding="utf-8-sig")

print(f"爬取完成，共爬取 {len(all_news_list)} 条新闻，数据已保存到 seu_news.csv")
