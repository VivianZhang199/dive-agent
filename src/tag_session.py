import argparse
import json
import boto3
import logging
from config import config

s3 = boto3.client("s3")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def update_session_metadata(session_id, dive_date=None, dive_number=None, dive_location=None):
    base_prefix = f"processed/{session_id}"
    metadata_key = f"{base_prefix}/session_metadata.json"

    try:
        obj = s3.get_object(Bucket=config.BUCKET_NAME, Key=metadata_key)
        metadata = json.loads(obj["Body"].read().decode("utf-8"))
    
        metadata["dive_date"] = dive_date
        metadata["dive_number"] = int(dive_number)
        metadata["dive_location"] = dive_location

        s3.put_object(
            Bucket=config.BUCKET_NAME,
            Key=metadata_key,
            Body=json.dumps(metadata, indent=2).encode("utf-8")
        )

        logger.info(f"Updated session {session_id} with dive date {dive_date}, dive number {dive_number}, and location {dive_location}")

    except Exception as e:
        logger.error(f"Error updating session {session_id}: {str(e)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tag a dive session with dive date and number")
    parser.add_argument("--session_id", required=True, help="The session ID to update")
    parser.add_argument("--dive_date", required=True, help="The dive date in YYYY-MM-DD format")
    parser.add_argument("--dive_number", required=True, help="Dive number of the day (int)")
    parser.add_argument("--dive_location", required=True, help="Dive location")

    args = parser.parse_args()
    update_session_metadata(args.session_id, args.dive_date, args.dive_number, args.dive_location)

