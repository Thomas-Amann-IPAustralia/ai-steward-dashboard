import os
import json
import hashlib
from seleniumwire.undetected_chromedriver import Chrome as uc_Chrome
from seleniumwire.undetected_chromedriver import ChromeOptions as uc_ChromeOptions
from bs4 import BeautifulSoup
import google.generativeai as genai
from datetime import datetime, timezone, timedelta
import sys
import shutil
import re
import time
from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

# --- Configuration ---
POLICY_SETS_FILE = 'policy_sets.json'

# --- Constants for File and Directory Paths ---
HASHES_FILE = 'hashes.json'
SNAPSHOTS_DIR = 'snapshots'
ANALYSIS_DIR = 'analysis'
LOG_DIR = 'logs'

# --- Helper Functions ---

def setup_directories():
    """Ensures that all necessary directories exist."""
    for dir_path in [SNAPSHOTS_DIR, ANALYSIS_DIR, LOG_DIR]:
        os.makedirs(dir_path, exist_ok=True)

def slugify_set_name(set_name):
    """Converts a policy set name into a filesystem-safe string."""
    return re.sub(r'[^a-zA-Z0-9\-]+', '_', set_name).strip('_')

def get_smarter_content_from_url(url, driver):
    """
    Fetches content from a URL using a Selenium-driven undetected-chromedriver instance,
    with explicit waits and better error checking.
    """
    try:
        driver.get(url)
        WebDriverWait(driver, 30).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(5)
        html = driver.page_source
        
        failure_signatures = ["Enable JavaScript and cookies to continue", "Waiting for openai.com to respond", "ERR_HTTP2_PROTOCOL_ERROR", "This site can’t be reached", "Checking if the site connection is secure", "net::ERR_CERT_AUTHORITY_INVALID"]
        if any(sig in html for sig in failure_signatures):
            print(f"    -> Block page or certificate error detected for {url}")
            return None

        soup = BeautifulSoup(html, 'html.parser')
        content_selectors = ['main', 'article', 'div[role="main"]', '#content', '#main-content', '.content', '.post-content']
        main_content = next((soup.select_one(s) for s in content_selectors if soup.select_one(s)), soup.find('body'))

        return main_content.get_text(separator='\n', strip=True) if main_content else ""
    except (TimeoutException, WebDriverException) as e:
        print(f"    -> WebDriver error for {url}: {type(e).__name__}")
        return None
    except Exception as e:
        print(f"    -> An unexpected error occurred while fetching {url}: {e}")
        return None

def generate_md5(text):
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def load_json_file(file_path):
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {} if file_path == HASHES_FILE else []
    return {} if file_path == HASHES_FILE else []

def save_json_file(data, file_path):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_gemini_analysis(set_name, old_content, new_content):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"summary": "Analysis failed: API key not configured.", "analysis": "The Gemini API key was not provided.", "date_time": datetime.now(timezone(timedelta(hours=10))).isoformat(), "priority": "critical"}
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = f"""Analyze changes for a policy document named "{set_name}". Your response MUST be a valid JSON object with four keys: 'summary', 'analysis', 'date_time', and 'priority'.

OLD CONTENT:
---
{old_content}
---

NEW CONTENT:
---
{new_content}
---
"""
    try:
        response = model.generate_content(prompt)
        cleaned_text = re.sub(r'^```json\s*|\s*```$', '', response.text, flags=re.MULTILINE | re.DOTALL).strip()
        return json.loads(cleaned_text)
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
    if os.path.exists(old_analysis_path):
        shutil.copy(old_analysis_path, os.path.join(LOG_DIR, f"{set_name}_{log_timestamp}_analysis.json"))
    old_snapshot_path = os.path.join(SNAPSHOTS_DIR, f"{file_id}.txt")
    if os.path.exists(old_snapshot_path):
        shutil.copy(old_snapshot_path, os.path.join(LOG_DIR, f"{set_name}_{log_timestamp}_snapshot.txt"))

def initialize_driver(with_proxy=False):
    """Initializes and returns a WebDriver instance, with or without a proxy."""
    selenium_wire_options = {}
    if with_proxy:
        proxy_host, proxy_port, proxy_user, proxy_pass = (os.environ.get(k) for k in ["PROXY_HOST", "PROXY_PORT", "PROXY_USER", "PROXY_PASS"])
        if all([proxy_host, proxy_port, proxy_user, proxy_pass]):
            print("    -> Configuring WebDriver with proxy.")
            selenium_wire_options['proxy'] = {'http': f'http://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}', 'https': f'https://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}'}
        else:
            print("    -> Proxy requested but credentials not found. Cannot initialize proxy driver.")
            return None

    chrome_options = uc_ChromeOptions()
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    # This is the key change: tell the browser to ignore SSL certificate errors.
    chrome_options.add_argument('--ignore-certificate-errors')
    
    try:
        driver = uc_Chrome(options=chrome_options, seleniumwire_options=selenium_wire_options)
        return driver
    except Exception as e:
        print(f"    -> Failed to initialize WebDriver: {e}")
        return None

def main():
    setup_directories()
    driver_direct = None
    driver_proxy = None
    
    try:
        print("Initializing direct WebDriver...")
        driver_direct = initialize_driver(with_proxy=False)
        if not driver_direct:
            print("FATAL: Could not initialize the direct WebDriver. Exiting.")
            return

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
                use_proxy_on_fail = True
                
                if policy_set.get("force_proxy"):
                    print(f"  -> {url} is flagged to force proxy.")
                    if not driver_proxy: driver_proxy = initialize_driver(with_proxy=True)
                    
                    if driver_proxy:
                        content = get_smarter_content_from_url(url, driver_proxy)
                    else:
                        print("    -> Skipping proxy attempt as proxy driver failed to initialize.")
                    use_proxy_on_fail = False
                else:
                    print(f"  -> Attempting direct connection for {url}...")
                    content = get_smarter_content_from_url(url, driver_direct)

                if content is None and use_proxy_on_fail:
                    print(f"  -> Direct connection failed. Retrying with proxy for {url}...")
                    if not driver_proxy: driver_proxy = initialize_driver(with_proxy=True)
                    
                    if driver_proxy:
                        content = get_smarter_content_from_url(url, driver_proxy)
                    else:
                        print("    -> Skipping proxy attempt as proxy driver failed to initialize.")

                if content:
                    aggregated_content.append(f"--- Content from {url} ---\n\n{content}")
                else:
                    print(f"  -> WARNING: All attempts to fetch content for {url} failed.")

            if not aggregated_content:
                print(f"Skipping set '{set_name}' as no content could be fetched.")
                if set_name in previous_hashes:
                    current_hashes[set_name] = previous_hashes[set_name]
                continue

            full_content = "\n\n".join(aggregated_content)
            new_hash = generate_md5(full_content)
            timestamp = datetime.now(aest_tz).isoformat()
            file_id = slugify_set_name(set_name)
            previous_entry = previous_hashes.get(set_name, {})
            previous_hash = previous_entry.get("hash")

            current_hashes[set_name] = {"hash": new_hash, "category": policy_set["category"], "urls": policy_set["urls"], "file_id": file_id, "last_checked": timestamp, "last_amended": previous_entry.get("last_amended")}

            if not previous_hash:
                print(f"  -> First scan for '{set_name}'.")
                current_hashes[set_name]["last_amended"] = timestamp
                save_snapshot(file_id, full_content)
                save_analysis(file_id, {"summary": "Initial snapshot captured.", "analysis": f"This is the first time the '{set_name}' policy set has been monitored.", "date_time": timestamp, "priority": "low"})
            elif new_hash != previous_hash:
                print(f"  -> Change detected for '{set_name}'. Analyzing...")
                current_hashes[set_name]["last_amended"] = timestamp
                if previous_entry.get("last_checked"): log_previous_version(file_id, file_id, previous_entry.get("last_checked"))
                old_content = load_snapshot(file_id)
                analysis_result = get_gemini_analysis(set_name, old_content, full_content)
                save_analysis(file_id, analysis_result)
                save_snapshot(file_id, full_content)
                print(f"  -> Analysis complete. Priority: {analysis_result.get('priority', 'N/A')}")
            else:
                print(f"  -> No changes detected for '{set_name}'.")

        save_json_file(current_hashes, HASHES_FILE)
        print("\nUpdate check complete.")

    finally:
        if driver_direct:
            print("Closing direct WebDriver.")
            driver_direct.quit()
        if driver_proxy:
            print("Closing proxy WebDriver.")
            driver_proxy.quit()

if __name__ == "__main__":
    main()
