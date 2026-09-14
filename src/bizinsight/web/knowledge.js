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
  let currentPage = 1;
  let pageCount = 1;
  let requestSerial = 0;
  let searchHandle = null;

  const badgeKinds = {
    "产品文档": ["W", "word"],
    "制度文档": ["P", "pdf"],
    "经营计划": ["X", "sheet"],
    "技术文档": ["P", "pdf"],
    "客户资料": ["W", "word"],
    "行业研究": ["P", "pdf"],
    "内部资料": ["M", "markdown"]
  };

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
    const [letter, kind] = badgeKinds[item.document_type] || badgeKinds["内部资料"];
    const nameCell = document.createElement("td");
    nameCell.innerHTML = `<span class="file-badge ${kind}" aria-hidden="true">${letter}</span>`;
    const title = document.createElement("strong");
    title.textContent = item.title;
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
    const action = document.createElement("button");
    action.type = "button";
    action.className = "row-menu";
    action.setAttribute("aria-label", `查看 ${item.title} 的索引信息`);
    action.textContent = "•••";
    action.addEventListener("click", (event) => showIndexInfo(item, event.currentTarget));
    actionCell.appendChild(action);

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

  loadDocuments();
})();
