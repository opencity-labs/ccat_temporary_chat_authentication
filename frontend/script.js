/**
 * Chatbot frontend -  ccat_temporary_chat_authentication plugin.
 *
 * Flow:
 *  1. User sees privacy overlay → checks consent → clicks "Inizia Chat"
 *  2. POST /custom/sessions/create  →  JWT + session_id
 *  3. WebSocket  ws(s)://host/ws?token=JWT
 *  4. Cat streams:  { type:"chat_token", content:"…" }  then  { type:"chat", content:"…", why:{…} }
 *  5. Reset: close WS, delete session, open a new one.
 *
 * Configuration is injected by the server as window.CHATBOT_CONFIG (see endpoints.py).
 */

"use strict";

// ---------------------------------------------------------------------------
// Config  (server-injected via window.CHATBOT_CONFIG, with safe fallbacks)
// ---------------------------------------------------------------------------
const _cfg = (typeof window.CHATBOT_CONFIG === "object" && window.CHATBOT_CONFIG) || {};
const CONFIG = {
    headerTitle:       _cfg.headerTitle       || "Assistente Virtuale",
    botName:           _cfg.botName           || "Assistente AI",
    accentColor:       _cfg.accentColor       || "#005fff",
    privacyUrl:        _cfg.privacyUrl        || "#",
    defaultQuestions:  Array.isArray(_cfg.defaultQuestions) ? _cfg.defaultQuestions : [],
};

// Apply accent colour as CSS custom property so the whole stylesheet picks it up
document.documentElement.style.setProperty("--primary-color", CONFIG.accentColor);

const API_BASE = window.location.origin;
const WS_BASE  = API_BASE.replace(/^http/, "ws");

// ---------------------------------------------------------------------------
// UI refs
// ---------------------------------------------------------------------------
const ui = {
    headerTitle:       document.getElementById("header-title"),
    tenantOverlay:     document.getElementById("tenant-name-overlay"),
    privacyLink:       document.getElementById("privacy-link"),
    footerPrivacyLink: document.getElementById("footer-privacy-link"),
    privacyCheck:      document.getElementById("privacy-check"),
    startBtn:          document.getElementById("start-chat-btn"),
    overlay:           document.getElementById("privacy-overlay"),
    input:             document.getElementById("user-input"),
    sendBtn:           document.getElementById("send-btn"),
    chatContainer:     document.getElementById("chat-container"),
    form:              document.getElementById("chat-form"),
    resetBtn:          document.getElementById("reset-btn"),
    statusDot:         document.querySelector(".status-dot"),
};

// ---------------------------------------------------------------------------
// Bootstrap static UI values
// ---------------------------------------------------------------------------
if (ui.headerTitle)       ui.headerTitle.textContent       = CONFIG.headerTitle;
if (ui.tenantOverlay)     ui.tenantOverlay.textContent     = CONFIG.headerTitle;
if (ui.privacyLink)       ui.privacyLink.href              = CONFIG.privacyUrl;
if (ui.footerPrivacyLink) ui.footerPrivacyLink.href        = CONFIG.privacyUrl;

// Update page title
document.title = CONFIG.headerTitle;

// Ensure checkbox is unchecked on page load
ui.privacyCheck.checked = false;
ui.startBtn.disabled = true;

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let socket          = null;
let sessionToken    = null;
let sessionId       = null;
let typingEl        = null;
let streamingBubble = null;
let streamingContent = "";

// ---------------------------------------------------------------------------
// Privacy gate
// ---------------------------------------------------------------------------
function syncPrivacyBtn() {
    ui.startBtn.disabled = !ui.privacyCheck.checked;
}
ui.privacyCheck.addEventListener("change", syncPrivacyBtn);
ui.privacyCheck.addEventListener("input",  syncPrivacyBtn);

ui.startBtn.addEventListener("click", async () => {
    ui.startBtn.textContent = "Connessione in corso…";
    ui.startBtn.disabled    = true;

    try {
        await initChat();
        ui.overlay.classList.add("hidden");
        ui.overlay.setAttribute("aria-hidden", "true");
        ui.input.disabled   = false;
        ui.sendBtn.disabled = false;
        ui.input.focus();
        if (ui.chatContainer.children.length === 0) {
            appendMessage("bot", `Ciao, sono l'assistente virtuale del ${CONFIG.headerTitle} e sono qui per rispondere alle tue domande. Come posso aiutarti?`);
        }
    } catch (err) {
        alert("Impossibile connettersi al server: " + err.message);
        ui.startBtn.textContent = "Inizia Chat";
        ui.startBtn.disabled    = false;
    }
});

// ---------------------------------------------------------------------------
// Reset
// ---------------------------------------------------------------------------
ui.resetBtn.addEventListener("click", async () => {
    ui.input.disabled   = true;
    ui.sendBtn.disabled = true;
    setStatus("offline");

    if (socket) {
        socket.onclose = null;
        socket.close();
        socket = null;
    }

    if (sessionId) {
        try {
            await fetch(`${API_BASE}/custom/sessions/${sessionId}`, {
                method:  "DELETE",
                headers: { Authorization: `Bearer ${sessionToken}` },
            });
        } catch (_) { /* best-effort */ }
    }

    sessionToken     = null;
    sessionId        = null;
    streamingBubble  = null;
    streamingContent = "";
    typingEl         = null;
    ui.chatContainer.innerHTML = "";

    try {
        await initChat();
        ui.input.disabled   = false;
        ui.sendBtn.disabled = false;
        ui.input.focus();
        appendMessage("bot", `Ciao, sono l'assistente virtuale del ${CONFIG.headerTitle} e sono qui per rispondere alle tue domande. Come posso aiutarti?`);
    } catch (err) {
        alert("Errore nella connessione: " + err.message);
    }
});

// ---------------------------------------------------------------------------
// WebSocket connection
// ---------------------------------------------------------------------------
async function initChat() {
    const res = await fetch(`${API_BASE}/custom/sessions/create`, { method: "POST" });
    if (!res.ok) throw new Error(`Session creation failed (HTTP ${res.status})`);
    const data = await res.json();
    sessionToken = data.session_token;
    sessionId    = data.user_id;

    const wsUrl = `${WS_BASE}/ws?token=${sessionToken}`;

    return new Promise((resolve, reject) => {
        socket = new WebSocket(wsUrl);

        const timeout = setTimeout(() => reject(new Error("Connection timeout")), 10_000);

        socket.onopen = () => {
            clearTimeout(timeout);
            setStatus("online");
            resolve();
        };

        socket.onerror = () => {
            clearTimeout(timeout);
            reject(new Error("WebSocket error"));
        };

        socket.onmessage = handleMessage;

        socket.onclose = () => {
            setStatus("offline");
            removeTyping();
            finalizeStream();
        };
    });
}

// ---------------------------------------------------------------------------
// Message handler
// ---------------------------------------------------------------------------
function handleMessage(event) {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }

    const type = msg.type;

    if (type === "chat_token") {
        const token = msg.content ?? msg.text ?? "";
        if (!streamingBubble) {
            removeTyping();
            streamingContent = "";
            streamingBubble  = createStreamingBubble();
        }
        streamingContent += token;
        updateStreamingBubble(streamingContent);
        return;
    }

    if (type === "chat" || msg.text !== undefined || msg.content !== undefined) {
        const text    = msg.content ?? msg.text ?? "";
        const sources = msg.why?.source_documents ?? msg.sources ?? [];
        removeTyping();
        if (streamingBubble) {
            finalizeStream(text || streamingContent, sources);
        } else if (text) {
            appendMessage("bot", text, sources);
        }
        return;
    }
    // all other message types silently ignored
}

// ---------------------------------------------------------------------------
// Typing indicator
// ---------------------------------------------------------------------------
function showTyping() {
    removeTyping();
    typingEl = document.createElement("div");
    typingEl.className = "message-wrapper bot-wrapper";
    typingEl.setAttribute("aria-label", `${CONFIG.botName} sta scrivendo`);
    typingEl.setAttribute("aria-live", "polite");
    typingEl.innerHTML = `
        <div class="message-header" aria-hidden="true">
            <div class="msg-avatar bot-avatar-small" aria-hidden="true">AI</div>
            <span>${escapeHtml(CONFIG.botName)}</span>
        </div>
        <div class="bubble typing-bubble">
            <span class="typing-dot"></span>
            <span class="typing-dot"></span>
            <span class="typing-dot"></span>
        </div>`;
    ui.chatContainer.appendChild(typingEl);
    scrollToBottom();
}

function removeTyping() {
    if (typingEl) { typingEl.remove(); typingEl = null; }
}

// ---------------------------------------------------------------------------
// Streaming bubble
// ---------------------------------------------------------------------------
function createStreamingBubble() {
    const wrapper = document.createElement("div");
    wrapper.className = "message-wrapper bot-wrapper";
    wrapper.setAttribute("aria-live", "polite");
    wrapper.innerHTML = `
        <div class="message-header" aria-hidden="true">
            <div class="msg-avatar bot-avatar-small" aria-hidden="true">AI</div>
            <span>${escapeHtml(CONFIG.botName)}</span>
        </div>
        <div class="bubble">
            <div class="bubble-content"></div>
        </div>`;
    ui.chatContainer.appendChild(wrapper);
    scrollToBottom();
    return wrapper;
}

function updateStreamingBubble(text) {
    if (!streamingBubble) return;
    const el = streamingBubble.querySelector(".bubble-content");
    if (el) {
        el.innerHTML = renderMarkdown(text) +
            '<span class="cursor-blink" aria-hidden="true">▍</span>';
    }
    scrollToBottom();
}

function finalizeStream(text, sources = []) {
    if (!streamingBubble) return;

    const final     = text || streamingContent;
    const contentEl = streamingBubble.querySelector(".bubble-content");

    if (contentEl && final) {
        contentEl.innerHTML = renderMarkdown(final);
    }

    // Add timestamp next to the sender name in the header
    const timeDiv = document.createElement("span");
    timeDiv.className = "message-time-header";
    timeDiv.setAttribute("aria-label", "Ricevuto alle " + nowStr());
    timeDiv.textContent = nowStr();
    const header = streamingBubble.querySelector(".message-header");
    if (header) header.appendChild(timeDiv);

    if (sources && sources.length > 0) appendSources(streamingBubble, sources);
    appendSuggestedQuestions(streamingBubble);

    streamingBubble.removeAttribute("aria-live");
    streamingBubble  = null;
    streamingContent = "";
    scrollToBottom();
}

// ---------------------------------------------------------------------------
// Message bubble
// ---------------------------------------------------------------------------
function appendMessage(sender, text, sources = []) {
    const isBot   = sender === "bot";
    const wrapper = document.createElement("div");
    wrapper.className = `message-wrapper ${isBot ? "bot-wrapper" : "user-wrapper"}`;
    wrapper.setAttribute("role", "article");
    wrapper.setAttribute("aria-label", isBot
        ? `Messaggio da ${CONFIG.botName}`
        : "Tuo messaggio");

    const header = document.createElement("div");
    header.className = "message-header";
    header.setAttribute("aria-hidden", "true");

    const avatar = document.createElement("div");
    avatar.className = `msg-avatar ${isBot ? "bot-avatar-small" : "user-avatar-small"}`;
    avatar.setAttribute("aria-hidden", "true");
    avatar.innerHTML = isBot
        ? "AI"
        : `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
               <path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/>
           </svg>`;

    const name = document.createElement("span");
    name.textContent = isBot ? CONFIG.botName : "Tu";

    header.appendChild(avatar);
    header.appendChild(name);

    // Timestamp near the sender name
    const headerTime = document.createElement("span");
    headerTime.className = "message-time-header";
    headerTime.setAttribute("aria-label", (isBot ? "Ricevuto" : "Inviato") + " alle " + nowStr());
    headerTime.textContent = nowStr();
    header.appendChild(headerTime);

    const bubble = document.createElement("div");
    bubble.className = "bubble";

    const content = document.createElement("div");
    content.className = "bubble-content";
    content.innerHTML = isBot ? renderMarkdown(text) : escapeHtml(text);

    bubble.appendChild(content);

    wrapper.appendChild(header);
    wrapper.appendChild(bubble);

    if (isBot && sources && sources.length > 0) appendSources(wrapper, sources);
    if (isBot) appendSuggestedQuestions(wrapper);
    ui.chatContainer.appendChild(wrapper);
    scrollToBottom();
}

// ---------------------------------------------------------------------------
// Sources
// ---------------------------------------------------------------------------
function appendSources(container, sources) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className   = "sources-btn";
    btn.textContent = "Fonti";
    btn.setAttribute("aria-expanded", "false");
    btn.setAttribute("aria-controls", "");

    const panelId = "src-panel-" + Date.now();
    const panel = document.createElement("div");
    panel.className = "sources-panel";
    panel.id = panelId;
    panel.setAttribute("role", "list");
    btn.setAttribute("aria-controls", panelId);

    sources.forEach((s) => {
        const item = document.createElement("div");
        item.setAttribute("role", "listitem");
        const a = document.createElement("a");
        const url = s.url ?? "#";
        a.href   = url;
        a.target = "_blank";
        a.rel    = "noopener noreferrer";

        let label = s.label || null;
        if (!label && url !== "#") {
            // No label (e.g. PDF sources) — extract filename from URL path
            try {
                label = decodeURIComponent(new URL(url).pathname.split("/").filter(Boolean).pop() || url);
            } catch { label = (url.split("?")[0]).split("/").filter(Boolean).pop() || url; }
        }
        a.textContent = label || "Fonte";

        item.appendChild(a);
        panel.appendChild(item);
    });

    btn.addEventListener("click", () => {
        const open = panel.classList.toggle("show");
        btn.setAttribute("aria-expanded", String(open));
    });

    // Determine wrapper: if caller passed the wrapper use it, otherwise
    // fallback to bubble.parentElement (bubble may be already inside wrapper).
    let wrapperEl;
    if (container && container.classList && container.classList.contains("message-wrapper")) {
        wrapperEl = container;
    } else {
        wrapperEl = container.parentElement || container;
    }

    wrapperEl.appendChild(btn);
    wrapperEl.appendChild(panel);
}

// ---------------------------------------------------------------------------
// Suggested questions (chips below bot messages)
// ---------------------------------------------------------------------------
function appendSuggestedQuestions(container) {
    if (CONFIG.defaultQuestions.length === 0) return;

    const wrapper = container.classList.contains("message-wrapper")
        ? container
        : container.parentElement || container;

    const chips = document.createElement("div");
    chips.className = "suggested-questions";

    CONFIG.defaultQuestions.forEach((q) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "suggested-chip";
        btn.textContent = q;
        btn.addEventListener("click", () => {
            if (!socket || socket.readyState !== WebSocket.OPEN) return;
            appendMessage("user", q);
            showTyping();
            socket.send(JSON.stringify({ text: q }));
        });
        chips.appendChild(btn);
    });

    wrapper.appendChild(chips);
}

// ---------------------------------------------------------------------------
// Markdown renderer
// ---------------------------------------------------------------------------
/** Render a markdown string to safe HTML. */
function renderMarkdown(raw) {
    if (!raw) return "";
    const str = String(raw);

    // Phase 1 -  extract fenced code blocks before HTML-escaping
    const fenced = [];
    let s = str.replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => {
        const i = fenced.length;
        const esc = code.trim()
            .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
        const cls = lang ? ` class="language-${lang.replace(/[^a-z0-9]/gi, "")}"` : "";
        fenced.push(`<pre><code${cls}>${esc}</code></pre>`);
        return `\x02F${i}\x02`;
    });

    // Phase 2 -  HTML-escape the remaining text
    s = s
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");

    // Phase 3 -  inline code (escaped so it's safe)
    s = s.replace(/`([^`\n]+)`/g, "<code>$1</code>");

    // Phase 4 -  block-level processing (line by line)
    const lines = s.split("\n");
    const out   = [];
    let i = 0;

    while (i < lines.length) {
        const line = lines[i];
        const trimmed = line.trim();

        // Fenced code placeholder (whole line)
        if (/^\x02F\d+\x02$/.test(trimmed)) {
            out.push(trimmed);
            i++;
            continue;
        }

        // Headings  #  ##  ###
        const hm = trimmed.match(/^(#{1,3})\s+(.+)$/);
        if (hm) {
            const level = hm[1].length + 2; // # → h3, ## → h4, ### → h5
            out.push(`<h${level} class="md-heading">${applyInline(hm[2])}</h${level}>`);
            i++;
            continue;
        }

        // Horizontal rule
        if (/^---+$/.test(trimmed)) {
            out.push("<hr>");
            i++;
            continue;
        }

        // Unordered list (collect consecutive items)
        if (/^[-*•]\s/.test(trimmed)) {
            out.push('<ul class="md-list">');
            while (i < lines.length && /^[-*•]\s/.test(lines[i].trim())) {
                out.push(`<li>${applyInline(lines[i].trim().replace(/^[-*•]\s/, ""))}</li>`);
                i++;
            }
            out.push("</ul>");
            continue;
        }

        // Ordered list (collect consecutive items)
        if (/^\d+\.\s/.test(trimmed)) {
            out.push('<ol class="md-list">');
            while (i < lines.length && /^\d+\.\s/.test(lines[i].trim())) {
                out.push(`<li>${applyInline(lines[i].trim().replace(/^\d+\.\s/, ""))}</li>`);
                i++;
            }
            out.push("</ol>");
            continue;
        }

        // Block quote
        if (/^&gt;\s?/.test(trimmed)) {
            out.push(`<blockquote class="md-blockquote">${applyInline(trimmed.replace(/^&gt;\s?/, ""))}</blockquote>`);
            i++;
            continue;
        }

        // Empty line → paragraph break (visually a gap)
        if (trimmed === "") {
            out.push("<br>");
            i++;
            continue;
        }

        // Regular paragraph line
        out.push(`<p class="md-p">${applyInline(trimmed)}</p>`);
        i++;
    }

    // Phase 5 -  restore fenced code blocks
    let result = out.join("\n");
    result = result.replace(/\x02F(\d+)\x02/g, (_, idx) => fenced[parseInt(idx, 10)]);

    return result;
}

/** Apply inline markdown (bold, italic, links) to an already HTML-escaped string. */
function applyInline(text) {
    // Bold  **text**
    text = text.replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>");
    // Italic  *text*  (not adjacent to another *)
    text = text.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, "<em>$1</em>");
    // Strikethrough ~~text~~
    text = text.replace(/~~([^~\n]+)~~/g, "<s>$1</s>");
    // Links  [label](url)  -  allow one level of nested parens in URL (e.g. file_(3).pdf)
    text = text.replace(
        /\[([^\]]+)\]\(((?:[^()]*|\([^()]*\))*)\)/g,
        (_, label, url) => {
            const href = url.replace(/&amp;/g, "&");
            return `<a href="${href}" target="_blank" rel="noopener noreferrer">${label}</a>`;
        }
    );
    return text;
}

function escapeHtml(str) {
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

// ---------------------------------------------------------------------------
// Send message
// ---------------------------------------------------------------------------
function sendMessage() {
    const text = ui.input.value.trim();
    if (!text) return;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
        alert("Non sei connesso. Ricarica la pagina.");
        return;
    }
    appendMessage("user", text);
    ui.input.value = "";
    showTyping();
    socket.send(JSON.stringify({ text: text }));
}

ui.form.addEventListener("submit", function (e) {
    e.preventDefault();
    e.stopPropagation();
    sendMessage();
    return false;
});

ui.sendBtn.addEventListener("click", function (e) {
    e.preventDefault();
    sendMessage();
});

ui.input.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function setStatus(state) {
    if (!ui.statusDot) return;
    if (state === "online") {
        ui.statusDot.textContent = "Online";
        ui.statusDot.classList.remove("offline");
        ui.statusDot.setAttribute("aria-label", "Stato connessione: connesso");
    } else {
        ui.statusDot.textContent = "Offline";
        ui.statusDot.classList.add("offline");
        ui.statusDot.setAttribute("aria-label", "Stato connessione: disconnesso");
    }
}

function nowStr() {
    return new Date().toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
}

function scrollToBottom() {
    ui.chatContainer.scrollTop = ui.chatContainer.scrollHeight;
}
