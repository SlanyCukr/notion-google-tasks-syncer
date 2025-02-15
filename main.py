#!/usr/bin/env python
"""
This application periodically synchronizes tasks between a Notion database
and a Google Tasks tasklist.

It will:
  - Query Notion for tasks that have:
      • Status == "Organized"
      • For later is unchecked (False)
      • Dump it is unchecked (False)
  - For each such task:
      • If it does not yet exist in Google Tasks, create it.
      • Otherwise, if the Notion “Done!” checkbox has changed, update the
        corresponding Google Task’s completion status.

A unique mapping is maintained by storing the Notion task’s ID in the
Google Task’s “notes” field.
"""
import time
import re
from pathlib import Path

# Load environment variables from .env file
from dotenv import load_dotenv
from ultimate_notion import prop
from ultimate_notion.adapters import sync

load_dotenv()

import ultimate_notion as uno
from ultimate_notion.config import get_cfg
from ultimate_notion.adapters.google import GTasksClient, SyncGTasks


# =============================================================================
# Specify the database URL and extract the database ID.
# =============================================================================

DATABASE_URL = "https://www.notion.so/110f4691b8df8196963fd95c0a64682f?v=110f4691b8df81038f97000cfdf7062f&pvs=4"
DATABASE_ID = "110f4691b8df8196963fd95c0a64682f"  # Extracted from the URL


# =============================================================================
# Helper functions for Google Tasks mapping and updating
# =============================================================================

def extract_notion_id(gtask):
    """
    Look for a Notion task id in the Google Task's notes field.
    Our convention is to store the Notion ID as:
       "Notion ID: <the_id>"
    """
    if gtask.notes:
        match = re.search(r'Notion ID:\s*(\S+)', gtask.notes)
        if match:
            return match.group(1)
    return None


def update_google_task_status(gtask, notion_done):
    """
    Given a Google Task (gtask) and the Notion task's done status (a bool),
    update the Google Task so that if notion_done is True the task is marked
    completed and vice-versa.
    """
    # We assume that gtask.completed is None if the task is not completed.
    gtask_is_done = gtask.completed is not None

    if notion_done and not gtask_is_done:
        gtask.mark_completed()  # Marks the task complete in Google Tasks
        print(f"Marked '{gtask.title}' as completed in Google Tasks.")
    elif (not notion_done) and gtask_is_done:
        gtask.mark_incomplete()  # Marks the task as not completed (if supported)
        print(f"Marked '{gtask.title}' as not completed in Google Tasks.")
    gtask.update()


# =============================================================================
# The main sync function: find matching Notion tasks and mirror them to Google Tasks.
# =============================================================================

def sync_inbox_to_gtasks():
    cfg = get_cfg()
    cfg.google.client_secret_json = Path("/home/slanycukr/Documents/notion-google-tasks-syncer/client_secret.json")

    # Optionally also override token_json if needed:
    cfg.google.token_json = Path("/home/slanycukr/Documents/notion-google-tasks-syncer/token.json")

    # Start a session with Notion and Google Tasks.
    with uno.Session() as notion, GTasksClient(cfg, read_only=False) as gtasks:
        # Retrieve the Notion database using its ID.
        # (Replace `get_db` with the appropriate method if needed.)
        inbox_db = notion.get_db(DATABASE_ID)
        if inbox_db.is_empty:
            print(f"Could not load the Notion database with ID: {DATABASE_ID}.")
            return

        organized_option = next(option for option in inbox_db.schema.status.type.options if option.name == 'Organized')

        class Status(uno.OptionNS):
            organized = uno.Option('Organized', color=uno.Color.GREEN)
            to_organize = uno.Option('To Organize', color=uno.Color.BLUE)
            dump = uno.Option('Dump', color=uno.Color.GRAY)

        # Construct filters with proper syntax
        status_filter = uno.prop('Status').has_value('Organized') # Status property filter
        for_later_filter = uno.prop('For Later') == False  # Checkbox filter
        dump_it_filter = uno.prop('Dump It') == False  # Checkbox filter

        # Combine filters with proper parentheses
        combined_filter = status_filter & for_later_filter & dump_it_filter

        # Execute query and process results
        results = inbox_db.query.filter(combined_filter).execute()
        for task in results:
            print(f"Task: {task.title}")
            print(f"Status: {task.props['Status']}")
            print(f"For Later: {task.props['For later']}")
            print(f"Dump It: {task.props['Dump it']}\n")

        # Retrieve column definitions from the database schema.
        status_col = inbox_db.schema.get_prop('Status')
        due_date_col = inbox_db.schema.get_prop('Date')

        # Retrieve or create the corresponding Google Tasks tasklist.
        tasklist = gtasks.get_or_create_tasklist('My synced task list')

        # Create the SyncGTasks object.
        # Note: 'completed_val' and 'not_completed_val' are pulled from the Status column's type options.
        # Ensure that 'Done' and 'Backlog' exactly match the option names as defined in your Notion database.
        sync_task = SyncGTasks(
            notion_db=inbox_db,
            tasklist=tasklist,
            completed_col=status_col,
            completed_val=status_col.type.options['Done'],
            not_completed_val=status_col.type.options['Backlog'],
            due_col=due_date_col,
        )

        # Schedule the sync task to run every second for a total of 2 iterations.
        sync_task.run_every(seconds=1).in_total(times=2).schedule()

        # Run all scheduled tasks.
        sync.run_all_tasks()

        print("Sync complete.\n")

# =============================================================================
# Main loop: run the sync periodically
# =============================================================================

if __name__ == "__main__":
    SYNC_INTERVAL = 60  # Run every 60 seconds

    print("Starting Notion-to-Google Tasks sync...")
    while True:
        try:
            sync_inbox_to_gtasks()
        except Exception as e:
            print("An error occurred during sync:", e)
        time.sleep(SYNC_INTERVAL)
