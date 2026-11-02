<div align="center">

# ✨ Ominix

### Your thinking space — an agentic AI workspace for writing, research and discovery

**Chat • Live Web Research • Document Intelligence • Personal Memory • Bring-Your-Own Keys**

<p align="center">
  <img src="https://readme-typing-svg.herokuapp.com?font=Poppins&weight=600&size=22&duration=3500&pause=1000&color=4DA6FF&center=true&vCenter=true&width=900&lines=Good+ideas+start+with+a+little+curiosity;Chat+%7C+Web+Research+%7C+Documents+%7C+Memory;Built+with+LangGraph+%2B+Groq+%2B+Tavily;Made+with+%E2%99%A5+by+Ankit+Gupta"/>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white"/>
  <img src="https://img.shields.io/badge/LangGraph-Agentic_AI-orange?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/LangChain-Framework-blueviolet?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/Groq-Fast_Inference-f55036?style=for-the-badge"/>
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white"/>
  <img src="https://img.shields.io/badge/Open_Source-%E2%9D%A4-red?style=for-the-badge"/>
</p>

<p align="center">
  <a href="https://ominix-ai.onrender.com/" target="_blank">
    <img src="https://img.shields.io/badge/🚀%20Live%20Demo-Open%20Ominix-success?style=for-the-badge"/>
  </a>
</p>

</div>

---

## 🌟 About

**Ominix** is a calm, dark-themed AI workspace built on an **agentic architecture**. Instead of juggling separate apps for chatting, searching the web, reading documents and keeping notes, Ominix brings it all into one place — and an agent decides which tool to use for each request.

> *"A quiet place to ask the big question, untangle the small one, or find something you didn't know you were looking for."*

> 🌐 **Live app:** [Ominix-AI](https://ominix-ai.onrender.com)


---

## 📸 Preview

<p align="center">
  <img src="./preview/live.png" width="100%" alt="Ominix preview"/>
</p>

---

## ✨ Features

### 💬 Intelligent Chat
- Multi-turn, context-aware conversations
- Streaming responses
- Multiple models to choose from (see [Supported Models](#-supported-models))
- Ultra-fast inference powered by Groq
- Quick actions with the `⌘ K` shortcut and `↵` to send

### 🌐 Go a Little Deeper — Web Research
- Live web search with real, source-backed answers
- Latest news and current events
- Weather, stock and flight updates
- Powered by Tavily search

### 📄 Make Sense of a Document
- Upload your files and get clear summaries
- Pull out the useful details, skip the noise
- Ask follow-up questions about your documents

### 🧠 Make It Yours — Personal Memory
- Save things worth remembering
- Long-term context across conversations
- More personal, more relevant answers over time

### 💡 Think It Through
- Brainstorm ideas
- Turn a knotty problem into a clear next step

### 🔑 Bring Your Own Keys
- Add your personal **Groq** and **Tavily** API keys from the Settings panel
- **Automatic fallback:** the shared Groq key is used first; if it hits a rate limit, Ominix seamlessly retries with your personal key
- Optional custom Groq model ID — use any model available to your account
- Keys are kept in your browser tab's session storage and are **never saved on the server**

### 🛠 Built-in Tools
| Tool | Purpose |
|------|---------|
| 🔍 Web Search | Real-time research with sources |
| 📄 Document Processing | Summaries and key-detail extraction |
| 🧠 Memory | Save and recall personal context |
| 🧮 Calculator | Accurate math on demand |

---

## 🤖 Supported Models

| Model | Best for |
|-------|----------|
| **GPT-OSS 120B** | Deep reasoning and complex tasks |
| **GPT-OSS 20B** | Balanced speed and quality |
| **Llama 3.3 70B** | General-purpose chat and writing |
| **Llama 3.1 8B** | Quick, lightweight responses |
| **Qwen 3 32B** | Multilingual and analytical work |

---

## 🧠 How the Agent Works

```text
                      User Query
                          │
                          ▼
                 Understand Intent
                          │
                          ▼
                  LangGraph Agent
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
     Web Search      Document AI        Memory
      (Tavily)           │                 │
          └───────────────┼───────────────┘
                          ▼
                    Tool Execution
                          │
                          ▼
                     LLM Reasoning
                          │
                          ▼
                 Streamed Final Response
```

---

## 🛠 Tech Stack

| Layer | Technology |
|-------|-----------|
| **Agent Framework** | LangGraph · LangChain |
| **LLM Providers** | Groq (GPT-OSS, Llama, Qwen) |
| **Search** | Tavily |
| **Backend** | Python 3.11 |
| **Frontend** | HTML · CSS · JavaScript |
| **Deployment** | Render · Docker |

---

## 🎯 Use Cases

- 🤖 Everyday AI assistant
- 🔎 Research assistant with real sources
- 📄 Document summarizer
- 🗂 Personal knowledge assistant
- ⚡ Productivity workspace
- 📚 Learning companion

---

## 🔒 Privacy

- Your workspace is private to your device
- Personal API keys live only in your browser tab's session storage
- Keys are sent over a secure connection and never stored on the server

> ⚠️ Ominix can make mistakes. Double-check anything that really matters.

---

## 🔮 Roadmap

- [ ] 🎙 Voice assistant
- [ ] 🖼 Image understanding
- [ ] 📚 RAG knowledge base
- [ ] 🤝 Multi-agent collaboration
- [ ] ☁️ Cloud memory sync
- [ ] 📱 Fully mobile-responsive UI

---

## 🤝 Contributing

Contributions, issues and feature requests are welcome!

1. Fork the project
2. Create your feature branch: `git checkout -b feature/amazing-feature`
3. Commit your changes: `git commit -m "Add amazing feature"`
4. Push to the branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

---

## 👨‍💻 Developer

<div align="center">

### **Ankit Gupta**

**AI Engineer • AI Backend Developer • GenAI & Agentic AI Developer**

*Building intelligent AI systems with LangGraph, LangChain and modern LLMs.*

</div>

---

## ⭐ Support

If Ominix helped you, please consider giving it a ⭐ on GitHub — it motivates me to keep building high-quality open-source AI projects.

---

<div align="center">

### ✨ Ominix

**Think smarter. Search faster. Remember better.**

*A calmer corner of the internet — made with ❤️ by **Ankit Gupta***

</div>