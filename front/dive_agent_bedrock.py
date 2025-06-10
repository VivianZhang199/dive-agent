import json
import logging
import os
import sys
import time
from datetime import datetime
import re

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
        "Partial or all fields (`dive_date`, `dive_number`, `dive_location`) must be clearly provided by the user before calling this tool if they are all missing. User may confirm they only want to update one field at a time."
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

    existing = chat.current_dive
    no_fields_yet = not any(k in existing for k in ("dive_date","dive_number","dive_location"))
    
    # And the user hasn’t provided all three:
    if no_fields_yet and (dive_date is None or dive_number is None or dive_location is None):
        return {
            "error": (
                "Looks like we’re missing some initial info. "
                "Please provide dive_date, dive_number and dive_location together."
            )
        }

    if dive_date is not None:
        try:
            dive_date = dive_date.strip()
            datetime.strptime(dive_date, "%Y-%m-%d")
        except Exception:
            return {"error": "Invalid date format—please use YYYY-MM-DD."}
        #session["dive_date"] = dive_date
        chat.current_dive["dive_date"] = dive_date

    if dive_number is not None:
        try:
            dive_number = dive_number.strip()
            assert dive_number.isdigit()
        except Exception:
            return {"error": "Dive number must be a whole number."}
        #session["dive_number"] = dive_number
        chat.current_dive["dive_number"] = dive_number

    if dive_location is not None:
        dive_location = dive_location.strip()
        if len(dive_location) < 3:
            return {"error": "Dive location must be at least three characters."}
        #session["dive_location"] = dive_location
        chat.current_dive["dive_location"] = dive_location
    logger.info(f"Updated dive information: {chat.current_dive}")

    updated_key = f"processed/{session_id}/session_metadata.json"

    try:
        s3.put_object(
            Bucket=config.BUCKET_NAME,
            Key=updated_key,
            Body=json.dumps(chat.current_dive, indent=2),
            ContentType="application/json"
        )
        logger.info(f"✅ Session metadata saved to s3://{config.BUCKET_NAME}/{updated_key}")

        verify_obj = s3.get_object(Bucket=config.BUCKET_NAME, Key=updated_key)
        verify_data = verify_obj["Body"].read().decode("utf-8")
        logger.info(f"🔍 Verification read from S3: {verify_data}")

        return chat.current_dive
    except Exception as e:
        logger.error(f"❌ Failed to update session metadata in S3: {e}")
        return {"error": str(e)}

# --- Claude setup ---
SYSTEM_PROMPT = """
🧠 **ROLE & PURPOSE**
You are **Claudey**, a happy and helpful dive-buddy assistant. Speak in Australian English.
You help users complete one clear task at a time—like updating dive session metadata or answering dive questions.
Always start a new conversation with **"Howdy!"**.

Before doing anything, check the “📋 Available skills to use:” message.
Only invoke one skill per message. If it shows **None**, do **not** call any tool—just ask “What would you like to do next?”

🛠️ **CRITICAL TOOL USAGE RULES:**
- When users provide dive information to update, you MUST actually call the update_dive_information tool
- DO NOT just describe calling it or show code examples  
- DO NOT use backticks or pretty formatting - actually invoke the tool
- If you mention "🔧 Claude is calling:" you MUST be actually calling a tool, not just talking about it

**Tool: update_dive_information**
- **Valid inputs**: `dive_date`, `dive_number`, `dive_location`
- **First-time upload** (no metadata yet): insist on **all three** fields provided together before calling the tool.
- **Subsequent updates** (at least one field already exists): accept any subset of these fields.
- After saving, respond: **"✅ I've updated your dive log with that info."**
- Only these three fields are valid. **Do not** ask for or infer other fields (e.g., depth, duration).

⚙️ **BEHAVIOR GUIDELINES**
- **Never guess** or autofill missing values; only use exactly what the user gives, in **correct formats** (YYYY-MM-DD for dates).
- Only call the tool when **all required inputs** are clearly provided and valid.
- If user input is vague, malformed, or incomplete, ask for clarification **in one short message**.
- Do **not** volunteer limitations; only mention inability if explicitly asked (e.g., “Can you process video?”).
- **Do not** convert or infer date formats (e.g., DD/MM/YYYY)—ask user to re-enter in YYYY-MM-DD.

🔄 **CONVERSATION FLOW**
1. On `[SYSTEM_EVENT] start_conversation` or when the user says “Howdy!”, introduce yourself: “Howdy! I’m Claudey, your dive-buddy assistant.”
2. Identify the current task (e.g., updating metadata vs. answering dive questions).
3. If metadata fields are missing:
   - **First-time**: ask for all three fields together.
   - **Subsequent**: ask only for missing or corrected fields.
4. Once fields are valid, call **update_dive_information**, then acknowledge.
5. After acknowledgement, wait for the next user request and do not mix tasks.

🔄 **CONVERSATION FLOW**
1. On `[SYSTEM_EVENT] start_conversation` or when the user says “Howdy!”, introduce yourself: “Howdy! I’m Claudey, your dive-buddy assistant.”
2. Identify the current task (e.g., updating metadata vs. answering dive questions).
3. If metadata fields are missing:
   - **First-time**: ask for all three fields together.
   - **Subsequent**: ask only for missing or corrected fields.
4. Once fields are valid, call **update_dive_information**, then acknowledge.
5. After acknowledgement, wait for the next user request and do not mix tasks.

📡 **SYSTEM EVENTS**
- You may receive:
  - `[SYSTEM_EVENT] start_conversation`
  - `[SYSTEM_EVENT] video_uploaded`
- **Do not** generate or invent other system events.

🤿 **TONE & STYLE**
- Sound like a **friendly dive buddy** logging dives.
- Keep replies **clear, concise, and helpful**.
- Use emojis: 🐠, 🤿, ✅.
- If you need multiple pieces of info, **ask in one message** to stay efficient.

**CRITICAL TOOL USAGE:**
- When the user provides dive information to update, you MUST actually call the update_dive_information tool
- Do NOT just say you're calling it - actually use the tool system to call it
- Only mention tools in text if you cannot determine what to update
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

def parse_fake_tool_call(text):
    """Extract tool name and arguments from Claude's fake tool calls."""
    tool_pattern = r'🔧 Claude is calling: `([^`]+)` with arguments:'
    tool_match = re.search(tool_pattern, text)

    if not tool_match:
        return None, None
    tool_name = tool_match.group(1)

    json_pattern = r'```json\s*(\{[^`]+\})\s*```'
    json_match = re.search(json_pattern, text, re.DOTALL)

    if json_match:
        try:
            args = json.loads(json_match.group(1))
            logger.info(f"🔧 Parsed fake call: {tool_name} with {args}")
            return tool_name, args
        except Exception as e:
            logger.error(f"Failed to parse fake tool call JSON: {e}")

    return tool_name, None
    
def invoke_claude(chat: ChatSession, include_tools=False, tool_prompt = "", max_retries = 4):
    tools_available = chat.next_tools()
    tool_names = [tool["name"] for tool in tools_available]

    tools_available_prompt = f"\n\n📋 Available tools for use: {', '.join(tool_names) or 'None'}"

    separator = "\n----------\n"
    enhanced_system_prompt = SYSTEM_PROMPT + separator + "CURRENT STATE:\n" + tools_available_prompt + "\n" + tool_prompt + separator

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

    '''logger.info("Sending messages to Claude:")
    for m in chat.messages:
        logger.info(f" - {m['role']}: {m['content'][:60]}")'''

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
        if message["type"] == "text":
            assistant_reply = message["text"]

            # Check for fake tool calls
            if "🔧 Claude is calling:" in assistant_reply:
                tool_name, fake_args = parse_fake_tool_call(assistant_reply)

                if tool_name and fake_args:
                    logger.info(f"Executing fake tool call: {tool_name} with {fake_args}")

                    if tool_name == "update_dive_information":
                        tool_result = update_dive_information(chat, **fake_args)
                    else:
                        logger.warning(f"Unknown fake tool call: {tool_name}")
                        tool_result = {"error": f"Unknown tool: {tool_name}"}

                    outcome = "failed" if tool_result.get("error") else "succeeded"
                    tool_result_message = f"[SYSTEM_EVENT] Tool `{tool_name}` {outcome}: {json.dumps(tool_result)}"

                    chat.add("assistant", assistant_reply)
                    chat.add("user", tool_result_message)
                    
                    follow_up = invoke_claude(chat, include_tools=False)
                    return assistant_reply + "\n\n" + follow_up
            
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
            
            outcome = "failed" if payload.get("error") else "succeeded"
            tool_result_message = f"[SYSTEM_EVENT] Tool `{tool}` {outcome}: {json.dumps(payload)}"

            combined_reply = assistant_reply + tool_invocation_reply
            chat.add("assistant", combined_reply)

            chat.add("user", tool_result_message)
            follow_up = invoke_claude(chat, include_tools=False, tool_prompt=tool_result_message)
            
            return combined_reply + "\n\n" + follow_up

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