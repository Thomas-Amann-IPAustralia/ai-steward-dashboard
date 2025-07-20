import os
import json
import hashlib
import undetected_chromedriver as uc
from bs4 import BeautifulSoup
import google.generativeai as genai
from datetime import datetime, timezone, timedelta
import sys
import shutil
import re
import time
# We use seleniumwire's webdriver to connect to BrightData
from seleniumwire import webdriver
from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

# --- Configuration ---
POLICY_SETS_FILE = 'policy_sets.json'

# --- Constants ---
HASHES_FILE = 'hashes.json'
SNAPSHOTS_DIR = 'snapshots'
ANALYSIS_DIR = 'analysis'
LOG_DIR = 'logs'

# --- Helper Functions ---

def setup_directories():
    for dir_path in [SNAPSHOTS_DIR, ANALYSIS_DIR, LOG_DIR]:
        os.makedirs(dir_path, exist_ok=True)

def slugify_set_name(set_name):
    return re.sub(r'[^a-zA-Z0-9\-]+', '_', set_name).strip('_')

def get_content_with_selenium(url, driver, driver_type="Direct"):
    """Fetches content using a Selenium-driven browser."""
    try:
        print(f"    -> [{driver_type}] Navigating to {url}")
        driver.get(url)
        WebDriverWait(driver, 60).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(5)
        html = driver.page_source
        
        failure_signatures = ["Enable JavaScript and cookies to continue", "This site can’t be reached", "Checking if the site connection is secure", "net::ERR_CERT_AUTHORITY_INVALID"]
        if any(sig in html for sig in failure_signatures):
            print(f"    -> [{driver_type}] Block page or error detected.")
            return None

        soup = BeautifulSoup(html, 'html.parser')
        main_content = next((soup.select_one(s) for s in ['main', 'article', 'div[role="main"]', '#content']), soup.find('body'))
        return main_content.get_text(separator='\n', strip=True) if main_content else ""
    except (TimeoutException, WebDriverException) as e:
        print(f"    -> [{driver_type}] WebDriver error for {url}: {type(e).__name__}")
        return None

def generate_md5(text):
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def load_json_file(file_path):
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            try: return json.load(f)
            except json.JSONDecodeError: return {}
    return {}

def save_json_file(data, file_path):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_gemini_analysis(set_name, old_content, new_content):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return {"summary": "Analysis failed: API key not configured.", "priority": "critical"}
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = f"""Analyze changes for a policy document named "{set_name}". Respond in valid JSON with keys: 'summary', 'analysis', 'date_time', 'priority'.
OLD: --- {old_content} ---
NEW: --- {new_content} ---"""
    try:
        response = model.generate_content(prompt)
        cleaned_text = re.sub(r'^```json\s*|\s*```$', '', response.text, flags=re.MULTILINE | re.DOTALL).strip()
        analysis_json = json.loads(cleaned_text)
        analysis_json['date_time'] = datetime.now(timezone(timedelta(hours=10))).isoformat()
        return analysis_json
    except Exception as e:
        return {"summary": "Analysis failed.", "analysis": f"API or parsing error: {e}", "date_time": datetime.now(timezone(timedelta(hours=10))).isoformat(), "priority": "medium"}

def save_snapshot(file_id, content):
    with open(os.path.join(SNAPSHOTS_DIR, f"{file_id}.txt"), 'w', encoding='utf-8') as f: f.write(content)

def load_snapshot(file_id):
    path = os.path.join(SNAPSHOTS_DIR, f"{file_id}.txt")
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f: return f.read()
    return ""

def save_analysis(file_id, analysis_data):
    save_json_file(analysis_data, os.path.join(ANALYSIS_DIR, f"{file_id}.json"))

def log_previous_version(set_name, file_id, timestamp):
    log_timestamp = datetime.fromisoformat(timestamp).strftime('%Y%m%d_%H%M%S')
    old_analysis_path = os.path.join(ANALYSIS_DIR, f"{file_id}.json")
    if os.path.exists(old_analysis_path): shutil.copy(old_analysis_path, os.path.join(LOG_DIR, f"{set_name}_{log_timestamp}_analysis.json"))
    old_snapshot_path = os.path.join(SNAPSHOTS_DIR, f"{file_id}.txt")
    if os.path.exists(old_snapshot_path): shutil.copy(old_snapshot_path, os.path.join(LOG_DIR, f"{set_name}_{log_timestamp}_snapshot.txt"))

def initialize_driver(with_proxy=False):
    """Initializes a WebDriver, either locally or connecting to BrightData."""
    try:
        if with_proxy:
            print("    -> Connecting to BrightData Scraping Browser...")
            proxy_user = os.environ.get("PROXY_USER")
            proxy_pass = os.environ.get("PROXY_PASS")
            proxy_host = os.environ.get("PROXY_HOST")
            if not all([proxy_user, proxy_pass, proxy_host]):
                print("    -> BrightData credentials not found.")
                return None
            
            auth = f'{proxy_user}:{proxy_pass}'
            browser_url = f'wss://{auth}@{proxy_host}'
            
            options = webdriver.ChromeOptions()
            seleniumwire_options = {'verify_ssl': False}
            
            # This is the key change, implementing your friend's suggestion
            # Convert the options object to the older capabilities format
            caps = options.to_capabilities()
            
            driver = webdriver.Remote(
                command_executor=browser_url, 
                desired_capabilities=caps,
                seleniumwire_options=seleniumwire_options
            )
            print("    -> Connected to BrightData successfully.")
            return driver
        else:
            print("    -> Initializing local direct WebDriver...")
            options = uc.ChromeOptions()
            options.add_argument('--headless=new')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            return uc.Chrome(options=options)
    except Exception as e:
        print(f"    -> Failed to initialize WebDriver: {e}")
        return None

def main():
    setup_directories()
    driver_direct, driver_proxy = None, None
    
    try:
        policy_sets = load_json_file(POLICY_SETS_FILE)
        previous_hashes = load_json_file(HASHES_FILE)
        current_hashes = {}
        aest_tz = timezone(timedelta(hours=10))

        for policy_set in policy_sets:
            set_name = policy_set["setName"]
            print(f"\nProcessing Policy Set: {set_name}...")
            
            aggregated_content = []
            for url in policy_set["urls"]:
                content = None
                
                if policy_set.get("force_proxy"):
                    if not driver_proxy: driver_proxy = initialize_driver(with_proxy=True)
                    if driver_proxy: content = get_content_with_selenium(url, driver_proxy, "BrightData")
                else:
                    if not driver_direct: driver_direct = initialize_driver()
                    if driver_direct: content = get_content_with_selenium(url, driver_direct, "Direct")
                    
                    if content is None:
                        print(f"  -> Direct failed. Retrying with BrightData...")
                        if not driver_proxy: driver_proxy = initialize_driver(with_proxy=True)
                        if driver_proxy: content = get_content_with_selenium(url, driver_proxy, "BrightData")

                if content:
                    aggregated_content.append(f"--- Content from {url} ---\n\n{content}")
                else:
                    print(f"  -> WARNING: All attempts to fetch content for {url} failed.")

            if not aggregated_content:
                if set_name in previous_hashes: current_hashes[set_name] = previous_hashes[set_name]
                continue

            full_content = "\n\n".join(aggregated_content)
            new_hash = generate_md5(full_content)
            timestamp = datetime.now(aest_tz).isoformat()
            file_id = slugify_set_name(set_name)
            previous_entry = previous_hashes.get(set_name, {})

            current_hashes[set_name] = {"hash": new_hash, "category": policy_set["category"], "urls": policy_set["urls"], "file_id": file_id, "last_checked": timestamp, "last_amended": previous_entry.get("last_amended")}

            if not previous_entry.get("hash"):
                current_hashes[set_name]["last_amended"] = timestamp
                save_snapshot(file_id, full_content)
                save_analysis(file_id, {"summary": "Initial snapshot captured.", "priority": "low", "date_time": timestamp})
            elif new_hash != previous_entry.get("hash"):
                current_hashes[set_name]["last_amended"] = timestamp
                if previous_entry.get("last_checked"): log_previous_version(file_id, file_id, previous_entry.get("last_checked"))
                old_content = load_snapshot(file_id)
                analysis_result = get_gemini_analysis(set_name, old_content, full_content)
                save_analysis(file_id, analysis_result)
                save_snapshot(file_id, full_content)
            
        save_json_file(current_hashes, HASHES_FILE)
        print("\nUpdate check complete.")

    finally:
        if driver_direct: print("Closing direct WebDriver."); driver_direct.quit()
        if driver_proxy: print("Closing BrightData WebDriver."); driver_proxy.quit()

if __name__ == "__main__":
    main()
