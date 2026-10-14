/* 个人任务看板 - 前端逻辑（原生 JS，无框架） */
(function () {
  "use strict";

  var state = {
    statuses: [],
    tasks: [],
    logs: [],
    view: "board",   // board | archive | logs
    search: "",
    logType: "all",
    logRange: "all",    // 日志时间范围：all | today | 7d | 30d
    logKeyword: "",     // 日志变更内容关键词
    expandedCols: {} // 单列模式下已展开的栏目（按状态名）
  };

  // 自动更新：定时轮询服务端的修订标记，仅在有变化时才重新拉取并渲染
  var POLL_INTERVAL = 3000; // 轮询间隔（毫秒）
  var lastRev = null;       // 最近一次已知的数据修订标记
  var pollBusy = false;     // 轮询请求进行中标志，避免请求重叠

  var STATUS_COLORS = ["#667085", "#2f6fed", "#d97706", "#16a34a", "#7c3aed", "#db2777", "#0891b2", "#ca8a04"];
  var LOG_TYPE_META = {
    create: { label: "新增", cls: "t-create" },
    view: { label: "查看", cls: "t-view" },
    update: { label: "修改", cls: "t-update" },
    archive: { label: "归档", cls: "t-archive" },
    restore: { label: "恢复", cls: "t-restore" },
    progress: { label: "进展", cls: "t-update" },
    delete: { label: "删除", cls: "t-delete" }
  };
  var FIELD_LABEL = { title: "标题", goal: "目标", note: "备注", status: "状态" };
  var LOG_RANGES = [
    ["all", "全部时间"],
    ["today", "今天"],
    ["7d", "最近 7 天"],
    ["30d", "最近 30 天"]
  ];

  // ---------- 基础工具 ----------

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function nl2br(value) {
    return esc(value).replace(/\n/g, "<br>");
  }

  function oneLine(value) {
    return esc(String(value == null ? "" : value).replace(/\s*\n\s*/g, " "));
  }

  function pad(n) { return n < 10 ? "0" + n : "" + n; }

  function fmtShort(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return pad(d.getMonth() + 1) + "-" + pad(d.getDate()) + " " + pad(d.getHours()) + ":" + pad(d.getMinutes());
  }

  function fmtFull(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
      " " + pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
  }

  function colorFor(index) {
    return STATUS_COLORS[index % STATUS_COLORS.length];
  }

  function val(id) {
    var el = document.getElementById(id);
    return el ? el.value : "";
  }

  function taskById(id) {
    for (var i = 0; i < state.tasks.length; i++) {
      if (state.tasks[i].id === id) return state.tasks[i];
    }
    return null;
  }

  function matchSearch(task) {
    if (!state.search) return true;
    return (task.title || "").toLowerCase().indexOf(state.search.toLowerCase()) >= 0;
  }

  // ---------- 网络 ----------

  function api(path, method, body) {
    var opts = { method: method || "GET" };
    if (opts.method !== "GET") opts.headers = { "X-Board-Request": "1" };
    if (body !== undefined) {
      opts.headers = opts.headers || {};
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    return fetch(path, opts).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) {
        if (!res.ok) {
          throw new Error((data && data.error) || ("请求失败（HTTP " + res.status + "）"));
        }
        return data;
      });
    });
  }

  function loadServerData() {
    return Promise.all([api("/api/state"), api("/api/logs"), api("/api/rev")]);
  }

  function applyServerData(results) {
    state.statuses = results[0].statuses || [];
    state.tasks = results[0].tasks || [];
    state.logs = results[1].logs || [];
    if (results[2] && results[2].rev != null) lastRev = results[2].rev;
  }

  function refresh() {
    return loadServerData().then(function (results) {
      applyServerData(results);
      render();
    }).catch(function (err) {
      toast(err.message, true);
    });
  }

  function syncFromServer() {
    // 轮询触发的静默同步：失败不打扰用户；日志页只刷新列表，避免打断筛选输入
    return loadServerData().then(function (results) {
      applyServerData(results);
      if (state.view === "logs" && document.getElementById("logsList")) {
        renderTabs();
        updateLogsList();
      } else {
        render();
      }
    }).catch(function () { /* 服务暂时不可用，等待下次轮询重试 */ });
  }

  function pollTick() {
    if (document.hidden || pollBusy) return;
    pollBusy = true;
    api("/api/rev").then(function (result) {
      if (result && result.rev != null && result.rev !== lastRev) {
        return syncFromServer();
      }
    }).catch(function () { /* 静默忽略，下次轮询重试 */ })
      .then(function () { pollBusy = false; });
  }

  // ---------- Toast ----------

  function toast(message, isError) {
    var root = document.getElementById("toastRoot");
    var el = document.createElement("div");
    el.className = "toast" + (isError ? " toast-error" : "");
    el.textContent = message;
    root.appendChild(el);
    setTimeout(function () { el.classList.add("toast-hide"); }, 2600);
    setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 3300);
  }

  // ---------- 渲染 ----------

  function render() {
    renderTabs();
    var main = document.getElementById("main");
    if (state.view === "archive") {
      main.innerHTML = renderArchive();
    } else if (state.view === "logs") {
      main.innerHTML = renderLogs();
    } else {
      main.innerHTML = renderBoard();
    }
  }

  function renderTabs() {
    var tabs = document.querySelectorAll(".tab");
    for (var i = 0; i < tabs.length; i++) {
      var el = tabs[i];
      el.classList.toggle("active", el.getAttribute("data-view") === state.view);
    }
    var active = state.tasks.filter(function (t) { return !t.archived; }).length;
    var archived = state.tasks.filter(function (t) { return t.archived; }).length;
    document.getElementById("countBoard").textContent = active;
    document.getElementById("countArchive").textContent = archived;
    document.getElementById("countLogs").textContent = state.logs.length;
  }

  function renderBoard() {
    var columns = state.statuses.map(function (name, index) {
      var list = state.tasks.filter(function (t) {
        return !t.archived && t.status === name && matchSearch(t);
      }).sort(function (a, b) {
        return (b.updatedAt || "").localeCompare(a.updatedAt || "");
      });
      var cards = list.map(renderCard).join("");
      // 单列模式默认收起；搜索时自动展开，便于直接看到匹配结果
      var expanded = !!state.expandedCols[name] || !!state.search;
      var expandBtn = list.length > 0
        ? '<button class="column-expand" data-action="toggle-column" aria-expanded="' + (expanded ? "true" : "false") + '">' +
          (expanded ? "收起" : "展开") + '</button>'
        : "";
      var body = cards
        ? '<div class="cards-fold"><div class="cards-fold-inner">' + cards + '</div></div>'
        : '<div class="empty-hint">暂无任务</div>';
      return '<section class="column' + (expanded ? " expanded" : "") + '" data-status="' + esc(name) + '">' +
        '<header class="column-head"><span class="dot" style="background:' + colorFor(index) + '"></span>' +
        '<span class="column-name">' + esc(name) + '</span>' +
        '<span class="column-count">' + list.length + '</span>' + expandBtn + '</header>' +
        '<div class="column-body">' + body + '</div>' +
        '</section>';
    }).join("");
    var total = state.tasks.filter(function (t) { return !t.archived; }).length;
    var banner = total === 0
      ? '<div class="board-banner">还没有任务，点击右上角「＋ 新建任务」开始记录你的第一个任务。</div>'
      : "";
    return banner + '<div class="board">' + columns + '</div>';
  }

  function renderCard(task) {
    var goal = task.goal ? '<div class="card-goal">' + nl2br(task.goal) + '</div>' : "";
    var flag = task.note ? '<span class="mini-flag">有备注</span>' : "";
    return '<article class="card" data-action="open-task" data-id="' + esc(task.id) + '">' +
      '<div class="card-title">' + esc(task.title) + '</div>' + goal +
      '<footer class="card-foot"><span>更新 ' + esc(fmtShort(task.updatedAt)) + '</span>' + flag + '</footer>' +
      '</article>';
  }

  function renderArchive() {
    var list = state.tasks.filter(function (t) {
      return t.archived && matchSearch(t);
    }).sort(function (a, b) {
      return (b.archivedAt || "").localeCompare(a.archivedAt || "");
    });
    if (!list.length) {
      return '<div class="empty-page">归档箱是空的。<br>任务归档后会出现在这里，可以随时查看或恢复。</div>';
    }
    return '<div class="archive-list">' + list.map(function (t) {
      return '<div class="archive-item">' +
        '<div class="archive-main" data-action="open-task" data-id="' + esc(t.id) + '">' +
        '<div class="archive-title">' + esc(t.title) + '</div>' +
        '<div class="archive-meta">状态：' + esc(t.status) + '　·　归档于 ' + esc(fmtFull(t.archivedAt)) + '</div>' +
        '</div>' +
        '<div class="archive-actions">' +
        '<button class="btn btn-sm" data-action="restore-task" data-id="' + esc(t.id) + '">恢复</button>' +
        '<button class="btn btn-sm btn-danger-ghost" data-action="delete-task" data-id="' + esc(t.id) + '">删除</button>' +
        '</div></div>';
    }).join("") + '</div>';
  }

  function logRangeStart() {
    // 当前时间范围筛选的起点（Date）；"全部时间" 返回 null
    var now = new Date();
    if (state.logRange === "today") {
      return new Date(now.getFullYear(), now.getMonth(), now.getDate());
    }
    if (state.logRange === "7d") return new Date(now.getTime() - 7 * 86400000);
    if (state.logRange === "30d") return new Date(now.getTime() - 30 * 86400000);
    return null;
  }

  function matchLogRange(log) {
    var start = logRangeStart();
    if (!start) return true;
    var at = new Date(log.at);
    return !isNaN(at.getTime()) && at >= start;
  }

  function logDetailText(log) {
    // 变更内容文本（关键词搜索用：修改前后的值 + 快照字段值）
    var parts = [];
    (log.changes || []).forEach(function (c) {
      parts.push(c.from || "");
      parts.push(c.to || "");
    });
    var snap = log.snapshot || {};
    parts.push(snap.title || "", snap.goal || "", snap.note || "", snap.status || "", snap.text || "");
    return parts.join("\n").toLowerCase();
  }

  function filteredLogs() {
    var kw = state.logKeyword.toLowerCase();
    return state.logs.filter(function (log) {
      if (state.logType !== "all" && log.type !== state.logType) return false;
      if (!matchLogRange(log)) return false;
      if (state.search) {
        var t = taskById(log.taskId);
        var title = t ? (t.title || "") : (log.taskTitle || "");
        if (title.toLowerCase().indexOf(state.search.toLowerCase()) < 0) return false;
      }
      if (kw && logDetailText(log).indexOf(kw) < 0) return false;
      return true;
    });
  }

  function logItemHtml(log) {
    var meta = LOG_TYPE_META[log.type] || { label: log.type, cls: "" };
    return '<div class="log-item">' +
      '<div class="log-head"><span class="log-type ' + meta.cls + '">' + esc(meta.label) + '</span>' +
      '<span class="log-time">' + esc(fmtFull(log.at)) + '</span></div>' +
      '<div class="log-body">' + logBody(log) + '</div></div>';
  }

  function logsListHtml(list) {
    if (!list.length) {
      return '<div class="empty-page">暂无符合条件的日志。<br>任务的每一次新增、修改、归档、恢复、删除都会记录在这里。</div>';
    }
    return list.map(logItemHtml).join("");
  }

  function renderLogs() {
    var typeOptions = [["all", "全部类型"]].concat(Object.keys(LOG_TYPE_META).map(function (k) {
      return [k, LOG_TYPE_META[k].label];
    })).map(function (pair) {
      return '<option value="' + pair[0] + '"' + (state.logType === pair[0] ? " selected" : "") + '>' +
        pair[1] + '</option>';
    }).join("");
    var rangeOptions = LOG_RANGES.map(function (pair) {
      return '<option value="' + pair[0] + '"' + (state.logRange === pair[0] ? " selected" : "") + '>' +
        pair[1] + '</option>';
    }).join("");
    var list = filteredLogs();
    var toolbar = '<div class="logs-toolbar">' +
      '<label>类型：<select id="logTypeFilter">' + typeOptions + '</select></label>' +
      '<label>时间：<select id="logTimeFilter">' + rangeOptions + '</select></label>' +
      '<input id="logKeywordFilter" type="text" placeholder="搜索变更内容…" value="' + esc(state.logKeyword) + '" autocomplete="off">' +
      '<span class="logs-count" id="logsCount">共 ' + list.length + ' 条</span>' +
      '<button class="btn btn-sm btn-danger-ghost" data-action="cleanup-logs">清理当前列表</button>' +
      '</div>';
    return '<div class="logs-wrap">' + toolbar +
      '<div class="logs-list" id="logsList">' + logsListHtml(list) + '</div></div>';
  }

  function updateLogsList() {
    // 只刷新列表与计数，避免筛选控件（尤其是关键词输入框）失焦
    var listEl = document.getElementById("logsList");
    var countEl = document.getElementById("logsCount");
    if (!listEl || !countEl) return;
    var list = filteredLogs();
    listEl.innerHTML = logsListHtml(list);
    countEl.textContent = "共 " + list.length + " 条";
  }

  function logBody(log) {
    var task = taskById(log.taskId);
    var titleHtml;
    if (task) {
      titleHtml = '<a class="log-task-link" data-action="open-task" data-id="' + esc(log.taskId) + '">' +
        esc(task.title) + '</a>';
    } else {
      titleHtml = '<span class="log-task-gone">' + esc(log.taskTitle || "未知任务") + '（已删除）</span>';
    }

    if (log.type === "create") {
      var snap = log.snapshot || {};
      var parts = [];
      if (snap.goal) parts.push("目标：" + oneLine(snap.goal));
      if (snap.note) parts.push("备注：" + oneLine(snap.note));
      parts.push("初始状态：" + esc(snap.status || ""));
      return "创建任务 " + titleHtml + '<div class="log-sub">' + parts.join("<br>") + '</div>';
    }
    if (log.type === "progress") {
      return "任务进展 " + titleHtml + '<div class="log-sub">' + nl2br((log.snapshot || {}).text || "") + "</div>";
    }
    if (log.type === "view") {
      return "查看任务 " + titleHtml;
    }
    if (log.type === "update") {
      var lines = (log.changes || []).map(function (c) {
        return (FIELD_LABEL[c.field] || c.field) + "：「" + oneLine(c.from) + "」→「" + oneLine(c.to) + "」";
      });
      return "修改任务 " + titleHtml + '<div class="log-sub">' + lines.join("<br>") + '</div>';
    }
    if (log.type === "archive") return "归档任务 " + titleHtml;
    if (log.type === "restore") return "恢复任务 " + titleHtml;
    if (log.type === "delete") return "删除任务 " + titleHtml;
    return titleHtml;
  }

  // ---------- 弹窗 ----------

  function openModal(html) {
    var root = document.getElementById("modalRoot");
    root.innerHTML = '<div class="modal-overlay"><div class="modal">' + html + '</div></div>';
  }

  function closeModal() {
    document.getElementById("modalRoot").innerHTML = "";
  }

  function openNewTask() {
    var options = state.statuses.map(function (s, i) {
      return '<option value="' + esc(s) + '"' + (i === 0 ? " selected" : "") + '>' + esc(s) + '</option>';
    }).join("");
    openModal(
      '<div class="modal-head"><h2>新建任务</h2><button class="icon-btn" data-action="close-modal">×</button></div>' +
      '<div class="modal-body">' +
      '<label class="field"><span>标题 <em>*</em></span><input id="ntTitle" type="text" placeholder="任务标题（必填）" autocomplete="off"></label>' +
      '<label class="field"><span>目标</span><textarea id="ntGoal" rows="3" placeholder="这个任务要达成什么？"></textarea></label>' +
      '<label class="field"><span>备注</span><textarea id="ntNote" rows="3" placeholder="补充说明（可选）"></textarea></label>' +
      '<label class="field"><span>状态</span><select id="ntStatus">' + options + '</select></label>' +
      '</div>' +
      '<div class="modal-foot">' +
      '<button class="btn" data-action="close-modal">取消</button>' +
      '<button class="btn btn-primary" data-action="save-new-task">创建任务</button>' +
      '</div>');
    var titleInput = document.getElementById("ntTitle");
    if (titleInput) titleInput.focus();
  }

  function saveNewTask() {
    var title = val("ntTitle").trim();
    if (!title) { toast("标题不能为空", true); return; }
    api("/api/tasks", "POST", {
      title: title,
      goal: val("ntGoal"),
      note: val("ntNote"),
      status: val("ntStatus")
    }).then(function () {
      closeModal();
      toast("任务已创建");
      return refresh();
    }).catch(function (err) { toast(err.message, true); });
  }

  function openEditModal(id) {
    var task = taskById(id);
    if (!task) return;
    var options = state.statuses.map(function (s) {
      return '<option value="' + esc(s) + '"' + (s === task.status ? " selected" : "") + '>' + esc(s) + '</option>';
    });
    if (state.statuses.indexOf(task.status) < 0) {
      options.push('<option selected value="' + esc(task.status) + '">' + esc(task.status) + '</option>');
    }
    openModal(
      '<div class="modal-head"><h2>编辑任务</h2><button class="icon-btn" data-action="close-modal">×</button></div>' +
      '<div class="modal-body">' +
      '<label class="field"><span>标题 <em>*</em></span><input id="etTitle" type="text" value="' + esc(task.title) + '" autocomplete="off"></label>' +
      '<label class="field"><span>目标</span><textarea id="etGoal" rows="3">' + esc(task.goal || "") + '</textarea></label>' +
      '<label class="field"><span>备注</span><textarea id="etNote" rows="3">' + esc(task.note || "") + '</textarea></label>' +
      '<label class="field"><span>状态</span><select id="etStatus">' + options.join("") + '</select></label>' +
      '</div>' +
      '<div class="modal-foot">' +
      '<button class="btn" data-action="close-modal">取消</button>' +
      '<button class="btn btn-primary" data-action="save-edit-task" data-id="' + esc(id) + '">保存修改</button>' +
      '</div>');
    var titleInput = document.getElementById("etTitle");
    if (titleInput) titleInput.focus();
  }

  function saveEditTask(id) {
    var title = val("etTitle").trim();
    if (!title) { toast("标题不能为空", true); return; }
    api("/api/tasks/" + encodeURIComponent(id), "PATCH", {
      title: title,
      goal: val("etGoal"),
      note: val("etNote"),
      status: val("etStatus")
    }).then(function (result) {
      toast(result.changed ? "修改已保存" : "没有检测到修改");
      return refresh().then(function () { renderDetailModal(id); });
    }).catch(function (err) { toast(err.message, true); });
  }

  function openTaskDetail(id) {
    var task = taskById(id);
    if (!task) { toast("任务不存在（可能已被删除）", true); return; }
    renderDetailModal(id);
    api("/api/tasks/" + encodeURIComponent(id) + "/view", "POST")
      .then(function () { return refresh(); })
      .catch(function (err) { toast(err.message, true); });
  }

  function renderDetailModal(id) {
    var task = taskById(id);
    if (!task) { closeModal(); return; }
    var statusIndex = state.statuses.indexOf(task.status);
    var taskLogs = state.logs.filter(function (l) { return l.taskId === id; }).slice(0, 30);
    var logsHtml = taskLogs.length
      ? taskLogs.map(function (l) {
          var meta = LOG_TYPE_META[l.type] || { label: l.type, cls: "" };
          var summary;
          if (l.type === "progress") {
            summary = "进展：" + ((l.snapshot || {}).text || "");
          } else if (l.type === "update") {
            summary = "修改：" + (l.changes || []).map(function (c) {
              return FIELD_LABEL[c.field] || c.field;
            }).join("、");
          } else {
            summary = meta.label;
          }
          return '<div class="mini-log"><span class="log-type ' + meta.cls + '">' + esc(meta.label) + '</span>' +
            '<span class="mini-log-time">' + esc(fmtFull(l.at)) + '</span>' +
            '<span class="mini-log-text">' + esc(summary) + '</span></div>';
        }).join("")
      : '<div class="hint">暂无日志</div>';

    var archiveButton = task.archived
      ? '<button class="btn" data-action="restore-task" data-id="' + esc(id) + '">恢复</button>'
      : '<button class="btn" data-action="archive-task" data-id="' + esc(id) + '">归档</button>';

    openModal(
      '<div class="modal-head"><h2>任务详情</h2><button class="icon-btn" data-action="close-modal">×</button></div>' +
      '<div class="modal-body">' +
      '<h3 class="detail-title">' + esc(task.title) + '</h3>' +
      '<div class="detail-status"><span class="dot" style="background:' + colorFor(statusIndex < 0 ? 0 : statusIndex) + '"></span>' +
      '<span>' + esc(task.status) + '</span>' +
      (task.archived ? '<span class="archived-tag">已归档</span>' : "") + '</div>' +
      '<section class="detail-section"><h4>目标</h4><p>' +
      (task.goal ? nl2br(task.goal) : '<span class="empty-text">未填写</span>') + '</p></section>' +
      '<section class="detail-section"><h4>备注</h4><p>' +
      (task.note ? nl2br(task.note) : '<span class="empty-text">未填写</span>') + '</p></section>' +
      '<section class="detail-section detail-meta">' +
      '<span>创建于 ' + esc(fmtFull(task.createdAt)) + '</span>' +
      '<span>最后修改 ' + esc(fmtFull(task.updatedAt)) + '</span>' +
      (task.archived && task.archivedAt ? '<span>归档于 ' + esc(fmtFull(task.archivedAt)) + '</span>' : "") +
      '</section>' +
      '<section class="detail-section"><h4>该任务日志（最近 30 条）</h4>' + logsHtml + '</section>' +
      '</div>' +
      '<div class="modal-foot">' +
      '<button class="btn" data-action="close-modal">关闭</button>' +
      archiveButton +
      '<button class="btn btn-danger-ghost" data-action="delete-task" data-id="' + esc(id) + '">删除</button>' +
      '<button class="btn btn-primary" data-action="edit-task" data-id="' + esc(id) + '">编辑</button>' +
      '</div>');
  }

  function openDeleteConfirm(id) {
    var task = taskById(id);
    if (!task) return;
    var archiveButton = task.archived ? "" :
      '<button class="btn" data-action="archive-instead" data-id="' + esc(id) + '">改为归档（推荐）</button>';
    openModal(
      '<div class="modal-head"><h2>删除任务</h2><button class="icon-btn" data-action="close-modal">×</button></div>' +
      '<div class="modal-body">' +
      '<p class="confirm-text">确定要删除任务「<b>' + esc(task.title) + '</b>」吗？</p>' +
      '<p class="warn-text">删除后无法恢复。建议改用“归档”：归档的任务可以随时查看和恢复。</p>' +
      '</div>' +
      '<div class="modal-foot">' +
      '<button class="btn" data-action="close-modal">取消</button>' + archiveButton +
      '<button class="btn btn-danger" data-action="confirm-delete-task" data-id="' + esc(id) + '">确认删除</button>' +
      '</div>');
  }

  function archiveTask(id) {
    api("/api/tasks/" + encodeURIComponent(id) + "/archive", "POST").then(function () {
      closeModal();
      toast("任务已归档");
      return refresh();
    }).catch(function (err) { toast(err.message, true); });
  }

  function restoreTask(id) {
    api("/api/tasks/" + encodeURIComponent(id) + "/restore", "POST").then(function () {
      closeModal();
      toast("任务已恢复");
      return refresh();
    }).catch(function (err) { toast(err.message, true); });
  }

  function deleteTask(id) {
    api("/api/tasks/" + encodeURIComponent(id), "DELETE").then(function () {
      closeModal();
      toast("任务已删除");
      return refresh();
    }).catch(function (err) { toast(err.message, true); });
  }

  function openStatusManager() {
    var rows = state.statuses.map(function (name) {
      var used = state.tasks.filter(function (t) { return t.status === name; }).length;
      return '<div class="status-row" data-name="' + esc(name) + '">' +
        '<input type="text" value="' + esc(name) + '" autocomplete="off">' +
        '<span class="usage">' + used + ' 个任务</span>' +
        '<button class="btn btn-sm" data-action="rename-status">保存</button>' +
        '<button class="btn btn-sm btn-danger-ghost" data-action="delete-status" data-name="' + esc(name) + '">删除</button>' +
        '</div>';
    }).join("");
    openModal(
      '<div class="modal-head"><h2>状态管理</h2><button class="icon-btn" data-action="close-modal">×</button></div>' +
      '<div class="modal-body">' +
      '<p class="hint">可自由新增、重命名、删除状态。重命名会自动应用到使用中的任务；若状态仍被任务使用，需先修改相关任务的状态才能删除。</p>' +
      '<div class="status-rows">' + rows + '</div>' +
      '<div class="status-add"><input id="newStatusName" type="text" placeholder="新状态名称，回车或点击添加" autocomplete="off">' +
      '<button class="btn" data-action="add-status">添加</button></div>' +
      '</div>' +
      '<div class="modal-foot"><button class="btn btn-primary" data-action="close-modal">完成</button></div>');
  }

  function addStatus() {
    var name = val("newStatusName").trim();
    if (!name) {
      toast("请输入状态名称", true);
      var input = document.getElementById("newStatusName");
      if (input) input.focus();
      return;
    }
    api("/api/statuses", "POST", { name: name }).then(function () {
      toast("状态已添加");
      return refresh();
    }).then(openStatusManager).catch(function (err) { toast(err.message, true); });
  }

  function renameStatus(el) {
    var row = el.closest(".status-row");
    var input = row ? row.querySelector("input") : null;
    var oldName = row ? row.getAttribute("data-name") : "";
    var newName = input ? input.value.trim() : "";
    if (!newName) { toast("状态名称不能为空", true); return; }
    if (newName === oldName) { toast("名称没有变化"); return; }
    api("/api/statuses/rename", "POST", { from: oldName, to: newName }).then(function (result) {
      toast(result.renamed ? ("状态已重命名，并同步更新了 " + result.renamed + " 个任务") : "状态已重命名");
      return refresh();
    }).then(openStatusManager).catch(function (err) { toast(err.message, true); });
  }

  function deleteStatus(name) {
    api("/api/statuses/delete", "POST", { name: name }).then(function () {
      toast("状态已删除");
      return refresh();
    }).then(openStatusManager).catch(function (err) { toast(err.message, true); });
  }

  function logRangeLabel(value) {
    var label = "全部时间";
    LOG_RANGES.forEach(function (pair) { if (pair[0] === value) label = pair[1]; });
    return label;
  }

  function logFiltersActive() {
    return state.logType !== "all" || state.logRange !== "all" || !!state.search || !!state.logKeyword;
  }

  function describeLogFilters() {
    var typeLabel = state.logType === "all"
      ? "全部类型"
      : (LOG_TYPE_META[state.logType] || { label: state.logType }).label;
    var parts = ["类型「" + typeLabel + "」", "时间「" + logRangeLabel(state.logRange) + "」"];
    if (state.search) parts.push("任务「" + state.search + "」");
    if (state.logKeyword) parts.push("关键词「" + state.logKeyword + "」");
    return parts.join("　·　");
  }

  function openCleanupLogsConfirm() {
    var list = filteredLogs();
    if (!list.length) {
      openModal(
        '<div class="modal-head"><h2>清理日志</h2><button class="icon-btn" data-action="close-modal">×</button></div>' +
        '<div class="modal-body"><p class="confirm-text">当前列表没有可清理的日志。</p></div>' +
        '<div class="modal-foot"><button class="btn btn-primary" data-action="close-modal">关闭</button></div>');
      return;
    }
    var warn = logFiltersActive()
      ? "仅删除当前列表中的日志，其他日志不受影响；清理后无法恢复。"
      : "当前未设置筛选条件，将删除全部日志，请谨慎操作。";
    openModal(
      '<div class="modal-head"><h2>清理日志</h2><button class="icon-btn" data-action="close-modal">×</button></div>' +
      '<div class="modal-body">' +
      '<p class="confirm-text">将清理当前列表筛选出的日志 <b>' + list.length + '</b> 条，确定继续吗？</p>' +
      '<p class="filter-note">当前筛选：' + esc(describeLogFilters()) + '</p>' +
      '<p class="warn-text">' + warn + '</p>' +
      '</div>' +
      '<div class="modal-foot">' +
      '<button class="btn" data-action="close-modal">取消</button>' +
      '<button class="btn btn-danger" data-action="confirm-cleanup-logs">确认清理</button>' +
      '</div>');
  }

  function confirmCleanupLogs() {
    var ids = filteredLogs().map(function (log) { return log.id; });
    if (!ids.length) {
      closeModal();
      toast("没有可清理的日志");
      return;
    }
    api("/api/logs/cleanup", "POST", { ids: ids }).then(function (result) {
      closeModal();
      toast(result.removed ? ("已清理 " + result.removed + " 条日志") : "没有可清理的日志");
      return refresh();
    }).catch(function (err) { toast(err.message, true); });
  }

  function exportData() {
    openModal(
      '<div class="modal-head"><h2>导出数据</h2><button class="icon-btn" data-action="close-modal">×</button></div>' +
      '<div class="modal-body"><p class="confirm-text">请选择导出范围</p>' +
      '<p class="filter-note">当前页面：' + esc(state.view === "board" ? "看板" : state.view === "archive" ? "归档箱" : "日志") + '</p></div>' +
      '<div class="modal-foot"><button class="btn" data-action="export-all">导出所有</button>' +
      '<button class="btn btn-primary" data-action="export-filtered">导出当前筛选结果</button></div>');
  }

  function runExport(mode) {
    var body = { mode: mode };
    if (mode === "filtered") {
      if (state.view === "logs") {
        var selectedLogs = filteredLogs();
        body.logIds = selectedLogs.map(function (log) { return log.id; });
        var linkedIds = {};
        selectedLogs.forEach(function (log) { linkedIds[log.taskId] = true; });
        body.taskIds = state.tasks.filter(function (task) { return linkedIds[task.id]; })
          .map(function (task) { return task.id; });
      } else {
        body.taskIds = state.tasks.filter(function (task) {
          return !!task.archived === (state.view === "archive") && matchSearch(task);
        }).map(function (task) { return task.id; });
        var selectedIds = {};
        body.taskIds.forEach(function (id) { selectedIds[id] = true; });
        body.logIds = state.logs.filter(function (log) { return selectedIds[log.taskId]; })
          .map(function (log) { return log.id; });
      }
    }
    openModal('<div class="modal-head"><h2>导出数据</h2></div>' +
      '<div class="modal-body"><div class="export-loading"><span class="spinner"></span>正在导出文件…</div></div>');
    api("/api/export", "POST", body).then(renderExportDone).catch(function (err) {
      closeModal();
      toast(err.message, true);
    });
  }

  function renderExportDone(result) {
    openModal(
      '<div class="modal-head"><h2>导出完成</h2><button class="icon-btn" data-action="close-modal">×</button></div>' +
      '<div class="modal-body">' +
      '<p class="confirm-text">备份文件已保存：</p>' +
      '<p class="export-path">' + esc(result.file || result.name || "") + '</p>' +
      '</div>' +
      '<div class="modal-foot">' +
      '<button class="btn" data-action="close-modal">关闭弹窗</button>' +
      '<button class="btn btn-primary" data-action="open-export-dir">打开目录</button>' +
      '</div>');
  }

  function openExportDir() {
    api("/api/export/open", "POST").catch(function (err) { toast(err.message, true); });
  }

  function switchView(view) {
    if (state.view === view) return;
    state.view = view;
    try { history.replaceState(null, "", "#" + view); } catch (e) { /* 忽略 */ }
    render();
  }

  function toggleColumn(el) {
    var col = el.closest ? el.closest(".column") : null;
    if (!col) return;
    var name = col.getAttribute("data-status") || "";
    var expanded = !col.classList.contains("expanded");
    col.classList.toggle("expanded", expanded);
    if (expanded) { state.expandedCols[name] = true; } else { delete state.expandedCols[name]; }
    el.textContent = expanded ? "收起" : "展开";
    el.setAttribute("aria-expanded", expanded ? "true" : "false");
  }

  // ---------- 事件 ----------

  document.addEventListener("click", function (ev) {
    var target = ev.target;

    var tab = target.closest ? target.closest(".tab") : null;
    if (tab) {
      switchView(tab.getAttribute("data-view"));
      return;
    }

    var el = target.closest ? target.closest("[data-action]") : null;
    if (!el) return;
    var action = el.getAttribute("data-action");
    var id = el.getAttribute("data-id") || "";

    switch (action) {
      case "new-task": openNewTask(); break;
      case "save-new-task": saveNewTask(); break;
      case "manage-statuses": openStatusManager(); break;
      case "export-data": exportData(); break;
      case "export-all": runExport("all"); break;
      case "export-filtered": runExport("filtered"); break;
      case "open-export-dir": openExportDir(); break;
      case "open-task": openTaskDetail(id); break;
      case "toggle-column": toggleColumn(el); break;
      case "edit-task": openEditModal(id); break;
      case "save-edit-task": saveEditTask(id); break;
      case "archive-task": archiveTask(id); break;
      case "restore-task": restoreTask(id); break;
      case "delete-task": openDeleteConfirm(id); break;
      case "archive-instead": archiveTask(id); break;
      case "confirm-delete-task": deleteTask(id); break;
      case "cleanup-logs": openCleanupLogsConfirm(); break;
      case "confirm-cleanup-logs": confirmCleanupLogs(); break;
      case "close-modal": closeModal(); break;
      case "add-status": addStatus(); break;
      case "rename-status": renameStatus(el); break;
      case "delete-status": deleteStatus(el.getAttribute("data-name") || ""); break;
    }
  });

  document.addEventListener("change", function (ev) {
    if (ev.target && ev.target.id === "logTypeFilter") {
      state.logType = ev.target.value;
      updateLogsList();
    }
    if (ev.target && ev.target.id === "logTimeFilter") {
      state.logRange = ev.target.value;
      updateLogsList();
    }
  });

  document.addEventListener("input", function (ev) {
    if (ev.target && ev.target.id === "logKeywordFilter") {
      state.logKeyword = ev.target.value.trim();
      updateLogsList();
    }
  });

  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Enter" && ev.target) {
      if (ev.target.id === "newStatusName") { addStatus(); }
      else if (ev.target.id === "ntTitle") { saveNewTask(); }
    }
  });

  // ---------- 初始化 ----------

  function init() {
    var hash = (location.hash || "").replace("#", "");
    if (hash === "archive" || hash === "logs" || hash === "board") {
      state.view = hash;
    }
    var search = document.getElementById("searchInput");
    search.addEventListener("input", function (ev) {
      state.search = ev.target.value.trim();
      render();
    });
    refresh();
    setInterval(pollTick, POLL_INTERVAL);
    // 页面重新可见时立即检查一次，避免后台挂起期间的更新被延迟到下一个周期
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) pollTick();
    });
  }

  document.addEventListener("DOMContentLoaded", init);
})();
