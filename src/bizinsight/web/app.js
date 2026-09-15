(() => {
  "use strict";

  const CONVERSATIONS_KEY = "bizinsight.web.conversations.v1";
  const ACTIVE_SESSION_KEY = "bizinsight.web.activeSession";
  const LEGACY_HISTORY_KEY = "bizinsight.web.history";
  const LEGACY_DRAFT_KEY = "bizinsight.web.draft";
  const LEGACY_REPORT_KEY = "bizinsight.web.report";
  const LEGACY_SESSION_KEY = "bizinsight.web.session";
  const MAX_CONVERSATIONS = 30;

  const form = document.getElementById("chatForm");
  const question = document.getElementById("question");
  const sendButton = document.getElementById("sendButton");
  const messageList = document.getElementById("messageList");
  const conversation = document.getElementById("conversation");
  const timer = document.getElementById("timer");
  const runtimeLabel = document.getElementById("runtimeLabel");
  const routeSummary = document.getElementById("routeSummary");
  const reportEmpty = document.getElementById("reportEmpty");
  const reportReady = document.getElementById("reportReady");
  const reportFrame = document.getElementById("reportFrame");
  const openReport = document.getElementById("openReport");
  const reportMeta = document.getElementById("reportMeta");
  const toast = document.getElementById("toast");
  const conversationEmpty = document.getElementById("conversationEmpty");
  const historyList = document.getElementById("conversationHistoryList");
  const newConversationButton = document.getElementById("newConversation");
  const nodes = Array.from(document.querySelectorAll(".agent-node"));
  const timelinePoints = Array.from(document.querySelectorAll(".timeline-point"));
  const timelineLines = Array.from(document.querySelectorAll(".timeline-line"));
  let startedAt = 0;
  let timerHandle = null;
  let busy = false;
  let conversations = [];
  let activeSessionId = "";
  let currentReport = null;
  let currentExecution = null;
  let restoringConversation = false;

  function newSessionId() {
    const random = crypto.randomUUID
      ? crypto.randomUUID().replaceAll("-", "")
      : `${Date.now()}${Math.random().toString(16).slice(2)}`;
    return `web-${random}`;
  }

  function makeConversation(messages = [], id = newSessionId()) {
    const firstQuestion = messages.find((message) => message.kind === "user")?.text?.trim();
    return {
      id,
      title: firstQuestion ? firstQuestion.slice(0, 28) : "新对话",
      updatedAt: Date.now(),
      messages,
      draft: "",
      report: null,
      execution: null
    };
  }

  function loadConversations() {
    try {
      const parsed = JSON.parse(localStorage.getItem(CONVERSATIONS_KEY) || "[]");
      if (Array.isArray(parsed)) {
        conversations = parsed.filter((item) =>
          item && typeof item.id === "string" && Array.isArray(item.messages)
        ).slice(0, MAX_CONVERSATIONS);
      }
    } catch (_) { conversations = []; }

    if (!conversations.length) {
      let legacyMessages = [];
      try {
        const parsed = JSON.parse(sessionStorage.getItem(LEGACY_HISTORY_KEY) || "[]");
        if (Array.isArray(parsed)) legacyMessages = parsed;
      } catch (_) { /* Start with a clean conversation. */ }
      const legacyId = sessionStorage.getItem(LEGACY_SESSION_KEY) || newSessionId();
      const migrated = makeConversation(legacyMessages, legacyId);
      migrated.draft = sessionStorage.getItem(LEGACY_DRAFT_KEY) || "";
      try {
        migrated.report = JSON.parse(sessionStorage.getItem(LEGACY_REPORT_KEY) || "null");
      } catch (_) { migrated.report = null; }
      conversations = [migrated];
    }

    const requestedSession = localStorage.getItem(ACTIVE_SESSION_KEY);
    activeSessionId = conversations.some((item) => item.id === requestedSession)
      ? requestedSession
      : conversations[0].id;
    persistConversations();
  }

  function activeConversation() {
    return conversations.find((item) => item.id === activeSessionId);
  }

  function captureMessages() {
    return Array.from(messageList.querySelectorAll("article.message"))
      .filter((element) => element.dataset.thinking !== "true")
      .map((element) => ({
        kind: element.classList.contains("user") ? "user" : element.classList.contains("error") ? "error" : "assistant",
        text: element.querySelector(".message-text")?.textContent || "",
        route: element.dataset.route || ""
      }));
  }

  function persistConversations() {
    conversations.sort((a, b) => Number(b.updatedAt || 0) - Number(a.updatedAt || 0));
    conversations = conversations.slice(0, MAX_CONVERSATIONS);
    try {
      localStorage.setItem(CONVERSATIONS_KEY, JSON.stringify(conversations));
      localStorage.setItem(ACTIVE_SESSION_KEY, activeSessionId);
    } catch (_) { /* Storage may be unavailable in privacy mode. */ }
  }

  function saveHistory() {
    if (restoringConversation) return;
    const item = activeConversation();
    if (!item) return;
    item.messages = captureMessages();
    const firstQuestion = item.messages.find((message) => message.kind === "user")?.text?.trim();
    item.title = firstQuestion ? firstQuestion.slice(0, 28) : "新对话";
    item.updatedAt = Date.now();
    item.draft = question.value;
    item.report = currentReport;
    item.execution = currentExecution;
    persistConversations();
    renderConversationHistory();
  }

  function saveCurrentWithoutTouch() {
    const item = activeConversation();
    if (!item || restoringConversation) return;
    item.messages = captureMessages();
    item.draft = question.value;
    item.report = currentReport;
    item.execution = currentExecution;
  }

  function saveDraft() {
    saveHistory();
  }

  function historyTime(timestamp) {
    const date = new Date(Number(timestamp) || Date.now());
    const today = new Date();
    if (date.toDateString() === today.toDateString()) {
      return date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
    }
    return date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
  }

  function renderConversationHistory() {
    historyList.replaceChildren();
    const visible = conversations.filter((item) => item.messages.length || item.id === activeSessionId);
    if (!visible.length) {
      const empty = document.createElement("p");
      empty.className = "history-empty";
      empty.textContent = "暂无历史会话";
      historyList.appendChild(empty);
      return;
    }
    visible.forEach((item) => {
      const row = document.createElement("div");
      row.className = `history-item${item.id === activeSessionId ? " active" : ""}`;
      row.dataset.sessionId = item.id;
      row.setAttribute("aria-current", item.id === activeSessionId ? "true" : "false");
      const main = document.createElement("button");
      main.type = "button";
      main.className = "history-item-main";
      main.setAttribute("aria-label", "切换到该会话");
      const title = document.createElement("span");
      title.className = "history-item-title";
      title.textContent = item.title || "新对话";
      const lastMessage = [...item.messages].reverse().find((message) => message.text?.trim());
      const preview = document.createElement("span");
      preview.className = "history-item-preview";
      preview.textContent = `${historyTime(item.updatedAt)} · ${lastMessage?.text || "等待输入问题"}`;
      main.append(title, preview);
      const del = document.createElement("button");
      del.type = "button";
      del.className = "history-item-delete";
      del.title = "删除该会话";
      del.setAttribute("aria-label", "删除该会话");
      del.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M10 11v6M14 11v6" /></svg>`;
      row.append(main, del);
      historyList.appendChild(row);
    });
  }

  function resetReport() {
    currentReport = null;
    reportFrame.removeAttribute("src");
    openReport.removeAttribute("href");
    reportMeta.textContent = "";
    reportReady.hidden = true;
    reportEmpty.hidden = false;
  }

  function restoreConversation() {
    const item = activeConversation();
    if (!item) return;
    restoringConversation = true;
    messageList.replaceChildren();
    conversationEmpty.hidden = Boolean(item.messages.length);
    item.messages.forEach((message) => {
      if (message?.kind && message.text != null) {
        addMessage(message.kind, message.text, message.route || "", false);
      }
    });
    question.value = item.draft || "";
    resetReport();
    if (item.report?.report_url) showReport(item.report, false);
    restoreExecution(item.execution);
    restoringConversation = false;
    renderConversationHistory();
  }

  function switchConversation(sessionIdValue) {
    if (busy || sessionIdValue === activeSessionId) return;
    saveCurrentWithoutTouch();
    activeSessionId = sessionIdValue;
    persistConversations();
    restoreConversation();
    question.focus();
  }

  function createConversation() {
    if (busy) return;
    saveCurrentWithoutTouch();
    const item = makeConversation();
    conversations.unshift(item);
    activeSessionId = item.id;
    persistConversations();
    restoreConversation();
    routeSummary.textContent = "完成后将根据本次运行记录展示真实调用情况";
    question.focus();
  }

  function deleteConversation(sessionId) {
    if (busy) { window.alert("正在执行分析，请稍后再删除"); return; }
    const item = conversations.find((c) => c.id === sessionId);
    if (!item) return;
    const isActive = sessionId === activeSessionId;
    const firstLine = item.messages.find((m) => m.text?.trim())?.text?.trim() || "该会话";
    const label = firstLine.length > 28 ? firstLine.slice(0, 28) + "…" : firstLine;
    const ok = window.confirm(`确定要删除会话「${label}」吗？\n\n此操作无法撤销。`);
    if (!ok) return;
    conversations = conversations.filter((c) => c.id !== sessionId);
    if (isActive) {
      if (conversations.length) {
        activeSessionId = conversations[0].id;
      } else {
        const fresh = makeConversation();
        conversations = [fresh];
        activeSessionId = fresh.id;
      }
      restoreConversation();
    }
    persistConversations();
    renderConversationHistory();
  }

  function sessionId() {
    return activeSessionId;
  }

  function elapsedText(milliseconds) {
    const seconds = Math.max(0, Math.floor(milliseconds / 1000));
    return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  }

  function startTimer() {
    startedAt = performance.now();
    timer.textContent = "00:00";
    runtimeLabel.textContent = "正在运行";
    clearInterval(timerHandle);
    timerHandle = setInterval(() => { timer.textContent = elapsedText(performance.now() - startedAt); }, 1000);
  }

  function stopTimer(measuredDurationMs = null) {
    clearInterval(timerHandle);
    timerHandle = null;
    const duration = Number.isFinite(measuredDurationMs)
      ? measuredDurationMs
      : performance.now() - startedAt;
    timer.textContent = elapsedText(duration);
    runtimeLabel.textContent = "本次运行";
  }

  function addMessage(kind, text, route = "", persist = true) {
    const article = document.createElement("article");
    article.className = `message ${kind}`;
    article.dataset.route = route;
    const avatar = document.createElement("span");
    avatar.className = "message-avatar";
    if (kind === "user") {
      avatar.innerHTML = '<svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg"><path d="M818.2784 878.592V510.9248l-163.1232 94.208V972.8l163.1232-94.208z" fill="#787878"/><path d="M368.8448 251.4432l-163.1232 94.208 449.4336 259.4816 163.1232-94.1568-449.4336-259.5328z" fill="#9A9A9A"/><path d="M205.7216 345.6v367.4112l449.4336 259.4816v-367.36L205.7216 345.6z" fill="#868686"/><path d="M354.1504 798.72l47.9232 27.648V459.008l-47.9232-27.648V798.72zM439.7056 848.0768l47.9232 27.6992V508.3648l-47.9232-27.648v367.36z" fill="#FFFFFF"/><path d="M511.2832 51.2L314.8288 164.6592 527.36 287.3856l196.5056-113.4592L511.2832 51.2z" fill="#787878"/><path d="M314.4192 164.4032v288.1024L527.36 575.4368V287.3344L314.4192 164.4032z" fill="#FFD09C"/><path d="M723.9168 173.824L527.36 287.3344v288.1024l196.5568-113.5104V173.824z" fill="#EFBA84"/><path d="M723.9168 173.824L527.36 287.3344v48.5888l38.2976-21.504v128.8192l60.0064-32.512v37.2736l98.2528-50.5344V173.824zM314.4192 164.4032v57.0368L484.1984 358.912v-48.5888l43.1616 25.6v-48.5888L314.4192 164.4032z" fill="#787878"/></svg>';
    } else if (kind === "error") {
      avatar.textContent = "!";
    } else {
      avatar.innerHTML = '<svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg"><path d="M512 127.0272c-133.4144 0-192.4864 72.1792-192.4864 192.4864V656.384h384.9856V319.5136c-0.0128-120.3072-78.72-192.4864-192.4992-192.4864z" fill="#A67C52"/><path d="M560.128 487.9488h-96.256l-24.0512 96.2432v312.8064h144.3584V584.192z" fill="#DBB59A"/><path d="M223.2576 704.4992c-45.2352 45.2352-48.128 192.4864-48.128 192.4864H512L415.7568 608.256s-169.8944 73.6256-192.4992 96.2432z m577.4848 0C778.112 681.8688 608.256 608.256 608.256 608.256L512 896.9984h336.8576s-2.88-147.264-48.1152-192.4992z" fill="#48A0DC"/><path d="M584.1792 584.192L512 896.9984h24.064l72.1792-168.4352 120.3072-24.064-144.3712-120.3072z m-288.7296 120.3072l120.3072 24.064 72.1792 168.4352H512L439.8208 584.192l-144.3712 120.3072z" fill="#FFFFFF"/><path d="M578.2144 270.976c-18.8288 41.6384-83.7888 72.6016-162.4576 72.6016h-47.7824c1.0496 47.1424 5.44 83.7248 23.7312 120.3072 24.064 48.128 73.1648 96.2432 120.3072 96.2432S608.256 512 632.32 463.8848c21.4272-42.8416 23.7696-85.696 24.0256-145.5232-1.4208-27.0464-52.48-47.3856-78.1312-47.3856z" fill="#F6CBAD"/><path d="M723.6864 283.8912c-21.0176-75.904-107.8016-132.8-211.6864-132.8s-190.6688 56.896-211.6864 132.8c-16.0512 8.8064-28.928 21.504-28.928 35.6224v48.128c0 26.5728 45.6064 48.128 72.1792 48.128v-96.2432c0-66.4448 75.4048-120.3072 168.4352-120.3072s168.4352 53.8624 168.4352 120.3072v48.128c0 51.5712-32.448 95.552-78.0288 112.6656-6.4384-9.8816-17.5872-16.4224-30.2464-16.4224h-48.128c-19.9296 0-36.096 16.1664-36.096 36.096 0 19.9296 16.1664 36.096 36.096 36.096H572.16c3.52 0 6.912-0.512 10.1248-1.4464 70.9888-9.3312 128.0512-62.8608 142.6432-132.0576 15.4752-8.768 27.6992-21.1712 27.6992-34.9184v-48.128c-0.0128-14.144-12.8896-26.8416-28.9408-35.648z" fill="#4D4D4D"/></svg>';
    }
    const body = document.createElement("div");
    body.className = "message-body";
    const meta = document.createElement("div");
    meta.className = "message-meta";
    const name = document.createElement("strong");
    name.textContent = kind === "user" ? "你" : kind === "error" ? "请求未完成" : "BizInsight Agent";
    meta.appendChild(name);
    if (route) {
      const tag = document.createElement("span");
      tag.className = "route-tag";
      tag.textContent = routeLabel(route);
      meta.appendChild(tag);
    }
    const content = document.createElement("p");
    content.className = "message-text";
    content.textContent = text;
    body.append(meta, content);
    article.append(avatar, body);
    messageList.appendChild(article);
    conversationEmpty.hidden = true;
    requestAnimationFrame(() => {
      conversation.scrollTo({ top: conversation.scrollHeight, behavior: "smooth" });
    });
    if (persist) saveHistory();
    return article;
  }

  function addThinking() {
    const article = addMessage("assistant", "", "", false);
    article.dataset.thinking = "true";
    const content = article.querySelector(".message-text");
    const dots = document.createElement("span");
    dots.className = "thinking-dots";
    dots.setAttribute("aria-label", "智能体正在处理");
    dots.innerHTML = "<i></i><i></i><i></i>";
    content.appendChild(dots);
    return article;
  }

  function routeLabel(route) {
    return ({
      general: "普通问答",
      knowledge: "内部 RAG",
      weather: "天气 MCP",
      weather_unavailable: "天气服务降级",
      business_analysis: "经营分析"
    })[route] || "智能路由";
  }

  function resetFlow() {
    nodes.forEach((node) => {
      node.classList.remove("running", "done", "failed");
      node.querySelector(".node-state span").textContent = "本次未调用";
      node.removeAttribute("title");
    });
    timelinePoints.forEach((point) => point.classList.remove("active", "done"));
    timelineLines.forEach((line) => line.classList.remove("done"));
    document.querySelectorAll(".capability-card").forEach((card) => card.classList.remove("active"));
  }

  function beginFlow() {
    currentExecution = null;
    resetFlow();
    routeSummary.textContent = "正在处理，完成后将显示本次运行的真实调用情况";
  }

  function completeFlow(route, flow) {
    resetFlow();
    const flowNodes = Array.isArray(flow?.nodes) ? flow.nodes : [];
    flowNodes.forEach((state) => {
      const node = document.querySelector(`[data-node="${state.key}"]`);
      if (!node) return;
      if (state.status === "success") node.classList.add("done");
      if (state.status === "failed") node.classList.add("failed");
      node.querySelector(".node-state span").textContent = state.summary || "本次未调用";
      if (Number.isFinite(state.duration_ms) && state.duration_ms > 0) {
        node.title = `实际耗时：${elapsedText(state.duration_ms)}`;
      }
    });

    const phaseValues = timelinePoints.map((point) => Boolean(flow?.phases?.[point.dataset.phase]));
    timelinePoints.forEach((point, index) => point.classList.toggle("done", phaseValues[index]));
    timelineLines.forEach((line, index) => {
      line.classList.toggle("done", phaseValues[index] && phaseValues[index + 1]);
    });

    const evidenceTypes = new Set(flowNodes.flatMap((state) => state.evidence_types || []));
    if (route === "knowledge" || evidenceTypes.has("document")) {
      document.querySelector('[data-capability="knowledge"]')?.classList.add("active");
    }
    if (evidenceTypes.has("database") || evidenceTypes.has("calculation")) {
      document.querySelector('[data-capability="data"]')?.classList.add("active");
    }

    if (route === "business_analysis") {
      const called = flowNodes.filter((state) => state.status !== "not_called");
      const succeeded = called.filter((state) => state.status === "success").length;
      const failed = called.filter((state) => state.status === "failed").length;
      routeSummary.textContent = `本次实际调用 ${called.length} 个节点：${succeeded} 个成功，${failed} 个失败`;
      return routeSummary.textContent;
    }
    routeSummary.textContent = ({
      general: "Supervisor 已直接完成本次普通问答",
      knowledge: "Supervisor 已调用内部 RAG 并生成可追溯回答",
      weather: "Supervisor 已通过 Weather MCP 获取实时信息",
      weather_unavailable: "Weather MCP 当前不可用，智能体已返回降级说明"
    })[route] || "智能体已完成本次请求";
    return routeSummary.textContent;
  }

  function restoreExecution(execution) {
    currentExecution = null;
    resetFlow();
    routeSummary.textContent = "完成后将根据本次运行记录展示真实调用情况";
    timer.textContent = "00:00";
    runtimeLabel.textContent = "本次运行";
    if (!execution || typeof execution !== "object") return;

    const route = typeof execution.route === "string" ? execution.route : "";
    const flow = execution.flow && typeof execution.flow === "object" ? execution.flow : null;
    if (flow) completeFlow(route, flow);
    if (typeof execution.summary === "string" && execution.summary.trim()) {
      routeSummary.textContent = execution.summary;
    }
    const duration = Number(execution.duration_ms);
    if (Number.isFinite(duration) && duration >= 0) timer.textContent = elapsedText(duration);
    currentExecution = execution;
  }

  function showReport(data, persist = true) {
    if (!data.report_url || !data.report_url.startsWith("/bizinsight/reports/") || data.report_url.includes("..")) return;
    currentReport = data;
    reportEmpty.hidden = true;
    reportReady.hidden = false;
    reportFrame.src = data.report_url;
    openReport.href = data.report_url;
    const details = [];
    if (data.review_status) details.push(`审核状态：${data.review_status}`);
    if (data.run_id) details.push(`Run ID：${data.run_id}`);
    reportMeta.textContent = details.join(" · ") || "证据审核已完成";
    if (persist) saveHistory();
  }

  function showToast(text) {
    toast.textContent = text;
    toast.hidden = false;
    clearTimeout(showToast.handle);
    showToast.handle = setTimeout(() => { toast.hidden = true; }, 3600);
  }

  async function readError(response) {
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string") return payload.detail;
      if (Array.isArray(payload.detail) && payload.detail[0]?.msg) return payload.detail[0].msg.replace(/^Value error, /, "");
    } catch (_) { /* Return a stable fallback below. */ }
    return "智能体暂时无法完成本次请求，请稍后重试。";
  }

  async function submit() {
    const text = question.value.trim();
    if (!text) {
      showToast("请输入问题后再发送");
      question.focus();
      return;
    }
    addMessage("user", text);
    const thinking = addThinking();
    busy = true;
    sendButton.disabled = true;
    question.disabled = true;
    beginFlow();
    startTimer();
    let measuredDurationMs = null;
    try {
      const response = await fetch("/bizinsight/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text, session_id: sessionId() })
      });
      if (!response.ok) throw new Error(await readError(response));
      const data = await response.json();
      thinking.remove();
      addMessage("assistant", data.answer, data.route);
      measuredDurationMs = data.execution_flow?.duration_ms ?? null;
      const summary = completeFlow(data.route, data.execution_flow);
      const duration = Number.isFinite(measuredDurationMs)
        ? measuredDurationMs
        : performance.now() - startedAt;
      currentExecution = {
        route: data.route || "",
        flow: data.execution_flow || null,
        duration_ms: duration,
        summary
      };
      showReport(data);
      question.value = "";
      saveDraft();
    } catch (error) {
      thinking.remove();
      addMessage("error", error instanceof Error ? error.message : "本次请求未完成，请重试。");
      routeSummary.textContent = "请求未完成；输入内容已保留，可以直接重试";
      document.querySelector('[data-node="supervisor"]').classList.remove("running");
      measuredDurationMs = performance.now() - startedAt;
      currentExecution = {
        route: "",
        flow: null,
        duration_ms: measuredDurationMs,
        summary: routeSummary.textContent
      };
      saveHistory();
    } finally {
      stopTimer(measuredDurationMs);
      sendButton.disabled = false;
      question.disabled = false;
      busy = false;
      question.focus();
    }
  }

  async function loadHealth() {
    const globalStatus = document.getElementById("globalStatus");
    const globalPill = globalStatus.closest(".online-pill");
    try {
      const response = await fetch("/bizinsight/health", { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error("health unavailable");
      const health = await response.json();
      const readiness = {
        model: health.model === "configured",
        business_mcp: health.business_mcp === "enabled",
        knowledge_base: health.knowledge_base === "available",
        external_search: health.external_search === "configured"
      };
      document.querySelectorAll("[data-health]").forEach((pill) => {
        const ready = readiness[pill.dataset.health];
        pill.classList.add(ready ? "ready" : "degraded");
        pill.title = ready ? "已就绪" : "未配置或使用降级模式";
      });
      globalStatus.textContent = health.model === "configured" ? "Online" : "需配置模型";
      globalPill.classList.toggle("degraded", health.model !== "configured");
    } catch (_) {
      globalStatus.textContent = "服务异常";
      globalPill.classList.add("degraded");
    }
  }

  form.addEventListener("submit", (event) => { event.preventDefault(); submit(); });
  question.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.isComposing) { event.preventDefault(); form.requestSubmit(); }
  });
  question.addEventListener("input", saveDraft);
  historyList.addEventListener("click", (event) => {
    const mainBtn = event.target.closest(".history-item-main");
    if (mainBtn) {
      const row = mainBtn.closest(".history-item");
      if (row?.dataset.sessionId) switchConversation(row.dataset.sessionId);
      return;
    }
    const delBtn = event.target.closest(".history-item-delete");
    if (delBtn) {
      const row = delBtn.closest(".history-item");
      if (row?.dataset.sessionId) deleteConversation(row.dataset.sessionId);
    }
  });
  newConversationButton.addEventListener("click", createConversation);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") { saveHistory(); saveDraft(); }
  });
  window.addEventListener("beforeunload", () => { saveHistory(); saveDraft(); });

  loadHealth();
  loadConversations();
  restoreConversation();
  question.focus();
})();
