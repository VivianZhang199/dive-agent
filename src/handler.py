from pipeline import run_pipeline
import json
import logging
import urllib.parse

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    
    logger.info(f"Lambda handler has been triggered with event: {json.dumps(event)} | Type: {type(event)}")

    # If the event is an S3 event, extract the s3 key
    if 'Records' in event:
        s3_record = event['Records'][0]['s3']
        s3_key = s3_record['object']['key']
        # URL decode the s3 key to handle special characters
        s3_key = urllib.parse.unquote_plus(s3_key)
        logger.debug(f"S3 key (after decoding): {s3_key}")
    
    # If the event is not an S3 event (i.e., direct invocation), extract the s3 key directly from the event
    else:
        s3_key = event.get('s3_key')

    if not s3_key:
        raise ValueError("s3_key was not provided in event.")

    logger.info(f"Processing S3 key: {s3_key}")
    session_id = run_pipeline(s3_key)

    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': 'The dive video analysis has been completed successfully.',
            'session_id': session_id,
            's3_key': s3_key
        })
    }

if __name__ == "__main__":
    event = {
        's3_key': 'raw/GX010353_ALTA4463795217888132720~3.mp4'
    }

    s3_event = {
        'Records': [
            {
                's3': {
                    'bucket': {'name': 'vivian-dive-bucket'},
                    'object': {'key': 'raw/GX010353_ALTA4463795217888132720~3.mp4'}
                }
            }
        ]
    }

    s3_event_encoded = {
        'Records': [
            {
                's3': {
                    'bucket': {'name': 'vivian-dive-bucket'},
                    'object': {'key': 'raw/GX010353_ALTA4463795217888132720~3.mp4'}
                }
            }
        ]
    }
    result = lambda_handler(s3_event, None)
    print(f"Lambda result: {result}")

    