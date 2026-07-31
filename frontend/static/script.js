const chatContainer = document.getElementById("chatContainer");
const messagesArea = document.getElementById("messagesArea");
const messageInput = document.getElementById("messageInput");
const sendBtn = document.getElementById("sendBtn");
const statusText = document.getElementById("statusText");
const statusEl = document.getElementById("status");
const conversationList = document.getElementById("conversationList");
const modelSelect = document.getElementById("modelSelect");
const noticeText = document.getElementById("noticeText");
const micBtn = document.getElementById("micBtn");
const scrollBottomBtn = document.getElementById("scrollBottomBtn");
const uploadProgress = document.getElementById("uploadProgress");
const uploadProgressFill = document.getElementById("uploadProgressFill");
const uploadProgressText = document.getElementById("uploadProgressText");
const welcomeScreen = document.getElementById("welcomeScreen");

// ── State ──
let threadId = localStorage.getItem("thread_id");
let isStreaming = false;
let abortController = null;
let recognition = null;
let isDictating = false;
let scrollTimeout = null;

if (!threadId) {
    threadId = crypto.randomUUID();
    localStorage.setItem("thread_id", threadId);
}

// ── Theme ──
const savedTheme = localStorage.getItem("theme") || "dark";
document.documentElement.setAttribute("data-theme", savedTheme);
updateThemeIcon(savedTheme);

function toggleTheme() {
    const current = document.documentElement.getAttribute("data-theme");
    const next = current === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("theme", next);
    updateThemeIcon(next);
}

function updateThemeIcon(theme) {
    const icon = document.getElementById("themeIcon");
    if (icon) icon.textContent = theme === "dark" ? "🌙" : "☀️";
}

// ── Model Selection ──
const savedModel = localStorage.getItem("selected_model");
if (savedModel && modelSelect) {
    modelSelect.value = savedModel;
}

if (modelSelect) {
    modelSelect.addEventListener("change", () => {
        localStorage.setItem("selected_model", modelSelect.value);
        if (noticeText) {
            noticeText.textContent = `Selected model: ${modelSelect.value}`;
            setTimeout(() => {
                noticeText.textContent = "Ominix can make mistakes. Check important information.";
            }, 3000);
        }
    });
}

// ── Status ──
function setStatus(text, busy = false) {
    statusText.textContent = text;
    statusEl.classList.toggle("busy", busy);
}

// ── Scroll Handling ──
function scrollToBottom() {
    chatContainer.scrollTo({ top: chatContainer.scrollHeight, behavior: "smooth" });
}

function updateScrollButton() {
    const threshold = 100;
    const isNearBottom = chatContainer.scrollHeight - chatContainer.scrollTop - chatContainer.clientHeight < threshold;
    scrollBottomBtn.classList.toggle("visible", !isNearBottom);
}

chatContainer.addEventListener("scroll", () => {
    clearTimeout(scrollTimeout);
    scrollTimeout = setTimeout(updateScrollButton, 100);
});

// ── Speech Recognition ──
function setupSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) return null;

    const rec = new SpeechRecognition();
    rec.lang = "en-US";
    rec.continuous = true;
    rec.interimResults = true;

    rec.onstart = () => {
        isDictating = true;
        micBtn?.classList.add("recording");
        setStatus("Listening...", true);
    };

    rec.onresult = (event) => {
        let finalTranscript = "";
        let interimTranscript = "";

        for (let i = event.resultIndex; i < event.results.length; i++) {
            const transcript = event.results[i][0].transcript;
            if (event.results[i].isFinal) {
                finalTranscript += transcript + " ";
            } else {
                interimTranscript += transcript;
            }
        }

        if (finalTranscript) {
            const current = messageInput.value.trim();
            messageInput.value = current ? current + " " + finalTranscript.trim() : finalTranscript.trim();
            autoResize(messageInput);
        }

        if (interimTranscript && noticeText) {
            noticeText.textContent = "Listening: " + interimTranscript;
        }
    };

    rec.onerror = (event) => {
        console.error("Speech recognition error:", event.error);
        if (event.error === "not-allowed") {
            alert("Microphone permission denied. Please allow microphone access in your browser settings.");
        }
        stopDictation();
    };

    rec.onend = () => {
        if (isDictating) {
            try { rec.start(); } catch { stopDictation(); }
        }
    };

    return rec;
}

function toggleDictation() {
    if (!recognition) recognition = setupSpeechRecognition();
    if (!recognition) {
        alert("Speech recognition is not supported in this browser. Please use Chrome or Edge.");
        return;
    }
    isDictating ? stopDictation() : startDictation();
}

function startDictation() {
    try { recognition.start(); } catch (e) { console.error("Dictation start failed:", e); }
}

function stopDictation() {
    isDictating = false;
    if (recognition) {
        try { recognition.stop(); } catch { /* ignore */ }
        recognition.abort?.();
    }
    micBtn?.classList.remove("recording");
    setStatus("Ready", false);
    if (noticeText) {
        noticeText.textContent = "Ominix can make mistakes. Check important information.";
    }
    messageInput?.focus();
}

// ── Sidebar ──
function toggleSidebar() {
    const sidebar = document.getElementById("sidebar");
    const backdrop = document.getElementById("sidebarBackdrop");
    if (!sidebar || !backdrop) return;
    sidebar.classList.toggle("open");
    backdrop.classList.toggle("open");
}

function closeSidebar() {
    const sidebar = document.getElementById("sidebar");
    const backdrop = document.getElementById("sidebarBackdrop");
    if (!sidebar || !backdrop) return;
    sidebar.classList.remove("open");
    backdrop.classList.remove("open");
}

// ── Input ──
function autoResize(textarea) {
    textarea.style.height = "auto";
    textarea.style.height = Math.min(textarea.scrollHeight, 160) + "px";
}

function handleKeyDown(event) {
    if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
    }
}

function usePrompt(text) {
    messageInput.value = text;
    autoResize(messageInput);
    messageInput.focus();
}

function openFilePicker() {
    document.getElementById("fileInput")?.click();
}

// ── Welcome Screen ──
function hideWelcome() {
    if (welcomeScreen) welcomeScreen.style.display = "none";
}

function showWelcome() {
    if (welcomeScreen) welcomeScreen.style.display = "flex";
    messagesArea.innerHTML = "";
}

// ── Message Rendering (Markdown + XSS-safe) ──
function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function renderMarkdown(text) {
    if (!text) return "";
    // Configure marked for safe rendering
    marked.setOptions({
        gfm: true,
        breaks: true,
        headerIds: false,
        mangle: false,
        sanitize: false, // we handle escaping ourselves
    });
    return marked.parse(text);
}

function addCodeCopyButtons(container) {
    container.querySelectorAll("pre code").forEach((codeBlock) => {
        const pre = codeBlock.parentElement;
        if (pre.parentElement?.classList.contains("code-block-wrapper")) return;

        const wrapper = document.createElement("div");
        wrapper.className = "code-block-wrapper";
        pre.parentNode.insertBefore(wrapper, pre);
        wrapper.appendChild(pre);

        const btn = document.createElement("button");
        btn.className = "copy-code-btn";
        btn.textContent = "Copy";
        btn.onclick = async () => {
            try {
                await navigator.clipboard.writeText(codeBlock.textContent);
                btn.textContent = "Copied!";
                btn.classList.add("copied");
                setTimeout(() => {
                    btn.textContent = "Copy";
                    btn.classList.remove("copied");
                }, 2000);
            } catch {
                btn.textContent = "Failed";
                setTimeout(() => { btn.textContent = "Copy"; }, 2000);
            }
        };
        wrapper.appendChild(btn);
    });
}

function addMessage(role, content = "") {
    hideWelcome();

    const messageDiv = document.createElement("div");
    messageDiv.className = `message ${role}`;

    const avatar = document.createElement("div");
    avatar.className = `avatar ${role === "user" ? "user-avatar" : "bot-avatar"}`;
    avatar.textContent = role === "user" ? "U" : "AI";

    const messageContent = document.createElement("div");
    messageContent.className = "message-content";

    if (role === "assistant") {
        // Render markdown for assistant
        messageContent.innerHTML = renderMarkdown(content);
        // Add copy buttons to code blocks
        addCodeCopyButtons(messageContent);
        // Syntax highlight
        messageContent.querySelectorAll("pre code").forEach((block) => {
            hljs?.highlightElement(block);
        });
    } else {
        // Plain text for user (escaped)
        messageContent.textContent = content;
    }

    messageDiv.appendChild(avatar);
    messageDiv.appendChild(messageContent);
    messagesArea.appendChild(messageDiv);

    scrollToBottom();
    updateScrollButton();

    return messageContent;
}

function appendToMessage(element, text) {
    if (!element || !text) return;
    // Re-render markdown with accumulated text
    const currentText = element.dataset.rawText || "";
    const newText = currentText + text;
    element.dataset.rawText = newText;
    element.innerHTML = renderMarkdown(newText);
    addCodeCopyButtons(element);
    element.querySelectorAll("pre code").forEach((block) => {
        hljs?.highlightElement(block);
    });
    scrollToBottom();
}

// ── Tool Detection (cosmetic only) ──
function detectLikelyTool(message) {
    const text = message.toLowerCase();
    const patterns = {
        "Calculator": /\b(?:calculate|calc|math\.?(?:sqrt|sin|cos|tan|log|pi)|\d+\s*[+\-*/^]\s*\d+)\b/,
        "Document Search": /\b(?:document|pdf|file|uploaded|summarize|summary|according to the file|based on the doc)\b/,
        "Memory Save": /\b(?:remember that|save this|store this|keep in mind|memorize|don\'t forget)\b/,
        "Memory Recall": /\b(?:what do you remember|recall|my memory|remember about me|what did i tell you)\b/,
        "Web Search": /\b(?:latest|current|today|now|recent news|search web|web search|internet|online|price of|version|update|trending|who is|what is happening|current ceo|stock price)\b/,
    };

    for (const [name, regex] of Object.entries(patterns)) {
        if (regex.test(text)) return name;
    }
    return null;
}

function addToolProgress(toolName) {
    const wrapper = document.createElement("div");
    wrapper.className = "tool-progress";

    const box = document.createElement("div");
    box.className = "tool-progress-box";

    const icon = document.createElement("span");
    icon.className = "tool-spinner";

    const text = document.createElement("span");
    text.textContent = `Using ${toolName}...`;

    box.appendChild(icon);
    box.appendChild(text);
    wrapper.appendChild(box);
    messagesArea.appendChild(wrapper);

    scrollToBottom();

    return { wrapper, icon, text };
}

function completeToolProgress(toolProgress, toolName) {
    if (!toolProgress) return;
    toolProgress.icon.className = "tool-check";
    toolProgress.icon.textContent = "✓";
    toolProgress.text.textContent = `${toolName} completed`;
    setTimeout(() => {
        toolProgress.wrapper.style.opacity = "0.6";
    }, 2000);
}

// ── SSE Parsing ──
function parseSSEPart(part) {
    const lines = part
        .split(/\r?\n/)
        .filter(line => line.trim().startsWith("data:"));

    if (lines.length === 0) return null;

    const jsonText = lines
        .map(line => line.replace(/^data:\s*/, ""))
        .join("\n")
        .trim();

    if (!jsonText || jsonText === "[DONE]") return null;

    try {
        return JSON.parse(jsonText);
    } catch (error) {
        console.error("Invalid stream JSON:", jsonText, error);
        return null;
    }
}

// ── Conversations ──
async function loadConversations() {
    try {
        const response = await fetch("/conversations");
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();

        conversationList.innerHTML = "";

        if (!data.conversations || data.conversations.length === 0) {
            conversationList.innerHTML = `<div class="history-item" style="cursor:default;opacity:0.5;">No chats yet</div>`;
            return;
        }

        data.conversations.forEach(conv => {
            const item = document.createElement("div");
            item.className = "history-item";
            item.setAttribute("role", "listitem");

            if (conv.thread_id === threadId) {
                item.classList.add("active");
            }

            item.textContent = conv.title || "New Chat";
            item.title = conv.title || "New Chat";
            item.onclick = () => loadConversation(conv.thread_id);

            conversationList.appendChild(item);
        });
    } catch (error) {
        console.error("Failed to load conversations:", error);
        conversationList.innerHTML = `<div class="history-item" style="cursor:default;color:var(--danger);">Failed to load</div>`;
    }
}

async function loadConversation(selectedThreadId) {
    if (selectedThreadId === threadId) {
        closeSidebar();
        return;
    }

    // Warn if unsent text exists
    if (messageInput?.value.trim()) {
        if (!confirm("You have unsent text. Switch conversation?")) return;
    }

    // Cancel any active stream
    if (abortController) {
        abortController.abort();
        abortController = null;
    }

    threadId = selectedThreadId;
    localStorage.setItem("thread_id", threadId);

    // Show loading
    messagesArea.innerHTML = `<div class="message-loading"></div>`;
    hideWelcome();

    try {
        const response = await fetch(`/history/${encodeURIComponent(threadId)}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();

        messagesArea.innerHTML = "";

        if (!data.messages || data.messages.length === 0) {
            showWelcome();
            await loadConversations();
            closeSidebar();
            return;
        }

        data.messages.forEach(msg => {
            addMessage(msg.role === "user" ? "user" : "assistant", msg.content);
        });

        await loadConversations();
        closeSidebar();
    } catch (error) {
        console.error("Failed to load conversation:", error);
        messagesArea.innerHTML = `<div class="error-message">Failed to load conversation: ${escapeHtml(error.message)}</div>`;
    }
}

// ── Send Message ──
async function sendMessage() {
    if (isStreaming) return; // Debounce

    const message = messageInput.value.trim();
    if (!message) return;

    if (isDictating) stopDictation();

    const selectedModel = modelSelect?.value || "llama-3.3-70b-versatile";

    // Add user message
    addMessage("user", message);

    messageInput.value = "";
    messageInput.style.height = "auto";
    sendBtn.disabled = true;
    isStreaming = true;

    setStatus(`Thinking with ${selectedModel}...`, true);

    // Tool progress indicator
    const likelyTool = detectLikelyTool(message);
    let toolProgress = null;
    if (likelyTool) {
        toolProgress = addToolProgress(likelyTool);
        setStatus(`Using ${likelyTool}...`, true);
    }

    // Assistant message placeholder
    const botElement = addMessage("assistant", "");
    botElement.dataset.rawText = "";
    let firstTokenReceived = false;

    // AbortController for cancellation
    abortController = new AbortController();

    function handleStreamData(data) {
        if (!data) return;

        if (data.token !== undefined && data.token !== null) {
            if (!firstTokenReceived) {
                firstTokenReceived = true;
                if (toolProgress) completeToolProgress(toolProgress, likelyTool);
                setStatus(`Generating with ${selectedModel}...`, true);
            }
            appendToMessage(botElement, data.token);
        }

        if (data.error) {
            if (toolProgress && !firstTokenReceived) {
                completeToolProgress(toolProgress, likelyTool);
            }
            appendToMessage(botElement, `\n\n**Error:** ${data.error}`);
            setStatus("Error", false);
        }

        if (data.done) {
            if (toolProgress && !firstTokenReceived) {
                completeToolProgress(toolProgress, likelyTool);
            }
            setStatus("Ready", false);
        }
    }

    try {
        const response = await fetch("/chat/stream", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                message: message,
                thread_id: threadId,
                model: selectedModel,
            }),
            signal: abortController.signal,
        });

        if (!response.ok) {
            let errorText = "Request failed.";
            try {
                const errorData = await response.json();
                errorText = errorData.detail || errorData.message || errorData.error || errorText;
            } catch { /* ignore parse error */ }
            botElement.innerHTML = renderMarkdown(`**Error:** ${errorText}`);
            return;
        }

        if (!response.body) {
            botElement.innerHTML = renderMarkdown("**Error:** Streaming is not supported by this browser.");
            return;
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });

            const parts = buffer.split(/\r?\n\r?\n/);
            buffer = parts.pop() || "";

            for (const part of parts) {
                const data = parseSSEPart(part);
                handleStreamData(data);
            }
        }

        // Flush remaining buffer
        buffer += decoder.decode();
        if (buffer.trim()) {
            const data = parseSSEPart(buffer);
            handleStreamData(data);
        }

    } catch (error) {
        if (error.name === "AbortError") {
            appendToMessage(botElement, "\n\n*Message generation was cancelled.*");
        } else {
            console.error("Streaming error:", error);
            if (toolProgress) completeToolProgress(toolProgress, likelyTool);
            appendToMessage(botElement, `\n\n**Error:** ${error.message}`);
        }
    } finally {
        isStreaming = false;
        abortController = null;
        sendBtn.disabled = false;
        setStatus("Ready", false);
        messageInput?.focus();
        await loadConversations();
    }
}

// ── File Upload ──
async function uploadFile() {
    const fileInput = document.getElementById("fileInput");
    if (!fileInput?.files?.length) return;

    const file = fileInput.files[0];

    addMessage("user", `📎 Uploaded document: ${file.name}`);

    const toolProgress = addToolProgress("Document Ingestion");
    setStatus("Processing document...", true);

    // Show upload progress
    uploadProgress.style.display = "block";
    uploadProgressFill.style.width = "0%";
    uploadProgressText.textContent = "Uploading...";

    const formData = new FormData();
    formData.append("file", file);
    formData.append("thread_id", threadId);

    // Simulate progress (since fetch doesn't expose upload progress easily)
    let progress = 0;
    const progressInterval = setInterval(() => {
        progress = Math.min(progress + Math.random() * 15, 90);
        uploadProgressFill.style.width = progress + "%";
    }, 200);

    try {
        const response = await fetch("/upload", {
            method: "POST",
            body: formData,
        });

        clearInterval(progressInterval);
        uploadProgressFill.style.width = "100%";

        const data = await response.json();
        completeToolProgress(toolProgress, "Document Ingestion");

        if (data.success) {
            addMessage("assistant", data.message + "\n\nYou can now ask questions about this document.");
            await loadConversations();
        } else {
            addMessage("assistant", "**Upload failed:** " + (data.message || "Unknown error"));
        }
    } catch (error) {
        clearInterval(progressInterval);
        completeToolProgress(toolProgress, "Document Ingestion");
        console.error("Upload error:", error);
        addMessage("assistant", "**Upload failed:** " + error.message);
    } finally {
        setTimeout(() => {
            uploadProgress.style.display = "none";
            uploadProgressFill.style.width = "0%";
        }, 1000);
        setStatus("Ready", false);
        fileInput.value = "";
    }
}

// ── New Chat ──
async function newChat() {
    if (isStreaming && abortController) {
        abortController.abort();
    }

    if (messageInput?.value.trim()) {
        if (!confirm("Start a new chat? Your current message will be lost.")) return;
    }

    threadId = crypto.randomUUID();
    localStorage.setItem("thread_id", threadId);

    if (isDictating) stopDictation();

    showWelcome();
    await loadConversations();
    closeSidebar();
    messageInput?.focus();
}

// ── Cleanup on page unload ──
window.addEventListener("beforeunload", () => {
    if (abortController) {
        abortController.abort();
    }
    if (isDictating) {
        stopDictation();
    }
});

// ── Keyboard shortcuts ──
document.addEventListener("keydown", (e) => {
    // Escape to close sidebar
    if (e.key === "Escape") {
        closeSidebar();
    }
    // Ctrl/Cmd + K to focus input
    if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        messageInput?.focus();
    }
});

// ── Initialize ──
loadConversations();
if (threadId) {
    loadConversation(threadId);
}