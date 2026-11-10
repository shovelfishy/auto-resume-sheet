from llama_cpp import Llama
import time
import re
import ast
import json
import os
from pathlib import Path
from bs4 import BeautifulSoup
from dotenv import dotenv_values
from googleapiclient.discovery import build
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright
from openai import OpenAI
from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode

env_path = Path(__file__).resolve().with_name(".env")
settings = dotenv_values(env_path, encoding="utf-8-sig", interpolate=False)


def required_setting(name: str) -> str:
    value = os.getenv(name) or settings.get(name)
    if not value:
        raise RuntimeError(f"Set {name} in the environment or in {env_path}.")
    return value

USE_LOCAL_LLM = True
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
CREDENTIALS = Credentials.from_service_account_info(
    json.loads(required_setting("GOOGLE_SERVICE_ACCOUNT_JSON")), scopes=SCOPES
)
sid = required_setting("GOOGLE_SHEETS_SPREADSHEET_ID")
service = build("sheets", "v4", credentials=CREDENTIALS)
sheet = service.spreadsheets().values()
client = OpenAI(api_key=required_setting("OPENAI_API_KEY"))

GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"

JOB_INFO_PROMPT = "Given a job listing, return JSON: {company,title,pay}. company: base name, no legal suffixes. title: remove (case-insensitive) intern/internship/co-op/trainee/graduate/campus; keep only core specifics (Python, iOS, Mobile, Full Stack, FDE, etc); determine the internship location; if the location is in the US, add only the city; if the location is not in the US, specify the location in the title. pay: concise, convert to monthly if possible. Use '' if no value can be found or inferred. JSON only"

def log_success(message: str):
    print(f"{GREEN}[ADDED]{RESET} {message}")

def log_error(message: str):
    print(f"{RED}[ERROR]{RESET} {message}")

def extract_job_info(content: str, llm: Llama | None, use_local_llm: bool) -> str:
    if use_local_llm:
        if llm is None:
            raise ValueError("Local LLM mode requires an initialized Llama model.")

        response = llm.create_chat_completion(
            messages=[
                {"role": "system", "content": JOB_INFO_PROMPT},
                {"role": "user", "content": content + "/no_think"},
            ],
            temperature=0.7,
            max_tokens=300,
        )
        return response["choices"][0]["message"]["content"]

    response = client.responses.create(
        model="gpt-5.4",
        instructions=JOB_INFO_PROMPT,
        input=content
    )
    return response.output_text

def process_urls(llm: Llama | None, urls: list[str], use_local_llm: bool):
    with sync_playwright() as p:
        errors = []
        for url in urls:
            result = sheet.get(spreadsheetId=sid, range="'2027'!A:A").execute()
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
                browser = p.chromium.launch(headless=True) #args=['--window-position=9999,9999']
                page = browser.new_page()
                page.goto(url)
                time.sleep(6)
                text = page.content()
            except Exception as e:
                log_error(str(e))
                continue

            # headers = {
            #     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            # }
            # r = requests.get(url, headers=headers)
            # text = r.text

            soup = BeautifulSoup(text, 'html.parser')

            content = soup.get_text().strip()
            content = re.sub(r"\n", "", content)
            try:
                answer = extract_job_info(content, llm, use_local_llm)
                formatted = re.findall(r"\{.*\}", answer, re.DOTALL)[0]
                dictionary = ast.literal_eval(formatted)
                info = [dictionary["company"], f'=HYPERLINK("{url}", "{dictionary["title"]}")', "Interested", dictionary["pay"]]
                sheet.update(spreadsheetId=sid, range=f"'2027'!A{empty_row}:D{empty_row}", valueInputOption="USER_ENTERED", body={"values": [info]}).execute()
                log_success(f'{dictionary["company"]} - {dictionary["title"]}')
            except Exception as e:
                log_error(e)
                errors.append(url)

        if errors:
            print()
            log_error("Failed URLs:")
            for index, item in enumerate(errors, start=1):
                print(f"{index}. {item}")

llm = None

if USE_LOCAL_LLM:
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
        url = input("Enter URL, 'q' to quit or blank to proceed: ")
        if url == "q":
            break
        elif url == "":
            proceed = True
            break
        else:
            parts = urlsplit(url)
            query = dict(parse_qs(parts.query))
            query.pop("utm_source", None)
            new_query = urlencode(query)
            new_url = urlunsplit(parts._replace(query=new_query))

            urls.extend(new_url.split())
    if not proceed:
        break
    process_urls(llm, urls, USE_LOCAL_LLM)