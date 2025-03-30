from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import os
import pickle
import json

def login_and_save_cookies(account_name, id, pw):
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 10)

    try:
        driver.get("https://www.tistory.com/auth/login")
        time.sleep(2)

        wait.until(EC.presence_of_element_located((By.NAME, "loginId"))).send_keys(id)
        wait.until(EC.presence_of_element_located((By.NAME, "password"))).send_keys(pw)
        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type=submit]"))).click()
        time.sleep(3)

        cookies = driver.get_cookies()
        pickle.dump(cookies, open(f"cookies_{account_name}.pkl", "wb"))

        # 계정 정보 저장
        try:
            with open("accounts.json", "r", encoding="utf-8") as f:
                accounts = json.load(f)
        except:
            accounts = {}

        accounts[account_name] = {
            "blog_url": f"https://{id}.tistory.com",
            "user_id": id
        }

        with open("accounts.json", "w", encoding="utf-8") as f:
            json.dump(accounts, f, indent=2)

    finally:
        driver.quit()

def post_to_tistory(account_name, blog_url, title, content):
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 10)

    try:
        driver.get("https://www.tistory.com/")
        time.sleep(2)

        cookie_file = f"cookies_{account_name}.pkl"
        if os.path.exists(cookie_file):
            cookies = pickle.load(open(cookie_file, "rb"))
            for cookie in cookies:
                driver.add_cookie(cookie)
            driver.refresh()
            time.sleep(2)

        driver.get(f"{blog_url}/manage/posts/write")
        time.sleep(3)

        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[placeholder='제목을 입력하세요']"))).send_keys(title)
        time.sleep(1)

        iframe = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "iframe[title='에디터 영역']")))
        driver.switch_to.frame(iframe)
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "body"))).send_keys(content)
        driver.switch_to.default_content()
        time.sleep(1)

        wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type=button][class*=publish]"))).click()
        time.sleep(3)

        driver.get(f"{blog_url}/manage/posts")
        time.sleep(2)
        try:
            link = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "a.link_blog"))).get_attribute("href")
        except:
            link = None

        return link

    finally:
        driver.quit() 