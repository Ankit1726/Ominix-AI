(() => {
  "use strict";

  const els = {
    sidebar: document.getElementById("sidebar"),
    sidebarBackdrop: document.getElementById("sidebarBackdrop"),
    conversationList: document.getElementById("conversationList"),
    historyLoading: document.getElementById("historyLoading"),
    themeIcon: document.getElementById("themeIcon"),
    topbarTitle: document.getElementById("topbarTitle"),
    modelSelect: document.getElementById("modelSelect"),
    modelStatusDot: document.getElementById("modelStatusDot"),
    statusDot: document.getElementById("statusDot"),
    statusText: document.getElementById("statusText"),
    chatContainer: document.getElementById("chatContainer"),
    welcomeScreen: document.getElementById("welcomeScreen"),
    messagesArea: document.getElementById("messagesArea"),
    scrollBottomBtn: document.getElementById("scrollBottomBtn"),
    fileInput: document.getElementById("fileInput"),
    messageInput: document.getElementById("messageInput"),
    micBtn: document.getElementById("micBtn"),
    sendBtn: document.getElementById("sendBtn"),
    uploadProgress: document.getElementById("uploadProgress"),
    uploadProgressFill: document.getElementById("uploadProgressFill"),
    uploadProgressText: document.getElementById("uploadProgressText"),
  };

  const state = {
    threadId: null,
    isStreaming: false,
    recognizing: false,
    conversations: [],
  };

  const uid = () =>
    crypto.randomUUID
      ? crypto.randomUUID()
      : `t-${Date.now()}-${Math.random().toString(16).slice(2)}`;

  /* -------------------- Sidebar -------------------- */
  window.toggleSidebar = function () {
    els.sidebar.classList.toggle("open");
    els.sidebarBackdrop.classList.toggle("visible");
  };

  window.closeSidebar = function () {
    els.sidebar.classList.remove("open");
    els.sidebarBackdrop.classList.remove("visible");
  };

  /* -------------------- Status -------------------- */
  function setStatus(kind, text) {
    els.statusDot.className =
      "status-dot" + (kind === "ready" ? "" : ` ${kind}`);
    els.statusText.textContent = text;
  }

  function showToast(message, isError = false) {
    let toast = document.getElementById("appToast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "appToast";
      toast.className = "toast";
      document.body.appendChild(toast);
    }
    toast.textContent = message;
    toast.className = "toast visible" + (isError ? " error" : "");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => toast.classList.remove("visible"), 2600);
  }

  /* -------------------- Conversations -------------------- */
  async function loadConversations() {
    try {
      const res = await fetch("/conversations");
      const data = await res.json();
      state.conversations = data.conversations || [];
      renderConversations();
    } catch (err) {
      els.conversationList.innerHTML =
        '<div class="empty-history">Couldn\'t load chat history.</div>';
    }
  }

  function renderConversations() {
    if (!state.conversations.length) {
      els.conversationList.innerHTML =
        '<div class="empty-history">No conversations yet.</div>';
      return;
    }

    els.conversationList.innerHTML = "";
    state.conversations.forEach((c) => {
      const item = document.createElement("div");
      item.className =
        "conversation-item" + (c.thread_id === state.threadId ? " active" : "");
      item.setAttribute("role", "listitem");
      item.textContent = c.title || "Untitled chat";
      item.title = c.title || "Untitled chat";
      item.onclick = () => openConversation(c.thread_id, c.title);
      els.conversationList.appendChild(item);
    });
  }

  async function openConversation(threadId, title) {
    state.threadId = threadId;
    localStorage.setItem("ominix_thread", threadId);
    els.topbarTitle.textContent = title || "Ominix Agentic AI";
    renderConversations();
    closeSidebar();

    els.messagesArea.innerHTML = "";
    setStatus("thinking", "Loading...");

    try {
      const res = await fetch(`/history/${threadId}`);
      const data = await res.json();
      const messages = data.messages || [];

      if (!messages.length) {
        els.welcomeScreen.style.display = "flex";
        els.messagesArea.style.display = "none";
      } else {
        els.welcomeScreen.style.display = "none";
        els.messagesArea.style.display = "flex";
        messages.forEach((m) => appendMessage(m.role, m.content));
      }
      scrollToBottom();
      setStatus("ready", "Ready");
    } catch (err) {
      setStatus("error", "Error");
      showToast("Couldn't load that conversation.", true);
    }
  }

  window.newChat = function () {
    state.threadId = uid();
    localStorage.setItem("ominix_thread", state.threadId);
    els.messagesArea.innerHTML = "";
    els.messagesArea.style.display = "none";
    els.welcomeScreen.style.display = "flex";
    els.topbarTitle.textContent = "Ominix Agentic AI";
    els.messageInput.value = "";
    autoResizeInternal();
    renderConversations();
    closeSidebar();
    setStatus("ready", "Ready");
  };

  /* -------------------- Prompt cards -------------------- */
  window.usePrompt = function (text) {
    els.messageInput.value = text;
    autoResizeInternal();
    els.messageInput.focus();
  };

  /* -------------------- Textarea -------------------- */
  window.autoResize = function (el) {
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  };

  function autoResizeInternal() {
    window.autoResize(els.messageInput);
  }

  window.handleKeyDown = function (event) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
  };

  /* -------------------- File upload -------------------- */
  window.openFilePicker = function () {
    els.fileInput.click();
  };

  window.uploadFile = function () {
    const file = els.fileInput.files[0];
    if (!file) return;

    if (!state.threadId) state.threadId = uid();

    const formData = new FormData();
    formData.append("file", file);
    formData.append("thread_id", state.threadId);

    const xhr = new XMLHttpRequest();
    els.uploadProgress.style.display = "flex";
    els.uploadProgressFill.style.width = "0%";
    els.uploadProgressText.textContent = `Uploading ${file.name}...`;

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) {
        const pct = Math.round((e.loaded / e.total) * 100);
        els.uploadProgressFill.style.width = pct + "%";
      }
    };

    xhr.onload = () => {
      els.uploadProgress.style.display = "none";
      els.fileInput.value = "";
      try {
        const data = JSON.parse(xhr.responseText);
        if (data.success) {
          showToast(data.message || "File uploaded.");
          loadConversations();
        } else {
          showToast(data.message || "Upload failed.", true);
        }
      } catch {
        showToast("Upload failed.", true);
      }
    };

    xhr.onerror = () => {
      els.uploadProgress.style.display = "none";
      els.fileInput.value = "";
      showToast("Upload failed. Check your connection.", true);
    };

    xhr.open("POST", "/upload");
    xhr.send(formData);
  };

  /* -------------------- Dictation -------------------- */
  let recognition = null;

  window.toggleDictation = function () {
    const SpeechRecognition =
      window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      showToast("Voice input isn't supported in this browser.", true);
      return;
    }

    if (state.recognizing) {
      recognition && recognition.stop();
      return;
    }

    recognition = new SpeechRecognition();
    recognition.lang = "en-US";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
      state.recognizing = true;
      els.micBtn.classList.add("recording");
    };

    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript;
      els.messageInput.value +=
        (els.messageInput.value ? " " : "") + transcript;
      autoResizeInternal();
    };

    recognition.onerror = () =>
      showToast("Couldn't hear that — try again.", true);

    recognition.onend = () => {
      state.recognizing = false;
      els.micBtn.classList.remove("recording");
    };

    recognition.start();
  };

  /* -------------------- Model selector -------------------- */
  window.onModelChange = function (value) {
    localStorage.setItem("ominix_model", value);
    const label =
      els.modelSelect.selectedOptions[0]?.textContent?.trim() || value;
    showToast(`Switched to ${label}`);
  };

  /* -------------------- Rendering messages -------------------- */
  function renderMarkdown(text) {
    if (window.marked) {
      try {
        return marked.parse(text);
      } catch {
        return escapeHtml(text);
      }
    }
    return escapeHtml(text);
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function highlightCode(container) {
    if (window.hljs) {
      container.querySelectorAll("pre code").forEach((block) => {
        hljs.highlightElement(block);
      });
    }
  }

  function appendMessage(role, content) {
    els.welcomeScreen.style.display = "none";
    els.messagesArea.style.display = "flex";

    const msg = document.createElement("div");
    msg.className = `msg ${role}`;

    const avatar = document.createElement("div");
    avatar.className = "msg-avatar";
    avatar.textContent = role === "user" ? "U" : "O";

    const body = document.createElement("div");
    body.className = "msg-body";

    const roleLabel = document.createElement("div");
    roleLabel.className = "msg-role";
    roleLabel.textContent = role === "user" ? "You" : "Ominix";

    const contentEl = document.createElement("div");
    contentEl.className = "msg-content";
    contentEl.innerHTML = renderMarkdown(content || "");
    highlightCode(contentEl);

    body.appendChild(roleLabel);
    body.appendChild(contentEl);
    msg.appendChild(avatar);
    msg.appendChild(body);
    els.messagesArea.appendChild(msg);

    return contentEl;
  }

  function appendTypingBubble() {
    els.welcomeScreen.style.display = "none";
    els.messagesArea.style.display = "flex";

    const msg = document.createElement("div");
    msg.className = "msg assistant";

    const avatar = document.createElement("div");
    avatar.className = "msg-avatar";
    avatar.textContent = "O";

    const body = document.createElement("div");
    body.className = "msg-body";

    const roleLabel = document.createElement("div");
    roleLabel.className = "msg-role";
    roleLabel.textContent = "Ominix";

    const contentEl = document.createElement("div");
    contentEl.className = "msg-content";
    contentEl.innerHTML =
      '<span class="typing-indicator"><span></span><span></span><span></span></span>';

    body.appendChild(roleLabel);
    body.appendChild(contentEl);
    msg.appendChild(avatar);
    msg.appendChild(body);
    els.messagesArea.appendChild(msg);

    return contentEl;
  }

  /* -------------------- Scroll -------------------- */
  window.scrollToBottom = function () {
    els.chatContainer.scrollTo({
      top: els.chatContainer.scrollHeight,
      behavior: "smooth",
    });
  };

  els.chatContainer.addEventListener("scroll", () => {
    const distance =
      els.chatContainer.scrollHeight -
      els.chatContainer.scrollTop -
      els.chatContainer.clientHeight;
    els.scrollBottomBtn.classList.toggle("visible", distance > 240);
  });

  /* -------------------- Sending / streaming -------------------- */
  async function sendMessage() {
    const text = els.messageInput.value.trim();
    if (!text || state.isStreaming) return;

    if (!state.threadId) state.threadId = uid();

    appendMessage("user", text);
    els.messageInput.value = "";
    autoResizeInternal();
    els.chatContainer.scrollTo({ top: els.chatContainer.scrollHeight });

    const assistantContentEl = appendTypingBubble();
    els.sendBtn.disabled = true;
    state.isStreaming = true;
    setStatus("thinking", "Thinking...");

    const model = els.modelSelect.value;
    let buffer = "";
    let firstToken = true;

    try {
      const res = await fetch("/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          thread_id: state.threadId,
          model,
        }),
      });

      if (!res.ok || !res.body) {
        throw new Error(`Server responded ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let sseBuffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        sseBuffer += decoder.decode(value, { stream: true });
        const frames = sseBuffer.split("\n\n");
        sseBuffer = frames.pop() || "";

        for (const frame of frames) {
          const line = frame.trim();
          if (!line.startsWith("data:")) continue;

          const jsonStr = line.slice(5).trim();
          if (!jsonStr) continue;

          let payload;
          try {
            payload = JSON.parse(jsonStr);
          } catch {
            continue;
          }

          if (payload.error) {
            assistantContentEl.innerHTML = `<span class="msg-error">Something went wrong: ${escapeHtml(payload.error)}</span>`;
            setStatus("error", "Error");
          } else if (payload.token) {
            if (firstToken) {
              buffer = "";
              firstToken = false;
            }
            buffer += payload.token;
            assistantContentEl.innerHTML = renderMarkdown(buffer);
            highlightCode(assistantContentEl);
            els.chatContainer.scrollTo({ top: els.chatContainer.scrollHeight });
          } else if (payload.done) {
            // finalize handled after loop
          }
        }
      }

      if (firstToken) {
        // no tokens ever arrived
        assistantContentEl.innerHTML =
          '<span class="msg-error">No response received. Please try again.</span>';
      }

      setStatus("ready", "Ready");
      loadConversations();
    } catch (err) {
      assistantContentEl.innerHTML = `<span class="msg-error">Connection error: ${escapeHtml(err.message)}</span>`;
      setStatus("error", "Error");
    } finally {
      state.isStreaming = false;
      els.sendBtn.disabled = false;
    }
  }
  window.sendMessage = sendMessage;

  /* -------------------- Init -------------------- */
  document.addEventListener("DOMContentLoaded", () => {
    initTheme();

    const savedModel = localStorage.getItem("ominix_model");
    if (
      savedModel &&
      [...els.modelSelect.options].some((o) => o.value === savedModel)
    ) {
      els.modelSelect.value = savedModel;
    }

    loadConversations();

    const savedThread = localStorage.getItem("ominix_thread");
    if (savedThread) {
      openConversation(savedThread, null);
    } else {
      state.threadId = uid();
      localStorage.setItem("ominix_thread", state.threadId);
    }

    els.messageInput.focus();
  });
})();
