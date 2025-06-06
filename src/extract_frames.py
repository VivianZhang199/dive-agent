import os
import cv2
import tempfile
import shutil
import logging
from config import config
from utils import generate_presigned_url

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def extract_frames(video_path, s3_client, s3_prefix, max_frames, frame_interval):

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
            s3_client.upload_file(filepath, config.BUCKET_NAME, key)
            logger.info(f"Uploaded frame {i+1} to s3://{config.BUCKET_NAME}/{key}")
            os.remove(filepath)

            url = generate_presigned_url(config.BUCKET_NAME, key)
            saved_urls.append(url)
        return saved_urls
    
    except Exception as e:
        logger.error(f"Error in frame extraction: {str(e)}")
        raise
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
