# Storyboard AI

> An intelligent, rule-based automation platform that transforms video editing from a manual, timeline-based process into a streamlined, API-driven workflow.

Storyboard AI is a backend service that automates the editing of common video formats (tutorials, podcasts, marketing clips) by letting users define a "recipe" of editing rules that AI interprets and executes. It leverages the Gemini API for advanced content analysis, transcription, and classification.

## Core Features

- **Rule-Based Editing:** Instead of manual timeline manipulation, you define an editing "recipe" in a JSON object.
- **AI-Powered Transcription:** Uses Gemini 2.5 Pro to generate highly accurate, word-level transcripts with speaker labels ("karaoke-style" captions).
- **Intelligent Filler Word Detection:** Leverages Gemini's audio analysis to identify and remove filler words like "um" and "ah" based on conversational context.
- **Smart Silence Removal:** Automatically detects and cuts periods of dead air or unnatural pauses.
- **Audio Noise Reduction:** Applies an audio filter to clean up background noise.
- **Customizable Caption Styling:** Burn subtitles directly into the video with full control over font, size, color, position, and words per line using ASS styling.
- **Smooth Video Cuts:** Implements a micro cross-fade at each edit point to eliminate jarring glitches and audio pops.

## Getting Started

Follow these instructions to get a local copy up and running for development and testing purposes.

### Prerequisites

- Python 3.10+
- FFmpeg installed and available in your system's PATH.
- A Google Gemini API Key.

### Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/techandthrottle/rnd-ai-edit.git
    cd rnd-ai-edit
    ```

2.  **Create and activate a virtual environment:**
    ```bash
    # On Windows
    python -m venv venv
    venv\Scripts\activate

    # On macOS/Linux
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Install the required dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

## Configuration

1.  Create a file named `.env` in the root of the project directory.
2.  Add your Google Gemini API key to this file:
    ```
    GOOGLE_API_KEY=YOUR_API_KEY_HERE
    ```

## Usage

### Running the Server

To start the Flask application, run the following command:

```bash
python app.py
```

The server will start on `http://0.0.0.0:8080`.

### API Endpoint

Send a `POST` request to the following endpoint to start a video processing job:

`http://localhost:8080/process_video`

### Sample Request Body

The request body must be a JSON object containing the `video_url` and an optional `recipe` object. If no recipe is provided, the default recipe will be used.

```json
{
  "video_url": "http://example.com/my_video.mp4",
  "recipe": {
    "apply_noise_reduction": true,
    "transcribe": true,
    "detect_silence": true,
    "classify_content": true,
    "classify_silence": true,
    "detect_filler_words": true,
    "cut_video": true,
    "remove_silence": true,
    "remove_filler_words": true,
    "burn_captions": true,
    "ass_style": {
      "position": "Bottom",
      "words_per_line": 10,
      "Fontname": "Arial",
      "Fontsize": "72",
      "PrimaryColour": "&H00FFFFFF",
      "Outline": 3,
      "Shadow": 2
    }
  }
}
```

### Checking Task Status

The initial `/process_video` request will return a `task_id`. You can check the status of the job by sending a `GET` request to:

`http://localhost:8080/task_status/<your_task_id>`

This endpoint uses Server-Sent Events (SSE) to stream real-time progress updates.
