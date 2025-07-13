import os
import json
import hashlib
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai

# --- Configuration ---
# URLs to monitor
URLS_TO_CHECK = [
    "https://www.industry.gov.au/topic/industry-science-and-resources/artificial-intelligence",
    # Add other relevant Australian AI policy or platform ToS pages here
]

# File to store hashes
HASHES_FILE = 'hashes.json'

# Directory for content snapshots
SNAPSHOTS_DIR = 'snapshots'

# Configure the Gemini API
# Best practice: Store your API key in GitHub Secrets (e.g., GEMINI_API_KEY)
# The script will access it as an environment variable in the GitHub Action
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash') # Using the specified model

# --- Helper Functions ---

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

    Your response MUST be a JSON object with two keys: 'summary' and 'analysis'.
    - 'summary': A concise, one-sentence overview of the change (e.g., "The policy was updated to include new guidelines on data privacy.").
    - 'analysis': A more detailed explanation of what was added, removed, or modified.

    OLD CONTENT:
    ---
    {old_content[:2000]}
    ---

    NEW CONTENT:
    ---
    {new_content[:2000]}
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
    if not os.path.exists(SNAPSHOTS_DIR):
        os.makedirs(SNAPSHOTS_DIR)

    previous_hashes = load_hashes()
    current_hashes = {}
    changes_detected = False

    for url in URLS_TO_CHECK:
        print(f"Processing {url}...")
        content = get_content_from_url(url)

        if content:
            current_hash = generate_md5(content)
            current_hashes[url] = current_hash
            snapshot_filename = f"{hashlib.md5(url.encode()).hexdigest()}.txt"
            snapshot_path = os.path.join(SNAPSHOTS_DIR, snapshot_filename)

            previous_hash = previous_hashes.get(url)

            if current_hash != previous_hash:
                changes_detected = True
                print(f"Change detected for {url}!")

                old_content = ""
                if os.path.exists(snapshot_path):
                    with open(snapshot_path, 'r') as f:
                        old_content = f.read()

                # Save the new snapshot
                with open(snapshot_path, 'w') as f:
                    f.write(content)

                # Get analysis if there was previous content to compare against
                if old_content:
                    analysis_result = get_gemini_analysis(old_content, content)
                    # You would integrate this result into your notification or dashboard data
                    print("Gemini Analysis:", json.dumps(analysis_result, indent=2))
            else:
                print(f"No change for {url}.")

    if changes_detected:
        print("Changes were detected. Updating hashes file.")
        save_hashes(current_hashes)
    else:
        print("No changes detected across all URLs.")


if __name__ == "__main__":
    main()
