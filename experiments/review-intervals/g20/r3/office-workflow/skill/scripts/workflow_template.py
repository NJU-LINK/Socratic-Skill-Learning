"""
Office Workflow Template

This script implements the five-step skeleton for office-workflow tasks.
Replace the TODO sections with task-specific logic.

Steps:
1. Discover & parse source artifacts
2. Apply selection predicate
3. Extract structured content
4. Transform / route / format into destination artifacts
5. Preserve consistency (don't mutate sources)
"""

import os
import glob
from pathlib import Path


def run():
    # =========================================================================
    # CWD ROBUSTNESS
    # =========================================================================
    # Ensure we're in the right working directory
    # The test harness expects solve.py to work from /app
    base_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(base_dir)
    
    # =========================================================================
    # STEP 1: Discover & parse source artifacts
    # =========================================================================
    # TODO: Set the source directory and file pattern
    source_dir = "data/emails/Bob/"
    file_pattern = "*.eml"
    
    source_files = sorted(glob.glob(os.path.join(source_dir, file_pattern)))
    
    # TODO: Choose the right parser based on file type
    # For .eml files:
    import email
    from email import policy
    
    parsed_artifacts = []
    for fpath in source_files:
        with open(fpath, "rb") as f:
            msg = email.message_from_binary_file(f, policy=policy.default)
        parsed_artifacts.append({
            "path": fpath,
            "filename": os.path.basename(fpath),
            "message": msg,
        })
    
    # For .ics files:
    # from icalendar import Calendar
    # for fpath in source_files:
    #     with open(fpath, "rb") as f:
    #         cal = Calendar.from_ical(f.read())
    #     parsed_artifacts.append({"path": fpath, "calendar": cal})
    
    # For .xlsx files:
    # import openpyxl
    # for fpath in source_files:
    #     wb = openpyxl.load_workbook(fpath)
    #     parsed_artifacts.append({"path": fpath, "workbook": wb})
    
    # =========================================================================
    # STEP 2: Apply selection predicate
    # =========================================================================
    # TODO: Define the selection criteria
    # Common predicates:
    # - Exact subject match: msg["subject"] in target_set
    # - Subject contains: "keyword" in msg["subject"].lower()
    # - Date range: start_date <= parsed_date <= end_date
    # - Recipient match: "target@example.com" in msg["to"]
    
    target_subjects = {"scheduled meeting", "application approved"}
    
    selected = []
    for artifact in parsed_artifacts:
        msg = artifact["message"]
        subject = msg["subject"]
        
        # TODO: Replace with task-specific predicate
        if subject and subject in target_subjects:
            selected.append(artifact)
    
    # =========================================================================
    # STEP 3: Extract structured content
    # =========================================================================
    # TODO: Extract the specific content needed for output
    # For emails: subject, body, date, from, to
    # For calendars: summary, dtstart, dtend, location
    # For spreadsheets: specific cells, rows, computed values
    
    extracted = []
    for artifact in selected:
        msg = artifact["message"]
        
        # Extract subject
        subject = msg["subject"]
        
        # Extract plain-text body
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_content()
                    break
        else:
            body = msg.get_content()
        
        body = body.strip()
        
        extracted.append({
            "filename": artifact["filename"],
            "subject": subject,
            "body": body,
        })
    
    # =========================================================================
    # STEP 4: Transform / route / format into destination artifacts
    # =========================================================================
    # TODO: Sort as required by task
    extracted.sort(key=lambda x: x["filename"])
    
    # TODO: Choose the right output format
    # For TXT output:
    output_file = "data/answer.txt"
    blocks = []
    for item in extracted:
        block = f"Subject: {item['subject']}\n{item['body']}"
        blocks.append(block)
    
    with open(output_file, "w") as f:
        f.write("\n\n".join(blocks) + "\n")
    
    # For ICS output:
    # from icalendar import Calendar, Event
    # cal = Calendar()
    # cal.add("prodid", "-//My Product//EN")
    # cal.add("version", "2.0")
    # for item in extracted:
    #     event = Event()
    #     event.add("summary", item["summary"])
    #     event.add("dtstart", item["start"])
    #     cal.add_component(event)
    # with open(output_file, "wb") as f:
    #     f.write(cal.to_ical())
    
    # For JSON output:
    # import json
    # with open(output_file, "w") as f:
    #     json.dump(extracted, f, indent=2)
    
    # For DOCX output:
    # from docx import Document
    # doc = Document()
    # for item in extracted:
    #     doc.add_heading(item["subject"], level=2)
    #     doc.add_paragraph(item["body"])
    # doc.save(output_file)


if __name__ == "__main__":
    run()
