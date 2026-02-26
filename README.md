# YouTube RAG AI Assistant 🎥🤖

An AI-powered Chrome Extension that allows you to chat with any YouTube video in real-time. It uses Semantic Search (RAG) to find specific moments in the transcript and provides citations with clickable timestamps.

## 🚀 Features
- **Instant Sync:** Extracts transcripts directly from the YouTube DOM.
- **Smart RAG:** Uses FAISS and Sentence-Transformers for high-accuracy context retrieval.
- **Clickable Citations:** AI answers include timestamps that jump to the specific part of the video.
- **Privacy Focused:** API keys and chat history are stored locally on your device.

## 🛠️ Setup & Installation

### 1. Backend (Hugging Face / Local)
The backend is a Flask app. You can deploy it to Hugging Face Spaces using the provided `Dockerfile`.
- **Repo:** [https://huggingface.co/spaces/Omnbhaltilak/youtube-rag-backend]
- **Host:** `https://omnbhaltilak-youtube-rag-backend.hf.space`

### 2. Chrome Extension
1. Download this repository.
2. Open Chrome and go to `chrome://extensions/`.
3. Enable **Developer Mode**.
4. Click **Load Unpacked** and select the `/extension` folder.

## 🔑 Configuration
1. Open the extension and go to the **API** tab.
2. Enter your **Hugging Face API Token**.
3. Navigate to a YouTube video and click **Resync** to start.

## 📄 License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
