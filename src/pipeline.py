import os
import subprocess
import datetime
import secrets
import logging
import boto3
import json
import cv2
from openai import OpenAI
import io
import tempfile
import shutil
import re

BUCKET_NAME = os.environ.get('BUCKET_NAME', 'vivian-dive-bucket')
REGION = os.environ.get('AWS_REGION', 'ap-southeast-2')
SECRET_NAME = os.environ.get('SECRET_NAME', 'dive-analysis-openai-key')
MAX_FRAMES = int(os.environ.get('MAX_FRAMES', '3'))
FRAME_INTERVAL = int(os.environ.get('FRAME_INTERVAL', '3'))

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

s3 = boto3.client('s3')

def get_openai_api_key():
    """Retrieve OpenAI API Key from AWS Secrets Manager"""
    try:
        secrets_client = boto3.client('secretsmanager', region_name=REGION)
        response = secrets_client.get_secret_value(SecretId=SECRET_NAME)
        secret = json.loads(response['SecretString'])
        return secret['dive-analysis-openai-key']
    except Exception as e:
        logger.error(f"Error retrieving OpenAI API Key: {str(e)}")
        return os.environ.get('OPENAI_API_KEY')

client = OpenAI(api_key=get_openai_api_key())


def generate_timestamp_id():
    timestamp = datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')
    random_hex = secrets.token_hex(5)
    return f"{timestamp}_{random_hex}"


def extract_n_frames(video_path, s3_client, bucket_name, s3_prefix, max_frames = MAX_FRAMES, frame_interval = FRAME_INTERVAL):
    """Extract frames with proper error handling and cleanup for Lambda"""
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp(dir='/tmp')

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Could not open video file: {video_path}")
            
        saliency_detector = cv2.saliency.StaticSaliencySpectralResidual_create()
        frame_scores = []
        frame_count = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            if frame_count % frame_interval == 0:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
                success, saliency = saliency_detector.computeSaliency(frame)
                saliency_score = saliency.mean() if success else 0
                combined_score = (sharpness * 0.7) + (saliency_score * 100 * 0.3)
                frame_scores.append((combined_score, frame.copy(), frame_count))

            frame_count += 1

        cap.release()

        saved_urls = []
        best_frames = sorted(frame_scores, key = lambda x: x[0], reverse = True)[:max_frames]

        for i, (_, frame, idx) in enumerate(best_frames):
            filename = f"frame_{i+1}_at_{idx}.jpg"
            filepath = os.path.join(temp_dir, filename)
            key = f"{s3_prefix}/{filename}"

            cv2.imwrite(filepath, frame)
            s3_client.upload_file(filepath, bucket_name, key)
            logger.info(f"Uploaded frame {i+1} to s3://{bucket_name}/{key}")
            os.remove(filepath)

            url = f"https://{bucket_name}.s3.{REGION}.amazonaws.com/{key}"
            saved_urls.append(url)
        return saved_urls
    
    except Exception as e:
        logger.error(f"Error in frame extraction: {str(e)}")
        raise
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

def load_system_prompt():
    """ Load system prompt from S3 for Lambda compatbility"""
    try:
        with open('system_prompt.txt', 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        logger.error("System prompt file not found")
        raise

def analyse_with_gpt(image_urls, system_prompt):
    logger.info(f"Analysing with GPT: {image_urls}")
    try:
        prompt_text = "Here are several cropped frames from a dive video."
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": build_image_input(image_urls, prompt_text)}
        ]

        response = client.responses.create(
            model="gpt-4.1-mini",
            input=messages
        )
        full_output = response.output_text
        logger.debug(f"GPT response: {full_output}")

        match = re.search(r'<BEGIN_JSON>(.*?)<END_JSON>', full_output, re.DOTALL)
        if not match:
            raise ValueError("No JSON found in GPT response")

        json_str = match.group(1).strip()
        reasoning_text = full_output[:match.start()].strip()

        # Validate JSON
        parsed_json = json.loads(json_str)

        return {
            "reasoning_text": reasoning_text,
            "json_only": json.dumps(parsed_json, indent=2)
        }
        
    except Exception as e:
        logger.error(f"Error in GPT analysis: {str(e)}")
        raise

def upload_file_to_s3(filepath, bucket, key):
    s3.upload_file(filepath, bucket, key)
    logger.info(f"Uploaded {filepath} to {bucket}/{key}")

def upload_string_to_s3(string_data, bucket, key):
    s3.upload_fileobj(io.BytesIO(string_data.encode()), bucket, key)
    logger.info(f"Uploaded string data to s3://{bucket}/{key}")

def build_image_input(image_urls, prompt_text):
    filenames = [url.split("/")[-1] for url in image_urls]
    full_prompt = f"{prompt_text}\n\nImages in order:\n" + "\n".join(f"- {f}" for f in filenames)
    content = [{"type": "input_text", "text": full_prompt}]
    for url in image_urls:
        content.append({
            "type": "input_image",
            "image_url": url,
            "detail": "low"
        })
    return content

def download_video_from_s3(bucket, key, destination):
    s3.download_file(bucket, key, destination)
    logger.info(f"Downloaded s3://{bucket}/{key} to {destination}")

def run_pipeline(s3_key):
    """Complete pipeline for processing dive videos"""
    temp_video_path = None
    session_id = generate_timestamp_id()

    upload_date = datetime.date.today().isoformat()
    extracted_date = upload_date
    confirmed_date = "unknown"

    try:
        temp_video_path = f"/tmp/{os.path.basename(s3_key)}"
        download_video_from_s3(BUCKET_NAME, s3_key, temp_video_path)
        
        base_prefix = f"dives/{session_id}"
        frames_prefix = f"{base_prefix}/frames"
        metadata_key = f"{base_prefix}/session_metadata.json"
        gpt_output_key = f"{base_prefix}/gpt_output.json"
        reasoning_key = f"{base_prefix}/reasoning.txt"

        logger.info(f"Processing dive session | Session ID: {session_id}")

        # Extract and upload frames
        image_urls = extract_n_frames(temp_video_path, s3, BUCKET_NAME, frames_prefix)

        # Run GPT analysis
        system_prompt = load_system_prompt()
        gpt_result = analyse_with_gpt(image_urls, system_prompt)

        # Upload reasoning and JSON to S3
        upload_string_to_s3(gpt_result['reasoning_text'], BUCKET_NAME, reasoning_key)
        upload_string_to_s3(gpt_result['json_only'], BUCKET_NAME, gpt_output_key)

        # Session metadata
        metadata = {
            'session_id': session_id,
            'video_filename': os.path.basename(s3_key),
            's3_key': s3_key,
            'dive_date': None,
            'dive_number': None,
            'dive_location': None,
            'gpt_output_url': f"https://{BUCKET_NAME}.s3.{REGION}.amazonaws.com/{gpt_output_key}",
            'frame_urls': image_urls
        }
        upload_string_to_s3(json.dumps(metadata, indent=2), BUCKET_NAME, metadata_key)

        logger.info(f"Dive Pipeline Complete: {session_id}")
        return session_id
    
    except Exception as e:
        logger.error(f"Dive Pipeline Failed: {str(e)}")
        raise
    
    finally:
        if temp_video_path and os.path.exists(temp_video_path):
            os.remove(temp_video_path)
