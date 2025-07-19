import os
import json
import hashlib
# Use selenium-wire's undetected_chromedriver to combine proxy support with bot evasion
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
        print(f"    -> Navigating to {url}")
        driver.get(url)
        
        # Explicitly wait for the body of the page to be loaded.
        WebDriverWait(driver, 30).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        
        # A short sleep can still be helpful for dynamic content to settle.
        time.sleep(5)

        html = driver.page_source
        
        # Check for common blocking/error messages.
        failure_signatures = [
            "Enable JavaScript and cookies to continue",
            "Waiting for openai.com to respond",
            "ERR_HTTP2_PROTOCOL_ERROR",
            "This site can’t be reached",
            "Checking if the site connection is secure"
        ]
        if any(sig in html for sig in failure_signatures):
            print(f"    -> Failed: Detected block page or connection error for {url}")
            return None

        soup = BeautifulSoup(html, 'html.parser')
        
        content_selectors = ['main', 'article', 'div[role="main"]', '#content', '#main-content', '.content', '.post-content']
        main_content = None
        for selector in content_selectors:
            main_content = soup.select_one(selector)
            if main_content:
                break
        
        if not main_content:
            main_content = soup.find('body')

        if main_content:
            return main_content.get_text(separator='\n', strip=True)
        return ""
    except TimeoutException:
        print(f"    -> Failed: Timed out waiting for page content to load at {url}")
        return None
    except WebDriverException as e:
        print(f"Error fetching {url} with Selenium: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred while fetching {url}: {e}")
        return None

def generate_md5(text):
    """Generates an MD5 hash for the given text."""
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def load_json_file(file_path):
    """Loads a JSON file with error handling."""
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                print(f"Warning: Could not decode {file_path}. Returning empty.")
                return {} if file_path == HASHES_FILE else []
    return {} if file_path == HASHES_FILE else []

def save_json_file(data, file_path):
    """Saves data to a JSON file."""
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def get_gemini_analysis(set_name, old_content, new_content):
    """Sends content to the Gemini API for analysis."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return {"summary": "Analysis failed: API key not configured.", "analysis": "The Gemini API key was not provided.", "date_time": datetime.now(timezone(timedelta(hours=10))).isoformat(), "priority": "critical"}
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')

    prompt = f"""You are an AI assistant for Australian public servants. Your role is to analyze changes between an OLD and NEW version of a policy document's text content. The document is named "{set_name}". Your response MUST be a valid JSON object with four keys: 'summary', 'analysis', 'date_time', and 'priority'.
- 'summary': A one-sentence summary of the most significant change.
- 'analysis': A detailed, markdown-formatted explanation of what was added, removed, or modified.
- 'date_time': The current timestamp in ISO 8601 format with a +10:00 timezone offset.
- 'priority': Assign a priority level: "critical", "high", "medium", or "low".

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
        return {"summary": "Analysis failed.", "analysis": f"Could not determine the difference due to an API or parsing error: {e}", "date_time": datetime.now(timezone(timedelta(hours=10))).isoformat(), "priority": "medium"}

def save_snapshot(file_id, content):
    snapshot_path = os.path.join(SNAPSHOTS_DIR, f"{file_id}.txt")
    with open(snapshot_path, 'w', encoding='utf-8') as f: f.write(content)

def load_snapshot(file_id):
    snapshot_path = os.path.join(SNAPSHOTS_DIR, f"{file_id}.txt")
    if os.path.exists(snapshot_path):
        with open(snapshot_path, 'r', encoding='utf-8') as f: return f.read()
    return ""

def save_analysis(file_id, analysis_data):
    analysis_path = os.path.join(ANALYSIS_DIR, f"{file_id}.json")
    save_json_file(analysis_data, analysis_path)

def log_previous_version(set_name, file_id, timestamp):
    log_timestamp = datetime.fromisoformat(timestamp).strftime('%Y%m%d_%H%M%S')
    old_analysis_path = os.path.join(ANALYSIS_DIR, f"{file_id}.json")
    if os.path.exists(old_analysis_path):
        shutil.copy(old_analysis_path, os.path.join(LOG_DIR, f"{set_name}_{log_timestamp}_analysis.json"))
    old_snapshot_path = os.path.join(SNAPSHOTS_DIR, f"{file_id}.txt")
    if os.path.exists(old_snapshot_path):
        shutil.copy(old_snapshot_path, os.path.join(LOG_DIR, f"{set_name}_{log_timestamp}_snapshot.txt"))

def main():
    """Main function to check policy sets for updates, analyze, and save results."""
    setup_directories()
    driver = None
    try:
        # --- Proxy Configuration ---
        proxy_host = os.environ.get("PROXY_HOST")
        proxy_port = os.environ.get("PROXY_PORT")
        proxy_user = os.environ.get("PROXY_USER")
        proxy_pass = os.environ.get("PROXY_PASS")

        selenium_wire_options = {}
        if all([proxy_host, proxy_port, proxy_user, proxy_pass]):
            print("-> Proxy credentials found. Configuring proxy...")
            selenium_wire_options = {
                'proxy': {
                    'http': f'http://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}',
                    'https': f'https://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}',
                    'no_proxy': 'localhost,127.0.0.1'
                }
            }
        else:
            print("-> No proxy credentials found in environment variables. Running directly.")

        print("Initializing WebDriver...")
        chrome_options = uc_ChromeOptions()
        chrome_options.add_argument('--headless=new')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        
        # Initialize the driver with proxy options if they exist
        driver = uc_Chrome(
            options=chrome_options,
            seleniumwire_options=selenium_wire_options
        )
        print("WebDriver initialized successfully.")

        policy_sets = load_json_file(POLICY_SETS_FILE)
        if not policy_sets:
            print(f"Error: {POLICY_SETS_FILE} is empty or not found. Exiting.")
            return

        previous_hashes = load_json_file(HASHES_FILE)
        current_hashes = previous_hashes.copy()
        aest_tz = timezone(timedelta(hours=10))

        for policy_set in policy_sets:
            set_name = policy_set["setName"]
            print(f"Processing Policy Set: {set_name}...")
            
            aggregated_content = []
            for url in policy_set["urls"]:
                content = get_smarter_content_from_url(url, driver)
                if content:
                    aggregated_content.append(f"--- Content from {url} ---\n\n{content}")
                else:
                    print(f"  -> WARNING: Failed to fetch content for {url}. It will be excluded from this run.")
            
            if not aggregated_content:
                print(f"Skipping set '{set_name}' as no content could be fetched.")
                continue

            full_content = "\n\n".join(aggregated_content)
            new_hash = generate_md5(full_content)
            timestamp = datetime.now(aest_tz).isoformat()
            file_id = slugify_set_name(set_name)
            
            previous_entry = previous_hashes.get(set_name, {})
            previous_hash = previous_entry.get("hash")

            if not previous_hash:
                print(f"  -> First scan for '{set_name}'.")
                save_snapshot(file_id, full_content)
                initial_analysis = {"summary": "Initial snapshot captured.", "analysis": f"This is the first time the '{set_name}' policy set has been monitored.", "date_time": timestamp, "priority": "low"}
                save_analysis(file_id, initial_analysis)
                current_hashes[set_name] = {"hash": new_hash, "category": policy_set["category"], "urls": policy_set["urls"], "file_id": file_id, "last_checked": timestamp, "last_amended": timestamp}
            elif new_hash != previous_hash:
                print(f"  -> Change detected for '{set_name}'. Analyzing...")
                if previous_entry.get("last_checked"):
                    log_previous_version(file_id, file_id, previous_entry.get("last_checked"))
                
                old_content = load_snapshot(file_id)
                analysis_result = get_gemini_analysis(set_name, old_content, full_content)
                
                save_analysis(file_id, analysis_result)
                save_snapshot(file_id, full_content)
                
                current_hashes[set_name] = {"hash": new_hash, "category": policy_set["category"], "urls": policy_set["urls"], "file_id": file_id, "last_checked": timestamp, "last_amended": timestamp}
                print(f"  -> Analysis complete. Priority: {analysis_result.get('priority', 'N/A')}")
            else:
                print(f"  -> No changes detected for '{set_name}'.")
                current_hashes[set_name]["last_checked"] = timestamp

        save_json_file(current_hashes, HASHES_FILE)
        print("\nUpdate check complete.")

    finally:
        if driver:
            print("Closing WebDriver.")
            driver.quit()

if __name__ == "__main__":
    main()
