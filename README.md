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

The request body must be a JSON object containing the `video_url` and an optional `recipe` object. If no recipe is provided, a default one will be used which enables most features.

**Minimal Request:**
The only required field is `video_url`.
```json
{
  "video_url": "http://example.com/my_video.mp4"
}
```

**Full Recipe Example:**
The `recipe` object allows you to customize the editing process. All parameters are optional.

```jsonc
{
  "video_url": "http://example.com/my_video.mp4",
  "recipe": {
    // --- Core Features ---
    "apply_noise_reduction": true, // Reduces background noise.
    "transcribe": true,            // Generates a transcript. Required for most features below.

    // --- Smart Trimming ---
    // These features identify segments to remove.
    "detect_silence": true,
    "detect_filler_words": true,
    "detect_retakes": true,

    // These flags control whether the identified segments are actually removed.
    "remove_silence": true,
    "remove_filler_words": true,
    "remove_retakes": true,

    // --- Content Analysis ---
    "classify_content": true,      // Classifies video as "Podcast" or "Short-form" and identifies topics.
    "suggest_b_roll": true,        // Suggests B-roll shots based on the transcript.

    // --- Output Options ---
    // Choose one of the following output methods:
    "cut_video": true,             // Physically cuts the video file based on the trimming rules.
    "export_to_premiere": false,   // Generates a Premiere Pro compatible XML file for non-destructive editing.

    // --- Captioning ---
    // Only used if "transcribe" is true.
    "burn_captions": true,
    "ass_style": { // Only used if "burn_captions" is true.
      "position": "Bottom",        // "Top", "Middle", or "Bottom"
      "words_per_line": 10,
      "Fontname": "Arial",
      "Fontsize": "72",
      "PrimaryColour": "&H00FFFFFF", // White
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
