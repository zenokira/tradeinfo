import asyncio
import re
import time
import schedule
from datetime import datetime
from typing import List, Optional, Tuple
from playwright.async_api import async_playwright, Page, Browser, BrowserContext
from __mysql_connect__ import parse_price, parse_percent, insert_energy_data, connect

# 상수 정의
BASE_URL = "https://finance.naver.com"
BOARD_URL = "https://finance.naver.com/item/board.naver?code=530111"
HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

class DataExtractor:
    """데이터 추출 및 처리 클래스"""
    
    @staticmethod
    def extract_third_settlement_price(lines: List[str]) -> str:
        """
        텍스트 라인에서 세 번째 정산가 정보를 추출합니다.
        
        Args:
            lines (List[str]): 텍스트 라인 리스트
            
        Returns:
            str: 추출된 정산가 정보 또는 "데이터 없음"
        """
        pattern = re.compile(r".*(정산가).*")
        matched_lines = []

        for line in lines:
            if pattern.match(line) and not line.startswith("※"):
                matched_lines.append(line.strip())

        return matched_lines[2] if len(matched_lines) > 2 else "데이터 없음"

    @staticmethod
    def string_to_list(text: str) -> List[str]:
        """
        텍스트를 리스트로 변환하고 정리합니다.
        
        Args:
            text (str): 처리할 텍스트
            
        Returns:
            List[str]: 정리된 데이터 리스트
        """
        cleaned = re.sub(r'[\u3000\s]+', ' ', text.strip())
        items = cleaned.split(' ')
        items[1] = f"{items[1]} {items[2]}"
        del items[2]

        if len(items) > 9:
            items[3] = f"{items[3]} {items[4]}"
            del items[4]
        cleaned_values = [item.replace("%", "") for item in items]
        return cleaned_values

class BoardScraper:
    """네이버 금융 게시판 스크래퍼 클래스"""
    
    def __init__(self):
        self.data_extractor = DataExtractor()
        
    async def extract_data(self, page: Page, url: str) -> List[str]:
        """
        게시글에서 데이터를 추출합니다.
        
        Args:
            page (Page): Playwright 페이지 객체
            url (str): 데이터를 추출할 URL
            
        Returns:
            List[str]: 추출된 데이터 리스트
        """
        await page.goto(f"{url}")
        body_text = await page.locator('div#body').inner_text()
        lines = body_text.split("\n")
        line = self.data_extractor.extract_third_settlement_price(lines)
        return self.data_extractor.string_to_list(line)

    async def check_new_post(self, page: Page) -> Optional[str]:
        """
        새로운 게시글의 존재 여부를 확인합니다.
        
        Args:
            page (Page): Playwright 페이지 객체
            
        Returns:
            Optional[str]: 새로운 게시글의 URL 또는 None
        """
        new_icon_link = page.locator('a:has(img[src="https://ssl.pstatic.net/imgstock/images5/new.gif"])')
        
        if await new_icon_link.is_visible():
            link_href = await new_icon_link.get_attribute("href")
            print(f"✅ 새로운 게시글 발견: {link_href}")
            return f"https://finance.naver.com{link_href}"
        return None

    async def process_new_post(self, page: Page, url: str) -> Optional[List[str]]:
        """
        새로운 게시글을 처리하고 데이터를 추출합니다.
        
        Args:
            page (Page): Playwright 페이지 객체
            url (str): 게시글 URL
            
        Returns:
            Optional[List[str]]: 추출된 데이터 또는 None
        """
        await page.goto(url)
        await page.wait_for_selector('div#body')
        
        # 날짜 추출
        date_el = page.locator('td:nth-child(1) > span.tah.p10.gray03')
        date = await date_el.inner_text()
        
        # 데이터 추출
        data = await self.extract_data(page, url)
        if data:
            data.insert(0, date)
            return data
        return None

    async def get_last_page_number(self, page: Page) -> int:
        """
        게시판의 마지막 페이지 번호를 가져옵니다.
        
        Args:
            page (Page): Playwright 페이지 객체
            
        Returns:
            int: 마지막 페이지 번호
        """
        await page.click("a:has-text('맨뒤')")
        await page.wait_for_load_state("load")
        
        current_url = page.url
        match = re.search(r'page=(\d+)', current_url)
        if match:
            return int(match.group(1))
        return 1

    async def process_post(self, subpage: Page, row, date: str, title: str, href: str) -> Optional[List[str]]:
        """
        개별 게시글을 처리하고 데이터를 추출합니다.
        
        Args:
            subpage (Page): Playwright 서브페이지 객체
            row: 게시글 행 객체
            date (str): 게시글 날짜
            title (str): 게시글 제목
            href (str): 게시글 URL
            
        Returns:
            Optional[List[str]]: 추출된 데이터 또는 None
        """
        pattern = r'^\[삼성증권\] \d{1,2}/\d{1,2} 장 전 예상 IIV$'
        if not re.fullmatch(pattern, title):
            return None
            
        full_url = f"https://finance.naver.com{href}"
        data = await self.extract_data(subpage, full_url)
        data.insert(0, date)
        return data

    async def scrape_board(self, conn, cursor) -> None:
        """
        게시판을 스크래핑하고 데이터를 처리합니다.
        
        Args:
            conn: 데이터베이스 연결 객체
            cursor: 데이터베이스 커서 객체
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()
            subpage = await context.new_page()

            await page.goto(BOARD_URL)
            search_input = page.locator('input[name="sw"]')
            await search_input.click()
            await search_input.fill("[삼성증권]")
            search_button = page.locator('img[alt="검색"]')
            await search_button.click()
            await page.wait_for_load_state("load")

            # 새로운 게시글 확인
            new_post_url = await self.check_new_post(page)
            if new_post_url:
                data = await self.process_new_post(page, new_post_url)
                if data:
                    print(f"📅 {data[0]} | 📝 새로운 게시글 데이터")
                    print(f'{data}')
                    insert_energy_data(conn, cursor, data)
                    return

            # 기존 스크래핑 로직
            last_page_number = await self.get_last_page_number(page)
            search_url = re.sub(r'page=\d+', 'page=', page.url)

            for page_number in range(last_page_number, 0, -1):
                await page.goto(f'{search_url}{page_number}')
                await page.wait_for_load_state("load")

                rows = page.locator('table.type2 tr')
                count = await rows.count()

                for i in range(count-1, -1, -1):
                    row = rows.nth(i)
                    date_el = row.locator('td:nth-child(1) > span.tah.p10.gray03')
                    title_el = row.locator('td.title > a')
                    writer_el = row.locator('td.p11')

                    if await date_el.count() > 0 and await title_el.count() > 0:
                        date = await date_el.inner_text()
                        title = await title_el.inner_text()
                        href = await title_el.get_attribute('href')
                        writer = await writer_el.inner_text()

                        if "예상" not in title or "sams****" not in writer:
                            continue

                        data = await self.process_post(subpage, row, date, title, href)
                        if data:
                            print(f"📅 {date} | 📝 {title} | {data}")
                            insert_energy_data(conn, cursor, data)

                time.sleep(5)

            await browser.close()

# 데이터베이스 연결 정보
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': '1234',
    'db': 'energy_data'
}

async def run_scraper():
    """스크래퍼 실행 함수"""
    conn = None
    cursor = None
    
    try:
        print(f"✅ {datetime.now()} 스크래핑 시작")
        
        # 스크래핑 직전에만 데이터베이스 연결
        conn, cursor = connect(**DB_CONFIG)
        if conn and cursor:
            scraper = BoardScraper()
            await scraper.scrape_board(conn, cursor)
            print(f"✅ {datetime.now()} 스크래핑 완료")
        else:
            print(f"❌ {datetime.now()} 데이터베이스 연결 실패")
    except Exception as e:
        print(f"❌ {datetime.now()} 오류 발생: {str(e)}")
    finally:
        # 작업 완료 후 즉시 연결 해제
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        print(f"✅ {datetime.now()} 데이터베이스 연결 종료")

def job():
    """스케줄러 작업"""
    asyncio.run(run_scraper())

def main():
    """메인 실행 함수"""
    # 매일 오전 8시 55분에 실행
    schedule.every().day.at("08:55").do(job)
    
    print(f"✅ {datetime.now()} 스케줄러 시작")
    
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)  # 1분마다 체크
    except KeyboardInterrupt:
        print("\n프로그램 종료 중...")

if __name__ == "__main__":
    main() 
