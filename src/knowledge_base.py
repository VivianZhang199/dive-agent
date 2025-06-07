import boto3
from botocore.exceptions import ClientError
import json
import logging
import os
from config import config
from urllib.parse import urlparse

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

s3 = boto3.client("s3")

dynamodb = boto3.resource('dynamodb', region_name = config.REGION)
table = dynamodb.Table(config.KNOWLEDGE_BASE_TABLE)


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
    kb = {'dives': {}}
    seen_video_keys = set()
    metadata_keys = list_metadata_keys()

    logger.info(f"Found {len(metadata_keys)} sessions")

    for meta_key in metadata_keys:
        try:
            metadata = load_json_from_s3(meta_key)
            s3_key = metadata.get('s3_key')

            # Skip any duplicates
            if not s3_key or s3_key in seen_video_keys:
                logger.info(f"Skipping duplicate video: {s3_key}")
                continue
            seen_video_keys.add(s3_key)
            
            # Required metadata
            dive_date = metadata.get('dive_date')
            dive_number = metadata.get('dive_number')
            if not dive_date or not dive_number:
                logger.info(f"Skipping session without dive info: {meta_key}")
                continue

            session_id = metadata.get('session_id')
            video_filename = metadata.get('video_filename')
            gpt_output_url = metadata.get('gpt_output_url')
            frame_urls = metadata.get('frame_urls', [])
            dive_location = metadata.get('dive_location')

            gpt = extract_gpt_data(gpt_output_url)

            if not gpt['animal'] or gpt['animal'].lower() == 'unknown':
                continue

            matched_url = next((url for url in frame_urls if gpt['filename'] in url), None)
            if not matched_url:
                logger.warning(f"No matching frame URL found for {gpt['filename]']} in session {session_id}")
                continue
            
            dive_id = f"{dive_date}_#{dive_number}"
            dive_entry = kb['dives'].setdefault(dive_id, {
                'dive_date': dive_date,
                'dive_number': dive_number,
                'dive_location': dive_location,
                'sessions': [],
                'species_seen': []
            })

            if session_id not in dive_entry['sessions']:
                dive_entry['sessions'].append(session_id)
                dive_entry['species_seen'].append({
                    'name': gpt['animal'],
                    'confidence': gpt['confidence'],
                    'description': gpt['description'], 
                    'image_url': matched_url,
                    'video_filename': video_filename,
                    's3_key': s3_key,
                    'session_id': session_id
                })
        
        except Exception as e:
            logger.error(f"Error processing {meta_key}: {str(e)}")
            continue

    return kb

def update_dynamodb_from_kb(kb):
    for dive_id, dive_data in kb['dives'].items():
        try:
            # Fetch the current record from DynamoDB
            response = table.get_item(Key = {"dive_id": dive_id})
            existing_item = response.get("Item", {})

            # Compare existing item to new data

            new_data = {
                "dive_id": dive_id,
                "dive_date": dive_data["dive_date"],
                "dive_number": dive_data["dive_number"],
                "dive_location": dive_data["dive_location"],
                "sessions": dive_data["sessions"],
                "species_seen": dive_data["species_seen"]
            }

            if existing_item and existing_item == new_data:
                logger.info(f"No change for {dive_id}, skipping update to dive-knowledge-base")
                continue

            # Update or insert
            table.put_item(Item = new_data)
            logger.info(f"{'Updated' if existing_item else 'Inserted'} dive {dive_id} in dynamodb table dive-knowledge-base")
         
        except ClientError as e:
            logger.error(f"Failed to update dive {dive_id}: {str(e)}")

'''def save_kb_to_s3(kb, key = "brain_kb.json"):
    s3.put_object(
        Bucket=config.BUCKET_NAME,
        Key=key,
        Body=json.dumps(kb, indent=2).encode("utf-8")
    )
    logger.info(f"Saved KB to s3://{BUCKET_NAME}/{key}")'''

if __name__ == "__main__":
    #print(extract_gpt_data('https://vivian-dive-bucket.s3.ap-southeast-2.amazonaws.com/dives/20250602093056_fbe6dcd954/gpt_output.json'))
    #print(update_knowledge_base())
    update_dynamodb_from_kb(kb = update_knowledge_base())