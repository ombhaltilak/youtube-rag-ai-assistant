# YouTube RAG AI Assistant 🎥🤖 (Firefox Edition)

An AI-powered Firefox Extension that allows you to chat with any YouTube video in real-time. By leveraging **Advanced Retrieval-Augmented Generation (RAG)**, the assistant indexes video transcripts to provide pinpoint-accurate answers with clickable timestamp citations.

---

## 🚀 Features
- **Instant Sync:** Extracts transcripts directly from the YouTube DOM using specialized content scripting.
- **Clickable Citations:** AI responses include `[MM:SS]` timestamps that jump to the exact moment in the video.
- **High-Fidelity Retrieval:** Implements a two-stage pipeline (Bi-Encoder + Cross-Encoder) for maximum accuracy.
- **Privacy Focused:** Your API keys and chat history are stored locally on your device via `browser.storage.local`.

---

## 🧠 Advanced RAG Architecture
This project implements enterprise-grade RAG patterns to handle the noisy and unstructured nature of automated YouTube transcripts.



### 1. Semantic Chunking & Multi-Vector Indexing
- **Recursive Character Splitting:** Transcripts are split at natural boundaries rather than fixed lengths to maintain logical flow.
- **Sliding Window Context:** A $10\%$-$15\%$ overlap between chunks ensures that topic transitions are captured by the vector store.

### 2. Two-Stage Retrieval (Retrieve & Re-Rank)
Most basic RAG systems suffer from low precision. This project solves that with a dual-stage process:
- **Stage 1 (Bi-Encoder):** Uses `all-MiniLM-L6-v2` and **FAISS** to perform a rapid search across thousands of chunks to find the top 20 candidates.
- **Stage 2 (Cross-Encoder):** Uses `cross-encoder/ms-marco-MiniLM-L-6-v2` to re-score those candidates. This model performs deep semantic comparison, ensuring the most contextually relevant snippet is prioritized even if keywords don't match exactly.

### 3. Metadata-Augmented Citations
Each vector is tied to a `start_time` metadata attribute. This allows the extension to map AI-generated insights back to the source video coordinates in real-time.

---

## 🛠️ Setup & Installation

### 1. Backend (Flask + Hugging Face)
The backend manages the vector database and inference logic.
- **Deployment:** Use the provided `Dockerfile` to deploy to Hugging Face Spaces.
- **Host:** `https://your-space-name.hf.space`

### 2. Firefox Extension (Manual Install)
1. Download or clone this repository.
2. Open Firefox and navigate to `about:debugging#/runtime/this-firefox`.
3. Click **Load Temporary Add-on...**.
4. Select the `manifest.json` file from your extension directory.

---

## 🔑 Configuration
1. Open the extension popup and go to the **API** tab.
2. Save your **Hugging Face API Token** (`hf_...`).
3. Navigate to a YouTube video and click **Resync**.
4. Once the system message says "Ready," you can ask questions about the video content.

---

## 🛠️ Tech Stack
| Component | Technology |
| :--- | :--- |
| **Frontend** | JavaScript (WebExtensions API), Bootstrap 5 |
| **Backend** | Python, Flask, Gunicorn |
| **Vector DB** | FAISS (Facebook AI Similarity Search) |
| **Embeddings** | Sentence-Transformers (`all-MiniLM-L6-v2`) |
| **Re-Ranker** | Cross-Encoders (`ms-marco-MiniLM-L-6-v2`) |

---

## 📄 License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
