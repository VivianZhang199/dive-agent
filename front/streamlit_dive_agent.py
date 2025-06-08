import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import streamlit as st
import boto3
import uuid
from datetime import datetime
from config import config
from handler import lambda_handler
from dive_agent_bedrock import start_chat, continue_chat, messages, send_system_event
from utils import load_json_from_s3
import time
import hashlib
import json

from botocore.exceptions import ClientError

s3 = boto3.client("s3")

st.set_page_config(page_title="Dive Agent", page_icon="🤿", layout="wide")
col1, col2 = st.columns([1, 2])

st.markdown("""
    <style>
    section[data-testid="stSidebar"] {
        background-color: #EAF6FB !important;
    }
    </style>
""", unsafe_allow_html=True)

def get_presigned_video_url(key, expiration=3600):
    try:
        response = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": config.BUCKET_NAME, "Key": key},
            ExpiresIn=expiration,
        )
        return response
    except ClientError as e:
        logger.warning(f"Couldn't generate pre-signed URL: {e}")
        return None

# LEFT: Upload video
with st.sidebar:
    st.subheader("Upload media")
    uploaded_file = st.file_uploader("Upload your dive video", type=["mp4", "mov"])

    if uploaded_file and not st.session_state.get("video_uploaded"):
        with st.spinner("Uploading and processing your dive video..."):
            raw_s3_key = f"raw/{uploaded_file.name}"
            s3.upload_fileobj(uploaded_file, config.BUCKET_NAME, raw_s3_key)
            st.success("✅ Video successfully uploaded!")
            st.session_state["video_uploaded"] = True
            st.session_state["s3_key"] = raw_s3_key

            # Determine session ID + processed prefix
            session_id = hashlib.md5(raw_s3_key.encode()).hexdigest()
            processed_prefix = f"processed/{session_id}"

            
            # 🕓 Poll for processed/{session_id}/session_metadata.json
            timeout = 120
            start_time = time.time()

            metadata_key = None
            while time.time() - start_time < timeout:
                result = s3.list_objects_v2(Bucket=config.BUCKET_NAME, Prefix=processed_prefix)
                for obj in result.get("Contents", []):
                    if obj["Key"].endswith("session_metadata.json"):
                        metadata_key = obj["Key"]
                        break
                
                if metadata_key:
                    break
                time.sleep(3)

            if metadata_key:
                session = load_json_from_s3(metadata_key)
                st.session_state["session_loaded"] = True
                st.session_state["session"] = session
                followup = send_system_event(session, "video_uploaded")
                st.session_state.chat_history.append({"role": "assistant", "content": followup})
            else:
                st.error("⏳ Timed out waiting for session metadata. Try again later.")

    st.markdown("---")
    st.subheader("Video Preview")
    if st.session_state.get("video_uploaded") and st.session_state.get("s3_key"):
        video_url = get_presigned_video_url(st.session_state["s3_key"])
        if video_url:
            st.video(video_url)
        else:
            st.write("Video preview unavailable")


# 📣 Chat section
st.title("🤿 Dive Agent")

# 👋 General intro
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
    first_reply = start_chat({})
    st.session_state.chat_history.append({'role': 'assistant', 'content': first_reply})

# 💬 Chat history
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant":
            st.markdown(f"🤖 **Dive Buddy Claude:** {msg['content']}")
        else:
            st.markdown(msg["content"])

# 💬 Claude interaction
user_input = st.chat_input("Help Dive Buddy Claude tag your dive session")

if user_input:
    with st.chat_message("user"):
        st.markdown(user_input)
    st.session_state.chat_history.append({"role": "user", "content": user_input})

    # If no session exists, use an empty one 
    session = st.session_state.get("session", {})
    continue_chat(session, user_input)

    reply = messages[-1]["content"] if messages else "Hmmm..."
    with st.chat_message("assistant"):
        st.markdown(f"🤖 **Dive Buddy Claude:** {reply}")
    st.session_state.chat_history.append({"role": "assistant", "content": reply})