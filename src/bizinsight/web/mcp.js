(() => {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const list = byId("mcpList");
  const empty = byId("mcpEmpty");
  const dialog = byId("addServerDialog");
  const form = byId("addServerForm");
  const probeButton = byId("probeBtn");
  const saveButton = byId("saveBtn");
  const probeResult = byId("probeResult");
  const formError = byId("formError");
  const transportSelect = byId("transportSelect");
  let registry = { servers: [], targets: [], summary: {} };
  let probedFingerprint = null;

  const TRANSPORTS = {
    stdio: "stdio",
    streamable_http: "Streamable HTTP",
    sse: "SSE",
  };

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function button(text, className, action) {
    const node = el("button", className, text);
    node.type = "button";
    node.addEventListener("click", action);
    return node;
  }

  function errorDetail(payload, fallback) {
    const detail = payload && payload.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length) {
      return detail.map((item) => item.msg || "参数无效").join("；");
    }
    return fallback;
  }

  async function request(url, options = {}) {
    const response = await fetch(url, {
      headers: { Accept: "application/json", ...(options.headers || {}) },
      ...options,
    });
    let payload = null;
    try { payload = await response.json(); } catch (_) { /* no body */ }
    if (!response.ok) throw new Error(errorDetail(payload, `请求失败（HTTP ${response.status}）`));
    return payload;
  }

  function toast(message, tone = "ok") {
    const node = byId("toast");
    node.textContent = message;
    node.dataset.tone = tone;
    node.hidden = false;
    window.clearTimeout(toast.timer);
    toast.timer = window.setTimeout(() => { node.hidden = true; }, 3600);
  }

  function showSessionNotice(response) {
    if (!response || !response.requires_new_session) return;
    byId("sessionNoticeText").textContent =
      `已有 ${response.affected_sessions} 个会话仍使用旧 Toolkit；请新建会话应用本次配置。`;
    byId("sessionNotice").hidden = false;
  }

  function statusInfo(server) {
    if (!server.enabled) return ["disabled", "已停用"];
    if (server.runtime_status === "on_demand") return ["ondemand", "按需连接"];
    const state = server.last_probe && server.last_probe.status;
    if (state === "ok") return ["ok", "探测正常"];
    if (state === "error") return ["error", "连接异常"];
    return ["never", "尚未探测"];
  }

  function renderSummary() {
    const summary = registry.summary || {};
    const fields = {
      summaryConfigured: summary.configured,
      summaryHealthy: summary.healthy,
      summaryTools: summary.tools,
      summarySessions: summary.active_sessions,
    };
    for (const [id, value] of Object.entries(fields)) {
      const node = byId(id);
      if (node) node.textContent = value ?? 0;
    }
    const failed = registry.servers.some((server) => statusInfo(server)[0] === "error");
    const global = byId("globalStatus");
    global.classList.toggle("has-error", failed);
    global.lastElementChild.textContent = failed ? "部分 MCP 异常" : "MCP 注册表已就绪";
  }

  function renderWiring() {
    const map = byId("wiringMap");
    map.replaceChildren();
    for (const target of registry.targets) {
      const row = el("article", "mcp-wire-row");
      const agent = el("div", "mcp-agent-node");
      agent.append(el("span", "mcp-node-type", "AGENT"), el("strong", "", target.label));
      const connector = el("div", "mcp-wire-line");
      connector.setAttribute("aria-hidden", "true");
      const toolkit = el("div", "mcp-toolkit-node");
      toolkit.append(el("span", "mcp-node-type", "TOOLKIT"), el("strong", "", "AgentScope Toolkit"));
      const servers = el("div", "mcp-wire-servers");
      const assigned = registry.servers.filter((server) =>
        (server.targets || []).includes(target.id) && server.enabled
      );
      if (!assigned.length) {
        servers.append(el("span", "mcp-wire-empty", "未授权 MCP"));
      } else {
        for (const server of assigned) {
          const [tone] = statusInfo(server);
          const chip = el("button", `mcp-wire-server ${tone}`);
          chip.type = "button";
          chip.textContent = server.display_name || server.name;
          chip.title = `${(server.tools || []).length} 个工具`;
          chip.addEventListener("click", () => {
            document.querySelector(`[data-server-name="${CSS.escape(server.name)}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
          });
          servers.append(chip);
        }
      }
      row.append(agent, connector, toolkit, servers);
      map.append(row);
    }
  }

  function createToolList(server) {
    const box = el("div", "mcp-tools");
    const title = el("div", "mcp-tools-title");
    title.append(el("strong", "", "已发现工具"), el("span", "", `${(server.tools || []).length} 个`));
    box.append(title);
    const tools = server.tools || [];
    if (!tools.length) {
      box.append(el("p", "mcp-no-tools", "尚无工具快照，请运行连接探测。"));
      return box;
    }
    const grid = el("div", "mcp-tool-grid");
    for (const tool of tools) {
      const item = el("div", "mcp-tool-item");
      item.append(el("code", "", tool.name || String(tool)));
      if (tool.description) item.append(el("p", "", tool.description));
      grid.append(item);
    }
    box.append(grid);
    return box;
  }

  function createTargetEditor(server) {
    const details = el("details", "mcp-target-editor");
    details.append(el("summary", "", "调整 Agent 授权"));
    const options = el("div", "mcp-target-options");
    for (const target of registry.targets) {
      const label = el("label");
      const input = document.createElement("input");
      input.type = "checkbox";
      input.value = target.id;
      input.checked = (server.targets || []).includes(target.id);
      label.append(input, el("span", "", target.label));
      options.append(label);
    }
    const save = button("保存授权", "mcp-mini-primary", async () => {
      const targets = [...options.querySelectorAll("input:checked")].map((item) => item.value);
      if (!targets.length) return toast("至少选择一个 Agent", "error");
      save.disabled = true;
      try {
        const response = await request(`/bizinsight/mcp/servers/${encodeURIComponent(server.name)}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ targets }),
        });
        showSessionNotice(response);
        toast("Agent 授权已保存");
        await load();
      } catch (error) {
        toast(error.message, "error");
      } finally { save.disabled = false; }
    });
    details.append(options, save);
    return details;
  }

  function renderServers() {
    list.replaceChildren();
    empty.hidden = registry.servers.length > 0;
    if (!registry.servers.length) empty.textContent = "还没有 MCP Server，添加一个并发现它的工具。";
    for (const server of registry.servers) {
      const [tone, status] = statusInfo(server);
      const card = el("article", `mcp-server-card ${tone}`);
      card.dataset.serverName = server.name;
      const top = el("div", "mcp-server-top");
      const identity = el("div", "mcp-server-identity");
      const type = el("span", `mcp-kind ${server.type}`, server.type === "builtin" ? "内置" : "自定义");
      const nameBox = el("div");
      nameBox.append(el("h3", "", server.display_name || server.name), el("code", "", server.name));
      identity.append(type, nameBox);
      const badge = el("span", `mcp-state ${tone}`);
      badge.append(el("i"), document.createTextNode(status));
      const topActions = el("div", "mcp-server-top-actions");
      topActions.append(badge);
      if (server.type === "custom") {
        const deleteButton = button("删除", "mcp-delete-visible", () => removeServer(server));
        deleteButton.setAttribute("aria-label", `删除 ${server.display_name || server.name}`);
        topActions.append(deleteButton);
      }
      top.append(identity, topActions);

      const description = el("p", "mcp-server-description", server.description || "未提供用途说明");
      const meta = el("div", "mcp-server-meta");
      meta.append(
        el("span", "", TRANSPORTS[server.transport] || server.transport || "stdio"),
        el("code", "", server.connection || "—"),
        el("span", "", `${(server.targets || []).length} 个 Agent`)
      );
      if (server.last_probe && server.last_probe.duration_ms != null) {
        meta.append(el("span", "", `${server.last_probe.duration_ms} ms`));
      }
      if (server.last_probe && server.last_probe.error) {
        card.append(top, description, meta, el("p", "mcp-server-error", server.last_probe.error));
      } else {
        card.append(top, description, meta);
      }

      const targetLine = el("div", "mcp-target-line");
      targetLine.append(el("span", "", "授权"));
      for (const id of server.targets || []) {
        const label = registry.targets.find((item) => item.id === id)?.label || id;
        targetLine.append(el("b", "", label));
      }
      card.append(targetLine, createToolList(server));

      if (server.type === "custom") {
        const bottom = el("div", "mcp-server-actions");
        bottom.append(createTargetEditor(server));
        const controls = el("div");
        controls.append(
          button("重新探测", "mcp-action", () => reprobe(server)),
          button(server.enabled ? "停用" : "启用", "mcp-action", () => toggleServer(server))
        );
        bottom.append(controls);
        card.append(bottom);
      }
      list.append(card);
    }
  }

  async function load() {
    empty.hidden = false;
    empty.textContent = "正在读取 MCP 注册表…";
    try {
      registry = await request("/bizinsight/mcp/servers");
      renderSummary();
      renderWiring();
      renderServers();
    } catch (error) {
      list.replaceChildren();
      empty.hidden = false;
      empty.textContent = `注册表不可用：${error.message}`;
      byId("globalStatus").classList.add("has-error");
      byId("globalStatus").lastElementChild.textContent = "MCP 注册表异常";
    }
  }

  async function reprobe(server) {
    toast(`正在连接 ${server.display_name || server.name}…`);
    try {
      const response = await request(`/bizinsight/mcp/servers/${encodeURIComponent(server.name)}/probe`, { method: "POST" });
      toast(response.probe.ok ? `探测成功，发现 ${response.probe.tools.length} 个工具` : response.probe.error, response.probe.ok ? "ok" : "error");
      await load();
    } catch (error) { toast(error.message, "error"); }
  }

  async function toggleServer(server) {
    try {
      const response = await request(`/bizinsight/mcp/servers/${encodeURIComponent(server.name)}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !server.enabled }),
      });
      showSessionNotice(response);
      toast(server.enabled ? "MCP 已停用" : "MCP 已启用");
      await load();
    } catch (error) { toast(error.message, "error"); }
  }

  async function removeServer(server) {
    if (!window.confirm(`删除「${server.display_name || server.name}」及其授权配置？`)) return;
    try {
      const response = await request(`/bizinsight/mcp/servers/${encodeURIComponent(server.name)}`, { method: "DELETE" });
      showSessionNotice(response);
      toast("MCP Server 已删除");
      await load();
    } catch (error) { toast(error.message, "error"); }
  }

  function formPayload() {
    const data = new FormData(form);
    return {
      name: String(data.get("name") || "").trim(),
      display_name: String(data.get("display_name") || "").trim(),
      description: String(data.get("description") || "").trim(),
      transport: String(data.get("transport") || "stdio"),
      command: String(data.get("command") || "").trim() || null,
      args: String(data.get("args") || "").split(/\r?\n/).map((item) => item.trim()).filter(Boolean),
      url: String(data.get("url") || "").trim() || null,
      api_key_env: String(data.get("api_key_env") || "").trim() || null,
      targets: data.getAll("targets"),
    };
  }

  function fingerprint(payload) { return JSON.stringify(payload); }

  function resetProbe() {
    probedFingerprint = null;
    saveButton.disabled = true;
    probeResult.hidden = true;
    formError.hidden = true;
    byId("saveHint").textContent = "请先测试连接，成功后即可保存";
    document.querySelectorAll(".mcp-steps li").forEach((item, index) => item.classList.toggle("active", index === 0));
  }

  function syncTransport() {
    const stdio = transportSelect.value === "stdio";
    document.querySelectorAll(".stdio-field").forEach((node) => { node.hidden = !stdio; });
    document.querySelectorAll(".http-field").forEach((node) => { node.hidden = stdio; });
    form.command.required = stdio;
    form.url.required = !stdio;
    resetProbe();
  }

  probeButton.addEventListener("click", async () => {
    if (!form.reportValidity()) return;
    const payload = formPayload();
    if (!payload.targets.length) {
      formError.textContent = "至少授权给一个 Agent";
      formError.hidden = false;
      return;
    }
    probeButton.disabled = true;
    probeButton.textContent = "正在连接并发现工具…";
    formError.hidden = true;
    try {
      const result = await request("/bizinsight/mcp/probe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      probeResult.replaceChildren();
      if (!result.ok) throw new Error(result.error || "连接失败");
      probeResult.append(el("strong", "", `连接成功 · ${result.duration_ms} ms`));
      const names = el("div", "mcp-probe-tools");
      for (const tool of result.tools) names.append(el("code", "", tool.name));
      if (!result.tools.length) names.append(el("span", "", "Server 未返回工具"));
      probeResult.append(names);
      probeResult.hidden = false;
      probedFingerprint = fingerprint(payload);
      saveButton.disabled = false;
      byId("saveHint").textContent = `已验证 ${result.tools.length} 个工具，可以保存`;
      document.querySelectorAll(".mcp-steps li").forEach((item, index) => item.classList.toggle("active", index < 3));
    } catch (error) {
      formError.textContent = error.message;
      formError.hidden = false;
      saveButton.disabled = true;
    } finally {
      probeButton.disabled = false;
      probeButton.textContent = "测试连接并发现工具";
    }
  });

  form.addEventListener("input", () => {
    if (probedFingerprint && fingerprint(formPayload()) !== probedFingerprint) resetProbe();
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = formPayload();
    if (!probedFingerprint || fingerprint(payload) !== probedFingerprint) return resetProbe();
    saveButton.disabled = true;
    saveButton.textContent = "正在验证并保存…";
    try {
      const response = await request("/bizinsight/mcp/servers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      showSessionNotice(response);
      dialog.close();
      form.reset();
      syncTransport();
      toast("MCP 已保存，新会话将按授权加载工具");
      await load();
    } catch (error) {
      formError.textContent = error.message;
      formError.hidden = false;
    } finally {
      saveButton.textContent = "保存并添加";
      saveButton.disabled = !probedFingerprint;
    }
  });

  byId("addServerBtn").addEventListener("click", () => {
    form.reset();
    syncTransport();
    dialog.showModal();
    form.name.focus();
  });
  byId("cancelAddBtn").addEventListener("click", () => dialog.close());
  byId("refreshBtn").addEventListener("click", load);
  transportSelect.addEventListener("change", syncTransport);
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) dialog.close();
  });

  syncTransport();
  load();
})();
