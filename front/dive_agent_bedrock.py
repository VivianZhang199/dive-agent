import json
import logging
import os
import sys
import time
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from chat_session import ChatSession
from config import config
from utils import load_json_from_s3

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Model configuration
MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"

# Initialise AWS clients
bedrock = boto3.client("bedrock-runtime", region_name=config.REGION)
s3 = boto3.client("s3", region_name=config.REGION)

UPDATE_DIVE_INFORMATION_TOOL = {
    "name": "update_dive_information",
    "description": (
        "Use this tool to store or update core dive session details. "
        "All fields (`dive_date`, `dive_number`, `dive_location`) must be clearly provided by the user before calling this tool if they are all missing. Otherwise, accept partial information and update the fields that are provided."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "dive_date":     {"type": "string",
                              "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$"},
            "dive_number":   {"type": "string",
                              "pattern": "^[0-9]+$"},
            "dive_location": {"type": "string",
                              "minLength": 3}
        },
        #"required": ["dive_date", "dive_number", "dive_location"]
    }
}

ALL_TOOLS = [UPDATE_DIVE_INFORMATION_TOOL]

# --- Tool: Update metadata ---
def update_dive_information(chat: ChatSession, dive_date=None, dive_number=None, dive_location=None):

    session_id = chat.dive_session_id
    #session = chat.current_dive
    logger.info(f"Validating tool input for session {session_id}")

    if dive_date is not None:
        try:
            dive_date = dive_date.strip()
            datetime.strptime(dive_date, "%Y-%m-%d")
        except Exception:
            return {"error": "Invalid date format—please use YYYY-MM-DD."}
        #session["dive_date"] = dive_date
        chat.current_dive.update(dive_date=dive_date)

    if dive_number is not None:
        try:
            dive_number = dive_number.strip()
            assert dive_number.isdigit()
        except Exception:
            return {"error": "Dive number must be a whole number."}
        #session["dive_number"] = dive_number
        chat.current_dive.update(dive_number=dive_number)

    if dive_location is not None:
        dive_location = dive_location.strip()
        if len(dive_location) < 3:
            return {"error": "Dive location must be at least three characters."}
        #session["dive_location"] = dive_location
        chat.current_dive.update(dive_location=dive_location)

    updated_key = f"processed/{session_id}/session_metadata.json"

    try:
        s3.put_object(
            Bucket=config.BUCKET_NAME,
            Key=updated_key,
            Body=json.dumps(chat.current_dive, indent=2),
            ContentType="application/json"
        )
        logger.info(f"✅ Session metadata saved to s3://{config.BUCKET_NAME}/{updated_key}")
        return chat.current_dive
    except Exception as e:
        logger.error(f"❌ Failed to update session metadata in S3: {e}")
        return {"error": str(e)}

# --- Claude setup ---
SYSTEM_PROMPT = """
🧠 **ROLE & PURPOSE**
**You are a happy and helpful dive assistant** who supports users in completing **specific dive session tasks**, like updating **dive session metadata** or answering dive questions. 
Your name is **Claudey**. The emoji that best represents you is 🤠. Speak in Australian English.

🛠️ **INTEGRATED TOOLS USAGE**
Before doing anything, look at the “📋 Available skills to use: ” message and only invoke one of those skills. If it says “None,” do not try to describe footage or update metadata—just ask the user what they’d like to do next.
You have two built-in dive tools — think of them as part of you, not external APIs:

- **update_dive_information** 
  • When the user provides or corrects any of these three fields—**dive date**, **dive number**, **dive location**—  
    you run update_dive_information to save them, then say “I’ve updated your dive log with that info.”  
  • **Only** these three fields are valid.  
  ❌ Do **not** ask for or infer any other fields like duration, depth, or temperature.

More capabilities may be added later—always rely on the built-in skill’s description, its input requirements, and the validity/completeness of what the user has provided.

⚙️ **BEHAVIOR GUIDELINES**
- **Only disclose any inability or limitation when the user explicitly asks** (e.g. “Can you process video?”). Otherwise, focus on the task at hand—do *not* volunteer “I can’t…” messages.
- Users may provide fields **all at once** or **across multiple replies**.
- **Never guess**, fabricate, or autofill missing data (e.g., don’t use defaults like "Unknown").
- **Do not convert or infer dive dates** from formats like like "01/02/2024" or "DD-MM-YYYY" - always ask the user to re-enter in the specified format in the schema.
- Never invent or assume values just to satisfy tool input requirements. Only use information the user has clearly provided.
- Only call tools when **all required inputs are clearly provided and valid**.
- If input is **vague, malformed, or incomplete**, ask the user to rephrase.
- ⚠️ Only use tools if it is explicitly listed under “Available skills” of "CURRENT STATE" section. The “Available skills” hint is for your internal reasoning; **never** say to the user “no tools are available.” It is only to help guide the user of next steps if you have no skills to run.

🎯 **TASK DISCIPLINE**
- **Focus on completing one clear task at a time**.
- Only call tools or respond in ways that **help complete the current task** (e.g, updating dive metadata).
- **Do not suggest unrelated tasks**, explore other information, or speculate - unless the user **explicitly asks**.

- If your tool call fails, clearly explain what’s wrong and ask the user for just the part that’s invalid.
- After the user corrects it, retry the tool with the updated input.
- Always continue the current task until it’s completed.
- Check the 'Tool has been successfully called' message to see if the tool was called successfully under "CURRENT STATE" section and let this guide your next step.
- Do not suggest you have successfully completed a task if you have not called the tool under "CURRENT STATE" section.

📡 **SYSTEM EVENTS**
You may receive system-triggered messages prefixed with `[SYSTEM_EVENT]` from the backend.
- `[SYSTEM_EVENT] start_conversation`
- `[SYSTEM_EVENT] video_uploaded`
**Do not** ever emit those prefixes yourself.
⚠️ **Do not** generate or invent any other `[SYSTEM_EVENT] …` messages. Only react to the two above.
Treat them as signals of app state changes, use them to guide the next helpful step, and never reveal the internal event details back to the user.

🤿 **TONE & STYLE**
- Sound like a **friendly dive buddy** logging dives.
- Keep replies **clear, concise, and helpful.**
- Emojis (🐠, 🤿, ✅) are highly encouraged.
- If multiple fields are missing, **ask for them in one short message** to keep things efficient and human.

🔄 **CONVERSATION FLOW**
- Start conversations by introducing yourself and explaining your purpose. Always start with 'Howdy!'.
- First, identify the current task (e.g., updating metadata or answering dive questions).
- Ask for any missing info to complete the task.
- Only after the current task is done, respond to new requests. Let the user know you're done with the current task before moving on to the next one.

This helps you stay focused and not mix different tasks together.
"""

# --- Conversation Logic ---
def start_chat(chat: ChatSession):
    chat.messages.clear()
    chat.add("user", "[SYSTEM_EVENT] start_conversation")
    return invoke_claude(chat, include_tools=False)

def continue_chat(chat: ChatSession, user_input):
    #if "update" in user_input.lower() or "change" in user_input.lower():
        #chat.metadata_done = False

    chat.add("user", user_input)
    has_tools = bool(chat.next_tools())
    return invoke_claude(chat, include_tools=has_tools)
    
def invoke_claude(chat: ChatSession, include_tools=False, tool_prompt = "", max_retries = 3):
    tools_available = chat.next_tools()
    tool_names = [tool["name"] for tool in tools_available]

    tools_available_prompt = f"\n\n📋 Available tools for use: {', '.join(tool_names) or 'None'}"

    separator = "\n----------\n"
    enhanced_system_prompt = SYSTEM_PROMPT + separator + "CURRENT STATE:\n" + tools_available_prompt + "\n" +tool_prompt + separator

    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "system": enhanced_system_prompt,
        "messages": chat.messages,
        "max_tokens":  5000
    }

    if include_tools and tools_available:
        payload["tools"] = tools_available
        payload["tool_choice"] = {"type": "auto"}
    
    body = {
        "modelId": MODEL_ID,
        "contentType": "application/json",
        "accept": "application/json",
        "body": json.dumps(payload)
    }

    logger.info("Sending messages to Claude:")
    for m in chat.messages:
        logger.info(f" - {m['role']}: {m['content'][:60]}")

    for attempt in range(max_retries + 1):
        try:
            logger.info(f"FINAL PAYLOAD: {json.dumps(payload, indent=2)}")
            response = bedrock.invoke_model(**body)
            response_body = json.loads(response["body"].read())
            break # Success - exit the loop
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'ThrottlingException':
                if attempt < max_retries:
                    wait_time = 2 ** attempt
                    logger.warning(f"Throttling detected. Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error("Max retries exceed for throttling")
                    return "🤖 Sorry, I'm currently experiencing high demand. Please try again."
            else:
                logger.error(f"Bedrock API error {e}")
                return "🤖 Sorry, I experienced an error. Please try again."

    assistant_reply = ""

    for message in response_body.get("content", []):
        logger.info(f"MESSAGE: {message}")
        logger.info(f"MESSAGE TYPE: {message['type']}")
        if message["type"] == "text":
            assistant_reply = message["text"]
            logger.info(f"{assistant_reply}")
            
        elif message["type"] == "tool_use":
            tool = message["name"]
            args = message["input"]
            
            logger.info(f"\n🔧 Claude is calling: {tool} with arguments: {json.dumps(args)}")

            tool_invocation_reply = (
                f"\n\n🔧 Claude is calling: `{tool}` with arguments:\n```json\n{json.dumps(args, indent=2)}\n```"
            )

            if tool == "update_dive_information":
                payload = update_dive_information(chat,**args)
            
            else:
                logger.warning(f"Claude called an unknown tool: {tool}")
                payload = {"error": f"Unknown tool: {tool}"}
            
            #chat.add("tool", json.dumps(payload))

            outcome = "failed" if payload.get("error") else "succeeded"
            tool_prompt = f"Tool `{tool}` {outcome}: {json.dumps(payload)}"

            #chat.add("user", f"✅ Tool `{tool}` succeeded: {json.dumps(payload)}")
            follow_up = invoke_claude(
                chat,
                include_tools=False,
                tool_prompt=tool_prompt
            )
            return assistant_reply + tool_invocation_reply + "\n\n" + follow_up

            #TOOL_PROMPT = f"Tool has been successfully called: {tool} with arguments: {json.dumps(args)}"
            #return invoke_claude(chat, include_tools=False, tool_prompt = TOOL_PROMPT)

    if assistant_reply:
        chat.add("assistant", assistant_reply)
        return assistant_reply
    else:
        return "🤖 Sorry, I didn’t catch that."
    

if __name__ == "__main__":
    logger.info("🎬 Dive Agent Started – Type 'exit' to quit\n")
    chat = ChatSession(available_tools=[UPDATE_DIVE_INFORMATION_TOOL])
    start_chat(chat)

    while True:
        user_reply = input("\nYou: ")
        if user_reply.strip().lower() in ["exit", "quit"]:
            logger.info("Exiting session.")
            break
        continue_chat(chat, user_reply)