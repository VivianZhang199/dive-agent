import streamlit as st
import boto3
import uuid
from datetime import datetime
from config import config
from handler import lambda_handler

s3 = boto3.client("s3")

st.title("Dive Agent")

uploaded_file = st.file_uploader("Upload a dive video", type = ["mp4", "mov"])

if uploaded_file:
    #session_id = datetime.now().strftime("%Y%m%d%H%M%S") + "_" + uuid.uuid4().hex[:10]
    s3_key = f"raw/{uploaded_file.name}"

    s3.upload_fileobj(uploaded_file, config.BUCKET_NAME, s3_key)
    st.success(f"Video uploaded to S3")
    print("Uploading to key:", s3_key)

    with st.spinner("Waiting for Dive Agent to process the video..."):
        st.info("Your video has been uploaded. Dive Agent will automatically begin processing it shortly via AWS Lambda.")