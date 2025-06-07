import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import boto3
import json
from botocore.exceptions import ClientError
from config import config
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"

bedrock = boto3.client("bedrock-runtime", region_name=config.REGION)
s3 = boto3.client("s3", region_name = config.REGION)

# --- Global message history ---
messages = []
def is_valid_date(date_str):
    try:
        datetime.strptime(date_str.strip(), "%Y-%m-%d")
        return True
    except:
        return False

# --- Tool: Update metadata ---
def update_session_metadata(session, session_id, dive_date=None, dive_number=None, dive_location=None):
    print(f"session_id: {session_id}")
    logger.info(f"Validating tool input for session {session_id}")
    if dive_date and not is_valid_date(dive_date):
        logger.warning("Dive date is invalid. Must be in YYYY-MM-DD format.")
        return False
    if dive_number and not dive_number.isdigit():
        logger.warning("Dive number must be numeric.")
        return False
    if dive_location and len(dive_location) < 3:
        logger.warning("Dive location seems too short or empty.")
        return False

    logger.info(f"🔧 Updating session metadata for session_id={session_id}")
    logger.info(f" - Date: {repr(dive_date)}")
    logger.info(f" - Dive number: {repr(dive_number)}")
    logger.info(f" - Location: {repr(dive_location)}")

    # Persist updates
    session["dive_date"] = dive_date
    session["dive_number"] = dive_number
    session["dive_location"] = dive_location

    updated_key = f"processed/{session_id}/session_metadata.json"

    try:
        s3.put_object(
            Bucket=config.BUCKET_NAME,
            Key=updated_key,
            Body=json.dumps(session, indent=2),
            ContentType="application/json"
        )
        logger.info(f"✅ Session metadata saved to s3://{config.BUCKET_NAME}/{updated_key}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to update session metadata in S3: {e}")
        return False

# --- Claude setup ---
SYSTEM_PROMPT = """
🧠 **ROLE & PURPOSE**
**You are a helpful and grounded dive assistant** who supports users in completing **specific dive session tasks**, like updating **dive session metadata** or answering dive questions.

🛠️ **TOOL USAGE**
You can use tools to:
- **Update missing dive metadata** (dive date, number, location)
More tools may be added. Always rely on:
- The **tool's description**
- Its **input schema**
- The **validity** of the user's input
To decide:
  - ✅ When to call a tool
  - ✅ What inputs are required
  - ✅ Whether the inputs are complete and valid

⚙️ **BEHAVIOR GUIDELINES**
- Users may provide fields **all at once** or **across multiple replies**.
- **Never guess**, fabricate, or autofill missing data (e.g., don’t use defaults like "Unknown").
- **Do not convert or infer dive dates** from formats like like "01/02/2024" or "DD-MM-YYYY" - always ask the user to re-enter in the specified format in the schema.
- Never invent or assume values just to satisfy tool input requirements. Only use information the user has clearly provided.
- Only call tools when **all required inputs are clearly provided and valid**.
- If input is **vague, malformed, or incomplete**, ask the user to rephrase.

🎯 **TASK DISCIPLINE**
- **Focus on completing one clear task at a time**.
- Only call tools or respond in ways that **help complete the current task** (e.g, updating dive metadata).
- **Do not suggest unrelated tasks**, explore other infomration, or speculate - unless the user **explicitly asks**.

- If your tool call fails, clearly explain what’s wrong and ask the user for just the part that’s invalid.
- After the user corrects it, retry the tool with the updated input.
- Always continue the current task until it’s completed.

🤿 **TONE & STYLE**
- Sound like a **friendly dive buddy** logging dives.
- Keep replies **clear, concise, and helpful.**
- Emojis (🐠, 🤿, ✅) are encouraged.
- If multiple fields are missing, **ask for them in one short message** to keep things efficient and human.
"""

TOOLS = [{
    "name": "update_session_metadata",
    "description": (
        "Use this tool to update a dive session’s metadata. "
        "All of the following fields must be clearly and explicitly provided by the user: "
        "`dive_date`, `dive_number`, and `dive_location`. "
        "Do not guess, infer, or assume values. "
        "If any field is missing, ask the user for all fields in a single follow-up message."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "Unique session ID of the dive session to update."
            },
            "dive_date": {
                "type": "string",
                "description": "Dive date in YYYY-MM-DD format."
            },
            "dive_number": {
                "type": "string",
                "description": "Dive number (e.g., '29'). Must be numeric."
            },
            "dive_location": {
                "type": "string",
                "description": "Dive location (e.g., 'North Alor'). Must be at least 3 characters."
            }
        },
        "required": ["session_id", "dive_date", "dive_number", "dive_location"]
    }
}]


# --- Conversation Logic ---
def start_chat(session):
    messages.clear()
    messages.append({"role": "user", "content": f"This is the session: {json.dumps(session)}"})
    return invoke_claude(session, include_tools=False)

def continue_chat(session, user_input):
    messages.append({"role": "user", "content": user_input})
    return invoke_claude(session, include_tools=True)

def invoke_claude(session, include_tools=True):
    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "system": SYSTEM_PROMPT,
        "messages": messages,
        "max_tokens":  5000
    }

    if include_tools:
        payload["tools"] = TOOLS
        payload["tool_choice"] = {"type": "auto"}
    
    body = {
        "modelId": MODEL_ID,
        "contentType": "application/json",
        "accept": "application/json",
        "body": json.dumps(payload)
    }

    response = bedrock.invoke_model(**body)
    response_body = json.loads(response["body"].read())

    assistant_reply = ""

    for message in response_body.get("content", []):
        if message["type"] == "text":
            assistant_reply = message["text"]
            logger.info(f"{assistant_reply}")
            
        elif message["type"] == "tool_use":
            tool = message["name"]
            args = message["input"]
            
            logger.info(f"\n🔧 Claude wants to call: {tool} with arguments: {json.dumps(args)}")

            assistant_reply += (
                f"\n\n🔧 Claude wants to call: `{tool}` with arguments:\n```json\n{json.dumps(args, indent=2)}\n```"
            )

            if tool == "update_session_metadata":
                success = update_session_metadata(session,**args)

                if success:
                    updated = json.dumps(session, indent=2)
                    assistant_reply += (
                        f"\n✅ Tool `{tool}` called successfully."
                        f"\n\nHere’s the updated session:\n\n```json\n{updated}\n```"
                    )
                else:
                    assistant_reply = (
                        f"⚠️ Tool `{tool}` failed due to invalid or missing input. "
                        f"Please double-check the dive date (YYYY-MM-DD), number (numeric), and location (min 3 chars). "
                        f"Let me know the corrected values so I can try again. 🛠️"
                    )

    if assistant_reply:
        messages.append({"role": "assistant", "content": assistant_reply})
        return assistant_reply
    else:
        return "🤖 Sorry, I didn’t catch that."
    

if __name__ == "__main__":
    logger.info("🎬 Dive Agent Started – Type 'exit' to quit\n")
    start_chat(session)

    while True:
        user_reply = input("\nYou: ")
        if user_reply.strip().lower() in ["exit", "quit"]:
            logger.info("Exiting session.")
            break
        continue_chat(user_reply)