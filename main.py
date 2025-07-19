import os
import json
import hashlib
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
from datetime import datetime, timezone, timedelta
import sys

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

def get_content_from_url(url):
    """Fetches and extracts the main text content from a URL."""
    try:
        # Use a reasonable timeout and headers to mimic a browser.
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, timeout=20, headers=headers)
        response.raise_for_status()  # Raises an exception for bad status codes (4xx or 5xx).
        soup = BeautifulSoup(response.content, 'html.parser')
        # Find the main body content, which is usually the most relevant part.
        main_content = soup.find('body')
        if main_content:
            # Extract text, using newline as a separator and stripping whitespace.
            return main_content.get_text(separator='\n', strip=True)
        return "" # Return empty string if no body is found
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
    """Saves the hashes to the JSON file with indentation."""
    with open(HASHES_FILE, 'w', encoding='utf-8') as f:
        json.dump(hashes, f, indent=4, ensure_ascii=False)

def get_gemini_analysis(old_content, new_content):
    """
    Sends content to the Gemini API for analysis and returns a structured JSON object.
    """
    # Configure the Gemini API Key from environment variables.
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY environment variable not set.")
        # Return a failure object so the process can continue gracefully.
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
    - 'summary': A one-sentence summary of the most significant change (e.g., "The privacy policy was updated to include a new clause on data sharing.").
    - 'analysis': A detailed, markdown-formatted explanation of what was added, removed, or modified. Use bullet points for clarity.
    - 'date_time': The current timestamp in ISO 8601 format with a +10:00 timezone offset (e.g., "2025-07-13T19:00:00+10:00").
    - 'priority': Assign a priority level from the following options: "critical", "high", "medium", or "low".
      - "critical": For changes with immediate legal, security, or compliance implications (e.g., changes to data sovereignty clauses).
      - "high": For significant policy changes requiring prompt review.
      - "medium": For notable changes that are not urgent.
      - "low": For minor changes like typo fixes, formatting, or clarifications.

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
        # Clean the response text to ensure it's valid JSON.
        cleaned_text = response.text.strip().replace('```json', '').replace('```', '')
        return json.loads(cleaned_text)
    except Exception as e:
        print(f"Error calling Gemini API or parsing JSON: {e}")
        # Provide a fallback error object in case of API or parsing failure.
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
    return "" # Return empty string if no snapshot exists

def save_analysis(url_hash, analysis_data):
    """Saves the analysis JSON object to a file."""
    analysis_path = os.path.join(ANALYSIS_DIR, f"{url_hash}.json")
    with open(analysis_path, 'w', encoding='utf-8') as f:
        json.dump(analysis_data, f, indent=4, ensure_ascii=False)

# --- Main Logic ---

def main():
    """
    Main function to check websites for updates, analyze changes,
    and save the results.
    """
    setup_directories()
    previous_hashes = load_hashes()
    current_hashes = previous_hashes.copy()
    
    # SUGGESTION IMPLEMENTED: Moved timezone object creation out of the loop.
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

        # SUGGESTION IMPLEMENTED: Handle both old (string) and new (dict) hash formats.
        if isinstance(previous_entry, dict):
            previous_hash = previous_entry.get("hash")
        else:
            previous_hash = previous_entry  # Handles string or None

        if previous_hash is None:
            # This is the first time we've seen this URL.
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
            # The content has changed.
            print(f"  -> Change detected for {url}. Analyzing...")
            old_content = load_snapshot(url_hash)
            
            # Get analysis from Gemini
            analysis_result = get_gemini_analysis(old_content, new_content)
            
            # Save the new analysis and snapshot
            save_analysis(url_hash, analysis_result)
            save_snapshot(url_hash, new_content)
            
            # Update the hash and timestamp
            current_hashes[url] = {"hash": new_hash, "last_checked": timestamp}
            print(f"  -> Analysis complete. Priority: {analysis_result.get('priority', 'N/A')}")

        else:
            # No change detected.
            print(f"  -> No changes detected for {url}.")
            
            # SUGGESTION IMPLEMENTED: Gracefully upgrade old string format to new dict format.
            if isinstance(current_hashes.get(url), str):
                current_hashes[url] = {"hash": current_hashes[url]}

            # Just update the 'last_checked' timestamp.
            current_hashes[url]["last_checked"] = timestamp

    # Save the updated hashes file at the end.
    save_hashes(current_hashes)
    print("\nUpdate check complete.")

# --- Script Execution ---
if __name__ == "__main__":
    # This ensures the main function runs when the script is executed.
    main()
