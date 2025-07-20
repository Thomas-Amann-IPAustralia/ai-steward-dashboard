import os
import json
import hashlib
from selenium import webdriver # Use standard Selenium
from selenium_stealth import stealth # Import the stealth library
from bs4 import BeautifulSoup
import google.generativeai as genai
from datetime import datetime, timezone, timedelta
import sys
import shutil
import re
import time
import zipfile
import random
from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager

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

def get_smarter_content_from_url(url_data, driver, driver_type="Direct"):
    """
    Fetches content from a URL, checks for block/error pages, then cleans it.
    """
    url = url_data['url']
    
    try:
        print(f"    -> [{driver_type}] Navigating to {url}")
        driver.get(url)
        
        # Wait for the `body` tag to be present as a baseline check.
        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.TAG_NAME, 'body'))
        )
        
        # More "human" interaction: scroll down the page a bit
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 4);")
        time.sleep(random.uniform(2, 4))
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
        time.sleep(random.uniform(1, 3))
        
        html = driver.page_source

        failure_signatures = [
            "This site can’t be reached", 
            "ERR_HTTP2_PROTOCOL_ERROR",
            "Enable JavaScript and cookies to continue",
            "Checking if the site connection is secure",
            "Just a moment...", 
            "Verifying you are human",
            "DDoS protection by Cloudflare",
            "Access denied"
        ]
        
        page_text_lower = html.lower()
        if any(sig.lower() in page_text_lower for sig in failure_signatures):
            print(f"    -> [{driver_type}] Block page or browser error detected.")
            return None

        soup = BeautifulSoup(html, 'html.parser')
        
        page_body = soup.body
        if page_body:
            tags_to_exclude = ['nav', 'footer', 'header', 'script', 'style', 'aside', '.noprint', '#sidebar']
            for tag_selector in tags_to_exclude:
                for tag in page_body.select(tag_selector):
                    tag.decompose()
            
            return page_body.get_text(separator='\n', strip=True)
        else:
            print(f"    -> [{driver_type}] Page loaded but no body content found.")
            return ""

    except TimeoutException:
        print(f"    -> [{driver_type}] Timed out waiting for page body to load at {url}")
        return None
    except WebDriverException as e:
        print(f"    -> [{driver_type}] WebDriver error for {url}: {type(e).__name__}")
        return None
    except Exception as e:
        print(f"    -> [{driver_type}] An unexpected error occurred while fetching {url}: {e}")
        return None


def generate_md5(text):
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def load_json_file(file_path):
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            try: return json.load(f)
            except json.JSONDecodeError: return {} if file_path == HASHES_FILE else []
    return {} if file_path == HASHES_FILE else []

def save_json_file(data, file_path):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_gemini_analysis(set_name, old_content, new_content):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return {"summary": "Analysis failed: API key not configured.", "analysis": "The Gemini API key was not provided.", "date_time": datetime.now(timezone(timedelta(hours=10))).isoformat(), "priority": "critical"}
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')
    prompt = f"""Analyze changes for a policy document named "{set_name}". Your response MUST be a valid JSON object with four keys: 'summary', 'analysis', 'date_time', and 'priority'.
OLD CONTENT: --- {old_content} ---
NEW CONTENT: --- {new_content} ---"""
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
    if os.path.exists(old_analysis_path): shutil.copy(old_analysis_path, os.path.join(LOG_DIR, f"{set_name}_{log_timestamp}_analysis.json"))
    old_snapshot_path = os.path.join(SNAPSHOTS_DIR, f"{file_id}.txt")
    if os.path.exists(old_snapshot_path): shutil.copy(old_snapshot_path, os.path.join(LOG_DIR, f"{set_name}_{log_timestamp}_snapshot.txt"))

def initialize_driver(with_proxy=False):
    """Initializes a stealth-configured WebDriver."""
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument('--headless=new')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-blink-features=AutomationControlled')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')
    chrome_options.add_argument('--lang=en-US,en;q=0.9')
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)

    if with_proxy:
        proxy_host, proxy_port, proxy_user, proxy_pass = (os.environ.get(k) for k in ["PROXY_HOST", "PROXY_PORT", "PROXY_USER", "PROXY_PASS"])
        if all([proxy_host, proxy_port, proxy_user, proxy_pass]):
            chrome_options.add_argument(f'--proxy-server=http://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}')
        else:
            print("    -> Proxy requested but credentials not found.")
            return None
    
    try:
        # Use webdriver-manager to handle the chromedriver binary
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)

        # Apply stealth measures
        stealth(driver,
                languages=["en-US", "en"],
                vendor="Google Inc.",
                platform="Win32",
                webgl_vendor="Intel Inc.",
                renderer="Intel Iris OpenGL Engine",
                fix_hairline=True,
                )
        
        return driver
    except Exception as e:
        print(f"    -> Failed to initialize WebDriver: {e}")
        return None

def main():
    setup_directories()
    
    policy_sets = load_json_file(POLICY_SETS_FILE)
    previous_hashes = load_json_file(HASHES_FILE)
    current_hashes = {}
    aest_tz = timezone(timedelta(hours=10))

    for policy_set in policy_sets:
        set_name = policy_set["setName"]
        print(f"\nProcessing Policy Set: {set_name}...")
        
        aggregated_content = []
        for url_data in policy_set["urls"]:
            content = None
            driver = None

            # --- Attempt 1: Direct Connection ---
            try:
                if not policy_set.get("force_proxy"):
                    print(f"  -> Attempting direct connection for {url_data['url']}")
                    driver = initialize_driver(with_proxy=False)
                    if driver:
                        content = get_smarter_content_from_url(url_data, driver, "Direct")
            finally:
                if driver:
                    driver.quit()

            # --- Attempt 2: Proxy Connection (if direct failed) ---
            if content is None:
                driver = None 
                try:
                    print(f"  -> Attempting proxy connection for {url_data['url']}")
                    driver = initialize_driver(with_proxy=True)
                    if driver:
                        content = get_smarter_content_from_url(url_data, driver, "Proxy")
                finally:
                    if driver:
                        driver.quit()

            if content:
                aggregated_content.append(f"--- Content from {url_data['url']} ---\n\n{content}")
            else:
                print(f"  -> WARNING: All attempts to fetch content for {url_data['url']} failed.")

        if not aggregated_content:
            print(f"Skipping set '{set_name}' as no content could be fetched.")
            if set_name in previous_hashes: current_hashes[set_name] = previous_hashes[set_name]
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

if __name__ == "__main__":
    main()
