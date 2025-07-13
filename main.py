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
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash')

# Save history of any overwritten snapshots
LOG_DIR = 'logs'

# Create directories if they don't exist
for dir_path in [SNAPSHOTS_DIR, ANALYSIS_DIR, LOG_DIR]:
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)

# --- Helper Functions ---

def get_content_from_url(url):
    """Fetches and extracts the main text content from a URL."""
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
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
        utc_plus_10 = timezone(timedelta(hours=10))
        timestamp = datetime.now(utc_plus_10).isoformat()
        return {
            "summary": "Analysis failed.",
            "analysis": "Could not determine the difference due to an API or parsing error.",
            "date_time": timestamp,
            "priority": "medium"
        }

def append_to_log(url, url_hash, summary, timestamp):
    """Appends a change summary to the log file for the given URL."""
    log_path = os.path.join(LOG_DIR, f"{url_hash}.json")
    
    entry = {
        "url": url,
        "summary": summary,
        "timestamp": timestamp
    }
    
    if os.path.exists(log_path):
        with open(log_path, 'r', encoding='utf-8') as f:
            log_entries = json.load(f)
    else:
        log_entries = []
    
    log_entries.append(entry)
    
    with open(log_path, 'w', encoding='utf-8') as f:
        json.dump(log_entries, f, indent=4)
        
def save_initial_snapshot(url, content, url_hash):
    """Saves initial snapshot without analysis."""
    snapshot_path = os.path.join(SNAPSHOTS_DIR, f"{url_hash}.txt")
    analysis_path = os.path.join(ANALYSIS_DIR, f"{url_hash}.json")
    
    # Save snapshot
    with open(snapshot_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    # Create initial analysis entry
    utc_plus_10 = timezone(timedelta(hours=10))
    timestamp = datetime.now(utc_plus_10).isoformat()
    
    initial_analysis = {
        "summary": "Initial snapshot captured",
        "analysis": "This is the first time this page has been monitored. No comparison available.",
        "date_time": timestamp,
        "priority": "low"
    }
    
    with open(analysis_path, 'w', encoding='utf-8') as f:
        json.dump(initial_analysis, f, indent=4)

def handle_content_change(url, new_content, url_hash, timestamp):
    """Handles when content changes are detected."""
    snapshot_path = os.path.join(SNAPSHOTS_DIR, f"{url_hash}.txt")
    analysis_path = os.path.join(ANALYSIS_DIR, f"{url_hash}.json")
    
    # Load old content
    old_content = ""
    if os.path.exists(snapshot_path):
        with open(snapshot_path, 'r', encoding='utf-8') as f:
            old_content = f.read()
    
    # Generate analysis only if we have old content
    if old_content:
        try:
            analysis_result = get_gemini_analysis(old_content, new_content)
            
            # Validate analysis result
            if not isinstance(analysis_result, dict):
                raise ValueError("Analysis result is not a dictionary")
            
            # Ensure required fields exist
            required_fields = ['summary', 'analysis', 'date_time', 'priority']
            for field in required_fields:
                if field not in analysis_result:
                    analysis_result[field] = get_default_value(field, timestamp)
            
            # Save analysis
            with open(analysis_path, 'w', encoding='utf-8') as f:
                json.dump(analysis_result, f, indent=4)
            
            # Log the change
            if "summary" in analysis_result:
                append_to_log(
                    url=url,
                    url_hash=url_hash,
                    summary=analysis_result["summary"],
                    timestamp=analysis_result.get("date_time", timestamp)
                )
            
        except Exception as e:
            print(f"Error generating analysis for {url}: {e}")
            # Create fallback analysis
            fallback_analysis = {
                "summary": "Content changed but analysis failed",
                "analysis": f"Unable to generate detailed analysis due to error: {str(e)}",
                "date_time": timestamp,
                "priority": "medium"
            }
            
            with open(analysis_path, 'w', encoding='utf-8') as f:
                json.dump(fallback_analysis, f, indent=4)
    else:
        print(f"No previous content found for {url}, treating as initial run")
        save_initial_snapshot(url, new_content, url_hash)
    
    # Always save new snapshot
    with open(snapshot_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

def get_default_value(field, timestamp):
    """Returns default values for missing analysis fields."""
    defaults = {
        'summary': 'Analysis incomplete',
        'analysis': 'Detailed analysis could not be generated',
        'date_time': timestamp,
        'priority': 'medium'
    }
    return defaults.get(field, '')
        
# --- Main Logic ---

def main():
    # Create directories if they don't exist
    for dir_path in [SNAPSHOTS_DIR, ANALYSIS_DIR, LOG_DIR]:
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)

    previous_hashes = load_hashes()
    current_hashes = {}
    any_changes_detected = False
    utc_plus_10 = timezone(timedelta(hours=10))
    
    for url in URLS_TO_CHECK:
        print(f"Processing {url}...")
        content = get_content_from_url(url)
        timestamp = datetime.now(utc_plus_10).isoformat()

        if content:
            current_hash = generate_md5(content)
            url_hash = hashlib.md5(url.encode()).hexdigest()
            
            # Always update current_hashes
            current_hashes[url] = {
                "hash": current_hash,
                "last_checked": timestamp
            }
            
            previous_hash = previous_hashes.get(url, {}).get("hash")

            if previous_hash is None:
                # First time checking this URL
                print(f"First time checking {url} - saving initial snapshot")
                save_initial_snapshot(url, content, url_hash)
            elif current_hash != previous_hash:
                # Change detected
                any_changes_detected = True
                print(f"Change detected for {url}!")
                handle_content_change(url, content, url_hash, timestamp)
            else:
                print(f"No changes detected for {url}")
        else:
            print(f"Failed to fetch content for {url}")
            # Keep the previous hash if fetch failed
            if url in previous_hashes:
                current_hashes[url] = previous_hashes[url]
    
    # Always save current hashes
    save_hashes(current_hashes)
    
    if any_changes_detected:
        print("Changes were detected and processed.")
    else:
        print("No changes detected across all URLs.")

if __name__ == "__main__":
    main()
