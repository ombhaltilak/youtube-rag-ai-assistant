from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import time
from langdetect import detect

# --- MODERN LANGCHAIN IMPORTS ---
# Standardizing LLM interaction and embedding generation
from langchain_huggingface import HuggingFaceEndpoint, ChatHuggingFace, HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.documents import Document

# --- ADVANCED RAG IMPORTS ---
# Cross-Encoder used for reranking retrieved documents to ensure high relevance
from sentence_transformers import CrossEncoder

app = Flask(__name__)
CORS(app)

# In-memory database to store vector indices and document references during runtime
video_database = {}

# ==========================================
#     Chunking & Translation Logic 
# ==========================================
def chunk_transcript(transcript_array, max_words=600, overlap_words=100):
    """
    Splits the raw transcript into manageable chunks with semantic overlap 
    to ensure context isn't lost at the boundaries.
    """
    chunks = []
    current_chunk = []
    current_word_count = 0
    for segment in transcript_array:
        text = segment.get("text", "")
        words = text.split()
        word_count = len(words)
        if current_word_count + word_count > max_words and current_chunk:
            chunks.append(current_chunk)
            overlap_chunk = []
            overlap_count = 0
            for s in reversed(current_chunk):
                overlap_chunk.insert(0, s)
                overlap_count += len(s.get("text", "").split())
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
    """
    Translates non-English transcripts to English using the Google Translate API 
    to normalize data before indexing.
    """
    try:
        url = "https://translate.googleapis.com/translate_a/single"
        params = {"client": "gtx", "sl": "auto", "tl": "en", "dt": "t", "q": text}
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return "".join([sentence[0] for sentence in data[0] if sentence[0]])
    except Exception as e:
        print(f"⚠️ Translation failed: {e}")
    return text

# ==========================================
# 🧹 FUNCTIONALITY: Clear Context Route
# ==========================================
@app.route('/clear_context', methods=['POST'])
def clear_context():
    """Endpoint to reset the backend state and clear out indexed video data."""
    video_database.clear() 
    print("🧹 Backend memory and Vector Store wiped.")
    return jsonify({"status": "success", "message": "Backend memory cleared"}), 200

# ==========================================
# 🟢 FUNCTIONALITY: Save Transcript & Semantic Indexing
# ==========================================
@app.route('/save_transcript', methods=['POST'])
def save_transcript():
    """
    Receives transcript, detects language, chunks text, and creates 
    a FAISS vector store for semantic search.
    """
    data = request.json
    raw_transcript = data.get("transcript", [])
    if not raw_transcript:
        return jsonify({"error": "No transcript provided"}), 400

    # Language detection on a small sample of the transcript
    sample_text = " ".join([s.get("text", "") for s in raw_transcript[:10]])
    try:
        detected_lang = detect(sample_text)
    except:
        detected_lang = "en"

    # Processing and translating chunks if necessary
    chunks = chunk_transcript(raw_transcript, max_words=600, overlap_words=100)
    formatted_chunks = []
    for i, chunk in enumerate(chunks):
        start_time = chunk[0].get('time', '0:00')
        end_time = chunk[-1].get('time', '0:00')
        text_block = " ".join([s.get('text', '') for s in chunk])
        if detected_lang != 'en':
            text_block = translate_chunk(text_block)
            time.sleep(1) # Simple rate limiting for translation API
        formatted_chunks.append({"time_range": f"{start_time} - {end_time}", "text": text_block})

    print("🧠 Creating Vector Embeddings...")
    # Converting chunks into LangChain Document objects with time-range metadata
    documents = [Document(page_content=c["text"], metadata={"time_range": c["time_range"]}) for c in formatted_chunks]
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
    # Building the searchable FAISS index
    vectorstore = FAISS.from_documents(documents, embeddings)
    
    video_database["vectorstore"] = vectorstore
    video_database["all_documents"] = documents
    return jsonify({"status": "success", "message": "Indexed successfully"}), 200

# ==========================================
# 🚀 FUNCTIONALITY: The Chat Pipeline
# ==========================================
@app.route('/chat', methods=['POST'])
def chat():
    """
    Main RAG pipeline: Query Rewriting -> Vector Search -> Reranking -> LLM Synthesis.
    """
    data = request.json
    raw_question = data.get("question", "")
    mode = data.get("mode", "concise")
    hf_token = request.headers.get("X-HF-Token")

    vectorstore = video_database.get("vectorstore", None)
    if not vectorstore:
        return jsonify({"error": "No video indexed. Please click Sync."}), 400
    if not hf_token:
        return jsonify({"error": "Missing Hugging Face Token."}), 401

    try:
        # --- DYNAMIC TOKEN ALLOCATION ---
        max_tokens = 512 if mode == "concise" else 900

        # Initializing the LLM via Hugging Face Inference Endpoint
        llm = HuggingFaceEndpoint(
            repo_id="Qwen/Qwen2.5-7B-Instruct",
            huggingfacehub_api_token=hf_token,
            task="text-generation",
            max_new_tokens=max_tokens,
            temperature=0.2
        )
        chat_model = ChatHuggingFace(llm=llm)

        # --- ADVANCED RAG 2: GUARDRAILING & QUERY EXPANSION ---
        # Cleans up user input and rejects harmful queries before searching the index
        rewrite_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a strict query analysis AI. 
            RULES:
            1. If the user's query contains explicit, harmful, or dangerous content, output exactly the word REJECT and absolutely nothing else.
            2. Otherwise, fix any typos, expand synonyms, and output a highly optimized search query to find information in a video transcript.
            3. DO NOT output conversational text. ONLY output the new query or REJECT."""),
            ("user", "Query: {question}")
        ])
        
        rewritten_query = (rewrite_prompt | chat_model | StrOutputParser()).invoke({"question": raw_question}).strip()
        
        # --- SMART FALLBACK LOGIC ---
        search_query = raw_question if "REJECT" in rewritten_query.upper() or not rewritten_query else rewritten_query

        # Identifying summary requests vs specific detail requests
        all_docs = video_database.get("all_documents", [])
        summary_keywords = ["summarize", "summary", "overview", "recap", "tldr", "entire video", "main points"]
        is_summary_request = any(word in search_query.lower() for word in summary_keywords)

        if is_summary_request and len(all_docs) > 3:
            # Map-reduce style summary: pick representative chunks across the whole video
            step = max(1, len(all_docs) // 5)
            top_docs = all_docs[::step][:5]
        else:
            # Traditional Similarity Search
            retrieved_docs = vectorstore.similarity_search(search_query, k=10)
            # Reranking with Cross-Encoder to verify which top-10 results are actually best
            reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
            pairs = [[search_query, doc.page_content] for doc in retrieved_docs]
            scores = reranker.predict(pairs)
            scored_docs = sorted(zip(scores, retrieved_docs), key=lambda x: x[0], reverse=True)
            top_docs = [doc for score, doc in scored_docs[:3]]

        # Formatting context for the prompt
        context_text = "\n\n".join([f"[{doc.metadata['time_range']}]: {doc.page_content}" for doc in top_docs])
        
        # --- DYNAMIC INSTRUCTIONS TO PREVENT TEXT CUTOFFS ---
        if mode == "concise":
            instructions = "Provide a concise 3 to 4 sentence answer. You MUST complete your final sentence and wrap up your response quickly to fit within limits. Cite multiple timestamps."
        else:
            instructions = "Provide a detailed, comprehensive explanation. You MUST complete your final sentence perfectly and wrap up naturally. Cite multiple timestamps."

        # --- STRICT PROMPT FOR MULTIPLE INLINE CITATIONS ---
        final_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an expert YouTube assistant. 
            STRICT RULES:
            1. Answer based ONLY on the provided Context.
            2. MULTIPLE INLINE CITATIONS REQUIRED: You MUST include a citation immediately after EVERY specific fact, topic change, or summary point. Do NOT group them all at the end.
            3. USE EXACT FORMAT: [MM:SS - MM:SS] strictly as seen in the Context metadata.
            4. EXAMPLE OUTPUT: "The video begins by introducing Python [00:00 - 01:20]. Later, it explains data types [03:15 - 04:30], and finally shows a web server example [08:00 - 09:15]."
            5. COMPLETION: You MUST write a complete, naturally finished answer. Do not let your text get cut off. Keep it within the requested length.
            6. If the answer is not in the context, output exactly: "[NO_SOURCES] I'm sorry, that information is not in the video." """),
            ("user", "Context:\n{context}\n\nQuestion: {question}\n\nInstructions: {instructions}")
        ])

        final_chain = final_prompt | chat_model | StrOutputParser()
        ai_answer = final_chain.invoke({
            "context": context_text,
            "question": search_query, 
            "instructions": instructions
        })
        
        # Handling edge cases where information isn't found
        if "[NO_SOURCES]" in ai_answer:
            sources = []
            ai_answer = ai_answer.replace("[NO_SOURCES]", "").strip()
        else:
            sources = [doc.metadata['time_range'] for doc in top_docs]

        return jsonify({"answer": ai_answer, "sources": sources}), 200
        
    except Exception as e:
        return jsonify({"error": f"Execution failed: {str(e)}"}), 500

# Entry point for the application
if __name__ == '__main__':
    # Bind to 0.0.0.0 and port 7860 for Hugging Face Spaces compatibility
    app.run(host="0.0.0.0", port=7860)