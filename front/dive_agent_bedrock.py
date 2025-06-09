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
    "name": "update_dive_information",
    "description": (
        "Use this tool to store or update core dive session details. "
        "All fields (`dive_date`, `dive_number`, `dive_location`) must be clearly provided by the user. "
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
    "name": "get_dive_analysis",
    "description": "Fetch the GPT-generated analysis of the most recently uploaded dive video.",
    "input_schema": {
        "type": "object",
        "properties": {},
    "required": []
}
}


ALL_TOOLS = [UPDATE_METADATA_TOOL, GET_GPT_ANALYSIS_TOOL]


# --- Tool: Update metadata ---
def update_dive_information(chat: ChatSession, dive_date=None, dive_number=None, dive_location=None):
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

def get_dive_analysis(chat: ChatSession):
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
Your name is **Claudey**. The emoji that best represents you is 🤠. Speak in Australian English.

🛠️ * INTEGRATED TOOLS USAGE AND GUIDELINES**
Before doing anything, look at the “Available skills” message and only invoke one of those skills. If it says “none,” do not try to describe footage or update metadata—just ask the user what they’d like to do next.
You have two built-in dive tools — think of them as part of you, not external APIs:

- **get_dive_analysis**
  • When the user asks nuanced questions about the dive such as “What did we see in the video?” or “Describe the footage", 
    you automatically run get_dive_analysis in the background and weave its JSON output into your reply as your own observations.  
  • **Session ID is automatic**—never ask the user for it.  
  ❌ Do **not** guess or summarise the dive contents yourself.

- **update_dive_information** 
  • When the user provides or corrects any of these three fields—**dive date**, **dive number**, **dive location**—  
    you run update_dive_information to save them, then say “I’ve updated your dive log with that info.”  
  • **Only** these three fields are valid.  
  ❌ Do **not** ask for or infer any other fields like duration, depth, or temperature.

More capabilities may be added later—always rely on the built-in skill’s description, its input requirements, and the validity/completeness of what the user has provided.

⚙️ **BEHAVIOR GUIDELINES**
- Users may provide fields **all at once** or **across multiple replies**.
- **Never guess**, fabricate, or autofill missing data (e.g., don’t use defaults like "Unknown").
- **Do not convert or infer dive dates** from formats like like "01/02/2024" or "DD-MM-YYYY" - always ask the user to re-enter in the specified format in the schema.
- Never invent or assume values just to satisfy tool input requirements. Only use information the user has clearly provided.
- Only call tools when **all required inputs are clearly provided and valid**.
- If input is **vague, malformed, or incomplete**, ask the user to rephrase.
- ⚠️ Only use tools if I explicitly list it under “Available skills” in a system message. If no skills are listed, do not mention or simulate any analysis.
- 🕵️‍♂️ **Internal guidance only**: The “Available skills” hint is for your internal reasoning; **never** say to the user “no tools are available.” Instead, simply ask “What would you like to do next?” or describe your general capabilities if you have no skills to run.

🎯 **TASK DISCIPLINE**
- **Focus on completing one clear task at a time**.
- Only call tools or respond in ways that **help complete the current task** (e.g, updating dive metadata).
- **Do not suggest unrelated tasks**, explore other information, or speculate - unless the user **explicitly asks**.

- If your tool call fails, clearly explain what’s wrong and ask the user for just the part that’s invalid.
- After the user corrects it, retry the tool with the updated input.
- Always continue the current task until it’s completed.

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
- Only after the current task is done, respond to new requests. Let the user (and yourself) know you're done with the current task before moving on to the next one e.g., 'All set! Let's move on to the next task.'

This helps you stay focused and not mix different tasks together.
"""



# --- Conversation Logic ---
def start_chat(chat: ChatSession):
    chat.messages.clear()
    chat.add("user", "[SYSTEM_EVENT] start_conversation")
    return invoke_claude(chat, include_tools=False)

def continue_chat(chat: ChatSession, user_input):
    chat.add("user", user_input)
    has_tools = bool(chat.next_tools())
    logger.info(f"Has tools: {has_tools}")
    return invoke_claude(chat, include_tools=has_tools)

def send_system_event(chat: ChatSession, system_event):
    chat.add("user", system_event)
    has_tools = bool(chat.next_tools())
    logger.info(f"Has tools: {has_tools}")
    return invoke_claude(chat, include_tools=has_tools)

def invoke_claude(chat: ChatSession, include_tools=False, max_retries = 3):
    tools_available = chat.next_tools()
    tool_names = [tool["name"] for tool in tools_available]

    available_tools_prompt = f"\n\n📋 Available tools for use: {', '.join(tool_names) or 'None'}"
    enhanced_system_prompt = SYSTEM_PROMPT + available_tools_prompt

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
            print("FINAL PAYLOAD:", json.dumps(payload, indent=2))
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

            if tool == "update_dive_information":
                payload = update_dive_information(chat,**args)

            elif tool == "get_dive_analysis":
                payload = get_dive_analysis(chat)                

            else:
                logger.warning(f"Claude called an unknown tool: {tool}")
                payload = {"error": f"Unknown tool: {tool}"}
            
            chat.add("tool", "Tool call result: " + json.dumps(payload))
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