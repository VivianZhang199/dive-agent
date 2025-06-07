import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

import streamlit as st
import boto3
import uuid
from datetime import datetime
from config import config
from handler import lambda_handler
from dive_agent_bedrock import start_chat, continue_chat, messages
from utils import load_json_from_s3
import time
import hashlib
import json

s3 = boto3.client("s3")

st.set_page_config(page_title="Dive Metadata Agent", page_icon="🤿", layout="centered")

st.title("🤖 Dive Assistant")

st.subheader("Current Dive Session")

# 👋 General intro
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
    welcome_msg = "Howdy! Upload a dive video and I’ll help you log it — species, location, and all. 🐠"
    st.session_state.chat_history.append({"role": "assistant", "content": welcome_msg})

# 📤 Upload video
with st.sidebar:
    st.subheader("Upload a dive video")
    uploaded_file = st.file_uploader("Upload your dive video", type=["mp4", "mov"])

if uploaded_file and "session_loaded" not in st.session_state:
    with st.spinner("Uploading and processing your dive video..."):
        raw_s3_key = f"raw/{uploaded_file.name}"
        s3.upload_fileobj(uploaded_file, config.BUCKET_NAME, raw_s3_key)
        st.success("✅ Video successfully uploaded!")
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
            print("DEBUG session to Claude:", json.dumps(session, indent=2))
            st.session_state["session_loaded"] = True
            st.session_state["session"] = session
            first_reply = start_chat(session)
            st.session_state.chat_history.append({"role": "assistant", "content": f"{first_reply}"})
        else:
            st.error("⏳ Timed out waiting for session metadata. Try again later.")

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

    continue_chat(st.session_state["session"], user_input)

    reply = messages[-1]["content"] if messages else "Hmmm..."
    with st.chat_message("assistant"):
        st.markdown(f"🤖 **Dive Buddy Claude:** {reply}")
    st.session_state.chat_history.append({"role": "assistant", "content": reply})