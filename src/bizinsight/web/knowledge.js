(() => {
  "use strict";

  const search = document.getElementById("knowledgeSearch");
  const rows = document.getElementById("knowledgeRows");
  const state = document.getElementById("knowledgeState");
  const stateTitle = document.getElementById("knowledgeStateTitle");
  const stateText = document.getElementById("knowledgeStateText");
  const retry = document.getElementById("knowledgeRetry");
  const total = document.getElementById("knowledgeTotal");
  const previous = document.getElementById("previousPage");
  const next = document.getElementById("nextPage");
  const pageNumbers = document.getElementById("pageNumbers");
  const pageSize = document.getElementById("pageSize");
  const popover = document.getElementById("knowledgePopover");
  const popoverClose = document.getElementById("popoverClose");
  const health = document.getElementById("knowledgeHealth");
  const healthPill = document.getElementById("knowledgeHealthPill");
  const uploadBtn = document.getElementById("uploadBtn");
  const fileInput = document.getElementById("fileInput");
  let currentPage = 1;
  let pageCount = 1;
  let requestSerial = 0;
  let searchHandle = null;

  const extKinds = {
    ".md": ["M", "markdown"],
    ".markdown": ["M", "markdown"],
  };

  function badgeForPath(sourcePath) {
    const ext = (sourcePath || "").split(".").pop();
    const key = ext ? "." + ext.toLowerCase() : ".md";
    return extKinds[key] || ["M", "markdown"];
  }

  function setLoading() {
    state.hidden = true;
    rows.replaceChildren();
    for (let index = 0; index < 6; index += 1) {
      const row = document.createElement("tr");
      row.className = "skeleton-row";
      row.innerHTML = "<td><i></i></td><td><i></i></td><td><i></i></td><td><i></i></td><td><i></i></td>";
      rows.appendChild(row);
    }
  }

  function showState(title, text, canRetry = false) {
    rows.replaceChildren();
    stateTitle.textContent = title;
    stateText.textContent = text;
    retry.hidden = !canRetry;
    state.hidden = false;
  }

  function documentRow(item) {
    const row = document.createElement("tr");
    const [letter, kind] = badgeForPath(item.source_path);
    const nameCell = document.createElement("td");
    nameCell.innerHTML = `<span class="file-badge ${kind}" aria-hidden="true">${letter}</span>`;
    const title = document.createElement("button");
    title.type = "button";
    title.className = "document-title-link";
    title.textContent = item.title;
    title.title = "点击下载";
    title.addEventListener("click", async () => {
      const url = `/bizinsight/knowledge/documents/${encodeURIComponent(item.document_id)}/download`;
      try {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error("下载失败");
        const blob = await resp.blob();
        const blobUrl = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = blobUrl;
        // 优先使用后端 Content-Disposition 里的真实文件名
        const cd = resp.headers.get("Content-Disposition") || "";
        const match = cd.match(/filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/i);
        let fname = match ? match[1].replace(/['"]/g, "") : "";
        if (!fname) {
          const dotIdx = item.source_path.lastIndexOf(".");
          const ext = dotIdx >= 0 ? item.source_path.substring(dotIdx) : ".md";
          fname = item.title + ext;
        }
        a.download = fname;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(blobUrl);
      } catch (err) {
        alert(err.message || "下载失败，请重启服务后重试");
      }
    });
    nameCell.appendChild(title);

    const typeCell = document.createElement("td");
    const type = document.createElement("span");
    type.className = "document-type";
    type.textContent = item.document_type;
    typeCell.appendChild(type);

    const statusCell = document.createElement("td");
    statusCell.innerHTML = '<span class="document-status"><i>✓</i> 已就绪</span>';

    const dateCell = document.createElement("td");
    dateCell.className = "document-date";
    dateCell.textContent = item.updated_at;

    const actionCell = document.createElement("td");
    actionCell.className = "document-action";

    // Row-menu (info) button
    const action = document.createElement("button");
    action.type = "button";
    action.className = "row-menu";
    action.setAttribute("aria-label", `查看 ${item.title} 的索引信息`);
    action.textContent = "•••";
    action.addEventListener("click", (event) => showIndexInfo(item, event.currentTarget));
    actionCell.appendChild(action);

    // Delete button
    const del = document.createElement("button");
    del.type = "button";
    del.className = "row-delete";
    del.setAttribute("aria-label", `删除 ${item.title}`);
    del.title = "删除文档（同步重建检索索引）";
    del.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18M9 6V4.5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2V6m3 0v13.5a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V6" /><path d="M10 11v6M14 11v6" /></svg>`;
    del.addEventListener("click", async () => {
      const ok = confirm(`确定删除「${item.title}」吗？\n\n删除后会自动重建 BM25 + 向量索引，该文档将不再参与 Agent 的知识库检索。此操作不可撤销。`);
      if (!ok) return;
      del.disabled = true;
      del.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true" class="spin"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-dasharray="42" stroke-dashoffset="14"/></svg>`;
      try {
        const resp = await fetch(`/bizinsight/knowledge/documents/${encodeURIComponent(item.document_id)}`, {
          method: "DELETE",
        });
        const body = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(body.detail || `删除失败 (${resp.status})`);
        await loadDocuments(currentPage);
      } catch (err) {
        alert(err.message || "删除失败");
        del.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18M9 6V4.5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2V6m3 0v13.5a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V6" /><path d="M10 11v6M14 11v6" /></svg>`;
        del.disabled = false;
      }
    });
    actionCell.appendChild(del);

    row.append(nameCell, typeCell, statusCell, dateCell, actionCell);
    return row;
  }

  function showIndexInfo(item, anchor) {
    document.getElementById("popoverTitle").textContent = item.title;
    document.getElementById("popoverId").textContent = item.document_id;
    document.getElementById("popoverSource").textContent = item.source_path;
    popover.hidden = false;
    const rect = anchor.getBoundingClientRect();
    popover.style.top = `${Math.min(window.innerHeight - popover.offsetHeight - 16, rect.bottom + 8)}px`;
    popover.style.left = `${Math.max(16, rect.right - popover.offsetWidth)}px`;
    popoverClose.focus();
  }

  function renderPagination(page, pages) {
    currentPage = page;
    pageCount = pages;
    previous.disabled = page <= 1;
    next.disabled = page >= pages;
    pageNumbers.replaceChildren();
    const first = Math.max(1, Math.min(page - 1, pages - 2));
    const last = Math.min(pages, Math.max(3, page + 1));
    for (let value = first; value <= last; value += 1) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = String(value);
      button.className = value === page ? "active" : "";
      if (value === page) button.setAttribute("aria-current", "page");
      button.addEventListener("click", () => loadDocuments(value));
      pageNumbers.appendChild(button);
    }
  }

  async function loadDocuments(page = 1) {
    const serial = ++requestSerial;
    setLoading();
    const parameters = new URLSearchParams({
      query: search.value.trim(),
      page: String(page),
      page_size: pageSize.value
    });
    try {
      const response = await fetch(`/bizinsight/knowledge/documents?${parameters}`, { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error("knowledge unavailable");
      const data = await response.json();
      if (serial !== requestSerial) return;
      health.textContent = "索引已就绪";
      healthPill.classList.remove("degraded");
      rows.replaceChildren();
      state.hidden = true;
      total.textContent = String(data.total);
      if (!data.items.length) {
        showState("暂无匹配文档", "请尝试其他文档名称或类型。");
      } else {
        data.items.forEach((item) => rows.appendChild(documentRow(item)));
      }
      renderPagination(data.page, data.pages);
    } catch (_) {
      if (serial !== requestSerial) return;
      health.textContent = "索引不可用";
      healthPill.classList.add("degraded");
      total.textContent = "—";
      renderPagination(1, 1);
      showState("知识库暂不可用", "索引没有成功加载，请检查服务状态后重试。", true);
    }
  }

  search.addEventListener("input", () => {
    clearTimeout(searchHandle);
    searchHandle = setTimeout(() => loadDocuments(1), 240);
  });
  search.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      search.value = "";
      loadDocuments(1);
    }
  });
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      search.focus();
    }
    if (event.key === "Escape" && !popover.hidden) popover.hidden = true;
  });
  previous.addEventListener("click", () => loadDocuments(currentPage - 1));
  next.addEventListener("click", () => loadDocuments(currentPage + 1));
  pageSize.addEventListener("change", () => loadDocuments(1));
  retry.addEventListener("click", () => loadDocuments(currentPage));
  popoverClose.addEventListener("click", () => { popover.hidden = true; });
  document.addEventListener("pointerdown", (event) => {
    if (!popover.hidden && !popover.contains(event.target) && !event.target.closest(".row-menu")) popover.hidden = true;
  });

  // Upload button logic
  uploadBtn.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", async () => {
    const file = fileInput.files?.[0];
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);
    uploadBtn.disabled = true;
    uploadBtn.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true" class="spin"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-dasharray="42" stroke-dashoffset="14"/></svg> 上传并重建索引中...`;
    try {
      const resp = await fetch("/bizinsight/knowledge/documents/upload", {
        method: "POST",
        body: formData,
      });
      const body = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        throw new Error(body.detail || `上传失败 (${resp.status})`);
      }
      await loadDocuments(1);
      const v = body.vector_status;
      let okText;
      if (v === "ok") {
        okText = `上传成功 · BM25 + 向量重建完成 ✓`;
      } else if (v === "skipped") {
        okText = `上传成功 · BM25 已重建，向量重建未启用（未配置 API Key）`;
      } else if (v === "degraded") {
        okText = `上传成功 · BM25 已重建，向量重建跳过（${body.vector_error || "未知错误"}）`;
      } else {
        okText = `上传成功 ✓`;
      }
      uploadBtn.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4m0 0-4 4m4-4 4 4M4 18v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" /></svg> ${okText}`;
      setTimeout(() => {
        uploadBtn.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4m0 0-4 4m4-4 4 4M4 18v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" /></svg> 上传文件`;
      }, 3500);
    } catch (err) {
      alert(err.message || "上传失败");
      uploadBtn.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4m0 0-4 4m4-4 4 4M4 18v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" /></svg> 上传文件`;
    } finally {
      uploadBtn.disabled = false;
      fileInput.value = "";
    }
  });

  loadDocuments();
})();
