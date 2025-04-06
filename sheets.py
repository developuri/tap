import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
from dotenv import load_dotenv

load_dotenv()

def get_google_credentials():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    
    if os.path.exists('credentials.json'):
        creds = ServiceAccountCredentials.from_json_keyfile_name('credentials.json', scope)
    else:
        creds_dict = {
            "type": "service_account",
            "project_id": os.getenv("GOOGLE_PROJECT_ID"),
            "private_key_id": os.getenv("GOOGLE_PRIVATE_KEY_ID"),
            "private_key": os.getenv("GOOGLE_PRIVATE_KEY").replace('\\n', '\n'),
            "client_email": os.getenv("GOOGLE_CLIENT_EMAIL"),
            "client_id": os.getenv("GOOGLE_CLIENT_ID"),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_x509_cert_url": os.getenv("GOOGLE_CLIENT_X509_CERT_URL")
        }
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    
    return creds

def get_sheet_columns(sheet_url: str, sheet_name: str):
    creds = get_google_credentials()
    client = gspread.authorize(creds)
    
    sheet = client.open_by_url(sheet_url).worksheet(sheet_name)
    num_cols = len(sheet.row_values(1))  # 첫 번째 행의 열 개수
    
    # A부터 시작하는 열 이름 생성
    columns = [chr(65 + i) for i in range(num_cols)]  # A, B, C, ...
    headers = sheet.row_values(1)  # 첫 번째 행의 값들
    
    # 열 이름과 헤더를 조합
    column_list = []
    for i, (col, header) in enumerate(zip(columns, headers)):
        if header:  # 헤더가 있는 경우
            column_list.append({"value": col, "label": f"{col} - {header}"})
        else:  # 헤더가 없는 경우
            column_list.append({"value": col, "label": col})
    
    return column_list

def get_google_sheet_data(sheet_url: str, sheet_name: str, title_col: str, content_col: str):
    creds = get_google_credentials()
    client = gspread.authorize(creds)

    sheet = client.open_by_url(sheet_url).worksheet(sheet_name)

    # 2행부터 데이터 가져오기
    title_data = sheet.col_values(ord(title_col.upper()) - 64)[1:]  # 2행부터 시작
    content_data = sheet.col_values(ord(content_col.upper()) - 64)[1:]  # 2행부터 시작

    return list(zip(title_data, content_data))  # 이미 2행부터의 데이터이므로 [1:] 제거 