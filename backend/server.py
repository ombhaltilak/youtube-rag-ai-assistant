import logging
import time
from functools import lru_cache

import requests
from flask import Flask, request, jsonify
from flask_cors import CORS
from langdetect import detect

# --- LANGCHAIN IMPORTS ---
from langchain_huggingface import HuggingFaceEndpoint, ChatHuggingFace, HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.documents import Document

# Cross-Encoder used for reranking retrieved documents
from sentence_transformers import CrossEncoder

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("youtube_rag")

app = Flask(__name__)
CORS(app)

# ---------- Configuration ----------
EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
LLM_REPO_ID = "Qwen/Qwen2.5-7B-Instruct"
MAX_QUESTION_CHARS = 1000
RETRIEVE_K = 10
RERANK_TOP_N = 3
LLM_RETRIES = 2

# In-memory store for the indexed video (shared across users: known limitation)
video_database = {}


# ==========================================
# Lazy, cached model loading (loaded once, on first use)
# ==========================================
@lru_cache(maxsize=1)
def get_embeddings():
    return HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)


@lru_cache(maxsize=1)
def get_reranker():
    return CrossEncoder(RERANKER_MODEL)


# ==========================================
# Helpers
# ==========================================
def get_json():
    """Return the request body as a dict, or {} if missing/invalid."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def invoke_with_retry(chain, payload, retries=LLM_RETRIES):
    """Call an LLM chain, retrying with exponential backoff on failure."""
    for attempt in range(retries + 1):
        try:
            return chain.invoke(payload)
        except Exception:
            if attempt == retries:
                raise
            logger.warning("LLM call failed (attempt %d), retrying...", attempt + 1)
            time.sleep(2 ** attempt)


def chunk_transcript(transcript_array, max_words=600, overlap_words=100):
    """Split transcript segments into chunks with overlap so context isn't lost at boundaries."""
    chunks = []
    current_chunk = []
    current_word_count = 0
    for segment in transcript_array:
        text = str(segment.get("text", ""))
        word_count = len(text.split())
        if current_word_count + word_count > max_words and current_chunk:
            chunks.append(current_chunk)
            overlap_chunk = []
            overlap_count = 0
            for s in reversed(current_chunk):
                overlap_chunk.insert(0, s)
                overlap_count += len(str(s.get("text", "")).split())
                if overlap_count >= overlap_words:
                    break
            current_chunk = overlap_chunk
            current_word_count = overlap_count
        current_chunk.append(segment)
        current_word_count += word_count
    if current_chunk:
        chunks.append(current_chunk)
    return chunks


def translate_chunk(text):
    """Translate non-English text to English; fall back to the original text on failure."""
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {"client": "gtx", "sl": "auto", "tl": "en", "dt": "t", "q": text}
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return "".join([sentence[0] for sentence in data[0] if sentence[0]])
    except Exception as e:
        logger.warning("Translation failed: %s", e)
    return text


# ==========================================
# Route: clear context
# ==========================================
@app.route("/clear_context", methods=["POST"])
def clear_context():
    """Reset backend state and clear indexed video data."""
    video_database.clear()
    logger.info("Backend memory and vector store cleared")
    return jsonify({"status": "success", "message": "Backend memory cleared"}), 200


# ==========================================
# Route: save transcript and build the index
# ==========================================
@app.route("/save_transcript", methods=["POST"])
def save_transcript():
    """Receive transcript, detect language, chunk, and build a FAISS index."""
    data = get_json()
    raw_transcript = data.get("transcript", [])

    if not raw_transcript:
        return jsonify({"error": "No transcript provided"}), 400
    if not isinstance(raw_transcript, list) or not all(isinstance(s, dict) for s in raw_transcript):
        return jsonify({"error": "Transcript must be a list of {time, text} objects."}), 400

    try:
        sample_text = " ".join(str(s.get("text", "")) for s in raw_transcript[:10])
        try:
            detected_lang = detect(sample_text)
        except Exception:
            detected_lang = "en"

        chunks = chunk_transcript(raw_transcript, max_words=600, overlap_words=100)
        formatted_chunks = []
        for chunk in chunks:
            start_time = chunk[0].get("time", "0:00")
            end_time = chunk[-1].get("time", "0:00")
            text_block = " ".join(str(s.get("text", "")) for s in chunk)
            if detected_lang != "en":
                text_block = translate_chunk(text_block)
                time.sleep(1)  # simple rate limiting for the translation API
            formatted_chunks.append({"time_range": f"{start_time} - {end_time}", "text": text_block})

        logger.info("Creating vector embeddings for %d chunks", len(formatted_chunks))
        documents = [
            Document(page_content=c["text"], metadata={"time_range": c["time_range"]})
            for c in formatted_chunks
        ]
        vectorstore = FAISS.from_documents(documents, get_embeddings())

        video_database["vectorstore"] = vectorstore
        video_database["all_documents"] = documents
        return jsonify({"status": "success", "message": "Indexed successfully"}), 200

    except Exception:
        logger.exception("Indexing failed")
        return jsonify({"error": "Indexing failed. Please try again."}), 500


# ==========================================
# Route: chat (query rewrite -> search -> rerank -> answer)
# ==========================================
@app.route("/chat", methods=["POST"])
def chat():
    """Main RAG pipeline: Query Rewriting -> Vector Search -> Reranking -> LLM Synthesis."""
    data = get_json()

    # --- Input validation ---
    raw_question = str(data.get("question", "")).strip()
    if not raw_question:
        return jsonify({"error": "Question is required."}), 400
    if len(raw_question) > MAX_QUESTION_CHARS:
        return jsonify({"error": f"Question too long (max {MAX_QUESTION_CHARS} characters)."}), 400

    mode = data.get("mode", "concise")
    if mode not in ("concise", "detailed"):
        mode = "concise"

    hf_token = request.headers.get("X-HF-Token")

    vectorstore = video_database.get("vectorstore")
    if not vectorstore:
        return jsonify({"error": "No video indexed. Please click Sync."}), 400
    if not hf_token:
        return jsonify({"error": "Missing Hugging Face Token."}), 401

    try:
        max_tokens = 512 if mode == "concise" else 900

        llm = HuggingFaceEndpoint(
            repo_id=LLM_REPO_ID,
            huggingfacehub_api_token=hf_token,
            task="text-generation",
            max_new_tokens=max_tokens,
            temperature=0.2,
        )
        chat_model = ChatHuggingFace(llm=llm)

        # --- Guardrail + query expansion ---
        rewrite_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a strict query analysis AI.
            RULES:
            1. If the user's query contains explicit, harmful, or dangerous content, output exactly the word REJECT and absolutely nothing else.
            2. Otherwise, fix any typos, expand synonyms, and output a highly optimized search query to find information in a video transcript.
            3. DO NOT output conversational text. ONLY output the new query or REJECT."""),
            ("user", "Query: {question}"),
        ])

        rewritten_query = invoke_with_retry(
            rewrite_prompt | chat_model | StrOutputParser(),
            {"question": raw_question},
        ).strip()

        # Real guardrail: stop the request instead of answering it anyway
        if rewritten_query.upper() == "REJECT":
            return jsonify({"error": "Query rejected by safety filter."}), 400

        search_query = rewritten_query or raw_question

        # --- Route: summary request vs specific question ---
        all_docs = video_database.get("all_documents", [])
        summary_keywords = ["summarize", "summary", "overview", "recap", "tldr", "entire video", "main points"]
        is_summary_request = any(word in search_query.lower() for word in summary_keywords)

        if is_summary_request and len(all_docs) > 3:
            # Evenly spaced chunk sampling across the whole video
            step = max(1, len(all_docs) // 5)
            top_docs = all_docs[::step][:5]
        else:
            retrieved_docs = vectorstore.similarity_search(search_query, k=RETRIEVE_K)
            if not retrieved_docs:
                return jsonify({
                    "answer": "I'm sorry, that information is not in the video.",
                    "sources": [],
                }), 200
            reranker = get_reranker()
            pairs = [[search_query, doc.page_content] for doc in retrieved_docs]
            scores = reranker.predict(pairs)
            scored_docs = sorted(zip(scores, retrieved_docs), key=lambda x: x[0], reverse=True)
            top_docs = [doc for _, doc in scored_docs[:RERANK_TOP_N]]

        context_text = "\n\n".join(
            f"[{doc.metadata['time_range']}]: {doc.page_content}" for doc in top_docs
        )

        if mode == "concise":
            instructions = "Provide a concise 3 to 4 sentence answer. You MUST complete your final sentence and wrap up your response quickly to fit within limits. Cite multiple timestamps."
        else:
            instructions = "Provide a detailed, comprehensive explanation. You MUST complete your final sentence perfectly and wrap up naturally. Cite multiple timestamps."

        final_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an expert YouTube assistant.
            STRICT RULES:
            1. Answer based ONLY on the provided Context.
            2. MULTIPLE INLINE CITATIONS REQUIRED: You MUST include a citation immediately after EVERY specific fact, topic change, or summary point. Do NOT group them all at the end.
            3. USE EXACT FORMAT: [MM:SS - MM:SS] strictly as seen in the Context metadata.
            4. EXAMPLE OUTPUT: "The video begins by introducing Python [00:00 - 01:20]. Later, it explains data types [03:15 - 04:30], and finally shows a web server example [08:00 - 09:15]."
            5. COMPLETION: You MUST write a complete, naturally finished answer. Do not let your text get cut off. Keep it within the requested length.
            6. If the answer is not in the context, output exactly: "[NO_SOURCES] I'm sorry, that information is not in the video." """),
            ("user", "Context:\n{context}\n\nQuestion: {question}\n\nInstructions: {instructions}"),
        ])

        ai_answer = invoke_with_retry(
            final_prompt | chat_model | StrOutputParser(),
            {"context": context_text, "question": search_query, "instructions": instructions},
        )

        if "[NO_SOURCES]" in ai_answer:
            sources = []
            ai_answer = ai_answer.replace("[NO_SOURCES]", "").strip()
        else:
            sources = [doc.metadata["time_range"] for doc in top_docs]

        return jsonify({"answer": ai_answer, "sources": sources}), 200

    except Exception:
        logger.exception("Chat pipeline failed")
        return jsonify({"error": "The model request failed. Please try again."}), 500


if __name__ == "__main__":
    # Port 7860 for Hugging Face Spaces compatibility
    app.run(host="0.0.0.0", port=7860)
