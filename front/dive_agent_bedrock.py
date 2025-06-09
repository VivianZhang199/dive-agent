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

UPDATE_METADATA_TOOL = {
    "name": "update_session_metadata",
    "description": (
        "Use this tool to update a dive session's metadata. "
        "All of the following fields must be clearly provided: "
        "`dive_date`, `dive_number`, `dive_location`."
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
        "required": ["dive_date", "dive_number", "dive_location"]
    }
}

GET_GPT_ANALYSIS_TOOL = {
    "name": "get_gpt_analysis",
    "description": "Returns the GPT dive analysis for a processed dive video session.",
    "input_schema": {
        "type": "object",
        "properties": {},
    "required": []
}
}


ALL_TOOLS = [UPDATE_METADATA_TOOL, GET_GPT_ANALYSIS_TOOL]


# --- Tool: Update metadata ---
def update_session_metadata(chat: ChatSession, dive_date=None, dive_number=None, dive_location=None):
    session_id = chat.dive_session_id
    logger.info(f"Validating tool input for session {session_id}")
    
    try: 
        datetime.strptime(date_str.strip(), "%Y-%m-%d")
        assert dive_number.isdigit()
        assert len(dive_location) >= 3
    except Exception as e:
        logger.warning("Validation failed")
        return {"error": "Invalid input for dive metadata update."}

    logger.info(f"Inputs are valid. Updating session metadata for session_id={session_id}")

    chat.current_dive.update(
         dive_date=dive_date,
         dive_number=dive_number,
         dive_location=dive_location
    )
    chat.metadata_done = True

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

def get_gpt_analysis(chat: ChatSession):
    session_id = chat.dive_session_id
    key = f"processed/{session_id}/gpt_output.json"
    
    try:
        gpt_analysis = load_json_from_s3(key)
        logger.info(f"GPT analysis is {gpt_analysis}")
        return gpt_analysis
    except Exception as e:
        error_msg = {"error": str(e)}
        logger.error(f"❌ Failed to get GPT analysis for session {session_id}: {e}")
        return error_msg

# --- Claude setup ---
SYSTEM_PROMPT = """
🧠 **ROLE & PURPOSE**
**You are a happy and helpful dive assistant** who supports users in completing **specific dive session tasks**, like updating **dive session metadata** or answering dive questions. 
Your name is **Claudey**. The emoji that best represents you is 🤠.

🛠️ **TOOL USAGE**
You can use tools to:
- **Update missing dive metadata** using the `update_session_metadata` tool.  
  Only the following fields are valid: `dive date`, `dive number`, and `dive location`.  
  ❌ Do **not** ask for or infer any other fields like dive duration, depth, temperature, etc.

- **Retrieve GPT dive analysis** using the `get_gpt_analysis` tool.  
  Only use this tool when a valid `session_id` has been provided.  
  The session ID is always available in system context. Never ask the user to provide or confirm it. When calling get_gpt_analysis, use the session already loaded into memory.
  ❌ Never summarize or guess the dive contents yourself.

More tools may be added. Always rely on:
- The **tool’s description**
- The tool’s **input schema**
- The **validity** and **completeness** of the user’s input

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
- **Do not suggest unrelated tasks**, explore other information, or speculate - unless the user **explicitly asks**.

- If your tool call fails, clearly explain what’s wrong and ask the user for just the part that’s invalid.
- After the user corrects it, retry the tool with the updated input.
- Always continue the current task until it’s completed.

📡 **SYSTEM EVENTS**
- Occasionally, you'll receive special system-triggered messages that are prefixed with `[SYSTEM_EVENT]`. 
Examples:
- `[SYSTEM_EVENT] start_conversation`: The user just opened the app. Start by introducing yourself and asking what they’d like help with — don’t assume the task yet.
- `[SYSTEM_EVENT] video_uploaded`: A dive video has been uploaded. Begin helping the user complete its metadata.

- These are **not user messages**. They signal that something changed in the app — like a video being uploaded or metadata being available.
- Treat them like backend notifications.
- When you see one, respond naturally — for example:
  - If `[SYSTEM_EVENT] video_uploaded`, you might say: “✅ Got your video! Let’s check the metadata and make sure everything’s filled out.”
- Use these events to guide the user toward next helpful steps. Don’t ignore them.
- Do not reveal any information about the system event details back to the user.

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
    chat.add("user", user_input)
    return invoke_claude(chat, include_tools=True)

def invoke_claude(chat: ChatSession, include_tools=True, max_retries = 3):
    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "system": SYSTEM_PROMPT,
        "messages": chat.messages,
        "max_tokens":  5000
    }

    if include_tools:
        tools = chat.next_tools()
        if tools:
            payload["tools"] = tools
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
            logger.info(f"{assistant_reply}")
            
        elif message["type"] == "tool_use":
            tool = message["name"]
            args = message["input"]
            
            logger.info(f"\n🔧 Claude is calling: {tool} with arguments: {json.dumps(args)}")

            assistant_reply += (
                f"\n\n🔧 Claude is calling: `{tool}` with arguments:\n```json\n{json.dumps(args, indent=2)}\n```"
            )

            if tool == "update_session_metadata":
                payload = update_session_metadata(chat,**args)

            elif tool == "get_gpt_analysis":
                payload = get_gpt_analysis(chat)                

            else:
                logger.warning(f"Claude called an unknown tool: {tool}")
                payload = {"error": f"Unknown tool: {tool}"}
            
            chat.add("tool_result", json.dumps(payload))
            return invoke_claude(chat, include_tools=False)

    if assistant_reply:
        chat.add("assistant", assistant_reply)
        return assistant_reply
    else:
        return "🤖 Sorry, I didn’t catch that."
    

if __name__ == "__main__":
    logger.info("🎬 Dive Agent Started – Type 'exit' to quit\n")
    chat = ChatSession(available_tools=[UPDATE_METADATA_TOOL, GET_GPT_ANALYSIS_TOOL])
    start_chat(chat)

    while True:
        user_reply = input("\nYou: ")
        if user_reply.strip().lower() in ["exit", "quit"]:
            logger.info("Exiting session.")
            break
        continue_chat(chat, user_reply)