// Configuration: Points to the Hugging Face Space where the Python RAG backend is hosted
// const BACKEND_URL = "http://127.0.0.1:5000";
const BACKEND_URL = "https://omnbhaltilak-youtube-rag-backend.hf.space";
let currentSessionId = null; // Tracks the active chat session ID during the popup's lifecycle

// --- TIMESTAMP UTILITIES ---
/**
 * Converts a "MM:SS" or "HH:MM:SS" string into total seconds.
 * Used for seeking the YouTube video player to specific segments.
 */
function timestampToSeconds(hms) {
    const parts = hms.split(':').reverse();
    let seconds = 0;
    for (let i = 0; i < parts.length; i++) {
        seconds += parseInt(parts[i]) * Math.pow(60, i);
    }
    return seconds;
}

/**
 * Uses regex to find timestamp patterns in AI responses and converts them 
 * into clickable HTML links that interact with the YouTube player.
 */
function linkifyTimestamps(text) {
    // Regex catches formats: [00:00 - 00:00], (00:00), or simple 00:00
    const regex = /[\[\(]?(\d{1,2}:\d{2}(?::\d{2})?)(?:\s*-\s*(\d{1,2}:\d{2}(?::\d{2})?))?[\]\)]?/g;
    return text.replace(regex, (match, startTime) => {
        const seconds = timestampToSeconds(startTime);
        return `<a href="#" class="time-link" data-time="${seconds}">${match}</a>`;
    });
}

// --- DEEP CLEAR FUNCTION ---
/**
 * Deletes the session from both the Python backend memory and 
 * the Chrome extension's local storage (IndexedDB).
 */
async function performFullClear() {
    if (!currentSessionId) {
        document.getElementById("chat-container").innerHTML = "";
        return;
    }

    const confirmClear = confirm("Are you sure? This will delete this chat from your history and the server.");
    if (!confirmClear) return;

    try {
        // Notify backend to wipe the FAISS vector store for this session
        await fetch(`${BACKEND_URL}/clear_context`, { method: "POST" });

        // Remove from Chrome's local storage
        chrome.storage.local.get({ sessions: {} }, (data) => {
            if (data.sessions[currentSessionId]) {
                delete data.sessions[currentSessionId];
                chrome.storage.local.set({ sessions: data.sessions }, () => {
                    renderHistory(); // Refresh the History tab UI
                });
            }
        });

        // Reset UI state
        document.getElementById("chat-container").innerHTML = "";
        currentSessionId = null;
        document.getElementById("questionInput").disabled = true;
        document.getElementById("askBtn").disabled = true;
        
        appendMessage("system", "🧹 <b>Wiped:</b> Session deleted from browser and server.", true, false, false);

    } catch (err) {
        console.error("Clear failed:", err);
        appendMessage("system", "⚠️ Data cleared locally, but server reset failed.", false, false, false);
    }
}

// --- EVENT DELEGATION FOR DYNAMIC LINKS (UNIFIED) ---
/**
 * Listens for clicks on elements that are added dynamically (timestamps, history items).
 */
document.addEventListener('click', async (e) => {
    // 1. Handle clicking a URL in the History tab (Opens video in a new tab)
    if (e.target.classList.contains('history-video-link')) {
        e.preventDefault();
        e.stopPropagation(); 
        chrome.tabs.create({ url: e.target.href });
        return;
    }

    // 2. Handle Timestamp Clicks: Injects a script into the YouTube tab to change video time
    if (e.target.classList.contains('time-link')) {
        e.preventDefault();
        const seconds = parseInt(e.target.getAttribute('data-time'));
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tab || !tab.url.includes("youtube.com/watch")) return;
        
        chrome.scripting.executeScript({
            target: { tabId: tab.id },
            func: (s) => {
                const video = document.querySelector('video');
                if (video) video.currentTime = s;
            },
            args: [seconds]
        });
        return;
    }

    // 3. Handle History Session Clicks: Restores a previous conversation
    const sessionLoader = e.target.closest('.session-loader');
    if (sessionLoader) {
        loadSpecificSession(sessionLoader.dataset.id);
    }
});

// --- CORE UI FUNCTIONS ---
/**
 * Adds a message bubble to the chat container.
 * @param {string} sender - 'user', 'ai', or 'system'
 * @param {boolean} useTypewriter - If true, text appears letter-by-letter
 * @param {boolean} shouldSave - If true, persists the message to chrome.storage
 */
function appendMessage(sender, text, isHTML = false, useTypewriter = false, shouldSave = true) {
    const container = document.getElementById("chat-container");
    if (!container) return null;

    const msgDiv = document.createElement("div");
    msgDiv.className = `message ${sender}-message`;
    container.appendChild(msgDiv);

    if (useTypewriter && isHTML) {
        typeWriter(msgDiv, text);
    } else {
        if (isHTML) msgDiv.innerHTML = text;
        else msgDiv.innerText = text;
    }
    
    container.scrollTop = container.scrollHeight;

    // Persist to local history so chat isn't lost on popup close
    if (shouldSave && currentSessionId) {
        chrome.storage.local.get({ sessions: {} }, (data) => {
            if (data.sessions[currentSessionId]) {
                data.sessions[currentSessionId].chatHistory.push({ sender, text, isHTML });
                data.sessions[currentSessionId].timestamp = new Date().toLocaleString();
                chrome.storage.local.set({ sessions: data.sessions });
            }
        });
    }
    return msgDiv; 
}

/**
 * Simulates a typewriter effect for AI responses to improve UX.
 */
function typeWriter(element, html, speed = 10) {
    let i = 0;
    const tempDiv = document.createElement("div");
    tempDiv.innerHTML = html;
    const content = tempDiv.innerHTML;
    element.innerHTML = "";
    
    function type() {
        if (i < content.length) {
            // Handle HTML tags so they don't appear as text while typing
            if (content.charAt(i) === "<") {
                let tagEnd = content.indexOf(">", i);
                i = tagEnd + 1;
            } else i++;
            element.innerHTML = content.substring(0, i);
            const container = document.getElementById("chat-container");
            container.scrollTop = container.scrollHeight;
            setTimeout(type, speed);
        }
    }
    type();
}

// --- HISTORY LOGIC ---
/**
 * Retrieves saved sessions from storage and renders the list in the History tab.
 */
function renderHistory() {
    const historyList = document.getElementById("history-list");
    if (!historyList) return;

    chrome.storage.local.get({ sessions: {} }, (data) => {
        const sessions = data.sessions || {};
        const sessionKeys = Object.keys(sessions).sort((a, b) => {
            return new Date(sessions[b].timestamp) - new Date(sessions[a].timestamp);
        });

        if (sessionKeys.length === 0) {
            historyList.innerHTML = '<div class="p-3 text-center">No previous chats found.</div>';
            return;
        }

        let html = `<button id="clearSelectedBtn" class="btn btn-sm btn-outline-danger w-100 mb-3">Clear Selected</button>`;
        html += sessionKeys.map(id => {
            const session = sessions[id];
            return `
                <div class="archive-item d-flex align-items-center mb-2">
                    <input type="checkbox" class="delete-checkbox me-2" value="${id}">
                    <div class="session-loader flex-grow-1" data-id="${id}" style="cursor:pointer; overflow:hidden;">
                        <div class="archive-title">${session.timestamp}</div>
                        <small class="text-muted d-block text-truncate">
                            <a href="${session.videoUrl}" class="history-video-link" style="color: #6366f1; text-decoration: none;">${session.videoUrl}</a>
                        </small>
                        <small style="color:gray;">${session.chatHistory.length} messages</small>
                    </div>
                </div>`;
        }).join('');
        
        historyList.innerHTML = html;
        document.getElementById("clearSelectedBtn").addEventListener("click", clearSelectedHistory);
    });
}

/**
 * Reloads a previous chat session and sends its transcript back to 
 * the server to re-initialize the RAG vector store.
 */
async function loadSpecificSession(id) {
    chrome.storage.local.get({ sessions: {} }, async (data) => {
        const session = data.sessions[id];
        if (!session) return;

        currentSessionId = id;
        const chatContainer = document.getElementById("chat-container");
        chatContainer.innerHTML = "";
        
        const loadingMsg = appendMessage("system", "⏳ Restoring video context...", false, false, false);

        try {
            // Re-index the old transcript into the backend FAISS store
            const response = await fetch(`${BACKEND_URL}/save_transcript`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ transcript: session.transcriptData })
            });

            if (response.ok) {
                if(loadingMsg) loadingMsg.remove();
                session.chatHistory.forEach(msg => {
                    appendMessage(msg.sender, msg.text, msg.isHTML, false, false);
                });

                document.querySelector('[data-target="tab-chat"]').click();
                document.getElementById("questionInput").disabled = false;
                document.getElementById("askBtn").disabled = false;
            } else {
                throw new Error("Server rejected transcript restoration");
            }
        } catch (err) {
            if(loadingMsg) loadingMsg.remove();
            appendMessage("system", "❌ Failed to restore context with server. Ensure the server is running.", false, false, false);
        }
    });
}

function clearSelectedHistory() {
    const selected = Array.from(document.querySelectorAll('.delete-checkbox:checked')).map(cb => cb.value);
    if (selected.length === 0) return;

    chrome.storage.local.get({ sessions: {} }, (data) => {
        selected.forEach(id => delete data.sessions[id]);
        chrome.storage.local.set({ sessions: data.sessions }, renderHistory);
    });
}

// --- INITIALIZATION ---
/**
 * Runs when the popup opens. Sets up API tokens and checks if current 
 * video already has an active session.
 */
document.addEventListener("DOMContentLoaded", () => {
    chrome.storage.local.get(["hfToken"], (res) => {
        if (res.hfToken) document.getElementById("hfToken").value = res.hfToken;
    });

    chrome.storage.local.get(["sessions"], async (data) => {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        const sessions = data.sessions || {};

        if (tab && tab.url.includes("youtube.com/watch")) {
            const existingId = Object.keys(sessions).find(id => sessions[id].videoUrl === tab.url);
            if (existingId) {
                loadSpecificSession(existingId);
            } else {
                appendMessage("system", "New video detected. Click <b>Resync</b> to start.", true, false, false);
            }
        } else {
            appendMessage("system", "Please navigate to a YouTube video to use the AI.", false, false, false);
        }
    });
    renderHistory();
});

// --- TAB NAVIGATION LOGIC ---
document.querySelectorAll('.nav-item').forEach(item => {
    item.addEventListener('click', () => {
        const targetId = item.getAttribute('data-target');
        document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
        document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
        item.classList.add('active');
        document.getElementById(targetId).classList.add('active');
        if (targetId === 'tab-history') renderHistory();
    });
});

// --- SYNC / SCRAPE (THE DOM SCRAPER) ---
/**
 * Executed inside the YouTube tab. Attempts to open the transcript panel 
 * and scrape all timestamped text segments.
 */
async function surgicalExtract() {
    const findButton = () => [...document.querySelectorAll('button')].find(b => 
        b.innerText?.includes('Show transcript') || b.getAttribute('aria-label')?.includes('Show transcript')
    );
    let btn = findButton();
    // If button is hidden, expand the description first
    if (!btn) {
        const expander = document.querySelector('#expand, .more-button, #description-inline-expander');
        if (expander) { expander.click(); await new Promise(r => setTimeout(r, 1000)); btn = findButton(); }
    }
    if (btn) { btn.click(); await new Promise(r => setTimeout(r, 2500)); }
    const segments = document.querySelectorAll('ytd-transcript-segment-renderer');
    return segments.length === 0 ? null : Array.from(segments).map(s => ({
        time: s.querySelector('.segment-timestamp')?.textContent.trim() || "0:00",
        text: s.querySelector('.segment-text')?.textContent.trim() || ""
    }));
}

/**
 * Resync logic: Scrapes YouTube, sends to backend, and initializes a new local session.
 */
document.getElementById("resyncBtn").addEventListener("click", async () => {
    const btn = document.getElementById("resyncBtn");
    const syncIcon = document.getElementById("syncIcon");
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

    if (!tab || !tab.url.includes("youtube.com/watch")) {
        appendMessage("system", "❌ Not a valid YouTube video.", false, false, false);
        return;
    }

    syncIcon.classList.add("fa-spin-custom");
    btn.disabled = true;
    document.getElementById("chat-container").innerHTML = ""; 
    const syncMsg = appendMessage("system", "🚀 <b>Syncing New Video...</b>", true, false, false);

    try {
        const results = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: surgicalExtract });

        if (results && results[0].result) {
            const transcriptData = results[0].result;
            // Send the raw transcript to the backend for FAISS indexing
            const res = await fetch(`${BACKEND_URL}/save_transcript`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ transcript: transcriptData })
            });

            if (!res.ok) throw new Error("Backend failed to save transcript");

            // Save session to Chrome Storage
            currentSessionId = Date.now().toString();
            chrome.storage.local.get({ sessions: {} }, (data) => {
                const sessions = data.sessions || {};
                sessions[currentSessionId] = {
                    timestamp: new Date().toLocaleString(),
                    videoUrl: tab.url,
                    chatHistory: [],
                    transcriptData: transcriptData 
                };
                chrome.storage.local.set({ sessions: sessions });
            });

            if(syncMsg) syncMsg.remove();
            appendMessage("system", "✨ <b>Ready.</b> Session started.", true, false, true);
            document.getElementById("questionInput").disabled = false;
            document.getElementById("askBtn").disabled = false;
        } else {
            throw new Error("Could not extract transcript from DOM.");
        }
    } catch (err) {
        console.error(err);
        appendMessage("system", `❌ Sync Failed: Ensure subtitles are available and the server is running.`, false, false, false);
    } finally {
        syncIcon.classList.remove("fa-spin-custom");
        btn.disabled = false;
    }
});

// --- CHAT LOGIC ---
/**
 * Sends the user question to the RAG pipeline and renders the response.
 */
document.getElementById("askBtn").addEventListener("click", async () => {
    const input = document.getElementById("questionInput");
    const askBtn = document.getElementById("askBtn");
    const askIcon = document.getElementById("askIcon");
    const question = input.value.trim();
    const isDetailed = document.getElementById("modeDetailed").checked;
    
    const tokenRes = await chrome.storage.local.get("hfToken");
    const hfToken = tokenRes.hfToken;

    if (!question) return;
    if (!hfToken) {
        appendMessage("system", "⚠️ Please save your Hugging Face API token in the API tab first.", false, false, false);
        return;
    }

    appendMessage("user", question);
    input.value = "";
    askBtn.disabled = true;
    askIcon.className = "fas fa-circle-notch fa-spin-custom";
    
    const loadingMsg = appendMessage("system", "Analyzing...", false, false, false);

    try {
        // Calling the Main RAG Chat Endpoint
        const res = await fetch(`${BACKEND_URL}/chat`, {
            method: "POST",
            headers: { "Content-Type": "application/json", "X-HF-Token": hfToken },
            body: JSON.stringify({ question: question, mode: isDetailed ? "detailed" : "concise" })
        });

        if (!res.ok) throw new Error("Server responded with an error");

        const data = await res.json();
        if (loadingMsg) loadingMsg.remove();
        if (data.answer) {
            // Convert newlines to breaks and turn timestamps into clickable links
            appendMessage("ai", linkifyTimestamps(data.answer).replace(/\n/g, "<br>"), true, true);
        }
    } catch (err) {
        console.error(err);
        if (loadingMsg) loadingMsg.remove();
        appendMessage("system", "❌ Chat Error: Make sure your Python backend is running.", false, false, false);
    } finally {
        askBtn.disabled = false;
        askIcon.className = "fas fa-paper-plane";
    }
});

// Shortcut: Allow 'Enter' key to send messages
document.getElementById("questionInput").addEventListener("keypress", (e) => {
    if (e.key === "Enter" && !document.getElementById("askBtn").disabled) {
        document.getElementById("askBtn").click();
    }
});

// --- API SETTINGS LOGIC ---
document.getElementById("clearChatBtn").addEventListener("click", performFullClear);

document.getElementById("saveTokenBtn").addEventListener("click", () => {
    const btn = document.getElementById("saveTokenBtn");
    const token = document.getElementById("hfToken").value.trim();
    if(!token) return;
    chrome.storage.local.set({ hfToken: token }, () => {
        btn.innerHTML = '✓ Saved';
        setTimeout(() => { btn.innerHTML = 'Save Token'; }, 2000);
    });
});