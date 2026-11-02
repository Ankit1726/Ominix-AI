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
    messageInput: document.getElementById("messageInput"),
    micBtn: document.getElementById("micBtn"),
    sendBtn: document.getElementById("sendBtn"),
    documentInput: document.getElementById("documentInput"),
    documentList: document.getElementById("documentList"),
    settingsDialog: document.getElementById("settingsDialog"),
    customModelId: document.getElementById("customModelId"),
    groqApiKey: document.getElementById("groqApiKey"),
    tavilyApiKey: document.getElementById("tavilyApiKey"),
    groqKeyState: document.getElementById("groqKeyState"),
    tavilyKeyState: document.getElementById("tavilyKeyState"),
    serverKeyStatus: document.getElementById("serverKeyStatus"),
  };

  function readSessionCredential(key) {
    try {
      return sessionStorage.getItem(key) || "";
    } catch {
      return "";
    }
  }

  const state = {
    threadId: null,
    isStreaming: false,
    recognizing: false,
    conversations: [],
    documents: [],
    credentials: {
      groqApiKey: readSessionCredential("ominix_groq_api_key"),
      tavilyApiKey: readSessionCredential("ominix_tavily_api_key"),
    },
  };

  const uid = () =>
    crypto.randomUUID
      ? crypto.randomUUID()
      : `t-${Date.now()}-${Math.random().toString(16).slice(2)}`;

  /* -------------------- Safe JSON helper -------------------- */
  async function readJson(response) {
    try {
      return await response.json();
    } catch {
      return {};
    }
  }

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
      if (!res.ok) throw new Error(`Server responded ${res.status}`);
      const data = await res.json();
      state.conversations = data.conversations || [];
      renderConversations();
      syncTopbarTitle();
    } catch (err) {
      els.conversationList.innerHTML =
        '<div class="empty-history">Couldn\'t load chat history.</div>';
    }
  }

  // Keep the topbar title in sync with the saved conversation title.
  function syncTopbarTitle() {
    const current = state.conversations.find(
      (c) => c.thread_id === state.threadId,
    );
    if (current && current.title) {
      els.topbarTitle.textContent = current.title;
    }
  }

  function renderConversations() {
    const conversationCount = document.getElementById("conversationCount");
    if (conversationCount) {
      conversationCount.textContent = String(state.conversations.length);
    }
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
      item.tabIndex = 0;
      item.textContent = c.title || "Untitled chat";
      item.title = c.title || "Untitled chat";
      item.onclick = () => openConversation(c.thread_id, c.title);
      item.onkeydown = (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          openConversation(c.thread_id, c.title);
        }
      };
      els.conversationList.appendChild(item);
    });
  }

  async function openConversation(threadId, title) {
    state.threadId = threadId;
    localStorage.setItem("ominix_thread", threadId);
    els.topbarTitle.textContent = title || "New conversation";
    renderConversations();
    closeSidebar();

    els.messagesArea.innerHTML = "";
    setStatus("thinking", "Loading...");

    try {
      const res = await fetch(`/history/${encodeURIComponent(threadId)}`);
      if (!res.ok) {
        const error = new Error(`Server responded ${res.status}`);
        error.status = res.status;
        throw error;
      }
      const data = await res.json();

      // Ignore stale responses if the user switched conversations meanwhile.
      if (state.threadId !== threadId) return;

      const messages = data.messages || [];

      if (!messages.length) {
        els.welcomeScreen.style.display = "flex";
        els.messagesArea.style.display = "none";
      } else {
        els.welcomeScreen.style.display = "none";
        els.messagesArea.style.display = "flex";
        messages.forEach((m) => appendMessage(m.role, m.content));
      }
      await loadDocuments(threadId);
      syncTopbarTitle();
      scrollToBottomInstant();
      setStatus("ready", "Ready");
    } catch (err) {
      if (state.threadId !== threadId) return;
      if (err.status === 404) {
        state.threadId = null;
        localStorage.removeItem("ominix_thread");
        window.newChat();
        return;
      }
      setStatus("error", "Error");
      showToast(
        "Couldn't load that conversation. Please check your connection and try again.",
        true,
      );
    }
  }

  window.newChat = function () {
    state.threadId = uid();
    localStorage.setItem("ominix_thread", state.threadId);
    els.messagesArea.innerHTML = "";
    els.messagesArea.style.display = "none";
    els.welcomeScreen.style.display = "flex";
    els.topbarTitle.textContent = "New conversation";
    els.messageInput.value = "";
    autoResizeInternal();
    renderConversations();
    loadDocuments(state.threadId);
    closeSidebar();
    setStatus("ready", "Ready");
    els.messageInput.focus();
  };

  // Cmd/Ctrl + K starts a new conversation (matches the shortcut hint in the UI).
  document.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      window.newChat();
    }
  });

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
    // Don't send while an IME (Hindi, Chinese, Japanese...) is composing text.
    if (event.isComposing || event.keyCode === 229) return;
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendMessage();
    }
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
    recognition.lang = navigator.language || "en-US";
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
    // An explicit dropdown choice should win over a previously saved custom ID.
    if (localStorage.getItem("ominix_custom_model")) {
      localStorage.removeItem("ominix_custom_model");
    }
    const label =
      els.modelSelect.selectedOptions[0]?.textContent?.trim() || value;
    showToast(`Switched to ${label}`);
  };

  /* -------------------- Theme -------------------- */
  function applyTheme(theme) {
    const selected = theme === "light" ? "light" : "dark";
    document.documentElement.dataset.theme = selected;
    els.themeIcon.textContent = selected === "dark" ? "☀" : "☾";
    document.getElementById("themeToggle").title =
      selected === "dark" ? "Switch to light theme" : "Switch to dark theme";
    document
      .getElementById("themeToggle")
      .setAttribute(
        "aria-label",
        selected === "dark" ? "Switch to light theme" : "Switch to dark theme",
      );
    localStorage.setItem("ominix_theme", selected);
  }

  function initTheme() {
    applyTheme(localStorage.getItem("ominix_theme") || "dark");
  }

  window.toggleTheme = function () {
    applyTheme(
      document.documentElement.dataset.theme === "dark" ? "light" : "dark",
    );
  };

  /* -------------------- API settings -------------------- */
  window.openSettings = function () {
    els.customModelId.value = localStorage.getItem("ominix_custom_model") || "";
    els.groqApiKey.value = "";
    els.tavilyApiKey.value = "";
    updateKeyStates();
    els.settingsDialog.showModal();
  };

  window.closeSettings = function () {
    els.settingsDialog.close();
  };

  function updateKeyStates() {
    els.groqKeyState.textContent = state.credentials.groqApiKey
      ? "ACTIVE · PRIVATE"
      : "NOT ADDED";
    els.tavilyKeyState.textContent = state.credentials.tavilyApiKey
      ? "ACTIVE · PRIVATE"
      : "NOT ADDED";
  }

  window.saveSettings = function () {
    const customModel = els.customModelId.value.trim();
    if (
      customModel &&
      !/^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$/.test(customModel)
    ) {
      showToast("Enter a valid model ID.", true);
      return;
    }

    const groqApiKey = els.groqApiKey.value.trim();
    const tavilyApiKey = els.tavilyApiKey.value.trim();
    if (groqApiKey) {
      state.credentials.groqApiKey = groqApiKey;
      try {
        sessionStorage.setItem("ominix_groq_api_key", groqApiKey);
      } catch {
        /* session storage unavailable: key stays in memory only */
      }
    }
    if (tavilyApiKey) {
      state.credentials.tavilyApiKey = tavilyApiKey;
      try {
        sessionStorage.setItem("ominix_tavily_api_key", tavilyApiKey);
      } catch {
        /* session storage unavailable: key stays in memory only */
      }
    }
    if (customModel) {
      localStorage.setItem("ominix_custom_model", customModel);
    } else {
      localStorage.removeItem("ominix_custom_model");
    }
    els.groqApiKey.value = "";
    els.tavilyApiKey.value = "";
    updateKeyStates();
    closeSettings();
    showToast("Settings saved for this page.");
  };

  window.clearSettings = function () {
    state.credentials = { groqApiKey: "", tavilyApiKey: "" };
    try {
      sessionStorage.removeItem("ominix_groq_api_key");
      sessionStorage.removeItem("ominix_tavily_api_key");
    } catch {
      /* ignore */
    }
    els.groqApiKey.value = "";
    els.tavilyApiKey.value = "";
    updateKeyStates();
    showToast("API keys cleared.");
  };

  async function loadServerConfig() {
    try {
      const response = await fetch("/config");
      if (!response.ok) throw new Error(`Server responded ${response.status}`);
      const config = await response.json();
      const groq = config.groq_key_configured
        ? "Groq default: ready"
        : "Groq default: not configured";
      const tavily = config.tavily_key_configured
        ? "Tavily default: ready"
        : "Tavily default: not configured";
      els.serverKeyStatus.textContent = `${groq} · ${tavily}`;
      return config;
    } catch {
      els.serverKeyStatus.textContent = "Could not check server key settings.";
      return {};
    }
  }

  function hasModelOption(value) {
    return [...els.modelSelect.options].some((o) => o.value === value);
  }

  /* -------------------- Uploaded documents -------------------- */
  async function loadDocuments(threadId) {
    if (!threadId) return;
    try {
      const response = await fetch(
        `/documents/${encodeURIComponent(threadId)}`,
      );
      if (!response.ok) throw new Error(`Server responded ${response.status}`);
      const data = await response.json();
      if (state.threadId === threadId) {
        state.documents = data.documents || [];
        renderDocuments();
      }
    } catch {
      if (state.threadId === threadId) {
        state.documents = [];
        renderDocuments();
      }
    }
  }

  function renderDocuments() {
    els.documentList.replaceChildren();
    state.documents.forEach((item) => {
      const chip = document.createElement("span");
      chip.className = "document-chip";
      chip.title = item.filename;
      chip.textContent = item.filename;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "document-remove";
      remove.textContent = "×";
      remove.setAttribute("aria-label", `Remove ${item.filename}`);
      remove.addEventListener("click", () => removeDocument(item.id));
      chip.appendChild(remove);
      els.documentList.appendChild(chip);
    });
  }

  window.chooseDocument = function () {
    if (state.isStreaming) {
      showToast(
        "Wait for the current response to finish before uploading.",
        true,
      );
      return;
    }
    els.documentInput.click();
  };

  async function uploadDocument(file) {
    const body = new FormData();
    body.append("file", file);
    const response = await fetch(
      `/documents/${encodeURIComponent(state.threadId)}`,
      { method: "POST", body },
    );
    const result = await readJson(response);
    if (!response.ok) {
      throw new Error(
        result.error ||
          (response.status === 413
            ? "That file is too large."
            : `Upload failed (${response.status})`),
      );
    }
    await loadDocuments(state.threadId);
    showToast(`Added ${result.document?.filename || file.name}`);
  }

  async function removeDocument(documentId) {
    try {
      const response = await fetch(
        `/documents/${encodeURIComponent(state.threadId)}/${encodeURIComponent(documentId)}`,
        { method: "DELETE" },
      );
      const result = await readJson(response);
      if (!response.ok)
        throw new Error(result.error || "Couldn't remove that file.");
      await loadDocuments(state.threadId);
    } catch (error) {
      showToast(error.message || "Couldn't remove that file.", true);
    }
  }

  els.documentInput.addEventListener("change", async () => {
    const file = els.documentInput.files?.[0];
    els.documentInput.value = "";
    if (!file) return;
    try {
      await uploadDocument(file);
    } catch (error) {
      showToast(error.message || "Couldn't upload that file.", true);
    }
  });

  els.settingsDialog.addEventListener("close", () => {
    els.groqApiKey.value = "";
    els.tavilyApiKey.value = "";
  });

  /* -------------------- Rendering messages -------------------- */
  // Open links in a new tab safely.
  if (window.DOMPurify) {
    DOMPurify.addHook("afterSanitizeAttributes", (node) => {
      if (node.tagName === "A" && node.hasAttribute("href")) {
        node.setAttribute("target", "_blank");
        node.setAttribute("rel", "noopener noreferrer");
      }
    });
  }

  function renderMarkdown(text) {
    if (window.marked && window.DOMPurify) {
      try {
        return DOMPurify.sanitize(marked.parse(text, { breaks: true }));
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
    addMessageActions(body, contentEl, role);
    msg.appendChild(avatar);
    msg.appendChild(body);
    els.messagesArea.appendChild(msg);

    return contentEl;
  }

  function addMessageActions(body, contentEl, role) {
    const actions = document.createElement("div");
    actions.className = "msg-actions";

    const copyButton = document.createElement("button");
    copyButton.type = "button";
    copyButton.className = "msg-action";
    copyButton.textContent = "Copy";
    copyButton.setAttribute("aria-label", "Copy message");
    copyButton.addEventListener("click", () => copyMessage(contentEl));
    actions.appendChild(copyButton);

    if (role === "assistant") {
      const pdfButton = document.createElement("button");
      pdfButton.type = "button";
      pdfButton.className = "msg-action";
      pdfButton.textContent = "Save as PDF";
      pdfButton.setAttribute("aria-label", "Save message as PDF");
      pdfButton.addEventListener("click", () => saveMessageAsPdf(contentEl));
      actions.appendChild(pdfButton);
    }

    body.appendChild(actions);
  }

  async function copyMessage(contentEl) {
    const text = contentEl.innerText.trim();
    if (!text) {
      showToast("There is no message content to copy.", true);
      return;
    }

    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const fallback = document.createElement("textarea");
        fallback.value = text;
        fallback.setAttribute("readonly", "");
        fallback.style.position = "fixed";
        fallback.style.opacity = "0";
        document.body.appendChild(fallback);
        fallback.select();
        const copied = document.execCommand("copy");
        fallback.remove();
        if (!copied) throw new Error("Clipboard access was denied.");
      }
      showToast("Message copied.");
    } catch {
      showToast(
        "Couldn't copy this message. Check your browser permissions.",
        true,
      );
    }
  }

  function saveMessageAsPdf(contentEl) {
    const printWindow = window.open("", "_blank");
    if (!printWindow) {
      showToast("Allow pop-ups to save this message as a PDF.", true);
      return;
    }

    const date = new Date().toLocaleDateString();
    printWindow.opener = null;
    printWindow.document.open();
    printWindow.document.write(`<!doctype html>
      <html lang="en">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>Ominix reading</title>
          <style>
            body { max-width: 760px; margin: 48px auto; padding: 0 28px; color: #20231f; font: 16px/1.75 Georgia, serif; }
            header { margin-bottom: 32px; padding-bottom: 14px; border-bottom: 1px solid #dfe3dc; font: 13px/1.5 Arial, sans-serif; color: #65705f; }
            header strong { display: block; margin-bottom: 4px; color: #263520; font-size: 18px; }
            h1, h2, h3 { margin: 1.5em 0 .5em; line-height: 1.3; }
            p, ul, ol, blockquote, pre { margin: 0 0 1em; }
            a { color: #456b38; }
            blockquote { margin-left: 0; padding-left: 16px; border-left: 3px solid #a6bd92; color: #53604d; }
            pre { padding: 14px; overflow-wrap: anywhere; white-space: pre-wrap; border-radius: 6px; background: #f2f4ef; font: 12px/1.6 Consolas, monospace; }
            code { font: .9em Consolas, monospace; }
            img { max-width: 100%; }
            @page { margin: 18mm; }
            @media print { body { margin: 0 auto; padding: 0; } }
          </style>
        </head>
        <body>
          <header><strong>Ominix · Reading note</strong>Saved ${date}</header>
          <main>${contentEl.innerHTML}</main>
        </body>
      </html>`);
    printWindow.document.close();
    // requestAnimationFrame may not fire in a background window; use a timeout.
    setTimeout(() => {
      printWindow.focus();
      printWindow.print();
    }, 300);
    showToast("Print dialog opened. Choose Save as PDF to download.");
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

  function scrollToBottomInstant() {
    els.chatContainer.scrollTo({ top: els.chatContainer.scrollHeight });
  }

  function distanceFromBottom() {
    return (
      els.chatContainer.scrollHeight -
      els.chatContainer.scrollTop -
      els.chatContainer.clientHeight
    );
  }

  els.chatContainer.addEventListener("scroll", () => {
    els.scrollBottomBtn.classList.toggle("visible", distanceFromBottom() > 240);
  });

  /* -------------------- Sending / streaming -------------------- */
  async function sendMessage() {
    const text = els.messageInput.value.trim();
    if (!text || state.isStreaming) return;

    if (!state.threadId) state.threadId = uid();

    appendMessage("user", text);
    els.messageInput.value = "";
    autoResizeInternal();
    scrollToBottomInstant();

    const assistantContentEl = appendTypingBubble();
    els.sendBtn.disabled = true;
    state.isStreaming = true;
    setStatus("thinking", "Thinking...");

    const model = els.modelSelect.value;
    const customModel = localStorage.getItem("ominix_custom_model") || "";
    let buffer = "";
    let firstToken = true;
    let streamFailed = false;
    let renderQueued = false;

    // Throttle markdown re-rendering to one per animation frame, and only
    // auto-scroll if the user is already near the bottom.
    function renderNow() {
      renderQueued = false;
      const stick = distanceFromBottom() < 120;
      assistantContentEl.innerHTML = renderMarkdown(buffer);
      highlightCode(assistantContentEl);
      if (stick) scrollToBottomInstant();
    }

    function scheduleRender() {
      if (renderQueued) return;
      renderQueued = true;
      requestAnimationFrame(renderNow);
    }

    function handleFrame(frame) {
      const line = frame.trim();
      if (!line.startsWith("data:")) return;

      const jsonStr = line.slice(5).trim();
      if (!jsonStr) return;

      let payload;
      try {
        payload = JSON.parse(jsonStr);
      } catch {
        return;
      }

      if (payload.error) {
        streamFailed = true;
        renderQueued = true; // suppress any pending render overwriting the error
        assistantContentEl.innerHTML = `<span class="msg-error">Something went wrong: ${escapeHtml(payload.error)}</span>`;
        setStatus("error", "Error");
      } else if (payload.token && !streamFailed) {
        if (firstToken) {
          buffer = "";
          firstToken = false;
        }
        buffer += payload.token;
        scheduleRender();
      }
    }

    try {
      const res = await fetch("/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          thread_id: state.threadId,
          model: customModel || model,
          groq_api_key: state.credentials.groqApiKey || undefined,
          tavily_api_key: state.credentials.tavilyApiKey || undefined,
        }),
      });

      if (!res.ok || !res.body) {
        const errorBody = await readJson(res);
        throw new Error(errorBody.error || `Server responded ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let sseBuffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        sseBuffer += decoder
          .decode(value, { stream: true })
          .replace(/\r\n/g, "\n");
        const frames = sseBuffer.split("\n\n");
        sseBuffer = frames.pop() || "";
        frames.forEach(handleFrame);
      }

      // Process anything left in the buffer when the stream closes.
      sseBuffer += decoder.decode().replace(/\r\n/g, "\n");
      if (sseBuffer.trim()) handleFrame(sseBuffer);

      if (!streamFailed && !firstToken) {
        renderNow(); // final, complete render
      }

      if (firstToken && !streamFailed) {
        assistantContentEl.innerHTML =
          '<span class="msg-error">No response received. Please try again.</span>';
      } else if (!streamFailed && buffer.trim()) {
        addMessageActions(
          assistantContentEl.closest(".msg-body"),
          assistantContentEl,
          "assistant",
        );
      }

      if (!streamFailed) setStatus("ready", "Ready");
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
  async function init() {
    initTheme();

    // Wait for server config so it can't overwrite the user's saved model.
    const config = await loadServerConfig();

    const savedModel = localStorage.getItem("ominix_model");
    if (savedModel && hasModelOption(savedModel)) {
      els.modelSelect.value = savedModel;
    } else if (config.default_model && hasModelOption(config.default_model)) {
      els.modelSelect.value = config.default_model;
    }

    const savedThread = localStorage.getItem("ominix_thread");
    if (savedThread) {
      state.threadId = savedThread;
      loadConversations();
      openConversation(savedThread, null);
    } else {
      state.threadId = uid();
      localStorage.setItem("ominix_thread", state.threadId);
      loadConversations();
      loadDocuments(state.threadId);
    }

    els.messageInput.focus();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
