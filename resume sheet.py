from llama_cpp import Llama
import time
import re
import ast
import json
import requests
from bs4 import BeautifulSoup
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CREDENTIALS = Credentials.from_service_account_file("credentials.json", scopes=SCOPES)
sid = "130Wt0KAlckBFin7BdB76sWzAeyAG1F1U8AHYUZByL6I"
service = build("sheets", "v4", credentials=CREDENTIALS)
sheet = service.spreadsheets().values()

def process_urls(llm: Llama, urls: list[str]):
    for url in urls:
        result = sheet.get(spreadsheetId=sid, range="'2026'!A:A").execute()
        values = result.get("values", [])
        header = "Company"
        header_found = False
        empty_row = len(values)+1
        for row_num, row in enumerate(values, start=1):
            if row and row[0] == header:
                header_found = True
            if header_found and not row:
                empty_row = row_num
                break

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False, args=['--window-position=9999,9999'])
                page = browser.new_page()
                page.goto(url)
                time.sleep(6)
                text = page.content()
                browser.close()
        except:
            continue

        # headers = {
        #     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        # }
        # r = requests.get(url, headers=headers)
        # text = r.text

        soup = BeautifulSoup(text, 'html.parser')

        content = soup.get_text().strip()
        content = re.sub(r"\n", "", content)

        response = llm.create_chat_completion(
            messages=[
                {"role": "system", "content": "Given a job listing, return JSON: {company,title,pay}. company: base name, no legal suffixes. title: remove (case-insensitive) intern/internship/co-op/trainee/graduate/campus; keep only core specifics (Python, iOS, Mobile, Full Stack); determine the internship location; if the locaiton is in the US, do not add the location; if the locaiton is not in the US, specify the location in the title. pay: concise. Use '' if no value can be found or inferred. JSON only"},
                {"role": "user", "content": content+"/no_think"},
            ],
            temperature=0.7,
            max_tokens=300,
        )

        answer = response["choices"][0]["message"]["content"]
        formatted = re.findall(r"\{.*\}", answer, re.DOTALL)[0]
        dictionary = ast.literal_eval(formatted)
        info = [dictionary["company"], f"=HYPERLINK(\"{url}\", \"{dictionary["title"]}\")", "Interested", dictionary["pay"]]
        sheet.update(spreadsheetId=sid, range=f"'2026'!A{empty_row}:D{empty_row}", valueInputOption="USER_ENTERED", body={"values": [info]}).execute()


llm = Llama(
    model_path="./Qwen3-8B-Q4_K_M.gguf",
    n_threads=18,
    n_ctx=6000,
    main_gpu=0,
    n_gpu_layers=-1,
)

while True:
    urls = []
    proceed = False
    while True:
        x = input("Enter URL, 'q' to quit or blank to proceed: ")
        if x == "q":
            break
        elif x == "":
            proceed = True
            break
        else:
            urls.append(x)
    if not proceed:
        break
    process_urls(llm, urls)
