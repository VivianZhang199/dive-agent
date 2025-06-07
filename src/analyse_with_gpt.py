import json
import logging
import re
from openai import OpenAI
from config import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_openai_client():
    return OpenAI(api_key=config.get_openai_api_key())

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

def load_system_prompt():
    """ Load system prompt from S3 for Lambda compatbility"""
    try:
        with open('system_prompt_v2.txt', 'r') as f:
            return f.read().strip()
    except FileNotFoundError:
        logger.error("System prompt file not found")
        raise

def analyse_with_gpt(image_urls, system_prompt):
    logger.debug(f"Analysing with GPT: {image_urls}")
    try:
        client = get_openai_client()
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
        logger.info(f"GPT response: {full_output}")

        match = re.search(r'<BEGIN_JSON>(.*?)<END_JSON>', full_output, re.DOTALL)
        if not match:
            raise ValueError("No JSON found in GPT response")

        json_str = match.group(1).strip()

        # Validate JSON
        parsed_json = json.loads(json_str)
        clean_json = json.dumps(parsed_json, indent=2)

        return {
            "json_only": clean_json
        }
        
    except Exception as e:
        logger.error(f"Error in GPT analysis: {str(e)}")
        raise

if __name__ == "__main__":
    system_prompt = load_system_prompt()
    gpt_result = analyse_with_gpt(image_urls, system_prompt)
    print(gpt_result)