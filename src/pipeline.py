import os
import datetime
import secrets
import logging
import json
import boto3
import hashlib

from config import config 
from extract_frames import extract_frames
from analyse_with_gpt import analyse_with_gpt, load_system_prompt
from utils import write_to_s3, download_video_from_s3

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

s3 = boto3.client('s3')

def generate_session_id(s3_key):
    return hashlib.md5(s3_key.encode()).hexdigest()

def run_pipeline(s3_key):
    session_id = generate_session_id(s3_key)

    try:
        logger.info(f"Downloading the video from S3: {s3_key}")

        # Extract the filename from the s3 key and download directly to the /tmp directory
        filename = s3_key.split("/")[-1]
        temp_video_path = f"{config.TEMP_DIR}/{filename}"
        download_video_from_s3(config.BUCKET_NAME, s3_key, temp_video_path)
        logger.info(f"Successfully downloaded the video to {temp_video_path}.")
        
        base_prefix = f"processed/{session_id}"
        frames_prefix = f"{base_prefix}/frames"
        metadata_key = f"{base_prefix}/session_metadata.json"
        gpt_output_key = f"{base_prefix}/gpt_output.json"
        reasoning_key = f"{base_prefix}/reasoning.txt"

        logger.info(f"Processing dive session with s3 key: {s3_key} | Session ID: {session_id}")

        # Extract and upload frames
        image_urls = extract_frames(
            temp_video_path, 
            s3,  
            frames_prefix, 
            config.MAX_FRAMES, 
            config.FRAME_INTERVAL
        )
        
        # Run GPT analysis
        system_prompt = load_system_prompt()
        logger.info(f"Image URLs: {image_urls}")
        gpt_result = analyse_with_gpt(image_urls, system_prompt)

        # Upload reasoning and JSON to S3
        write_to_s3(gpt_result['json_only'], config.BUCKET_NAME, gpt_output_key)

        # Session metadata
        metadata = {
            'session_id': session_id,
            'video_filename': s3_key.split("/")[-1],
            's3_key': s3_key,
            'dive_date': None,
            'dive_number': None,
            'dive_location': None,
            'gpt_output_url': gpt_output_key
        }
        write_to_s3(json.dumps(metadata, indent=2), config.BUCKET_NAME, metadata_key)

        logger.info(f"Dive Pipeline Complete: {session_id}")
        return session_id
    
    except Exception as e:
        logger.error(f"Dive Pipeline Failed: {str(e)}")
        raise
    
    finally:
        if temp_video_path and os.path.exists(temp_video_path):
            os.remove(temp_video_path)

if __name__ == "__main__":
    run_pipeline(s3_key = 'raw/GX010345_ALTA4463795217888132720~4.mp4')