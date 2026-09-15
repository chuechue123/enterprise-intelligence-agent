(() => {
  "use strict";

  const list = document.getElementById("reportList");
  const frame = document.getElementById("reportFrame");
  const empty = document.getElementById("previewEmpty");
  const downloadMd = document.getElementById("downloadReportMd");
  const previewToolbar = downloadMd?.parentElement;
  const refreshBtn = document.getElementById("refreshReports");
  let reports = [];
  let activeRun = null;

  function sanitizeTitle(raw) {
    const s = (raw || "").trim();
    if (!s) return "未命名报告";
    return s.replace(/\s+/g, " ").slice(0, 80);
  }

  function renderList() {
    list.replaceChildren();
    if (!reports.length) {
      list.innerHTML = `<p class="sidebar-empty">暂无已生成的报告<span class="hint">完成一次分析后，报告会出现在这里</span></p>`;
      return;
    }
    for (const item of reports) {
      const row = document.createElement("div");
      row.className = "report-item" + (activeRun === item.run_id ? " active" : "");
      row.dataset.runId = item.run_id;
      row.innerHTML = `
        <button type="button" class="report-item-main" aria-label="选择报告">
          <svg class="report-item-icon" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M14 3.5H6a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5z" />
            <path d="M14 3.5V7h3.5M8 12h8M8 16h5" />
          </svg>
          <div class="report-item-body">
            <span class="report-item-title">${sanitizeTitle(item.title)}</span>
            <span class="report-item-excerpt">${sanitizeTitle(item.excerpt || item.run_id)}</span>
            <span class="report-item-meta">
              <span>${item.generated_at}</span>
              <span class="chip-done"><i></i>已完成</span>
            </span>
          </div>
        </button>
        <button type="button" class="report-item-delete" title="删除报告" aria-label="删除报告">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M10 11v6M14 11v6" />
          </svg>
        </button>
      `;
      row.querySelector(".report-item-main").addEventListener("click", (e) => {
        e.stopPropagation();
        selectReport(item);
      });
      row.querySelector(".report-item-delete").addEventListener("click", (e) => {
        e.stopPropagation();
        confirmDelete(item);
      });
      list.appendChild(row);
    }
  }

  function selectReport(item) {
    activeRun = item.run_id;
    renderList();
    empty.hidden = true;
    frame.hidden = false;
    frame.src = item.html_url;
    downloadMd.href = item.md_url;
    downloadMd.download = `${item.run_id}-report.md`;
    if (previewToolbar) previewToolbar.hidden = false;
  }

  async function confirmDelete(item) {
    const ok = window.confirm(`确定要删除这份报告吗？\n\n标题：${item.title}\n时间：${item.generated_at}\n\n删除后无法恢复。`);
    if (!ok) return;
    const prevActive = activeRun;
    try {
      const resp = await fetch(`/bizinsight/reports/${encodeURIComponent(item.run_id)}`, { method: "DELETE" });
      if (!resp.ok) {
        let detail = "删除失败";
        try { detail = (await resp.json()).detail || detail; } catch (_) {}
        window.alert(detail);
        return;
      }
      // Refresh list; if the deleted one was active, clear preview.
      reports = reports.filter((r) => r.run_id !== item.run_id);
      if (prevActive === item.run_id) {
        activeRun = null;
        frame.hidden = true;
        frame.src = "";
        empty.hidden = false;
        if (previewToolbar) previewToolbar.hidden = true;
      }
      renderList();
    } catch (err) {
      window.alert(`删除请求失败：${err instanceof Error ? err.message : err}`);
    }
  }

  async function loadReports() {
    list.replaceChildren();
    const loading = document.createElement("p");
    loading.className = "sidebar-empty";
    loading.textContent = "加载中...";
    list.appendChild(loading);
    try {
      const resp = await fetch("/bizinsight/reports", { headers: { Accept: "application/json" } });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      reports = await resp.json();
    } catch (err) {
      reports = [];
    }
    renderList();
  }

  refreshBtn?.addEventListener("click", loadReports);

  loadReports();
})();
