import os
import json
import hashlib
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
from datetime import datetime, timezone, timedelta
import sys
import shutil
import re

# --- Configuration ---
# List of URLs to monitor for changes.
URLS_TO_CHECK = [
    "https://www.tomamann.com/about",
    "https://www.tomamann.com/life-in-silicon",
    "https://www.tomamann.com/hiwthi"
]

# --- Constants for File and Directory Paths ---
HASHES_FILE = 'hashes.json'
SNAPSHOTS_DIR = 'snapshots'
ANALYSIS_DIR = 'analysis'
LOG_DIR = 'logs'

# --- Helper Functions ---

def setup_directories():
    """Ensures that all necessary directories exist."""
    for dir_path in [SNAPSHOTS_DIR, ANALYSIS_DIR, LOG_DIR]:
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)

def slugify_url(url):
    """Converts a URL into a filesystem-safe string."""
    url = re.sub(r'^https?://(www\.)?', '', url)
    url = re.sub(r'[^a-zA-Z0-9\-]+', '_', url).strip('_')
    return url

def get_content_from_url(url):
    """Fetches and extracts the main text content from a URL."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, timeout=20, headers=headers)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        main_content = soup.find('body')
        if main_content:
            return main_content.get_text(separator='\n', strip=True)
        return ""
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return None

def generate_md5(text):
    """Generates an MD5 hash for the given text."""
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def load_hashes():
    """Loads the stored hashes from the JSON file."""
    if os.path.exists(HASHES_FILE):
        with open(HASHES_FILE, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                print(f"Warning: Could not decode {HASHES_FILE}. Starting fresh.")
                return {}
    return {}

def save_hashes(hashes):
    """Saves the hashes to the JSON file."""
    with open(HASHES_FILE, 'w', encoding='utf-8') as f:
        json.dump(hashes, f, indent=4, ensure_ascii=False)

def get_gemini_analysis(old_content, new_content):
    """Sends content to the Gemini API for analysis."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not set.")
        return {
            "summary": "Analysis failed: API key not configured.",
            "analysis": "The Gemini API key was not provided, so no analysis could be performed.",
            "date_time": datetime.now(timezone(timedelta(hours=10))).isoformat(),
            "priority": "critical"
        }
    
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-1.5-flash')

    prompt = f"""
    You are an AI assistant for Australian public servants. Your role is to analyze changes between an OLD and NEW version of a webpage's text content.
    Your analysis should be neutral, factual, and concise.

    Your response MUST be a valid JSON object with four keys: 'summary', 'analysis', 'date_time', and 'priority'.
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
        cleaned_text = response.text.strip().replace('```json', '').replace('```', '')
        return json.loads(cleaned_text)
    except Exception as e:
        print(f"Error calling Gemini API or parsing JSON: {e}")
        return {
            "summary": "Analysis failed.",
            "analysis": f"Could not determine the difference due to an API or parsing error: {e}",
            "date_time": datetime.now(timezone(timedelta(hours=10))).isoformat(),
            "priority": "medium"
        }

def save_snapshot(url_hash, content):
    """Saves the text content to a snapshot file."""
    snapshot_path = os.path.join(SNAPSHOTS_DIR, f"{url_hash}.txt")
    with open(snapshot_path, 'w', encoding='utf-8') as f:
        f.write(content)

def load_snapshot(url_hash):
    """Loads the text content from a snapshot file."""
    snapshot_path = os.path.join(SNAPSHOTS_DIR, f"{url_hash}.txt")
    if os.path.exists(snapshot_path):
        with open(snapshot_path, 'r', encoding='utf-8') as f:
            return f.read()
    return ""

def save_analysis(url_hash, analysis_data):
    """Saves the analysis JSON object to a file."""
    analysis_path = os.path.join(ANALYSIS_DIR, f"{url_hash}.json")
    with open(analysis_path, 'w', encoding='utf-8') as f:
        json.dump(analysis_data, f, indent=4, ensure_ascii=False)

def log_previous_version(url, url_hash, timestamp):
    """Copies the old analysis and snapshot to the logs directory."""
    url_slug = slugify_url(url)
    log_timestamp = datetime.fromisoformat(timestamp).strftime('%Y%m%d_%H%M%S')
    
    old_analysis_path = os.path.join(ANALYSIS_DIR, f"{url_hash}.json")
    old_snapshot_path = os.path.join(SNAPSHOTS_DIR, f"{url_hash}.txt")

    if os.path.exists(old_analysis_path):
        dest_path = os.path.join(LOG_DIR, f"{url_slug}_{log_timestamp}_analysis.json")
        shutil.copy(old_analysis_path, dest_path)
        print(f"  -> Logged old analysis to {dest_path}")

    if os.path.exists(old_snapshot_path):
        dest_path = os.path.-join(LOG_DIR, f"{url_slug}_{log_timestamp}_snapshot.txt")
        shutil.copy(old_snapshot_path, dest_path)
        print(f"  -> Logged old snapshot to {dest_path}")

# --- Main Logic ---

def main():
    """Main function to check websites for updates, analyze changes, and save results."""
    setup_directories()
    previous_hashes = load_hashes()
    current_hashes = previous_hashes.copy()
    
    aest_tz = timezone(timedelta(hours=10))

    for url in URLS_TO_CHECK:
        print(f"Processing {url}...")
        url_hash = generate_md5(url)
        timestamp = datetime.now(aest_tz).isoformat()
        
        new_content = get_content_from_url(url)

        if new_content is None:
            print(f"Skipping {url} due to fetch error.")
            continue

        new_hash = generate_md5(new_content)
        previous_entry = previous_hashes.get(url)

        previous_hash = previous_entry.get("hash") if isinstance(previous_entry, dict) else previous_entry

        if previous_hash is None:
            print(f"  -> First scan for {url}. Saving initial snapshot.")
            save_snapshot(url_hash, new_content)
            initial_analysis = {
                "summary": "Initial snapshot captured.",
                "analysis": "This is the first time this page has been monitored. Future changes will be analyzed.",
                "date_time": timestamp,
                "priority": "low"
            }
            save_analysis(url_hash, initial_analysis)
            current_hashes[url] = {"hash": new_hash, "last_checked": timestamp}

        elif new_hash != previous_hash:
            print(f"  -> Change detected for {url}. Analyzing...")
            
            if isinstance(previous_entry, dict) and previous_entry.get("last_checked"):
                log_previous_version(url, url_hash, previous_entry.get("last_checked"))
            else:
                print("  -> Could not log previous version (no last_checked timestamp found).")

            old_content = load_snapshot(url_hash)
            analysis_result = get_gemini_analysis(old_content, new_content)
            
            save_analysis(url_hash, analysis_result)
            save_snapshot(url_hash, new_content)
            
            current_hashes[url] = {"hash": new_hash, "last_checked": timestamp}
            print(f"  -> Analysis complete. Priority: {analysis_result.get('priority', 'N/A')}")

        else:
            print(f"  -> No changes detected for {url}.")
            if isinstance(current_hashes.get(url), str):
                current_hashes[url] = {"hash": current_hashes[url]}
            current_hashes[url]["last_checked"] = timestamp

    save_hashes(current_hashes)
    print("\nUpdate check complete.")

if __name__ == "__main__":
    main()
