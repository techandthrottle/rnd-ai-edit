from flask import Flask, request, jsonify, Response
import os
from urllib.parse import urlparse
from dotenv import load_dotenv
import logging
from logging.handlers import RotatingFileHandler
import threading
import uuid
import time
import json

# Configure logging
log_file = 'app.log'
file_handler = RotatingFileHandler(log_file, maxBytes=1024 * 1024 * 10, backupCount=5) # 10 MB per file, 5 backup files
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

logging.basicConfig(level=logging.INFO, handlers=[file_handler])

from video_processing import process_video_with_recipe

app = Flask(__name__)

load_dotenv()

task_status = {}

@app.route('/process_video', methods=['POST'])
def process_video():
    data = request.json
    if not data or 'video_url' not in data:
        return jsonify({"error": "video_url is required in the JSON body"}), 400

    video_url = data['video_url']
    recipe = data.get('recipe', {
        "apply_noise_reduction": True,
        "transcribe": True,
        "detect_silence": True,
        "classify_content": True,
        "classify_silence": True,
        "detect_filler_words": True,
        "cut_video": True,
        "remove_silence": True,
        "remove_filler_words": True,
        "burn_captions": True,
        "ass_style": {
            "position": "Bottom",  # Options: "Top", "Middle", "Bottom"
            "words_per_line": 10,
            "Fontname": "Arial",
            "Fontsize": "72",
            "PrimaryColour": "&H00FFFFFF",
            "Outline": 3,
            "Shadow": 2
        }
    })
    task_id = str(uuid.uuid4())

    thread = threading.Thread(target=process_video_with_recipe, args=(task_id, video_url, recipe, task_status))
    thread.start()

    return jsonify({"task_id": task_id, "message": "Video processing started."}), 202

@app.route('/task_status/<task_id>')
def get_task_status(task_id):
    def generate_updates():
        while True:
            if task_id in task_status:
                status = task_status[task_id]
                yield f"data: {json.dumps(status)}\n\n"
                if status["status"] in ["COMPLETED", "FAILED"]:
                    break
            time.sleep(1) # Poll every 1 second

    return Response(generate_updates(), mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)