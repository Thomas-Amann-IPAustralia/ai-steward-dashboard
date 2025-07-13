import os
import json
import hashlib
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
from datetime import datetime, timezone, timedelta

# --- Configuration ---
# URLs to monitor
URLS_TO_CHECK = [
    "https://www.tomamann.com/about",
    # Add other relevant Australian AI policy or platform ToS pages here
]

# File to store hashes
HASHES_FILE = 'hashes.json'

# Directory for content snapshots
SNAPSHOTS_DIR = 'snapshots'

# Directory to store analysis files
ANALYSIS_DIR = 'analysis'

# Configure the Gemini API
# Best practice: Store your API key in GitHub Secrets (e.g., GEMINI_API_KEY)
# The script will access it as an environment variable in the GitHub Action
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash') # Using the specified model

# --- Helper Functions (get_content_from_url, generate_md5, load_hashes, save_hashes) ---

def get_content_from_url(url):
    """Fetches and extracts the main text content from a URL."""
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        # This is a generic selector. You may need to inspect each site
        # to find a more specific and reliable selector for the main content.
        main_content = soup.find('body')
        if main_content:
            return main_content.get_text(separator='\n', strip=True)
        return None
    except requests.exceptions.RequestException as e:
        print(f"Error fetching {url}: {e}")
        return None

def generate_md5(text):
    """Generates an MD5 hash for the given text."""
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def load_hashes():
    """Loads the stored hashes from the JSON file."""
    if os.path.exists(HASHES_FILE):
        with open(HASHES_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_hashes(hashes):
    """Saves the hashes to the JSON file."""
    with open(HASHES_FILE, 'w') as f:
        json.dump(hashes, f, indent=4)

def get_gemini_analysis(old_content, new_content):
    """Sends content to Gemini for analysis and returns a JSON object."""
    prompt = f"""
    You are an AI assistant for Australian public servants.
    Analyze the difference between the OLD and NEW text from a webpage.
    Explain the key changes in a clear, neutral tone.

    Your response MUST be a JSON object with four keys: 'summary', 'analysis', 'date_time', 'priority'.
    - 'summary': A concise, one-sentence overview of the change (e.g., "The policy was updated to include new guidelines on data privacy.").
    - 'analysis': A more detailed explanation of what was added, removed, or modified. Try to direct the reader to the locations of the changes.
    - 'date_time': A time stamp indicating the date and time the query was processed by Gemini. Timestamp should follow the ISO 8601 with a time zone offset of +10:00 (e.g., "2025-07-13T19:00:00+10:00").
    - 'priority': Select exactly one of these values: "critical", "high", "medium", or "low"
  - Use "critical" for changes that could immediately impact government compliance or data sovereignty
  - Use "high" for changes requiring prompt review and potential policy updates
  - Use "medium" for changes that should be monitored but may not require immediate action
  - Use "low" for changes for awareness but minimal operational impact
  
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
        # Attempt to parse the JSON from Gemini's response text
        return json.loads(response.text)
    except Exception as e:
        print(f"Error calling Gemini API or parsing JSON: {e}")
        # Fallback in case of an error
        return {
            "summary": "Analysis failed.",
            "analysis": "Could not determine the difference due to an API or parsing error."
        }


# --- Main Logic ---

def main():
    # Create directories if they don't exist
    for dir_path in [SNAPSHOTS_DIR, ANALYSIS_DIR]:
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)

    previous_hashes = load_hashes()
    current_hashes = {}
    changes_made = False
    utc_plus_10 = timezone(timedelta(hours=10))
    
    for url in URLS_TO_CHECK:
        print(f"Processing {url}...")
        content = get_content_from_url(url)

        if content:
            current_hash = generate_md5(content)
            url_hash = hashlib.md5(url.encode()).hexdigest() # Consistent hash for filenames
            snapshot_path = os.path.join(SNAPSHOTS_DIR, f"{url_hash}.txt")
            analysis_path = os.path.join(ANALYSIS_DIR, f"{url_hash}.json")

            previous_hash = previous_hashes.get(url, {}).get("hash")

            if current_hash != previous_hash:
                changes_made = True
                print(f"Change detected for {url}!")

                old_content = ""
                if os.path.exists(snapshot_path):
                    with open(snapshot_path, 'r', encoding='utf-8') as f:
                        old_content = f.read()

                # Save new snapshot
                with open(snapshot_path, 'w', encoding='utf-8') as f:
                    f.write(content)

                # Get and save analysis
                if old_content:
                    analysis_result = get_gemini_analysis(old_content, content)
                    with open(analysis_path, 'w', encoding='utf-8') as f:
                        json.dump(analysis_result, f, indent=4)
                    print(f"Analysis saved to {analysis_path}")
                
            # Always update to the latest hash
            timestamp = datetime.now(utc_plus_10).isoformat()
            current_hashes[url] = {
                "hash": current_hash,
                "last_checked": timestamp
                 }
    if changes_made:
        print("Changes were detected. Updating hashes file.")
        save_hashes(current_hashes)
    else:
        print("No changes detected across all URLs.")


if __name__ == "__main__":
    main()
