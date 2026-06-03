class AssignedTasksCard extends HTMLElement {
  setConfig(config) {
    this.config = config || {};
    this.state = { people: [], lists: [], tasks: [] };
    this.selectedListId = "";
    this.selectedTaskId = "";
    this.showArchived = false;
    this.showVisibility = false;
    this.expandedSimpleLists = new Set();
    this.expandedAssignees = new Set();
    this.expandedDescriptions = new Set();
  }

  set hass(hass) {
    this._hass = hass;
    this.subscribeUpdates();
    if (!this.loaded) {
      this.loaded = true;
      this.load();
    }
  }

  connectedCallback() {
    this.subscribeUpdates();
    if (!this.boundResumeRefresh) {
      this.boundResumeRefresh = () => this.scheduleRefresh();
    }
    window.addEventListener("focus", this.boundResumeRefresh);
    document.addEventListener("visibilitychange", this.boundResumeRefresh);
  }

  disconnectedCallback() {
    if (this.unsubscribeUpdates) {
      Promise.resolve(this.unsubscribeUpdates).then((unsubscribe) => unsubscribe?.());
      this.unsubscribeUpdates = null;
    }
    if (this.refreshTimer) clearTimeout(this.refreshTimer);
    this.refreshTimer = null;
    if (this.boundResumeRefresh) {
      window.removeEventListener("focus", this.boundResumeRefresh);
      document.removeEventListener("visibilitychange", this.boundResumeRefresh);
    }
  }

  getCardSize() {
    return 10;
  }

  subscribeUpdates() {
    if (this.unsubscribeUpdates || !this._hass?.connection) return;
    this.unsubscribeUpdates = this._hass.connection.subscribeEvents((event) => {
      if (event?.data?.entity_id === "sensor.assigned_tasks_updates") {
        this.scheduleRefresh();
      }
    }, "state_changed");
  }

  scheduleRefresh() {
    if (this.refreshTimer) clearTimeout(this.refreshTimer);
    this.refreshTimer = setTimeout(() => {
      this.refreshTimer = null;
      this.load();
    }, 150);
  }

  async api(method, path, data) {
    const result = await this._hass.callApi(method, `assigned_tasks/${path}`, data);
    if (result) {
      this.state = result;
      this.ensureSelection();
      this.render();
    }
    return result;
  }

  async load() {
    await this.api("GET", "state");
  }

  ensureSelection() {
    const visible = this.visibleLists();
    if (!visible.some((list) => list.id === this.selectedListId)) {
      this.selectedListId = visible[0]?.id || "";
      this.selectedTaskId = "";
    }
  }

  visibleLists() {
    const personId = this.effectivePersonId();
    return this.state.lists.filter((list) => {
      if (!this.showArchived && list.archived) return false;
      if (personId && !this.isVisibleToPerson(list, personId)) return false;
      return true;
    });
  }

  selectedList() {
    return this.state.lists.find((list) => list.id === this.selectedListId) || null;
  }

  selectedTask() {
    return this.state.tasks.find((task) => task.id === this.selectedTaskId) || null;
  }

  listTasks() {
    return this.tasksForList(this.selectedListId);
  }

  render() {
    this.renderSimple();
  }

  renderPanel() {
    this.ensureSelection();
    const personId = this.effectivePersonId();
    const list = this.selectedList();
    const task = this.selectedTask();
    this.innerHTML = `
      <ha-card>
        <style>
          .app{display:grid;grid-template-columns:minmax(220px,280px) 1fr;min-height:620px}
          aside{border-right:1px solid var(--divider-color);padding:16px;display:flex;flex-direction:column;gap:12px}
          main{padding:16px;display:grid;gap:16px;align-content:start}
          h2,h3{margin:0 0 10px}
          .new-list{display:grid;gap:8px}
          .lists{display:grid;gap:6px}
          .list-btn{width:100%;display:flex;align-items:center;justify-content:space-between;gap:8px;text-align:left;background:transparent;color:var(--primary-text-color);border:1px solid var(--divider-color);border-radius:8px;padding:10px;cursor:pointer}
          .list-btn[selected]{background:var(--primary-color);color:var(--text-primary-color)}
          .list-progress{font-size:12px;line-height:1;color:#fff;white-space:nowrap;border-radius:999px;padding:4px 8px;min-width:34px;text-align:center;background-clip:border-box}
          .list-check{color:var(--success-color,#43a047);font-weight:700}
          .list-btn[selected] .list-progress{color:#fff}
          .panel{border:1px solid var(--divider-color);border-radius:8px;padding:14px;background:var(--card-background-color)}
          .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}
          .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
          label{display:block;font-size:12px;color:var(--secondary-text-color);margin:8px 0 4px}
          input,select,textarea{box-sizing:border-box;width:100%;padding:8px;border:1px solid var(--divider-color);border-radius:6px;background:var(--card-background-color);color:var(--primary-text-color)}
          textarea{min-height:72px}
          button{cursor:pointer;border:1px solid var(--divider-color);border-radius:6px;padding:8px 10px;background:var(--primary-color);color:var(--text-primary-color)}
          button.secondary{background:transparent;color:var(--primary-text-color)}
          button.danger{background:var(--error-color);color:var(--text-primary-color)}
          .people{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:6px;margin-top:8px}
          .people label{display:flex;gap:8px;align-items:center;margin:0;color:var(--primary-text-color);font-size:14px}
          .people input{width:auto}
          .visibility-box{margin-top:12px;border-top:1px solid var(--divider-color);padding-top:12px}
          .assignee-status{display:flex;gap:6px;flex-wrap:wrap}
          .chip{display:inline-flex;align-items:center;border-radius:999px;padding:4px 8px;font-size:12px;line-height:1;color:#fff;background-clip:border-box}
          .chip,.chip *{color:#fff !important}
          .chip-button{appearance:none;-webkit-appearance:none;border:0;padding:4px 8px;margin:0;background:var(--secondary-text-color);line-height:1;color:#fff}
          .chip-button:hover,.chip-button:focus{color:#fff !important}
          .assignee-toggle:hover,.assignee-toggle:focus{filter:brightness(1.08)}
          .assignee-toggle.done{background:var(--success-color,#43a047)}
          .assignee-toggle.todo{background:var(--error-color,#db4437)}
          .chip.done{background:var(--success-color,#43a047);text-decoration:none}
          .chip.todo{background:var(--error-color,#db4437)}
          tr.deadline-warning td{background:rgba(255,193,7,.22)}
          tr.deadline-critical td{background:rgba(244,67,54,.18)}
          table{width:100%;border-collapse:collapse}
          td,th{text-align:left;border-top:1px solid var(--divider-color);padding:8px;vertical-align:top}
          a{color:var(--primary-color)}
          .muted{color:var(--secondary-text-color)}
          .done{text-decoration:line-through;color:var(--secondary-text-color)}
          .empty{color:var(--secondary-text-color);padding:18px;text-align:center}
          @media (max-width: 760px){.app{grid-template-columns:1fr} aside{border-right:0;border-bottom:1px solid var(--divider-color)}}
        </style>
        <div class="app">
          <aside>
            <h2>Task Lists</h2>
            <div class="new-list">
              <input id="new-list-name" placeholder="New list name">
              <button id="create-list">Create list</button>
            </div>
            <label class="row"><input id="show-archived" type="checkbox" ${this.showArchived ? "checked" : ""} style="width:auto"> Show archived</label>
            <div class="lists">
              ${this.visibleLists().map((item) => `<button class="list-btn" data-id="${item.id}" ${item.id === this.selectedListId ? "selected" : ""}><span>${this.escape(item.name)}${item.archived ? " (archived)" : ""}</span>${this.renderListProgress(item)}</button>`).join("") || `<div class="empty">Create a list to begin.</div>`}
            </div>
          </aside>
          <main>
            ${personId ? this.renderPersonTasksPanel(list, personId) : (list ? this.renderListPanel(list) + this.renderTasksPanel(list, task) : `<div class="empty">Create a task list first.</div>`)}
          </main>
        </div>
      </ha-card>
    `;
    this.bind();
  }

  renderSimple() {
    const personId = this.effectivePersonId();
    const person = personId ? this.state.people.find((item) => item.id === personId) : null;
    this.innerHTML = `
      <ha-card header="${this.escape(this.config.title || (person ? `${person.name}'s Tasks` : "Tasks"))}">
        <style>
          .simple{padding:0 16px 16px;display:grid;gap:14px;justify-items:start}
          .list{border:1px solid var(--divider-color);border-radius:8px;overflow:hidden;width:fit-content;max-width:100%;min-width:min(100%,320px)}
          .list-header{display:grid;grid-template-columns:auto 1fr auto;gap:10px;align-items:center;padding:12px 14px;background:var(--secondary-background-color)}
          .list-title{font-weight:600}
          .expand-toggle{width:32px;height:32px;padding:0}
          .list-summary{font-size:12px;line-height:1;color:#fff;white-space:nowrap;border-radius:999px;padding:4px 8px;min-width:34px;text-align:center;background-clip:border-box}
          .list-summary.complete{color:#fff;font-size:12px;font-weight:400}
          .task-table{display:grid;grid-template-columns:minmax(10rem,max-content) minmax(0,max-content) 96px;width:fit-content;max-width:100%;overflow:hidden}
          .due-group,.task{display:contents}
          .due-heading{grid-column:1 / -1;padding:8px 14px;background:var(--secondary-background-color);color:var(--secondary-text-color);font-size:12px;font-weight:600;border-top:1px solid var(--divider-color)}
          .task-title,.assignee-cell,.assignment-cell{padding:12px 14px;border-top:1px solid var(--divider-color);box-sizing:border-box}
          .description-row{grid-column:1 / -1;color:var(--secondary-text-color);font-size:13px;line-height:1.4;white-space:pre-wrap;overflow-wrap:anywhere;padding:0 14px 12px 14px}
          .title{font-weight:500}
          .task-title{min-width:0;display:flex;align-items:center;gap:8px;flex-wrap:wrap;overflow-wrap:anywhere}
          .assignee-cell{min-width:0;width:100%;align-self:stretch;justify-self:stretch;display:flex;align-items:center}
          .done .title{text-decoration:line-through;color:var(--secondary-text-color)}
          .meta{font-size:12px;color:var(--secondary-text-color);margin-top:3px}
          .assignee-status{display:flex;gap:6px;flex-wrap:wrap;align-items:center;max-width:100%;overflow:hidden}
          .chip{display:inline-flex;align-items:center;border-radius:999px;padding:4px 8px;font-size:12px;line-height:1;color:#fff;max-width:100%;box-sizing:border-box;white-space:nowrap;background-clip:border-box}
          .chip,.chip *{color:#fff !important}
          .chip-button{appearance:none;-webkit-appearance:none;border:0;padding:4px 8px;margin:0;background:var(--secondary-text-color);line-height:1;color:#fff}
          .chip-button:hover,.chip-button:focus{color:#fff !important}
          .assignee-toggle:hover,.assignee-toggle:focus{filter:brightness(1.08)}
          .assignee-toggle.done{background:var(--success-color,#43a047)}
          .assignee-toggle.todo{background:var(--error-color,#db4437)}
          .chip.done{background:var(--success-color,#43a047);text-decoration:none}
          .chip.todo{background:var(--error-color,#db4437)}
          .deadline-warning{background:rgba(255,193,7,.22)}
          .deadline-critical{background:rgba(244,67,54,.18)}
          button{cursor:pointer;border:1px solid var(--divider-color);border-radius:6px;padding:7px 10px;background:transparent;color:var(--primary-text-color)}
          .assignment-cell{width:96px;display:flex;align-items:center;justify-content:flex-end}
          .assignment-toggle{width:72px;white-space:nowrap}
          .empty{color:var(--secondary-text-color);padding:16px;text-align:center}
          .description-toggle{padding:3px 8px;font-size:12px;white-space:nowrap}
          @media (max-width: 520px){.task-table{grid-template-columns:minmax(8rem,max-content) minmax(0,max-content) 96px}.task-title,.assignee-cell,.assignment-cell{padding:10px 8px}.description-row{padding:0 8px 10px 8px}}
        </style>
        <div class="simple">
          ${this.simpleListSections(personId)}
        </div>
      </ha-card>
    `;
    this.bindSimple();
  }

  simpleListSections(personId) {
    const lists = this.visibleLists();
    if (personId && !this.state.people.some((person) => person.id === personId)) {
      return `<div class="empty">No Home Assistant person is linked to this card.</div>`;
    }
    if (lists.length === 0) {
      return `<div class="empty">No tasks to show.</div>`;
    }
    return lists.map((list) => {
      const tasks = this.tasksForList(list.id);
      if (tasks.length === 0) return "";
      const expanded = this.expandedSimpleLists.has(list.id);
      const progress = this.listCompletion(list.id);
      return `
        <section class="list">
          <div class="list-header">
            <button class="expand-toggle" data-id="${list.id}">${expanded ? "▾" : "▸"}</button>
            <div class="list-title">${this.escape(list.name)}</div>
            ${progress.total > 0 ? `<div class="list-summary ${progress.complete === progress.total ? "complete" : ""}" ${this.progressStyle(progress.complete, progress.total)}>${progress.complete}/${progress.total}</div>` : ""}
          </div>
          ${expanded ? `<div class="task-table">${this.simpleDueGroups(tasks, personId)}</div>` : ""}
        </section>
      `;
    }).join("") || `<div class="empty">No tasks to show.</div>`;
  }

  simpleDueGroups(tasks, personId) {
    return this.groupTasksByDue(tasks).map((group) => `
      <div class="due-group">
        <div class="due-heading">${this.escape(group.label)}</div>
        ${group.tasks.map((task) => this.simpleTaskRow(task, personId)).join("")}
      </div>
    `).join("");
  }

  groupTasksByDue(tasks) {
    const groups = new Map();
    tasks.forEach((task) => {
      const key = this.dateInputValue(task.computed_due_at) || "none";
      const label = key === "none" ? "No due date" : `Due ${key}`;
      if (!groups.has(key)) groups.set(key, { key, label, tasks: [] });
      groups.get(key).tasks.push(task);
    });
    return [...groups.values()];
  }

  simpleTaskRow(task, personId) {
    const assignedToViewer = personId && (task.assignees || []).includes(personId);
    const viewerDone = personId ? this.isCompleteForPerson(task, personId) : this.isTaskComplete(task);
    const globallyDone = this.isTaskGloballyComplete(task);
    const deadlineClass = this.deadlineClass(task);
    const descriptionExpanded = this.expandedDescriptions.has(task.id);
    return `
      <div class="task ${globallyDone ? "done" : ""}">
        <div class="task-title ${deadlineClass}">
          <div class="title">${this.escape(task.title)}</div>
          ${task.description ? `<button class="description-toggle" data-id="${task.id}">${descriptionExpanded ? "Hide description" : "Description"}</button>` : ""}
        </div>
        <div class="assignee-cell ${deadlineClass}">
          ${this.renderAssigneeStatus(task)}
        </div>
        <div class="assignment-cell ${deadlineClass}">
          ${assignedToViewer ? `<button class="assignment-toggle" data-id="${task.id}" data-complete="${viewerDone ? "false" : "true"}">${viewerDone ? "Reopen" : "Done"}</button>` : ""}
        </div>
        ${descriptionExpanded ? `<div class="description-row ${deadlineClass}">${this.escape(task.description)}</div>` : ""}
      </div>
    `;
  }

  bindSimple() {
    this.querySelectorAll(".expand-toggle").forEach((node) => node.addEventListener("click", (event) => {
      const listId = event.currentTarget.dataset.id;
      if (this.expandedSimpleLists.has(listId)) this.expandedSimpleLists.delete(listId);
      else this.expandedSimpleLists.add(listId);
      this.render();
    }));
    this.bindAssigneeToggles();
    this.bindDescriptionToggles();
    this.querySelectorAll(".assignment-toggle").forEach((node) => node.addEventListener("click", (event) => {
      const personId = this.effectivePersonId();
      if (!personId) return;
      this.api("PATCH", `tasks/${event.currentTarget.dataset.id}/assignments/${personId}`, {
        complete: event.currentTarget.dataset.complete === "true",
      });
    }));
  }

  renderListPanel(list) {
    return `
      <section class="panel">
        <h2>${this.escape(list.name)}</h2>
        <div class="grid">
          <div><label>List name</label><input id="list-name" value="${this.escape(list.name)}"></div>
        </div>
        <div class="row" style="margin-top:12px">
          <button id="save-list">Save list</button>
          <button id="archive-list" class="secondary">${list.archived ? "Unarchive" : "Archive"}</button>
          <button class="secondary visibility-toggle">${this.showVisibility ? "Hide visibility" : "Visibility"}</button>
        </div>
        ${this.showVisibility ? this.renderVisibilityControls("list-visible", list.visible_to || []) : ""}
      </section>`;
  }

  renderTasksPanel(list, task) {
    const defaults = this.taskDefaults(list, task);
    return `
      <section class="panel">
        <h3>${task ? "Edit Task" : "New Task"}</h3>
        <div class="grid">
          <div><label>Title</label><input id="task-title" value="${this.escape(task?.title || "")}"></div>
          <div><label>Starts</label><input id="task-resets" type="date" min="${this.todayDate()}" value="${this.escape(this.dateInputValue(defaults.resets_at))}"></div>
          <div><label>Ends</label><input id="task-expires" type="date" min="${this.todayDate()}" value="${this.escape(this.dateInputValue(defaults.expires_at))}"></div>
          <div><label>Repeat every</label><div class="row"><input id="task-reset-every" type="number" min="1" value="${this.escape(defaults.reset_every)}" style="max-width:90px"><select id="task-reset-interval">${this.intervalOptions(defaults.reset_interval)}</select></div></div>
        </div>
        <label>Description</label><textarea id="task-description">${this.escape(task?.description || "")}</textarea>
        <label>Who must complete it?</label>
        <select id="task-completion">
          <option value="each_assignee" ${!task || task.completion_mode === "each_assignee" ? "selected" : ""}>Every assigned person must complete it</option>
          <option value="any_assignee" ${task?.completion_mode === "any_assignee" ? "selected" : ""}>Any one assigned person completes it for everyone</option>
        </select>
        <label>Assigned Home Assistant people</label>
        <div class="row">
          <button id="select-all-people" class="secondary">Select all</button>
          <button id="clear-all-people" class="secondary">Clear all</button>
          ${this.effectivePersonId() ? `<button id="select-current-user" class="secondary">Select current user</button>` : ""}
        </div>
        <div class="people">
          ${this.state.people.filter((p) => p.enabled).map((person) => `<label><input type="checkbox" class="assignee" value="${person.id}" ${task?.assignees?.includes(person.id) ? "checked" : ""}>${this.escape(person.name)}</label>`).join("") || `<span class="muted">No Home Assistant people found.</span>`}
        </div>
        <div class="row" style="margin-top:12px">
          <button id="save-task">${task ? "Save task" : "Create task"}</button>
          ${task ? `<button id="delete-task" class="danger">Delete task</button><button id="new-task" class="secondary">New task</button>` : ""}
          <button class="secondary visibility-toggle">${this.showVisibility ? "Hide visibility" : "Visibility"}</button>
        </div>
        ${this.showVisibility ? this.renderVisibilityControls("task-visible", task?.visible_to || []) : ""}
      </section>
      <section class="panel">
        <h3>Tasks in ${this.escape(list.name)}</h3>
        <table>
          <thead><tr><th>Task</th><th>Assigned</th><th>Due</th></tr></thead>
          <tbody>${this.listTasks().map((item) => `<tr class="${this.deadlineClass(item)}"><td><a href="#" class="task-edit" data-id="${item.id}">${this.escape(item.title)}</a></td><td>${this.renderAssigneeStatus(item)}</td><td>${this.escape(this.dateInputValue(item.computed_due_at))}</td></tr>`).join("") || `<tr><td colspan="3" class="empty">No tasks in this list.</td></tr>`}</tbody>
        </table>
      </section>`;
  }

  renderPersonTasksPanel(list, personId) {
    const person = this.state.people.find((item) => item.id === personId);
    if (!person) {
      return `<div class="empty">No Home Assistant person is linked to the current user.</div>`;
    }
    if (!list) {
      return `<div class="empty">No tasks assigned to ${this.escape(person.name)}.</div>`;
    }
    return `
      <section class="panel">
        <h2>${this.escape(person.name)}'s Tasks</h2>
        <p class="muted">${this.escape(list.name)}</p>
        <table>
          <thead><tr><th>Task</th><th>Assigned</th><th>Due</th><th>Status</th></tr></thead>
          <tbody>${this.listTasks().map((item) => `
            <tr class="${this.deadlineClass(item)}">
              <td class="${this.isCompleteForPerson(item, personId) ? "done" : ""}">${this.escape(item.title)}</td>
              <td>${this.renderAssigneeStatus(item)}</td>
              <td>${this.escape(this.dateInputValue(item.computed_due_at))}</td>
              <td>${(item.assignees || []).includes(personId) ? `<button class="secondary assignment-toggle" data-id="${item.id}" data-complete="${this.isCompleteForPerson(item, personId) ? "false" : "true"}">${this.isCompleteForPerson(item, personId) ? "Reopen" : "Done"}</button>` : `<span class="muted">Not assigned</span>`}</td>
            </tr>
          `).join("") || `<tr><td colspan="4" class="empty">No tasks in this list.</td></tr>`}</tbody>
        </table>
      </section>`;
  }

  taskDefaults(list, task) {
    return {
      expires_at: task?.expires_at || "",
      resets_at: task?.resets_at || "",
      reset_interval: task?.reset_interval || "",
      reset_every: task?.reset_every || 1,
    };
  }

  renderVisibilityControls(className, selected) {
    const enabledPeople = this.state.people.filter((p) => p.enabled);
    const checkedPeople = selected.length === 0 ? enabledPeople.map((person) => person.id) : selected;
    return `
      <div class="visibility-box">
        <div class="muted">All checked means everyone can see it. Uncheck people to limit visibility.</div>
        <div class="row" style="margin-top:8px">
          <button class="secondary visibility-all" data-class="${className}">Select all</button>
        </div>
        <div class="people">
          ${enabledPeople.map((person) => `<label><input type="checkbox" class="${className}" value="${person.id}" ${checkedPeople.includes(person.id) ? "checked" : ""}>${this.escape(person.name)}</label>`).join("") || `<span class="muted">No Home Assistant people found.</span>`}
        </div>
      </div>
    `;
  }

  bind() {
    this.querySelector("#create-list")?.addEventListener("click", () => this.createList());
    this.querySelector("#show-archived")?.addEventListener("change", (event) => {
      this.showArchived = event.target.checked;
      this.render();
    });
    this.querySelectorAll(".list-btn").forEach((node) => node.addEventListener("click", (event) => {
      this.selectedListId = event.currentTarget.dataset.id;
      this.selectedTaskId = "";
      this.render();
    }));
    this.querySelector("#save-list")?.addEventListener("click", () => this.saveList());
    this.querySelector("#archive-list")?.addEventListener("click", () => this.archiveList());
    this.querySelectorAll(".visibility-toggle").forEach((node) => node.addEventListener("click", () => {
      this.showVisibility = !this.showVisibility;
      this.render();
    }));
    this.querySelectorAll(".visibility-all").forEach((node) => node.addEventListener("click", (event) => this.setVisibility(event.currentTarget.dataset.class, "all")));
    this.bindAssigneeToggles();
    this.querySelector("#select-all-people")?.addEventListener("click", () => this.setAssignees("all"));
    this.querySelector("#clear-all-people")?.addEventListener("click", () => this.setAssignees("none"));
    this.querySelector("#select-current-user")?.addEventListener("click", () => this.setAssignees("current"));
    this.querySelector("#save-task")?.addEventListener("click", () => this.saveTask());
    this.querySelector("#delete-task")?.addEventListener("click", () => this.deleteTask());
    this.querySelector("#new-task")?.addEventListener("click", () => {
      this.selectedTaskId = "";
      this.render();
    });
    this.querySelectorAll(".task-edit").forEach((node) => node.addEventListener("click", (event) => {
      event.preventDefault();
      this.selectedTaskId = event.currentTarget.dataset.id;
      this.render();
    }));
    this.querySelectorAll(".assignment-toggle").forEach((node) => node.addEventListener("click", (event) => {
      const personId = this.effectivePersonId();
      if (!personId) return;
      this.api("PATCH", `tasks/${event.currentTarget.dataset.id}/assignments/${personId}`, {
        complete: event.currentTarget.dataset.complete === "true",
      });
    }));
  }

  async createList() {
    const name = this.value("#new-list-name");
    if (!name) return;
    await this.api("POST", "lists", {
      name,
      visible_to: [],
    });
  }

  async saveList() {
    const list = this.selectedList();
    if (!list) return;
    await this.api("PATCH", `lists/${list.id}`, {
      name: this.value("#list-name"),
      visible_to: this.showVisibility ? this.visibilityValues(".list-visible") : (list.visible_to || []),
    });
  }

  async archiveList() {
    const list = this.selectedList();
    if (!list) return;
    await this.api("PATCH", `lists/${list.id}`, { action: list.archived ? "unarchive" : "archive" });
  }

  setAssignees(mode) {
    const currentPersonId = this.effectivePersonId();
    this.querySelectorAll(".assignee").forEach((node) => {
      node.checked =
        mode === "all" || (mode === "current" && node.value === currentPersonId);
    });
  }

  setVisibility(className, mode) {
    this.querySelectorAll(`.${className}`).forEach((node) => {
      node.checked = mode === "all";
    });
  }

  bindAssigneeToggles() {
    this.querySelectorAll(".assignee-summary").forEach((node) => node.addEventListener("click", (event) => {
      const taskId = event.currentTarget.dataset.id;
      if (this.expandedAssignees.has(taskId)) this.expandedAssignees.delete(taskId);
      else this.expandedAssignees.add(taskId);
      this.render();
    }));
    this.querySelectorAll(".assignee-toggle").forEach((node) => node.addEventListener("click", (event) => {
      event.stopPropagation();
      this.api("PATCH", `tasks/${event.currentTarget.dataset.id}/assignments/${event.currentTarget.dataset.personId}`, {
        complete: event.currentTarget.dataset.complete === "true",
      });
    }));
  }

  bindDescriptionToggles() {
    this.querySelectorAll(".description-toggle").forEach((node) => node.addEventListener("click", (event) => {
      const taskId = event.currentTarget.dataset.id;
      if (this.expandedDescriptions.has(taskId)) this.expandedDescriptions.delete(taskId);
      else this.expandedDescriptions.add(taskId);
      this.render();
    }));
  }

  taskPayload() {
    const task = this.selectedTask();
    return {
      list_id: this.selectedListId,
      title: this.value("#task-title"),
      description: this.value("#task-description"),
      completion_mode: this.value("#task-completion") || "each_assignee",
      assignees: [...this.querySelectorAll(".assignee:checked")].map((node) => node.value),
      expires_at: this.dateValue("#task-expires", true),
      resets_at: this.dateValue("#task-resets", true),
      reset_interval: this.value("#task-reset-interval"),
      reset_every: this.numberValue("#task-reset-every") || 1,
      visible_to: this.showVisibility ? this.visibilityValues(".task-visible") : (task?.visible_to || []),
    };
  }

  async saveTask() {
    const payload = this.taskPayload();
    if (!payload.title || !payload.list_id || payload.assignees.length === 0) return;
    if (this.selectedTaskId) await this.api("PATCH", `tasks/${this.selectedTaskId}`, payload);
    else await this.api("POST", "tasks", payload);
    this.selectedTaskId = "";
  }

  async deleteTask() {
    if (!this.selectedTaskId) return;
    await this.api("DELETE", `tasks/${this.selectedTaskId}`);
    this.selectedTaskId = "";
  }

  intervalOptions(value) {
    return [["", "Does not repeat"], ["daily", "Days"], ["weekly", "Weeks"], ["monthly", "Months"], ["yearly", "Years"]]
      .map(([id, label]) => `<option value="${id}" ${value === id ? "selected" : ""}>${label}</option>`)
      .join("");
  }

  renderListProgress(list) {
    const progress = this.listCompletion(list.id);
    if (progress.total === 0) return `<span class="list-progress" ${this.progressStyle(0, 1)}>0/0</span>`;
    return `<span class="list-progress" ${this.progressStyle(progress.complete, progress.total)}>${progress.complete}/${progress.total}</span>`;
  }

  tasksForList(listId) {
    const personId = this.effectivePersonId();
    return this.state.tasks
      .filter((task) => task.list_id === listId && (!personId || this.isVisibleToPerson(task, personId)))
      .map((task, index) => ({ task, index }))
      .sort((left, right) => {
        const leftComplete = this.isTaskGloballyComplete(left.task);
        const rightComplete = this.isTaskGloballyComplete(right.task);
        if (leftComplete !== rightComplete) return leftComplete ? 1 : -1;
        return left.index - right.index;
      })
      .map(({ task }) => task);
  }

  isTaskComplete(task) {
    const personId = this.effectivePersonId();
    if (personId) return this.isCompleteForPerson(task, personId);
    return this.isTaskGloballyComplete(task);
  }

  listCompletion(listId) {
    const tasks = this.tasksForList(listId);
    return {
      total: tasks.length,
      complete: tasks.filter((task) => this.isTaskGloballyComplete(task)).length,
    };
  }

  progressStyle(complete, total) {
    const percent = total > 0 ? Math.max(0, Math.min(100, Math.round((complete / total) * 100))) : 0;
    return `style="background:linear-gradient(90deg,var(--success-color,#43a047) 0 ${percent}%,var(--error-color,#db4437) ${percent}% 100%)"`;
  }

  isTaskGloballyComplete(task) {
    const assignees = task.assignees || [];
    if (assignees.length === 0) return false;
    if (task.completion_mode === "any_assignee") {
      return Object.keys(task.completed_by || {}).length > 0;
    }
    return !assignees.some((person) => !task.completed_by?.[person]);
  }

  deadlineClass(task) {
    if (this.isTaskGloballyComplete(task)) return "";
    const deadline = this.parseDate(task.computed_due_at || task.expires_at);
    const now = new Date();
    const configuredStart = this.parseDate(task.resets_at || task.due_at);
    const start = this.deadlineStart(configuredStart, deadline, task, now);
    if (!start || !deadline || deadline <= start) return "";
    const remaining = deadline.getTime() - now.getTime();
    const total = deadline.getTime() - start.getTime();
    const remainingRatio = remaining / total;
    if (remainingRatio <= 0.15) return "deadline-critical";
    if (remainingRatio <= 0.30) return "deadline-warning";
    return "";
  }

  parseDate(value) {
    if (!value) return null;
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  deadlineStart(start, deadline, task, now) {
    if (!deadline) return null;
    if (!start) return this.startOfDay(deadline);
    if (start <= now) return start;
    const previousStart = this.subtractInterval(
      start <= deadline ? start : deadline,
      task.reset_interval,
      task.reset_every,
    );
    if (previousStart && previousStart <= now && previousStart < deadline) return previousStart;
    return start <= deadline ? start : null;
  }

  subtractInterval(date, interval, every = 1) {
    const amount = Math.max(1, Number(every) || 1);
    const result = new Date(date.getTime());
    if (interval === "daily") result.setDate(result.getDate() - amount);
    else if (interval === "weekly") result.setDate(result.getDate() - (amount * 7));
    else if (interval === "monthly") result.setMonth(result.getMonth() - amount);
    else if (interval === "yearly") result.setFullYear(result.getFullYear() - amount);
    else return null;
    return result;
  }

  startOfDay(date) {
    if (!date) return null;
    return new Date(date.getFullYear(), date.getMonth(), date.getDate());
  }

  value(selector) {
    return this.querySelector(selector)?.value.trim() || null;
  }

  numberValue(selector) {
    const value = this.value(selector);
    return value ? Number(value) : null;
  }

  checkedValues(selector) {
    return [...this.querySelectorAll(`${selector}:checked`)].map((node) => node.value);
  }

  visibilityValues(selector) {
    const checked = this.checkedValues(selector);
    const enabledCount = this.state.people.filter((p) => p.enabled).length;
    return checked.length === enabledCount ? [] : checked;
  }

  isVisibleToPerson(item, personId) {
    const visibleTo = item.visible_to || [];
    return visibleTo.length === 0 || visibleTo.includes(personId);
  }

  todayDate() {
    return this.localDateString(new Date());
  }

  dateInputValue(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value).slice(0, 10);
    return this.localDateString(date);
  }

  dateValue(selector, endOfDay = false) {
    const raw = this.value(selector);
    if (!raw) return null;
    const date = raw < this.todayDate() ? this.todayDate() : raw;
    return `${date}T${endOfDay ? "23:59:59" : "00:00:00"}`;
  }

  localDateString(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }

  effectivePersonId() {
    if (this.config.person_id) return this.config.person_id;
    if (!this.config.current_user) return "";
    const userId = this._hass?.user?.id;
    return this.state.people.find((person) => person.user_id === userId)?.id || "";
  }

  canToggleAssigneeChips() {
    return Boolean(
      this.state.permissions?.can_toggle_assignments
      || this.isPanel
      || !this.effectivePersonId()
    );
  }

  isCompleteForPerson(task, personId) {
    if (task.completion_mode === "any_assignee") {
      return Object.keys(task.completed_by || {}).length > 0;
    }
    return Boolean(task.completed_by && task.completed_by[personId]);
  }

  renderAssigneeStatus(task) {
    const assignees = task.assignees || [];
    const doneCount = assignees.filter((personId) => this.isCompleteForPerson(task, personId)).length;
    const total = assignees.length;
    const allDone = total > 0 && doneCount === total;
    const expanded = this.expandedAssignees.has(task.id);
    const summary = `<button class="chip chip-button assignee-summary ${allDone ? "done" : ""}" data-id="${task.id}" ${this.progressStyle(doneCount, total)} title="Show assigned people">${doneCount}/${total}</button>`;
    if (!expanded) {
      return `<div class="assignee-status">${summary}</div>`;
    }
    const chips = (task.assignees || []).map((personId) => {
      const person = this.state.people.find((item) => item.id === personId);
      const done = this.isCompleteForPerson(task, personId);
      const name = this.escape(person?.name || personId);
      if (this.canToggleAssigneeChips()) {
        return `<button class="chip chip-button assignee-toggle ${done ? "done" : "todo"}" data-id="${task.id}" data-person-id="${personId}" data-complete="${done ? "false" : "true"}" title="Mark ${name} ${done ? "not done" : "done"}">${name}</button>`;
      }
      return `<span class="chip ${done ? "done" : "todo"}">${name}</span>`;
    });
    return `<div class="assignee-status">${summary}${chips.join("")}</div>`;
  }

  escape(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[char]));
  }
}

if (!customElements.get("assigned-tasks-card")) {
  customElements.define("assigned-tasks-card", AssignedTasksCard);
}

class AssignedTasksPanel extends AssignedTasksCard {
  constructor() {
    super();
    this.isPanel = true;
  }

  set hass(hass) {
    if (!this.config) this.setConfig({ title: "Assigned Tasks" });
    super.hass = hass;
  }

  render() {
    this.renderPanel();
  }
}

if (!customElements.get("assigned-tasks-panel")) {
  customElements.define("assigned-tasks-panel", AssignedTasksPanel);
}
