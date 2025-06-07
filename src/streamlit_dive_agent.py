import streamlit as st
import boto3
import uuid
from datetime import datetime
from config import config
from handler import lambda_handler
from dive_agent_bedrock import session, start_chat, continue_chat, messages

s3 = boto3.client("s3")

st.set_page_config(page_title="Dive Metadata Agent", page_icon="🤿", layout="centered")

st.title("🤖 Dive Metadata Assistant")

st.subheader("Current Dive Session")
st.json(session)

# initial Claude call
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
    first_reply = start_chat(session)
    st.session_state.chat_history.append({"role": "assistant", "content": first_reply})

# Render previous messages
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        if msg["role"] == "assistant":
            st.markdown(f"🤖 **Dive Buddy Claude:** {msg['content']}")
        else:
            st.markdown(msg["content"])

# Chat input
user_input = st.chat_input("Help Claude tag your dive session")

if user_input:
    with st.chat_message("user"):
        st.markdown(user_input)
    st.session_state.chat_history.append({"role": "user", "content": user_input})

    continue_chat(user_input)

    reply = messages[-1]["content"] if messages else "Hmmm..."
    with st.chat_message("assistant"):
        st.markdown(f"🤖 **Dive Buddy Claude:** {reply}")
    st.session_state.chat_history.append({"role": "assistant", "content": reply})