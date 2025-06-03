import boto3
import json
import logging
import os
from config import config
from urllib.parse import urlparse

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

s3 = boto3.client("s3")

def list_metadata_keys(prefix="dives/"):
    """List all session_metadata.json keys in the bucket."""
    keys = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=config.BUCKET_NAME, Prefix=prefix):
        for obj in page.get("Contents", []):
            if obj["Key"].endswith("session_metadata.json"):
                keys.append(obj["Key"])
    return keys

def load_json_from_s3(key):
    obj = s3.get_object(Bucket=config.BUCKET_NAME, Key=key)
    return json.loads(obj["Body"].read().decode("utf-8"))

def extract_gpt_data(gpt_output_url):
    parsed = urlparse(gpt_output_url)
    key = parsed.path.lstrip("/")
    #bucket = parsed.netloc.split('.')[0]
    obj = s3.get_object(Bucket=config.BUCKET_NAME, Key=key)
    data = json.loads(obj["Body"].read().decode("utf-8"))

    return {
        'filename': data.get('filename'),
        'animal': data.get('animal'),
        'description': data.get('description'),
        'confidence': data.get('confidence')
    }


def update_knowledge_base():
    kb = {'species_seen': {}}
    seen_video_keys = set()
    metadata_keys = list_metadata_keys()

    logger.info(f"Found {len(metadata_keys)} sessions")

    for meta_key in metadata_keys:
        try:
            metadata = load_json_from_s3(meta_key)
            s3_key = metadata.get('s3_key')

            if not s3_key or s3_key in seen_video_keys:
                continue

            seen_video_keys.add(s3_key)
            logger.info(f"Seen video key: {seen_video_keys}")

            session_id = metadata.get('session_id')
            video_filename = metadata.get('video_filename')
            gpt_output_url = metadata.get('gpt_output_url')
            frame_urls = metadata.get('frame_urls', [])

            gpt = extract_gpt_data(gpt_output_url)

            matched_url = next((url for url in frame_urls if gpt['filename'] in url), None)
            if not matched_url:
                logger.warning(f"No matching frame url found for {gpt['filename]']} in session {session_id}")
                continue
            
            sighting = {
                "session_id": session_id,
                "video_filename": video_filename,
                "s3_key": s3_key,
                "filename": gpt["filename"],
                "image_url": matched_url,
                "description": gpt["description"]
            }

            species_key = gpt["animal"].lower()
            kb['species_seen'].setdefault(species_key, []).append(sighting)
        
        except Exception as e:
            logger.error(f"Error processing {meta_key}: {str(e)}")
            continue

    return kb

def save_kb_to_s3(kb, key = "brain_kb.json"):
    s3.put_object(
        Bucket=config.BUCKET_NAME,
        Key=key,
        Body=json.dumps(kb, indent=2).encode("utf-8")
    )
    logger.info(f"Saved KB to s3://{BUCKET_NAME}/{key}")
if __name__ == "__main__":
    #print(extract_gpt_data('https://vivian-dive-bucket.s3.ap-southeast-2.amazonaws.com/dives/20250602093056_fbe6dcd954/gpt_output.json'))
    print(update_knowledge_base())