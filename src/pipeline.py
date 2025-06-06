import os
import datetime
import secrets
import logging
import json
import boto3

from config import config 
from extract_frames import extract_n_frames
from analyse_with_gpt import analyse_with_gpt, load_system_prompt
from utils import upload_string_to_s3, download_video_from_s3

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

s3 = boto3.client('s3')

def generate_session_id(s3_key):
    return hashlib.md5(s3_key.encode()).hexdigest()

def run_pipeline(s3_key):
    """Complete pipeline for processing dive videos"""
    temp_video_path = None
    session_id = generate_session_id(s3_key)
    
    upload_date = datetime.date.today().isoformat()
    extracted_date = upload_date
    confirmed_date = "unknown"

    try:
        logger.info(f"Downloading video from S3: {s3_key}")
        temp_video_path = f"{config.TEMP_DIR}/{s3_key}"
        os.makedirs(os.path.dirname(temp_video_path), exist_ok=True)
        
        download_video_from_s3(config.BUCKET_NAME, s3_key, temp_video_path)
        logger.info(f"Downloaded video to {temp_video_path}")
        
        base_prefix = f"dives/{session_id}"
        frames_prefix = f"{base_prefix}/frames"
        metadata_key = f"{base_prefix}/session_metadata.json"
        gpt_output_key = f"{base_prefix}/gpt_output.json"
        reasoning_key = f"{base_prefix}/reasoning.txt"

        logger.info(f"Processing dive session | Session ID: {session_id}")

        # Extract and upload frames
        image_urls = extract_n_frames(
            temp_video_path, 
            s3, 
            config.BUCKET_NAME, 
            frames_prefix, 
            config.MAX_FRAMES, 
            config.FRAME_INTERVAL
        )

        # Run GPT analysis
        system_prompt = load_system_prompt()
        gpt_result = analyse_with_gpt(image_urls, system_prompt)

        # Upload reasoning and JSON to S3
        upload_string_to_s3(gpt_result['reasoning_text'], config.BUCKET_NAME, reasoning_key)
        upload_string_to_s3(gpt_result['json_only'], config.BUCKET_NAME, gpt_output_key)

        # Session metadata
        metadata = {
            'session_id': session_id,
            'video_filename': s3_key.split("/")[-1],
            's3_key': s3_key,
            'dive_date': None,
            'dive_number': None,
            'dive_location': None,
            'gpt_output_url': f"https://{config.BUCKET_NAME}.s3.{config.REGION}.amazonaws.com/{gpt_output_key}"
        }
        upload_string_to_s3(json.dumps(metadata, indent=2), config.BUCKET_NAME, metadata_key)

        logger.info(f"Dive Pipeline Complete: {session_id}")
        return session_id
    
    except Exception as e:
        logger.error(f"Dive Pipeline Failed: {str(e)}")
        raise
    
    finally:
        if temp_video_path and os.path.exists(temp_video_path):
            os.remove(temp_video_path)

if __name__ == "__main__":
    run_pipeline(s3_key = 'raw/GX010477_ALTA4463795217888132720~3.mp4')