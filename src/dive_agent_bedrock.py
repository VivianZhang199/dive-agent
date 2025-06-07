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

# Dummy session 
session = {
    "session_id": "abc123",
    "dive_date": None,
    "dive_number": None,
    "dive_location": None,
    "video_filename": "GX01001.mp4"
}

def is_valid_date(date_str):
    try:
        datetime.strptime(date_str.strip(), "%Y-%m-%d")
        return True
    except:
        return False

# --- Tool: Update metadata ---
def update_session_metadata(session_id, dive_date=None, dive_number=None, dive_location=None):
    logger.info(f"Validating tool input for session {session_id}")
    if dive_date and not is_valid_date(dive_date):
        logger.warning("Dive date is invalid. Must be in YYYY-MM-DD format.")
        return
    if dive_number and not dive_number.isdigit():
        logger.warning("Dive number must be numeric.")
        return
    if dive_location and len(dive_location) < 3:
        logger.warning("Dive location seems too short or empty.")
        return

    logger.info(f"🔧 Updating session metadata for session_id={session_id}")
    logger.info(f" - Date: {repr(dive_date)}")
    logger.info(f" - Dive number: {repr(dive_number)}")
    logger.info(f" - Location: {repr(dive_location)}")

    # Persist updates to the global session
    session["dive_date"] = dive_date
    session["dive_number"] = dive_number
    session["dive_location"] = dive_location

# --- Claude setup ---
SYSTEM_PROMPT = """
You are a helpful and grounded dive assistant who helps users manage dive sessions. Always start with 'Howdy!'

You can use tools to:
- Update missing dive metadata (dive date, number, location)
- More tools may be added — always rely on the tool's description and schema to decide:
  - When to call it
  - What inputs are required
  - Whether the user’s input is valid

Behavior:
- Users may provide all fields at once or across replies.
- Never guess or fill in missing data (e.g. no defaults like "Unknown")
- **Do not convert or infer dive dates from non-standard formats** like "01/02/2024" or "DD-MM-YYYY". Ask the user to re-enter them in valid YYYY-MM-DD format.
- Never invent or assume values just to satisfy tool input requirements. Only use information the user has clearly provided.
- Only call tools after all required inputs are clearly provided and valid.
- If input is vague, malformed, or incomplete, ask the user to rephrase that part.

Tone:
- Sound like a helpful dive buddy logging dives.
- Keep replies clear and concise.
- Mirror the user's tone — emojis (🐠, 🤿, ✅) are fine if they’re playful.
- Ask for multiple missing fields in one short message when possible. Keep it efficient and human.
"""

TOOLS = [{
    "name": "update_session_metadata",
    "description": "Updates dive metadata. Requires dive_date, dive_number, and dive_location to be clearly and explicitly provided by the user. Do not guess or assume any value. Ask for all fields in one message if possible.",
    "input_schema": {
        "type": "object",
        "properties": {
            "session_id": { "type": "string" },
            "dive_date": { "type": "string", "description": "Dive date in YYYY-MM-DD format." },
            "dive_number": { "type": "string", "description": "Dive number (e.g., '14'). Should be numeric." },
            "dive_location": { "type": "string", "description": "Dive location, e.g., 'West Reef'." }
        },
        "required": ["session_id", "dive_date", "dive_number", "dive_location"]
    }
}]


# --- Conversation Logic ---
def start_chat(session_data):
    messages.clear()
    messages.append({"role": "user", "content": f"This is the session: {json.dumps(session_data)}"})
    return invoke_claude(include_tools=False)

def continue_chat(user_input):
    messages.append({"role": "user", "content": user_input})
    return invoke_claude(include_tools=True)

def invoke_claude(include_tools=True):
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

    assistant_reply = None

    for message in response_body.get("content", []):
        if message["type"] == "text":
            assistant_reply = message["text"]
            logger.info(f"🤖 Claude: {assistant_reply}")
            print(f"\n🤖 Claude: {assistant_reply}")
            
        elif message["type"] == "tool_use":
            tool = message["name"]
            args = message["input"]
            
            logger.info(f"🔧 Claude wants to call: {tool} with arguments: {json.dumps(args)}")
            print(f"\n🔧 Claude wants to call: {tool} with arguments:\n{json.dumps(args, indent=2)}")

            if tool == "update_session_metadata":
                update_session_metadata(**args)

                updated = json.dumps(session, indent=2)

            if assistant_reply:
                assistant_reply += (
                    f"\n✅ Tool `{tool}` called successfully."
                    f"\n\nHere’s the updated session:\n\n```json\n{updated}\n```"
                )

                assistant_reply = (
                    f"\n✅ Tool `{tool}` called successfully."
                    f"\n\nHere’s the updated session:\n\n```json\n{updated}\n```"
                )
    if assistant_reply:
        messages.append({"role": "assistant", "content": assistant_reply})
        return assistant_reply
    else:
        return "🤖 Sorry, I didn’t catch that."
    

if __name__ == "__main__":
    logger.info("🎬 Dive Agent Started – Type 'exit' to quit\n")
    print("🎬 Dive Agent Started – Type 'exit' to quit\n")
    start_chat(session)

    while True:
        user_reply = input("\nYou: ")
        if user_reply.strip().lower() in ["exit", "quit"]:
            logger.info("Exiting session.")
            break
        continue_chat(user_reply)