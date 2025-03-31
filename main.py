from fastapi import FastAPI, Request, Form, File, UploadFile, Body, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sheets import get_google_sheet_data, get_sheet_columns
from tistory import login_and_save_cookies, post_to_tistory
from scheduler import schedule_post
import json
from datetime import datetime
import shutil
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from pathlib import Path
from starlette.responses import RedirectResponse
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time
from cryptography.fernet import Fernet
import base64
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from selenium.common.exceptions import UnexpectedAlertPresentException, TimeoutException, NoAlertPresentException
from typing import List
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
import pyperclip
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
import re

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="your-secret-key-here")
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# 상태 정보를 저장할 전역 변수
def load_state():
    try:
        with open("post_state.json", "r", encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def save_state(state_data):
    with open("post_state.json", "w", encoding='utf-8') as f:
        json.dump(state_data, f, ensure_ascii=False, indent=2)

state = load_state()

def load_accounts():
    try:
        with open("accounts.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_account(account_name, user_id, password):
    try:
        accounts = {}
        if os.path.exists("accounts.json"):
            with open("accounts.json", "r", encoding='utf-8') as f:
                accounts = json.load(f)
        
        accounts[account_name] = {
            "user_id": user_id,
            "password": password,
            "cookies": None
        }
        
        with open("accounts.json", "w", encoding='utf-8') as f:
            json.dump(accounts, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"계정 저장 중 오류 발생: {str(e)}")
        return False

# 암호화 키 생성 함수
def generate_key(password: str) -> bytes:
    salt = b'fixed_salt_for_session'  # 고정된 솔트 사용
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    return key

# 비밀번호 암호화 함수
def encrypt_password(password: str) -> str:
    key = generate_key("your-secret-key-here")
    f = Fernet(key)
    return f.encrypt(password.encode()).decode()

# 비밀번호 복호화 함수
def decrypt_password(encrypted_password: str) -> str:
    key = generate_key("your-secret-key-here")
    f = Fernet(key)
    return f.decrypt(encrypted_password.encode()).decode()

@app.get("/", response_class=HTMLResponse)
async def read_form(request: Request):
    return templates.TemplateResponse("form.html", {
        "request": request
    })

@app.post("/upload-credentials")
async def upload_credentials(file: UploadFile = File(...)):
    try:
        # 파일 저장 경로 설정
        save_path = os.path.join(os.getcwd(), "credentials.json")
        
        # 파일 저장
        contents = await file.read()
        with open(save_path, "wb") as f:
            f.write(contents)
            
        # 설정 업데이트
        settings = load_sheets_settings()
        settings["credentials_file"] = file.filename
        save_sheets_settings(settings)
        
        return {"success": True, "message": "파일이 성공적으로 업로드되었습니다."}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"파일 업로드 중 오류가 발생했습니다: {str(e)}"}
        )

@app.get("/tistory-login", response_class=HTMLResponse)
async def login_form(request: Request):
    # 저장된 계정 목록 불러오기
    accounts = load_accounts()
    
    # 세션에서 저장된 계정 정보 불러오기
    account_data = request.session.get("account_data", {})
    
    # 암호화된 비밀번호가 있다면 복호화
    password = ""
    if account_data.get("encrypted_password"):
        try:
            password = decrypt_password(account_data["encrypted_password"])
        except Exception:
            password = ""
    
    return templates.TemplateResponse(
        "tistory_login.html", 
        {
            "request": request, 
            "state": state,
            "accounts": accounts,  # 계정 딕셔너리 그대로 전달
            "account_name": account_data.get("account_name", ""),
            "user_id": account_data.get("user_id", ""),
            "password": password,
            "blog_url": account_data.get("blog_url", "")
        }
    )

@app.post("/tistory-login", response_class=HTMLResponse)
async def login_process(
    request: Request,
    account_name: str = Form(...),
    blog_url: str = Form(...),
    user_id: str = Form(...),
    password: str = Form(...)
):
    try:
        # 비밀번호 암호화
        encrypted_password = encrypt_password(password)
        
        # 블로그 주소 정리
        blog_url = blog_url.strip().replace(".tistory.com", "")
        
        # 계정 정보를 세션에 저장
        request.session["account_data"] = {
            "account_name": account_name,
            "user_id": user_id,
            "encrypted_password": encrypted_password,
            "blog_url": blog_url
        }
        
        # 계정 정보 저장
        if not save_account(account_name, user_id, password):
            return templates.TemplateResponse(
                "tistory_login.html",
                {
                    "request": request,
                    "error": "계정 정보 저장 중 오류가 발생했습니다.",
                    "state": state,
                    "account_name": account_name,
                    "user_id": user_id,
                    "blog_url": blog_url
                }
            )
        
        # Chrome WebDriver 설정
        options = webdriver.ChromeOptions()
        options.add_argument('--start-maximized')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')  # 자동화 감지 비활성화
        options.add_argument('--disable-popup-blocking')  # 팝업 차단 비활성화
        options.add_experimental_option('excludeSwitches', ['enable-logging'])
        options.set_capability('unhandledPromptBehavior', 'dismiss')  # alert 자동 닫기
        
        try:
            # 로컬에 설치된 ChromeDriver 경로 설정
            chrome_driver_path = os.path.join(os.getcwd(), 'chromedriver.exe')
            
            # ChromeDriver가 없으면 다운로드
            if not os.path.exists(chrome_driver_path):
                chrome_driver_path = ChromeDriverManager().install()

            service = Service(chrome_driver_path)
            driver = webdriver.Chrome(service=service, options=options)
            driver.implicitly_wait(10)
            
            try:
                # 카카오 로그인 페이지로 직접 이동
                kakao_login_url = "https://accounts.kakao.com/login/?continue=https%3A%2F%2Fkauth.kakao.com%2Foauth%2Fauthorize%3Fclient_id%3D3e6ddd834b023f24221217e370daed18%26prompt%3Dselect_account%26redirect_uri%3Dhttps%253A%252F%252Fwww.tistory.com%252Fauth%252Fkakao%252Fredirect%26response_type%3Dcode"
                print("카카오 로그인 페이지로 이동 중...")
                driver.get(kakao_login_url)
                time.sleep(2)
                
                print(f"현재 URL: {driver.current_url}")
                
                # 이메일 입력
                print("이메일 입력 필드 찾는 중...")
                email_input = WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[name=loginId]"))
                )
                print("이메일 입력 중...")
                email_input.clear()
                email_input.send_keys(user_id)
                print("이메일 입력 완료")
                
                # 비밀번호 입력
                print("비밀번호 입력 필드 찾는 중...")
                password_input = WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "input[name=password]"))
                )
                print("비밀번호 입력 중...")
                password_input.clear()
                password_input.send_keys(password)
                print("비밀번호 입력 완료")
                
                # 로그인 버튼 클릭
                print("로그인 버튼 찾는 중...")
                login_button = WebDriverWait(driver, 20).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type=submit]"))
                )
                print("로그인 버튼 클릭 시도...")
                login_button.click()
                print("로그인 버튼 클릭 완료")
                
                # 로그인 후 페이지 전환 대기
                try:
                    print("페이지 전환 대기 중...")
                    # 티스토리로 리디렉션될 때까지 대기 (최대 30초)
                    WebDriverWait(driver, 30).until(
                        lambda x: any([
                            "tistory.com/dashboard" in x.current_url,
                            "tistory.com/member" in x.current_url,
                            ".tistory.com" in x.current_url,
                            "tistory.com/auth/kakao" in x.current_url
                        ])
                    )
                    print(f"리디렉션 완료. 현재 URL: {driver.current_url}")
                    
                    # 충분한 대기 시간 추가
                    time.sleep(10)
                    
                    # 블로그 관리 페이지로 직접 이동
                    manage_url = f"https://{blog_url}.tistory.com/manage"
                    print(f"블로그 관리 페이지로 이동: {manage_url}")
                    driver.get(manage_url)
                    time.sleep(5)
                    
                    # 현재 URL 출력
                    print(f"현재 URL (관리 페이지): {driver.current_url}")
                    
                    try:
                        # 글쓰기 버튼 찾기 시도
                        print("글쓰기 버튼 찾는 중...")
                        write_button = WebDriverWait(driver, 20).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, ".btn_write, .link_write"))
                        )
                        print("글쓰기 버튼 찾음, 클릭 시도...")
                        write_button.click()
                        print("글쓰기 버튼 클릭 완료")
                        time.sleep(5)  # 글쓰기 페이지 로드 대기
                    except Exception as e:
                        print(f"글쓰기 버튼 찾기 실패, 다른 방법 시도: {str(e)}")
                        # 글쓰기 페이지로 직접 이동
                        write_url = f"https://{blog_url}.tistory.com/manage/newpost"
                        print(f"글쓰기 페이지로 직접 이동: {write_url}")

                        try:
                            print("페이지 이동 시도...")
                            driver.get(write_url)
                            time.sleep(1)
                        except UnexpectedAlertPresentException as e:
                            print(f"UnexpectedAlertPresentException 발생: {str(e)}")
                            try:
                                # 페이지 로딩 강제 중단
                                print("페이지 로딩 중단 시도...")
                                driver.execute_script("window.stop();")
                                
                                # alert 처리
                                alert = driver.switch_to.alert
                                print(f"[예외 처리] alert 감지됨: {alert.text}")
                                alert.dismiss()
                                print("[예외 처리] alert 닫기 완료")
                                time.sleep(2)
                                
                                # 페이지 다시 로드
                                print("페이지 재로딩 시도...")
                                driver.get(write_url)
                                time.sleep(2)
                                print("페이지 재로딩 완료")
                            except Exception as e:
                                print(f"[예외 처리] alert 처리 실패: {str(e)}")

                        # 혹시 get()는 정상적으로 끝났지만 alert가 떠 있는 경우 대비
                        try:
                            alert = driver.switch_to.alert
                            print(f"[정상 흐름] alert 감지됨: {alert.text}")
                            alert.dismiss()
                            print("[정상 흐름] alert 닫기 완료")
                            time.sleep(2)
                        except Exception as e:
                            print("[정상 흐름] alert 없음")
                    
                    print(f"최종 URL: {driver.current_url}")
                    
                    # 에디터 영역이 로드될 때까지 대기
                    print("에디터 영역 로드 대기 중...")
                    editor_selectors = [
                        "#editor",
                        ".textarea_tit",
                        ".editor_area",
                        "#content",
                        "iframe#editor"
                    ]
                    editor_found = False
                    for selector in editor_selectors:
                        try:
                            WebDriverWait(driver, 10).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                            )
                            editor_found = True
                            print(f"에디터 영역 찾음: {selector}")
                            break
                        except:
                            continue

                    if not editor_found:
                        print("에디터 영역을 찾을 수 없어 페이지 새로고침 시도...")
                        driver.refresh()
                        time.sleep(5)
                        
                        # 새로고침 후 다시 알림창 처리
                        try:
                            alert = driver.switch_to.alert
                            print(f"알림창 다시 감지됨: {alert.text}")
                            alert.dismiss()
                            print("알림창 닫기 완료")
                            time.sleep(5)  # 알림창 처리 후 충분히 대기
                        except:
                            print("새로고침 후 알림창 없음")
                    
                    # HTML 모드로 전환
                    try:
                        print("HTML 모드 전환 시도...")

                        # 1. '기본모드' 버튼 클릭
                        mode_button = WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable((By.XPATH, "//button[./span[text()='기본모드']]"))
                        )
                        driver.execute_script("arguments[0].click();", mode_button)
                        print("'기본모드' 클릭 완료")

                        # ✅ 드롭다운 애니메이션 대기 (조금 기다림)
                        time.sleep(1.5)

                        # 2. HTML 모드 div(id=editor-mode-html) 클릭
                        WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.ID, "editor-mode-html"))
                        )
                        html_div = driver.find_element(By.ID, "editor-mode-html")
                        driver.execute_script("arguments[0].click();", html_div)
                        print("HTML 버튼 클릭 완료")

                        # ✅ HTML 클릭 후 모달창 뜨는 시간 대기
                        time.sleep(1)

                        # 3. 브라우저 alert 처리 (모드 변경 확인)
                        print("모드 전환 확인창 대기 중...")
                        WebDriverWait(driver, 5).until(EC.alert_is_present())
                        alert = driver.switch_to.alert
                        print(f"⚠ 알림창 감지됨: {alert.text}")
                        alert.accept()
                        print("✅ 알림창 확인 클릭 완료")

                        # 4. 에디터 iframe 등장 대기 (여러 선택자 시도)
                        print("HTML 에디터 iframe 대기 중...")
                        iframe_found = False
                        iframe_selectors = [
                            "iframe[id*='tiny']",
                            "iframe.tox-edit-area__iframe",
                            "iframe[title='Rich Text Area']",
                            "iframe[title='에디터 영역']"
                        ]

                        for selector in iframe_selectors:
                            try:
                                WebDriverWait(driver, 3).until(
                                    EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                                )
                                iframe_found = True
                                print(f"✅ HTML 에디터 iframe 감지됨 ({selector})")
                                break
                            except Exception:
                                continue

                        if not iframe_found:
                            print("⚠ iframe을 찾을 수 없지만 HTML 모드 전환은 완료된 것으로 간주")
                            
                        print("✅ HTML 모드 전환 프로세스 완료")

                    except Exception as e:
                        print(f"⚠ HTML 모드 전환 중 예외 발생: {str(e)}")
                        print("HTML 모드 전환은 계속 진행합니다.")

                    # 최종 에디터 확인
                    try:
                        final_editor = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, "#editor, .textarea_tit, .editor_area"))
                        )
                        print("에디터 준비 완료")
                        time.sleep(5)  # 에디터 로드 후 충분히 대기
                    except Exception as e:
                        print(f"최종 에디터 확인 실패: {str(e)}")
                        raise Exception("에디터 영역을 찾을 수 없습니다.")
                    
                    # 쿠키 저장
                    print("쿠키 저장 중...")
                    cookies = driver.get_cookies()
                    
                    # accounts.json 파일에 쿠키와 블로그 URL 저장
                    accounts = {}
                    if os.path.exists("accounts.json"):
                        with open("accounts.json", "r", encoding='utf-8') as f:
                            accounts = json.load(f)
                    
                    if account_name in accounts:
                        accounts[account_name].update({
                            "cookies": cookies,
                            "blog_url": f"{blog_url}.tistory.com"
                        })
                        
                        with open("accounts.json", "w", encoding='utf-8') as f:
                            json.dump(accounts, f, ensure_ascii=False, indent=2)
                    
                    print("로그인 프로세스 완료")
                    return templates.TemplateResponse(
                        "tistory_login.html",
                        {
                            "request": request,
                            "message": "로그인에 성공했습니다. 글쓰기 페이지로 이동되었습니다.",
                            "state": state
                        }
                    )
                    
                except Exception as e:
                    raise Exception(f"로그인 후 페이지 전환 실패: {str(e)}")
                
            except Exception as e:
                error_msg = f"로그인 프로세스 중 오류 발생: {str(e)}"
                print(error_msg)  # 서버 로그에 오류 출력
                return templates.TemplateResponse(
                    "tistory_login.html",
                    {
                        "request": request,
                        "error": error_msg,
                        "state": state
                    }
                )
            finally:
                if 'driver' in locals():
                    driver.quit()
            
        except Exception as e:
            error_msg = f"WebDriver 초기화 중 오류 발생: {str(e)}"
            print(error_msg)  # 서버 로그에 오류 출력
            return templates.TemplateResponse(
                "tistory_login.html",
                {
                    "request": request,
                    "error": error_msg,
                    "state": state
                }
            )
            
    except Exception as e:
        return templates.TemplateResponse(
            "tistory_login.html",
            {
                "request": request,
                "error": f"오류가 발생했습니다: {str(e)}",
                "state": state
            }
        )

def write_tistory_post(driver, title, content):
    """
    티스토리 글쓰기 페이지에서 글을 작성하고 발행하는 함수
    """
    try:
        # HTML 모드 전환
        try:
            print("HTML 모드 전환 시도...")
            time.sleep(3)  # 페이지 로드 대기

            # 1. '기본모드' 버튼 클릭
            mode_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[./span[text()='기본모드']]"))
            )
            driver.execute_script("arguments[0].click();", mode_button)
            print("'기본모드' 클릭 완료")

            # ✅ 드롭다운 애니메이션 대기
            time.sleep(1.5)

            # 2. HTML 모드 div(id=editor-mode-html) 클릭
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "editor-mode-html"))
            )
            html_div = driver.find_element(By.ID, "editor-mode-html")
            driver.execute_script("arguments[0].click();", html_div)
            print("HTML 버튼 클릭 완료")

            # ✅ HTML 클릭 후 모달창 뜨는 시간 대기
            time.sleep(1)

            # 3. 브라우저 alert 처리 (모드 변경 확인)
            print("모드 전환 확인창 대기 중...")
            WebDriverWait(driver, 5).until(EC.alert_is_present())
            alert = driver.switch_to.alert
            print(f"⚠ 알림창 감지됨: {alert.text}")
            alert.accept()
            print("✅ 알림창 확인 클릭 완료")
            time.sleep(2)

        except Exception as e:
            print(f"⚠ HTML 모드 전환 중 오류 발생: {str(e)}")
            print("HTML 모드 전환은 계속 진행합니다.")

        # 제목 입력 - 여러 방법으로 시도
        print("제목 입력 필드 찾는 중...")
        title_input = None
        
        # 1. CSS 선택자로 시도 (textarea)
        try:
            title_input = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((
                    By.CSS_SELECTOR,
                    "textarea#post-title-inp.textarea_tit, textarea[placeholder*='제목']"
                ))
            )
            print("CSS 선택자로 제목 입력 필드(textarea) 찾음")
        except Exception as e:
            print(f"CSS 선택자로 제목 입력 필드 찾기 실패: {str(e)}")

        # 2. 모든 textarea 태그 탐색
        if not title_input:
            try:
                print("모든 textarea 태그 탐색 중...")
                textareas = driver.find_elements(By.TAG_NAME, "textarea")
                for textarea in textareas:
                    try:
                        placeholder = textarea.get_attribute("placeholder")
                        textarea_id = textarea.get_attribute("id")
                        if (placeholder and "제목" in placeholder) or textarea_id == "post-title-inp":
                            title_input = textarea
                            print(f"textarea 찾음 - ID: {textarea_id}, Placeholder: {placeholder}")
                            break
                    except:
                        continue
            except Exception as e:
                print(f"textarea 태그 탐색 중 오류 발생: {str(e)}")

        # 3. XPath로 시도
        if not title_input:
            try:
                print("XPath로 제목 입력 필드 찾는 중...")
                title_input = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((
                        By.XPATH,
                        "//textarea[@id='post-title-inp' or contains(@placeholder, '제목')]"
                    ))
                )
                print("XPath로 제목 입력 필드 찾음")
            except Exception as e:
                print(f"XPath로 제목 입력 필드 찾기 실패: {str(e)}")

        if title_input:
            print(f"제목 입력 중: {title}")
            title_input.clear()
            title_input.send_keys(title)
            print("제목 입력 완료")
            time.sleep(1)
        else:
            raise Exception("제목 입력 필드(textarea)를 찾을 수 없습니다.")

        # HTML 본문 입력 - Codemirror 에디터 대상
        print("본문 입력 시도 중...")
        try:
            # [1] 클립보드에 HTML 내용 저장
            print("클립보드에 본문 내용 복사 중...")
            pyperclip.copy(content)
            print("✅ 클립보드에 본문 내용 복사 완료")

            # [2] CodeMirror div 포커스
            print("CodeMirror div 찾아서 클릭 중...")
            codemirror_div = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CLASS_NAME, "CodeMirror"))
            )
            ActionChains(driver).move_to_element(codemirror_div).click().perform()
            time.sleep(1)

            # [3] Ctrl+V 붙여넣기 이벤트 실행
            ActionChains(driver).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
            print(f"[{account_name}] 본문 내용 Ctrl+V 붙여넣기 완료")
            time.sleep(1)
            
        except Exception as e:
            print(f"❌ 본문 입력 실패: {str(e)}")
            raise Exception(f"본문 입력 중 오류 발생: {str(e)}")

        # 1. 완료 버튼 클릭
        print(f"[{account_name}] 완료 버튼 찾는 중...")
        try:
            complete_button = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "button#publish-layer-btn.btn.btn-default"))
            )
            # 버튼이 보이도록 스크롤
            driver.execute_script("arguments[0].scrollIntoView(true);", complete_button)
            time.sleep(1)  # 스크롤 완료 대기
            
            # 버튼 클릭
            driver.execute_script("arguments[0].click();", complete_button)
            print(f"[{account_name}] 완료 버튼 클릭 완료")
            time.sleep(2)  # 완료 클릭 후 팝업 등장 대기
        except Exception as e:
            print(f"[{account_name}] 완료 버튼 클릭 실패: {str(e)}")
            # 다른 선택자로 재시도
            try:
                complete_button = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, ".btn-publish, .btn_publish"))
                )
                driver.execute_script("arguments[0].scrollIntoView(true);", complete_button)
                time.sleep(1)
                driver.execute_script("arguments[0].click();", complete_button)
                print(f"[{account_name}] 완료 버튼 클릭 완료 (대체 선택자)")
                time.sleep(2)
            except Exception as sub_e:
                raise Exception(f"완료 버튼을 찾을 수 없습니다: {str(e)} / {str(sub_e)}")

        # 2. 공개 발행 버튼 클릭
        print(f"[{account_name}] 공개 발행 버튼 찾는 중...")
        try:
            publish_button = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "button#publish-btn.btn.btn-default"))
            )
            # 버튼이 보이도록 스크롤
            driver.execute_script("arguments[0].scrollIntoView(true);", publish_button)
            time.sleep(1)  # 스크롤 완료 대기
            
            # 버튼 클릭
            driver.execute_script("arguments[0].click();", publish_button)
            print(f"[{account_name}] 공개 발행 버튼 클릭 완료")
            time.sleep(3)  # 발행 완료 대기
        except Exception as e:
            print(f"[{account_name}] 공개 발행 버튼 클릭 실패: {str(e)}")
            raise Exception("공개 발행 버튼을 찾을 수 없습니다.")

        return True

    except Exception as e:
        print(f"❌ 글쓰기 중 오류 발생: {str(e)}")
        return False

@app.get("/publish", response_class=HTMLResponse)
async def publish_page(request: Request):
    # accounts.json 파일에서 계정 정보 로드
    accounts = {}
    if os.path.exists("accounts.json"):
        with open("accounts.json", "r", encoding='utf-8') as f:
            accounts = json.load(f)
    
    return templates.TemplateResponse(
        "publish.html",
        {
            "request": request,
            "accounts": accounts
        }
    )

@app.get("/status", response_class=HTMLResponse)
async def status_page(request: Request):
    sheet_data = request.session.get("sheet_data", {})
    return templates.TemplateResponse("status.html", {
        "request": request,
        "state": state,
        "sheet_data": sheet_data
    })

@app.get("/preview/{title}")
async def get_post_preview(request: Request, title: str):
    try:
        print(f"미리보기 요청 - 제목: {title}")  # 로그 추가
        
        # 세션에서 sheet_data 가져오기
        sheet_data = request.session.get("sheet_data", {})
        posts = sheet_data.get("posts", {})  # 딕셔너리로 가져오기
        
        if not posts:
            print("세션에 포스트 데이터가 없음")  # 로그 추가
            return JSONResponse(
                content={"error": "세션에서 포스트 데이터를 찾을 수 없습니다. 구글 시트에서 데이터를 다시 가져와주세요."},
                status_code=404
            )
        
        # 제목으로 포스트 찾기
        post = posts.get(title)
        
        if post:
            print(f"포스트 찾음: {post['title']}")  # 로그 추가
            return JSONResponse(content={"content": post["content"]})
        else:
            print(f"포스트를 찾을 수 없음. 사용 가능한 제목들: {list(posts.keys())}")  # 로그 추가
            return JSONResponse(
                content={"error": "포스트를 찾을 수 없습니다."},
                status_code=404
            )
    except Exception as e:
        print(f"미리보기 에러: {str(e)}")  # 로그 추가
        return JSONResponse(
            content={"error": f"미리보기를 가져오는 중 오류가 발생했습니다: {str(e)}"},
            status_code=500
        ) 

@app.get("/fetch-posts")
async def fetch_posts(request: Request):
    try:
        # 세션에서 구글 시트 설정 가져오기
        sheet_data = request.session.get("sheet_data")
        if not sheet_data:
            return JSONResponse(
                content={"error": "구글 시트 설정이 없습니다. 먼저 '구글 시트 연동' 메뉴에서 구글 시트를 연동해주세요."},
                status_code=400
            )

        if not os.path.exists("credentials.json"):
            return JSONResponse(
                content={"error": "credentials.json 파일이 없습니다. 먼저 '구글 시트 연동' 메뉴에서 파일을 업로드해주세요."},
                status_code=400
            )

        # 필수 설정 값 확인
        required_fields = {
            "url": "구글 시트 URL",
            "name": "시트 이름",
            "title_col": "제목 열",
            "content_col": "내용 열"
        }
        
        for field, name in required_fields.items():
            if not sheet_data.get(field):
                return JSONResponse(
                    content={"error": f"{name}이(가) 설정되지 않았습니다. '구글 시트 연동' 메뉴에서 설정을 완료해주세요."},
                    status_code=400
                )

        # 구글 시트에서 데이터 가져오기
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        credentials = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
        gc = gspread.authorize(credentials)
        
        try:
            # 스프레드시트 열기
            sheet = gc.open_by_url(sheet_data["url"]).worksheet(sheet_data["name"])
        except Exception as e:
            return JSONResponse(
                content={"error": f"구글 시트에 접근할 수 없습니다. URL과 시트 이름이 올바른지 확인해주세요. 오류: {str(e)}"},
                status_code=400
            )
        
        # 모든 데이터 가져오기
        all_values = sheet.get_all_values()
        if not all_values:  # 데이터가 없는 경우
            return JSONResponse(
                content={"error": "구글 시트에 데이터가 없습니다."},
                status_code=400
            )
            
        # 열 번호를 인덱스로 변환 (A=0, B=1, ...)
        try:
            title_col_idx = ord(sheet_data["title_col"].upper()) - ord('A')
            content_col_idx = ord(sheet_data["content_col"].upper()) - ord('A')
            
            if title_col_idx < 0 or content_col_idx < 0:
                raise ValueError("열 이름은 A부터 Z까지의 알파벳이어야 합니다.")
        except Exception as e:
            return JSONResponse(
                content={"error": f"잘못된 열 이름입니다. A부터 Z까지의 알파벳을 입력해주세요. 오류: {str(e)}"},
                status_code=400
            )
        
        # 선택된 열의 데이터 유효성 검사
        has_valid_data = False
        posts = {}
        
        for row in all_values:  # 모든 행 처리
            if len(row) > max(title_col_idx, content_col_idx):  # 행이 충분히 긴 경우에만 처리
                title = row[title_col_idx].strip()
                content = row[content_col_idx].strip()
                if title and content:  # 제목과 내용이 모두 있는 경우만 추가
                    has_valid_data = True
                    posts[title] = {  # 제목을 키로 사용
                        "title": title,
                        "content": content
                    }
        
        if not has_valid_data:
            return JSONResponse(
                content={"error": f"선택한 열({sheet_data['title_col']}열, {sheet_data['content_col']}열)에 데이터가 없습니다."},
                status_code=400
            )
        
        # 세션에 데이터 저장
        sheet_data["posts"] = posts
        request.session["sheet_data"] = sheet_data
        
        print(f"가져온 포스트 수: {len(posts)}")  # 디버깅 로그
        return JSONResponse(content={"posts": list(posts.values())})  # 리스트로 변환하여 반환
        
    except Exception as e:
        print(f"데이터 가져오기 오류: {str(e)}")  # 로그 추가
        return JSONResponse(
            content={"error": f"데이터를 가져오는 중 오류가 발생했습니다: {str(e)}"},
            status_code=400
        ) 

@app.post("/tistory-login/selected-posts")
async def handle_selected_posts(request: Request, data: dict = Body(...)):
    account_name = data.get("accountName")
    selected_posts = data.get("posts", [])

    print(f"\n[{account_name}] 글 발행 프로세스 시작...")

    if not account_name:
        return JSONResponse(
            content={"error": "계정명이 전달되지 않았습니다."},
            status_code=400
        )

    if not selected_posts:
        return JSONResponse(
            content={"error": "발행할 글이 선택되지 않았습니다."},
            status_code=400
        )

    accounts = load_accounts()
    account_data = accounts.get(account_name)

    if not account_data:
        return JSONResponse(
            content={"error": "계정 정보를 찾을 수 없습니다."},
            status_code=404
        )

    try:
        print(f"[{account_name}] Chrome WebDriver 설정 중...")
        # Chrome WebDriver 설정
        options = webdriver.ChromeOptions()
        options.add_argument('--start-maximized')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--disable-popup-blocking')
        options.add_experimental_option('excludeSwitches', ['enable-logging'])
        options.set_capability('unhandledPromptBehavior', 'dismiss')

        # 로컬에 설치된 ChromeDriver 경로 설정
        chrome_driver_path = os.path.join(os.getcwd(), 'chromedriver.exe')
        print(f"[{account_name}] ChromeDriver 경로: {chrome_driver_path}")
        
        # ChromeDriver가 없으면 다운로드
        if not os.path.exists(chrome_driver_path):
            print(f"[{account_name}] ChromeDriver 다운로드 중...")
            chrome_driver_path = ChromeDriverManager().install()

        service = Service(chrome_driver_path)
        driver = webdriver.Chrome(service=service, options=options)
        driver.implicitly_wait(10)

        try:
            # 카카오 로그인 페이지로 이동
            print(f"[{account_name}] 카카오 로그인 페이지로 이동 중...")
            kakao_login_url = "https://accounts.kakao.com/login/?continue=https%3A%2F%2Fkauth.kakao.com%2Foauth%2Fauthorize%3Fclient_id%3D3e6ddd834b023f24221217e370daed18%26prompt%3Dselect_account%26redirect_uri%3Dhttps%253A%252F%252Fwww.tistory.com%252Fauth%252Fkakao%252Fredirect%26response_type%3Dcode"
            driver.get(kakao_login_url)
            time.sleep(2)

            # 로그인 정보 입력
            print(f"[{account_name}] 로그인 정보 입력 중...")
            email_input = WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[name=loginId]"))
            )
            email_input.clear()
            email_input.send_keys(account_data["user_id"])

            password_input = WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[name=password]"))
            )
            password_input.clear()
            password_input.send_keys(account_data["password"])

            # 로그인 버튼 클릭
            print(f"[{account_name}] 로그인 버튼 클릭...")
            login_button = WebDriverWait(driver, 20).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type=submit]"))
            )
            login_button.click()

            # 로그인 후 페이지 전환 대기
            print(f"[{account_name}] 로그인 후 페이지 전환 대기 중...")
            WebDriverWait(driver, 30).until(
                lambda x: any([
                    "tistory.com/dashboard" in x.current_url,
                    "tistory.com/member" in x.current_url,
                    ".tistory.com" in x.current_url,
                    "tistory.com/auth/kakao" in x.current_url
                ])
            )
            time.sleep(5)

            results = []
            for post in selected_posts:
                try:
                    print(f"\n[{account_name}] '{post['title']}' 글 발행 시작...")
                    
                    # 글쓰기 페이지로 이동
                    write_url = f"https://{account_data['blog_url'].replace('.tistory.com', '')}.tistory.com/manage/newpost"
                    print(f"[{account_name}] 글쓰기 페이지로 이동: {write_url}")
                    driver.get(write_url)
                    time.sleep(3)

                    # 저장된 글 알림창 처리
                    try:
                        print(f"[{account_name}] 알림창 확인 중...")
                        alert = driver.switch_to.alert
                        alert.dismiss()
                        time.sleep(2)
                        print(f"[{account_name}] 알림창 처리 완료")
                    except:
                        print(f"[{account_name}] 알림창 없음")

                    # 제목 입력
                    print(f"[{account_name}] 제목 입력 중...")
                    title_input = WebDriverWait(driver, 20).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, "textarea#post-title-inp"))
                    )
                    title_input.clear()
                    title_input.send_keys(post["title"])
                    print(f"[{account_name}] 제목 입력 완료")

                    # HTML 모드 전환
                    try:
                        print(f"[{account_name}] HTML 모드 전환 시도...")
                        time.sleep(2)  # 페이지 로드 대기

                        # 1. '기본모드' 버튼 클릭
                        mode_button = WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable((By.XPATH, "//button[./span[text()='기본모드']]"))
                        )
                        driver.execute_script("arguments[0].click();", mode_button)
                        print(f"[{account_name}] '기본모드' 클릭 완료")

                        # 드롭다운 애니메이션 대기
                        time.sleep(1.5)

                        # 2. HTML 모드 div(id=editor-mode-html) 클릭
                        WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.ID, "editor-mode-html"))
                        )
                        html_div = driver.find_element(By.ID, "editor-mode-html")
                        driver.execute_script("arguments[0].click();", html_div)
                        print(f"[{account_name}] HTML 버튼 클릭 완료")

                        # HTML 클릭 후 모달창 뜨는 시간 대기
                        time.sleep(1)

                        # 3. 브라우저 alert 처리 (모드 변경 확인)
                        print(f"[{account_name}] 모드 전환 확인창 대기 중...")
                        WebDriverWait(driver, 5).until(EC.alert_is_present())
                        alert = driver.switch_to.alert
                        print(f"[{account_name}] 알림창 감지됨: {alert.text}")
                        alert.accept()
                        print(f"[{account_name}] 알림창 확인 클릭 완료")
                        time.sleep(2)

                    except Exception as e:
                        print(f"[{account_name}] HTML 모드 전환 중 오류 발생: {str(e)}")
                        raise Exception("HTML 모드 전환 실패")

                    # HTML 본문 입력 - Codemirror 에디터 대상
                    print(f"[{account_name}] 본문 입력 시도 중...")
                    try:
                        # 클립보드에 HTML 내용 저장
                        print(f"[{account_name}] 클립보드에 본문 내용 복사 중...")
                        pyperclip.copy(post["content"])
                        print(f"[{account_name}] 클립보드에 본문 내용 복사 완료")

                        # CodeMirror div 포커스
                        print(f"[{account_name}] CodeMirror div 찾아서 클릭 중...")
                        codemirror_div = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.CLASS_NAME, "CodeMirror"))
                        )
                        ActionChains(driver).move_to_element(codemirror_div).click().perform()
                        time.sleep(1)

                        # Ctrl+V 붙여넣기 이벤트 실행
                        ActionChains(driver).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
                        print(f"[{account_name}] 본문 내용 Ctrl+V 붙여넣기 완료")
                        time.sleep(1)
                        
                    except Exception as e:
                        print(f"[{account_name}] 본문 입력 실패: {str(e)}")
                        raise Exception(f"본문 입력 중 오류 발생: {str(e)}")

                    # 1. 완료 버튼 클릭
                    print(f"[{account_name}] 완료 버튼 찾는 중...")
                    try:
                        complete_button = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, "button#publish-layer-btn.btn.btn-default"))
                        )
                        # 버튼이 보이도록 스크롤
                        driver.execute_script("arguments[0].scrollIntoView(true);", complete_button)
                        time.sleep(1)  # 스크롤 완료 대기
                        
                        # 버튼 클릭
                        driver.execute_script("arguments[0].click();", complete_button)
                        print(f"[{account_name}] 완료 버튼 클릭 완료")
                        time.sleep(2)  # 완료 클릭 후 팝업 등장 대기
                    except Exception as e:
                        print(f"[{account_name}] 완료 버튼 클릭 실패: {str(e)}")
                        # 다른 선택자로 재시도
                        try:
                            complete_button = WebDriverWait(driver, 5).until(
                                EC.presence_of_element_located((By.CSS_SELECTOR, ".btn-publish, .btn_publish"))
                            )
                            driver.execute_script("arguments[0].scrollIntoView(true);", complete_button)
                            time.sleep(1)
                            driver.execute_script("arguments[0].click();", complete_button)
                            print(f"[{account_name}] 완료 버튼 클릭 완료 (대체 선택자)")
                            time.sleep(2)
                        except Exception as sub_e:
                            raise Exception(f"완료 버튼을 찾을 수 없습니다: {str(e)} / {str(sub_e)}")

                    # 2. 공개 발행 버튼 클릭
                    print(f"[{account_name}] 공개 발행 버튼 찾는 중...")
                    try:
                        publish_button = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, "button#publish-btn.btn.btn-default"))
                        )
                        # 버튼이 보이도록 스크롤
                        driver.execute_script("arguments[0].scrollIntoView(true);", publish_button)
                        time.sleep(1)  # 스크롤 완료 대기
                        
                        # 버튼 클릭
                        driver.execute_script("arguments[0].click();", publish_button)
                        print(f"[{account_name}] 공개 발행 버튼 클릭 완료")
                        time.sleep(3)  # 발행 완료 대기
                    except Exception as e:
                        print(f"[{account_name}] 공개 발행 버튼 클릭 실패: {str(e)}")
                        raise Exception("공개 발행 버튼을 찾을 수 없습니다.")

                    print(f"[{account_name}] '{post['title']}' 글 발행 완료")
                    
                    results.append({
                        "title": post["title"],
                        "status": "성공",
                        "message": "발행 완료"
                    })

                except Exception as e:
                    print(f"[{account_name}] '{post['title']}' 글 발행 실패: {str(e)}")
                    results.append({
                        "title": post["title"],
                        "status": "실패",
                        "message": str(e)
                    })

            return JSONResponse(content={"results": results})

        finally:
            print(f"[{account_name}] WebDriver 종료")
            driver.quit()

    except Exception as e:
        print(f"[{account_name}] 전체 프로세스 실패: {str(e)}")
        return JSONResponse(
            content={"error": f"글 발행 중 오류가 발생했습니다: {str(e)}"},
            status_code=500
        )

@app.get("/get-account/{account_name}")
async def get_account(account_name: str):
    try:
        accounts = load_accounts()
        if account_name not in accounts:
            return JSONResponse(
                content={"error": "계정을 찾을 수 없습니다."},
                status_code=404
            )
        
        account_data = accounts[account_name]
        return JSONResponse(content={
            "account_name": account_name,
            "blog_url": account_data.get("blog_url", ""),
            "user_id": account_data.get("user_id", ""),
            "password": account_data.get("password", "")
        })
    except Exception as e:
        return JSONResponse(
            content={"error": f"계정 정보를 불러오는 중 오류가 발생했습니다: {str(e)}"},
            status_code=500
        )

@app.post("/save-account")
async def save_account_endpoint(
    request: Request,
    account_name: str = Form(...),
    blog_url: str = Form(...),
    user_id: str = Form(...),
    password: str = Form(...)
):
    try:
        # 블로그 주소 정리
        blog_url = blog_url.strip()
        if not blog_url.endswith('.tistory.com'):
            blog_url = f"{blog_url}.tistory.com"
        
        # 계정 정보 저장
        if not save_account(account_name, user_id, password):
            return JSONResponse(
                content={"error": "계정 정보 저장 중 오류가 발생했습니다."},
                status_code=500
            )
        
        # accounts.json 파일에 블로그 URL 추가
        accounts = load_accounts()
        if account_name in accounts:
            accounts[account_name]["blog_url"] = blog_url
            with open("accounts.json", "w", encoding='utf-8') as f:
                json.dump(accounts, f, ensure_ascii=False, indent=2)
        
        return JSONResponse(content={"message": "계정이 성공적으로 저장되었습니다."})
        
    except Exception as e:
        return JSONResponse(
            content={"error": f"계정 저장 중 오류가 발생했습니다: {str(e)}"},
            status_code=500
        ) 

@app.post("/delete-account/{account_name}")
async def delete_account(account_name: str):
    try:
        accounts = load_accounts()
        if account_name in accounts:
            del accounts[account_name]
            with open("accounts.json", "w", encoding='utf-8') as f:
                json.dump(accounts, f, ensure_ascii=False, indent=2)
            return JSONResponse(content={"message": "계정이 성공적으로 삭제되었습니다."})
        else:
            return JSONResponse(
                content={"error": "해당 계정을 찾을 수 없습니다."},
                status_code=404
            )
    except Exception as e:
        return JSONResponse(
            content={"error": f"계정 삭제 중 오류가 발생했습니다: {str(e)}"},
            status_code=500
        ) 

@app.get("/google-sheets/fetch-data")
async def fetch_google_sheets_data():
    try:
        print("구글 시트 데이터 가져오기 시작...")
        
        # sheets_settings.json에서 구글 시트 설정 읽기
        settings = load_sheets_settings()
        if not settings:
            raise Exception("구글 시트 설정이 없습니다. 먼저 구글 시트를 설정해주세요.")
            
        if not settings.get('spreadsheet_id') or not settings.get('sheet_name'):
            raise Exception("구글 시트 ID 또는 시트 이름이 설정되지 않았습니다.")
        
        if not settings.get('title_col') or not settings.get('content_col'):
            raise Exception("제목 열과 내용 열이 설정되지 않았습니다.")
                
        print(f"구글 시트 설정 확인: ID={settings['spreadsheet_id']}, 시트명={settings['sheet_name']}, 제목열={settings['title_col']}, 내용열={settings['content_col']}")

        # credentials.json 파일 확인
        if not os.path.exists("credentials.json"):
            raise Exception("credentials.json 파일이 없습니다. 먼저 인증 파일을 업로드해주세요.")

        try:
            # 구글 시트 API 인증
            print("구글 시트 API 인증 시도...")
            scope = ['https://www.googleapis.com/auth/spreadsheets.readonly']
            credentials = Credentials.from_service_account_file(
                'credentials.json',
                scopes=scope
            )
            
            # 구글 시트 서비스 생성
            service = build('sheets', 'v4', credentials=credentials)
            sheets = service.spreadsheets()
            
            # 설정된 열의 데이터 가져오기 (1행부터)
            title_col = settings['title_col']
            content_col = settings['content_col']
            range_name = f"{settings['sheet_name']}!{title_col}1:{content_col}"
            print(f"데이터 범위 요청: {range_name}")
            
            result = sheets.values().get(
                spreadsheetId=settings['spreadsheet_id'],
                range=range_name
            ).execute()
            
            values = result.get('values', [])
            print(f"가져온 데이터 행 수: {len(values)}")
            
            if not values:
                print("가져온 데이터가 없습니다.")
                return {"posts": []}
            
            # 데이터를 포스트 형식으로 변환
            posts = []
            title_idx = 0
            content_idx = ord(content_col) - ord(title_col)
            
            for row in values:
                if len(row) > content_idx:  # 제목과 내용이 모두 있는 경우만 처리
                    title = row[title_idx].strip()
                    content = row[content_idx].strip()
                    if title and content:  # 빈 값이 아닌 경우만 추가
                        posts.append({
                            "title": title,
                            "content": content
                        })
            
            print(f"변환된 포스트 수: {len(posts)}")
            return {"posts": posts}
            
        except Exception as e:
            print(f"구글 시트 API 호출 중 오류: {str(e)}")
            raise Exception(f"구글 시트에서 데이터를 가져오는 중 오류가 발생했습니다: {str(e)}")
        
    except Exception as e:
        print(f"전체 프로세스 오류: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

def get_credentials():
    """구글 API 인증 정보를 가져오는 함수"""
    try:
        scope = ['https://www.googleapis.com/auth/spreadsheets.readonly']
        credentials = Credentials.from_service_account_file(
            'credentials.json',
            scopes=scope
        )
        return credentials
    except Exception as e:
        raise Exception(f"인증 정보를 불러오는데 실패했습니다: {str(e)}") 

def load_sheets_settings():
    try:
        with open("sheets_settings.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_sheets_settings(settings):
    try:
        with open("sheets_settings.json", "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        print(f"구글 시트 설정 저장 중 오류 발생: {str(e)}")
        return False

@app.post("/save-google-sheet-settings")
async def save_google_sheet_settings(data: dict = Body(...)):
    try:
        # 스프레드시트 URL에서 ID 추출
        spreadsheet_url = data.get("spreadsheet_url", "")
        spreadsheet_id = None
        
        if spreadsheet_url:
            match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", spreadsheet_url)
            if match:
                spreadsheet_id = match.group(1)
            else:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "error": "올바른 스프레드시트 URL이 아닙니다."}
                )
        
        # 필수 필드 검증
        title_col = data.get("title_col")
        content_col = data.get("content_col")
        sheet_name = data.get("sheet_name")
        
        if not all([title_col, content_col, sheet_name]):
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": "필수 입력값이 누락되었습니다."}
            )
            
        # 설정 저장
        settings = {
            "spreadsheet_url": spreadsheet_url,  # URL도 저장
            "spreadsheet_id": spreadsheet_id,
            "sheet_name": sheet_name,
            "title_col": title_col,
            "content_col": content_col
        }
        
        if save_sheets_settings(settings):
            return {"success": True, "message": "설정이 저장되었습니다."}
        else:
            return JSONResponse(
                status_code=500,
                content={"success": False, "error": "설정 저장 중 오류가 발생했습니다."}
            )
            
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"설정 저장 중 오류가 발생했습니다: {str(e)}"}
        )

@app.get("/get-google-sheet-settings")
async def get_google_sheet_settings():
    try:
        settings = load_sheets_settings()
        
        # credentials.json 파일 정보 확인
        credentials_file = None
        if os.path.exists("credentials.json"):
            credentials_file = "credentials.json"
            
        return {
            "success": True,
            "settings": {
                "spreadsheet_url": settings.get("spreadsheet_url"),  # URL도 반환
                "spreadsheet_id": settings.get("spreadsheet_id"),
                "sheet_name": settings.get("sheet_name"),
                "title_col": settings.get("title_col"),
                "content_col": settings.get("content_col"),
                "credentials_file": credentials_file
            }
        }
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"설정을 불러오는 중 오류가 발생했습니다: {str(e)}"}
        ) 