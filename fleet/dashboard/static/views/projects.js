/* Projects: which repositories this farm serves, and how to add one. Everything in the table
   is what the registry holds; nothing here is a second store. */

import { h, card, panel, emptyState, skeletonStack, toast, activate } from "../core/ui.js";
import * as fmt from "../core/fmt.js";
import { apiPost, access, list, serverReason } from "../core/api.js";

const local = { busy: false, error: "" };

function ports(row) {
  const block = (row && row.ports) || {};
  const parts = [["web", block.web], ["api", block.api], ["e2e", block.e2e]]
    .filter(([, value]) => value != null)
    .map(([name, value]) => `${name} ${value}`);
  return parts.length ? parts.join(", ") : "none";
}

function table(rows, context) {
  return h("div", { class: "tablewrap" },
    h("table", null,
      h("thead", null, h("tr", null,
        h("th", null, "Project"),
        h("th", null, "Repository"),
        h("th", null, "Base branch"),
        h("th", null, "Ports"),
        h("th", { class: "num" }, "Lanes open"),
        h("th", { class: "num" }, "Last activity"))),
      h("tbody", null, rows.map((row) => h("tr", {
        key: row.name,
        class: "clickable",
        tabindex: "0",
        role: "button",
        onclick: () => context.go("agents", { project: row.name }),
        onkeydown: activate(() => context.go("agents", { project: row.name })),
      },
        h("td", null, row.name),
        h("td", null, row.repo || "none"),
        h("td", null, row.base_branch || "none"),
        h("td", { class: "mono" }, ports(row)),
        h("td", { class: "num", "data-flash": "" }, fmt.num(row.lanes_open, "0")),
        h("td", { class: "num" }, fmt.ago(row.last_activity)))))));
}

function addForm(context) {
  const allowed = access.writable;
  return card({ class: "card-pad", key: "add", "data-write": "" },
    h("div", { class: "section-head" }, h("h2", null, "Add a project")),
    h("p", { class: "muted" },
      "A project is a repository this farm may open a lane in. The port block is picked for you unless you name one."),
    h("div", { class: "row" },
      h("input", { id: "projectName", type: "text", placeholder: "name", disabled: allowed ? null : true }),
      h("input", { id: "projectRepo", type: "text", placeholder: "owner/repo", disabled: allowed ? null : true }),
      h("input", { id: "projectPort", type: "text", placeholder: "port base (optional)", disabled: allowed ? null : true }),
      h("button", {
        class: "button primary",
        disabled: allowed && !local.busy ? null : true,
        onclick: () => submit(context),
      }, local.busy ? "Adding" : "Add")),
    local.error ? h("p", { class: "readonly-note" }, local.error) : null,
    allowed ? null : h("p", { class: "readonly-note" }, access.reason || "This dashboard is read-only."));
}

async function submit(context) {
  const name = document.getElementById("projectName").value.trim();
  const repo = document.getElementById("projectRepo").value.trim();
  const portBase = document.getElementById("projectPort").value.trim();
  if (!name || !repo) {
    local.error = "A project needs a name and a repository, for example demo and your-org/demo.";
    context.paint();
    return;
  }
  local.busy = true;
  local.error = "";
  context.paint();
  try {
    const body = { name, repo };
    if (portBase) body.port_base = Number(portBase);
    const answer = await apiPost("/api/projects", body);
    if (answer && answer.error) {
      local.error = answer.error;
    } else {
      document.getElementById("projectName").value = "";
      document.getElementById("projectRepo").value = "";
      document.getElementById("projectPort").value = "";
      toast(`${name} is registered.`);
    }
  } catch (error) {
    // The server's own words first: they name what is wrong with this form.
    local.error = serverReason(error)
      || "The project was not registered. The server refused the request.";
  } finally {
    local.busy = false;
    await context.refresh("/api/projects");
  }
}

export default {
  id: "projects",
  title: "Projects",
  needs: ["/api/projects"],
  render(context) {
    const resource = context.res("/api/projects");
    return [
      panel(resource, {
        loading: () => h("div", { class: "tablewrap" }, skeletonStack(4)),
        isEmpty: (data) => !list(data).length,
        empty: () => emptyState({
          title: "No projects yet",
          body: "A project tells the farm which repository a lane may work in.",
          command: "fleet add-project --name <name> --repo <owner>/<repo>",
        }),
        ready: (data) => table(list(data), context),
      }),
      h("div", { class: "gap", key: "gap" }),
      addForm(context),
    ];
  },
};
