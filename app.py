from flask import Flask, request, render_template, jsonify,redirect
import requests
import json
import nltk
from rake_nltk import Rake
from pydantic import BaseModel
import os
import re


nltk.download('stopwords')
nltk.download('punkt')

app = Flask(__name__)

# JIRA API Credentials
JIRA_URL = "https://jira.gtie.dell.com"
JIRA_USERNAME = "username@xyz.com"
JIRA_API_TOKEN = "jiratoken"

# Log Lookup Table
log_table = {
    "power": "-S30",
    "racadm": "-S3",
    "ipmi": "-S4",
    "scp": "-S24 -S14 -S16 -S18 -S5 -S8 -S9",
    "ssm": "-S23 -S28 -S5 -S8 -S9",
    "gui": "-S11",
    "redfish": "-S139",
    "front panel": "-S90",
    "sekm": "-S32 -S31",
    "boss": "-S32 -S31",
    "system erase": "-S120 -S23",
    "job": "-S5 -S8 -S9",
    "mother board replace": "-S106 -S112",
    "network": "-S322",
    "sma": "-S112",
    "pr7": "-S28",
    "pr8": "-S28"
}


def extract_logs_NLP(issue_details, issue_steps):
    """Extracts logs based on NLP keyword extraction from JIRA issue description"""
    
    r = Rake()
    text = issue_details + issue_steps
    r.extract_keywords_from_text(text)
    keywords = r.get_ranked_phrases_with_scores()

    logs_str = ""
    key_words_str = ""

    for score, kw in keywords[:20]:  # Limit to top 20 keywords
        words = kw.split()
        for word in words:
            word_lower = word.lower()
            if word_lower in log_table:
                log_to_enable = log_table[word_lower].lower()
                key_words_str += f"#{word_lower}"
                logs_str += log_to_enable + " "

    print ("Logs Prompt NLP: " + logs_str)
    print ("Key Words NLP: " + key_words_str)

    return logs_str, key_words_str


def extract_logs_Prompt_Engine(issue_details, issue_steps):

  from google import genai
  from pydantic import BaseModel, TypeAdapter

  class Log_entry(BaseModel):
    key: str
    log_to_enable: str

  prompt="Use each word in Description as Key to look in Log_lookup and generate Log_to_enable."
  prompt1="Description: " + issue_details
  prompt2="Log_lookup: " + str(log_table) 
   
  client = genai.Client(api_key="AIzaSyDhIm1gsXnjKg7Rb2F6xO4awfTqPMcC1AU")
  response = client.models.generate_content(
        model='gemini-2.0-flash',
        contents=prompt+prompt1+prompt2,
        config={
            'response_mime_type': 'application/json',
            'response_schema': list[Log_entry],
        },
    )
  # Use the response as a JSON string.
  print(response.text)

  # Parse the JSON data
  data = json.loads(response.text.lower())

  logs_str=""
  key_words_str = ""
  # Loop over the list of dictionaries
  for item in data:
       key = item["key"]
       log_to_enable = item["log_to_enable"]
       
       if log_to_enable != "" and ("-s" in log_to_enable):
           key_words_str +=   f"#{key}"
           logs_str +=  log_to_enable + " "
      
  print ("Logs Prompt Engine: " + logs_str)
  print ("Key Words Prompt Engine: " + key_words_str)

  return logs_str,key_words_str


def fetch_jira_issue(issue_key):
    """Fetches issue details from JIRA"""
    headers = {
        "Authorization": f"Bearer {JIRA_API_TOKEN}",
        "Content-Type": "application/json"
    }
    response = requests.get(f"{JIRA_URL}/rest/api/2/issue/{issue_key}", headers=headers)
    
    if response.status_code == 200:
        issue_details = response.json()
        issue_summary = issue_details["fields"]["summary"]
        issue_description = issue_details["fields"]["description"]
        issue_steps = issue_details["fields"].get("customfield_12707", "")
        return issue_summary, issue_description, issue_steps
    else:
        return None, None

LOGS_PATH = "debug_logs.txt"

def save_debug_logs(issue_key, issue_details, logs_str, key_words, debug_command):
    """Saves extracted logs and debug command to a specific path"""
    with open(LOGS_PATH, "a", encoding="utf-8") as file:
        file.write(f"\n{'='*50}\n")
        file.write(f"JIRA Issue Key: {issue_key}\n")
        file.write(f"Issue Details: {issue_details}\n")
        file.write(f"Extracted Keywords: {key_words}\n")
        file.write(f"Logs to be Enabled: {logs_str}\n")
        file.write(f"Debug Command: {debug_command}\n")
        file.write(f"{'='*50}\n")

@app.route("/", methods=["GET", "POST"])
def index():
    logs_str = ""
    key_words = ""
    issue_details = ""

    if request.method == "POST":
        
        issue_key = request.form["issue_key"]
       
        # Validate issue key format (must match "JIT-" followed by 6 digits)
        if not re.match(r"^JIT-\d{6}$", issue_key):
            return render_template("index.html", error="Invalid JIRA Ticket Number. Format must be 'JIT-XXXXXX' (6 digits).")

        issue_summary, issue_description, issue_steps = fetch_jira_issue(issue_key)
        issue_details = issue_summary + issue_description
        issue_info= "Issue: " + issue_key + "\n" + "Summary: " + issue_summary +"\n" + "Description: " + issue_description + "\n" + "Steps to Reproduce: " + issue_steps
        if issue_details:
            logs_str_PE, key_words_str_PE = extract_logs_Prompt_Engine(issue_details,issue_steps)
            logs_str_NLP, key_words_str_NLP = extract_logs_NLP(issue_details, issue_steps)
            
            logs_str = logs_str_PE+logs_str_NLP
            key_words_str = key_words_str_PE+key_words_str_NLP

            unique_logs = " ".join(set(logs_str.split()))
            unique_key_words = " ".join(set(key_words_str.split("#")))

            debug_command = f"debugcontrol -l10 {unique_logs} -o2"
            save_debug_logs(issue_key, issue_details, unique_logs, unique_key_words, debug_command)
            return render_template("index.html", issue_key=issue_key,issue_details=issue_info, key_words=unique_key_words, logs=unique_logs, debug_command=debug_command)

        else:
            return render_template("index.html", error="Invalid JIRA Ticket Number")

    return render_template("index.html", logs=logs_str,issue_details=issue_details, key_words=key_words)


if __name__ == "__main__":
    app.run(debug=True)
