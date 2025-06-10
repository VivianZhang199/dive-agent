import hashlib
import logging
import os
import sys
import time

import boto3
import streamlit as st
from botocore.exceptions import ClientError

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from chat_session import ChatSession
from config import config
from dive_agent_bedrock import start_chat, continue_chat, ALL_TOOLS
from utils import load_json_from_s3

# Initialise clients and logger
s3 = boto3.client("s3")
logger = logging.getLogger(__name__) 

# Set up the Streamlit page
st.set_page_config(page_title="Dive Agent", page_icon="🤿", layout="wide")

st.markdown(
    """
    <style>
    [data-testid="stChatMessage"] {
      background-color: transparent !important;
      padding-left: 0 !important;
    }

    [data-testid="stChatMessageContent"] {
      display: inline-block !important;   /* shrink-wrap to text */
      max-width: 70% !important;          /* cap width at ~70% */
      padding: 8px 12px !important;
      border-radius: 12px !important;     /* smooth curves */
      line-height: 1.4 !important;
      margin-left: 4px !important;      /* pin to left */
    }

    [data-testid="stChatMessageContent"][aria-label^="Chat message from assistant"] {
      background-color: #FFF9E5 !important;
      color: #00334d    !important;
    }

    [data-testid="stChatMessageContent"][aria-label^="Chat message from user"] {
      background-color: #FFE9EC !important;
      color: #4d0014   !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Style the sidebar
st.markdown("""
    <style>
    section[data-testid="stSidebar"] {
        background-color: #EAF6FB !important;
    }
    </style>
""", unsafe_allow_html=True)

col1, col2 = st.columns([1, 2])

def has_complete_metadata(metadata: dict) -> bool:
    """ Returns True only when all the required fields are not None."""
    return all(metadata.get(field) for field in ["dive_date", "dive_number", "dive_location"])

# Initialise the chat session
if "chat" not in st.session_state:
    chat = ChatSession(available_tools=ALL_TOOLS)
    st.session_state["chat"] = chat

# Get the chat session from the session state
chat: ChatSession = st.session_state["chat"]

# Start the chat session with the user
if "chat_started" not in st.session_state:
    st.session_state["chat_started"] = True
    first_reply = start_chat(chat)
    
# Left sidebar [Top section]: Video Upload
with st.sidebar:
    st.subheader("Upload a dive video!")
    uploaded_file = st.file_uploader("Note: .mp4 or .mov videos are supported.", type=["mp4", "mov"])

    # If a new video is uploaded, process it and update the chat session
    if uploaded_file and uploaded_file.name != st.session_state.get("last_uploaded_filename"):
        with st.spinner("Uploading and processing your dive video..."):
            raw_s3_key = f"raw/{uploaded_file.name}"
            s3.upload_fileobj(uploaded_file, config.BUCKET_NAME, raw_s3_key)
            st.success(f"✅ Video {uploaded_file.name} has been successfully uploaded!")

            # Generate a unique deterministic session ID
            session_id = hashlib.md5(raw_s3_key.encode()).hexdigest()
            logger.info(f"Uploaded video file: {uploaded_file.name} | dive_session_id = {session_id}")

            # Update the chat session with the new video
            chat.dive_session_id = session_id
            chat.current_dive = {}
            #chat.metadata_done = False
            
            # Send a system event to the chat session so that Claude knows the video has been uploaded
            continue_chat(chat, "[SYSTEM_EVENT] video_uploaded")

            st.session_state["last_uploaded_filename"] = uploaded_file.name
            
            processed_prefix = f"processed/{session_id}"
            timeout = 120
            start_time = time.time()
            metadata_key = None

            time.sleep(15)
            while time.time() - start_time < timeout:
                result = s3.list_objects_v2(Bucket=config.BUCKET_NAME, Prefix=processed_prefix)
                for obj in result.get("Contents", []):
                    if obj["Key"].endswith("session_metadata.json"):
                        metadata_key = obj["Key"]
                        break
                if metadata_key:
                    break
                time.sleep(3)

            # If the metadata is available (i.e., the video has been processed by the pipeline), load it into the chat session.
            if metadata_key:
                chat.current_dive = load_json_from_s3(metadata_key)
                #chat.metadata_done = has_complete_metadata(chat.current_dive)
                st.success("✅ The dive video has been processed.")
            else:
                st.error("⏳ Timed out waiting to retrieve the session metadata. Re-check that the video has been processed by the pipeline.")

    # Left sidebar [Bottom section]: Video Preview
    st.markdown("---")
    st.subheader("Video Preview")
    if uploaded_file is not None: 
        # Generate a presigned URL for the S3 video so that it can be previewed in the browser
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": config.BUCKET_NAME, "Key": f"raw/{uploaded_file.name}"},
            ExpiresIn=3600,
        )
        st.video(url)

# Chat interface
st.title("🤿 Dive Agent")
for message in chat.messages:

    content = message["content"]
    # Skip display of system events
    if content.startswith("[SYSTEM_EVENT]"):
        continue
    
    role = message["role"]
    if role == "assistant":
        with st.chat_message(role):
            st.write(f"**Dive Buddy Claude:** {content}")
    else:
        with st.chat_message("user"):
            st.write(f"**You:** {content}")

# User interaction
user_input = st.chat_input("Talk to Dive Buddy Claude.")

if user_input:
    st.chat_message("user").write(f"**You:** {user_input}")
    # After the user input, continue the chat session with Claude
    assistant_reply = continue_chat(chat, user_input)
    with st.chat_message("assistant"):
        st.write(f"**Dive Buddy Claude:** {assistant_reply}")

# Debug section to help with dev
with st.expander("🔍 Debug"):
    st.write("Current ChatSession state")
    st.json({
        "dive_session_id": chat.dive_session_id,
        "metadata_done": chat.metadata_done,
        "current_dive": chat.current_dive,
        "next_tools": chat.next_tools(),
        "last_uploaded_filename": st.session_state.get("last_uploaded_filename"),
        "messages": [f"{message['role']}: {message['content'][:60]}..." for message in chat.messages]
    })