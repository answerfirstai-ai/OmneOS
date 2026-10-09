const $ = (s) => document.querySelector(s);
const escapeHTML = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
let base =
  localStorage.getItem("omne-hub-runtime-url") ||
  (location.port === "8787" ? location.origin : "http://localhost:8787");
let token = sessionStorage.getItem("omne-hub-runtime-token") || "";
let state = null,
  online = false,
  attachment = "",
  history = [],
  jobs = new Set(),
  seenJobs = new Set(),
  generationIntent = false,
  selected = null,
  pendingInstructions = [];
let worldCanvases = [],
  universeSignature = "",
  lastEvent = 0;
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

function toast(message) {
  $("#toast").textContent = message;
  $("#toast").style.display = "block";
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => ($("#toast").style.display = "none"), 6500);
}
async function api(path, data, credentials = { base, token }) {
  const res = await fetch(credentials.base.replace(/\/$/, "") + "/hub/api/" + path, {
    method: data === undefined ? "GET" : "POST",
    headers: {
      Authorization: "Bearer " + credentials.token,
      ...(data === undefined ? {} : { "Content-Type": "application/json" }),
    },
    ...(data === undefined ? {} : { body: JSON.stringify(data) }),
    signal: AbortSignal.timeout(12000),
  });
  const value = await res.json();
  if (!res.ok) throw Error(value.error || `Runtime returned ${res.status}`);
  return value;
}
function connection(ok) {
  online = ok;
  $("#connection").textContent = ok ? "Runtime connected" : "Runtime offline";
  $("#connection").classList.toggle("online", ok);
  $("#footer-state").textContent = ok
    ? "RUNTIME ONLINE · PERSISTENT EXECUTION"
    : "LOCAL INTERFACE · NOT CONNECTED";
}
function openSettings() {
  $("#runtime-url").value = base;
  $("#runtime-token").value = token;
  if (state) {
    $("#daily-tokens").value = state.settings.daily_tokens;
    $("#concurrency").value = state.settings.concurrency;
    $("#eco-mode").checked = state.settings.eco_mode;
  }
  $("#settings").showModal();
}
$("#settings-open").onclick = openSettings;
$("#budget-open").onclick = openSettings;
for (const button of document.querySelectorAll("[data-close]"))
  button.onclick = () => button.closest("dialog").close();
$("#settings-form").onsubmit = async (e) => {
  e.preventDefault();
  const credentials = {
    base: $("#runtime-url").value.trim().replace(/\/$/, ""),
    token: $("#runtime-token").value.trim(),
  };
  $("#settings-message").textContent = "Connecting…";
  try {
    const parsed = new URL(credentials.base);
    if (!["http:", "https:"].includes(parsed.protocol) || parsed.username || parsed.password)
      throw Error("Use an HTTP(S) runtime URL without embedded credentials.");
    const connected = await api("state", undefined, credentials);
    await api(
      "settings",
      {
        daily_tokens: Number($("#daily-tokens").value),
        concurrency: Number($("#concurrency").value),
        eco_mode: $("#eco-mode").checked,
      },
      credentials,
    );
    base = credentials.base;
    token = credentials.token;
    lastEvent = 0;
    state = null;
    localStorage.setItem("omne-hub-runtime-url", base);
    sessionStorage.setItem("omne-hub-runtime-token", token);
    state = { ...connected, events: [] };
    $("#settings-message").textContent = "";
    $("#settings").close();
    await refresh();
    toast("Runtime connected. Your Core is ready.");
  } catch (err) {
    $("#settings-message").textContent =
      err.message === "Failed to fetch"
        ? "Cannot reach runtime. Check its URL, allowed origins, and HTTPS/browser local-network permissions."
        : err.message;
  }
};
$("#disconnect").onclick = () => {
  token = "";
  sessionStorage.removeItem("omne-hub-runtime-token");
  state = null;
  lastEvent = 0;
  jobs.clear();
  worldCanvases = [];
  $("#worlds").replaceChildren();
  $("#connections").replaceChildren();
  $("#core-model").innerHTML = '<option value="">Connect a model</option>';
  universeSignature = "";
  document.body.classList.remove("has-worlds");
  connection(false);
  $("#settings").close();
  $("#harness-count").textContent = "0";
  $("#resource-summary").textContent = "0 HARNESSES · 0 ACTIVE AGENTS";
};
function message(role, content) {
  if ($("#conversation .welcome")) $("#conversation").replaceChildren();
  const el = document.createElement("div");
  el.className = "message " + role;
  const label = document.createElement("span");
  label.className = "speaker";
  label.textContent = role === "user" ? "You" : "Core";
  el.append(label, document.createTextNode(content));
  $("#conversation").append(el);
  while ($("#conversation").children.length > 40) $("#conversation").firstChild.remove();
  $("#conversation").scrollTop = $("#conversation").scrollHeight;
}
$("#generate").onclick = () => {
  generationIntent = true;
  $("#prompt").placeholder = "Describe the harness you want to create…";
  $("#prompt").focus();
  if (!online) toast("Connect a runtime and model in settings to generate a real harness.");
};
$("#prompt").addEventListener("input", () => {
  $("#prompt").style.height = "auto";
  $("#prompt").style.height = Math.min($("#prompt").scrollHeight, 60) + "px";
});
$("#prompt").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    $("#prompt-form").requestSubmit();
  }
});
$("#file").onchange = async () => {
  const f = $("#file").files[0];
  if (!f) return;
  if (f.size > 40000) {
    toast("Attach a text file smaller than 40 KB.");
    return;
  }
  attachment = await f.text();
  $("#file-status").textContent = f.name;
  $("#file-status").title = f.name;
  toast("Context attached to your next instruction.");
};
async function sendInstruction(item) {
  const job = await api("prompt", { ...item, history: history.slice(-12) });
  jobs.add(job.id);
  history.push({ role: "user", content: item.prompt });
  $("#core-log span:last-child").textContent = job.message;
}
$("#prompt-form").onsubmit = async (e) => {
  e.preventDefault();
  const text = $("#prompt").value.trim();
  if (!text) return;
  if (!online) {
    openSettings();
    return;
  }
  const model_id = $("#core-model").value;
  if (!model_id) {
    toast("Select a configured model.");
    return;
  }
  const item = {
    prompt: (generationIntent ? "Create a new harness for this intent: " : "") + text,
    model_id,
    context: attachment,
  };
  message("user", text);
  $("#prompt").value = "";
  $("#prompt").style.height = "auto";
  attachment = "";
  $("#file-status").textContent = "";
  $("#file").value = "";
  generationIntent = false;
  $("#prompt").placeholder = "Speak to your Core…";
  if (jobs.size) {
    pendingInstructions.push(item);
    message(
      "assistant",
      "Adjustment queued. I’ll apply it after the current architecture pass; you can keep adding instructions.",
    );
    return;
  }
  try {
    await sendInstruction(item);
  } catch (err) {
    message("assistant", err.message);
  }
};
async function refresh() {
  if (!token || refresh.busy || document.hidden) return;
  refresh.busy = true;
  try {
    const data = await api("state?after=" + lastEvent);
    data.events = [...(state?.events || []), ...data.events].slice(-150);
    state = data;
    connection(true);
    const modelSelect = $("#core-model"),
      previous = modelSelect.value;
    const signature = JSON.stringify(data.models);
    if (modelSelect.dataset.signature !== signature) {
      modelSelect.replaceChildren();
      for (const m of data.models) {
        const option = new Option(m.label + (m.ready ? "" : " · key needed"), m.id);
        option.disabled = !m.ready;
        modelSelect.add(option);
      }
      modelSelect.dataset.signature = signature;
      if (data.models.some((m) => m.id === previous)) modelSelect.value = previous;
    }
    for (const job of data.jobs) {
      if (jobs.has(job.id) && ["complete", "failed"].includes(job.status)) {
        jobs.delete(job.id);
        seenJobs.add(job.id);
        message("assistant", job.message);
        history.push({ role: "assistant", content: job.message });
      } else if (["queued", "running"].includes(job.status)) {
        jobs.add(job.id);
        $("#core-log span:last-child").textContent = job.message;
      }
    }
    $("#build-preview").hidden = !jobs.size;
    $("#core-log").hidden = !!jobs.size;
    $("#build-label").textContent = "Core is designing the agent graph…";
    if (!jobs.size && pendingInstructions.length) {
      const next = pendingInstructions.shift();
      try {
        await sendInstruction(next);
      } catch (err) {
        message("assistant", err.message);
      }
    }
    const latest = data.events.at(-1);
    if (latest && latest.seq !== lastEvent) {
      lastEvent = latest.seq;
      $("#core-log span:last-child").textContent = latest.message;
    }
    $("#harness-count").textContent = data.harnesses.length;
    $("#resource-summary").textContent =
      `${data.harnesses.length} HARNESSES · ${data.usage.active_agents} ACTIVE AGENTS · ${data.usage.tokens.toLocaleString()} TOKENS`;
    $("#empty-caption").textContent = data.harnesses.length
      ? "Every world connected. Every operation in view."
      : "Your universe is empty. Create its first world.";
    renderWorlds();
    if ($("#inspector").open && selected) {
      renderHarness(selected, true);
    }
  } catch {
    connection(false);
  } finally {
    refresh.busy = false;
  }
}
setInterval(refresh, 5000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) refresh();
});
if (token) refresh();
function positionWorld(i, n) {
  const box = $("#universe").getBoundingClientRect();
  if (innerWidth < 800) {
    return {
      x: box.width * 0.5 + ((i % 3) - (Math.min(n, 3) - 1) / 2) * 100,
      y: 190 + Math.floor(i / 3) * 105,
    };
  }
  const col = i % 2 === 0 ? -1 : 1,
    row = Math.floor(i / 2),
    rows = Math.ceil(n / 2);
  return {
    x: box.width * 0.5 + col * Math.min(box.width * 0.31, 400),
    y: 270 + (row - (rows - 1) / 2) * 170,
  };
}
function renderWorlds(force = false) {
  if (!state) return;
  const sig =
    JSON.stringify(
      state.harnesses.map((h) => [h.id, h.revision, h.status, h.tasks.map((t) => t.status)]),
    ) + innerWidth;
  if (!force && sig === universeSignature) return;
  universeSignature = sig;
  document.body.classList.toggle("has-worlds", !!state.harnesses.length);
  $("#worlds").replaceChildren();
  $("#connections").replaceChildren();
  worldCanvases = [];
  const main = $("#universe").getBoundingClientRect(),
    core = $(".core-stage").getBoundingClientRect();
  for (const [i, h] of state.harnesses.entries()) {
    const pos = positionWorld(i, state.harnesses.length);
    const button = document.createElement("button");
    button.className = "world-node";
    button.style.left = pos.x - (innerWidth < 800 ? 47 : 76) + "px";
    button.style.top = pos.y - 60 + "px";
    button.setAttribute("aria-label", `Open ${h.name}, ${h.status}`);
    const canvas = document.createElement("canvas");
    button.append(canvas);
    const strong = document.createElement("strong");
    strong.textContent = h.name;
    button.append(strong);
    const small = document.createElement("small");
    small.textContent = `${h.agents.length} agents · ${h.status}`;
    button.append(small);
    button.onclick = () => openHarness(h.id);
    $("#worlds").append(button);
    worldCanvases.push({ canvas, h });
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", core.x - main.x + core.width / 2);
    line.setAttribute("y1", core.y - main.y + core.height / 2);
    line.setAttribute("x2", pos.x);
    line.setAttribute("y2", pos.y);
    $("#connections").append(line);
  }
  if (state.harnesses.length > 6)
    $("#universe").style.minHeight =
      Math.max(innerHeight - 150, Math.ceil(state.harnesses.length / 2) * 180 + 250) + "px";
}
const avatars = { researcher: "⌕", builder: "⚒", analyst: "◈", guardian: "◇", creator: "✧" };
function openHarness(id) {
  selected = id;
  renderHarness(id);
  $("#inspector").showModal();
}
function renderHarness(id, update = false) {
  const h = state.harnesses.find((h) => h.id === id);
  if (!h) return;
  const sig = JSON.stringify(h);
  if (update && $("#inspector-body").dataset.signature === sig) return;
  $("#inspector-body").dataset.signature = sig;
  $("#inspector-eyebrow").textContent = "HARNESS WORLD · " + h.world.theme;
  $("#inspector-title").textContent = h.name;
  $("#inspector-body").innerHTML =
    `<canvas class="world-large" id="world-detail"></canvas><span class="chip">${escapeHTML(h.status)} · cycle ${h.cycle}</span><p class="muted">${escapeHTML(h.objective)}</p><div class="detail-actions"><button id="toggle-harness">${["paused", "attention"].includes(h.status) ? "Resume" : "Pause"}</button><button id="edit-harness">Adjust with Core</button><button id="export-harness">Export blueprint</button><button id="artifacts-open">View artifacts</button></div><label>Harness model <select id="harness-model">${state.models.map((m) => `<option value="${escapeHTML(m.id)}" ${m.id === h.model_id ? "selected" : ""} ${m.ready ? "" : "disabled"}>${escapeHTML(m.label)}</option>`).join("")}</select></label><p class="field-note">${h.interval_minutes ? "Repeats every " + h.interval_minutes + " minutes after completion." : "Single execution. No recurring model calls after completion."} Model changes affect the next task. Pausing stops new tasks; in-flight calls finish.</p>${h.agents
      .map((a) => {
        const ts = h.tasks.filter((t) => t.agent_id === a.id);
        const status = ts.some((t) => t.status === "running")
          ? "working"
          : ts.some((t) => t.status === "failed")
            ? "attention"
            : ts.every((t) => t.status === "complete")
              ? "complete"
              : "waiting";
        return `<div class="agent-row"><span class="agent-avatar">${avatars[a.avatar] || "◈"}</span><div><strong>${escapeHTML(a.name)}</strong><small>${escapeHTML(a.role)}</small></div><span class="chip">${status}</span></div>`;
      })
      .join(
        "",
      )}<h3>Task graph</h3>${h.tasks.map((t) => `<div class="activity-item"><span class="chip">${escapeHTML(t.status)}</span> ${escapeHTML(t.title)}<time>${t.depends_on.length ? "After: " + escapeHTML(t.depends_on.join(", ")) : "Independent task"}${t.error ? " · " + escapeHTML(t.error) : ""}</time></div>`).join("")}`;
  $("#toggle-harness").onclick = async () => {
    try {
      await api("control", {
        id,
        action: ["paused", "attention"].includes(h.status) ? "resume" : "pause",
      });
      await refresh();
    } catch (e) {
      toast(e.message);
    }
  };
  $("#harness-model").onchange = async (e) => {
    try {
      await api("control", { id, action: "model", model_id: e.target.value });
      toast("Harness model updated for future tasks.");
      await refresh();
    } catch (err) {
      toast(err.message);
    }
  };
  $("#edit-harness").onclick = () => {
    $("#inspector").close();
    $("#prompt").value = `Update harness "${h.name}" (${id}): `;
    $("#prompt").focus();
  };
  $("#export-harness").onclick = async () => {
    try {
      download(await api("export/" + id), h.name.replace(/[^a-z0-9]/gi, "-") + ".json");
    } catch (e) {
      toast(e.message);
    }
  };
  $("#artifacts-open").onclick = async () => {
    try {
      const { artifacts } = await api("artifacts/" + id);
      selected = null;
      $("#inspector-title").textContent = h.name + " · artifacts";
      $("#inspector-body").innerHTML = artifacts.length
        ? artifacts
            .map(
              (a) =>
                `<div class="activity-item">${escapeHTML(a.title)} · cycle ${a.cycle}</div><pre class="artifact">${escapeHTML(a.content || a.error)}</pre>`,
            )
            .join("")
        : '<p class="muted">No artifacts yet. Outputs appear here when an agent finishes a task.</p>';
    } catch (e) {
      toast(e.message);
    }
  };
}
function download(data, name) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$("#import-open").onclick = () => {
  if (!online) {
    openSettings();
    return;
  }
  $("#import-file").click();
};
$("#import-file").onchange = async () => {
  const f = $("#import-file").files[0];
  if (!f) return;
  try {
    if (f.size > 400000) throw Error("Blueprint is too large (400 KB maximum).");
    const harness = JSON.parse(await f.text());
    await api("import", { harness, model_id: $("#core-model").value });
    await refresh();
    toast("Harness imported and connected. Review its world, then resume to run.");
  } catch (e) {
    toast(e.message);
  } finally {
    $("#import-file").value = "";
  }
};
$("#harness-list").onclick = () => {
  selected = null;
  $("#inspector-eyebrow").textContent = "CONNECTED WORLDS";
  $("#inspector-title").textContent = "Your harnesses";
  $("#inspector-body").innerHTML = state?.harnesses.length
    ? state.harnesses
        .map(
          (h) =>
            `<div class="activity-item"><button class="text-button" data-harness="${escapeHTML(h.id)}">${escapeHTML(h.name)} ↗</button><span class="chip">${escapeHTML(h.status)}</span></div>`,
        )
        .join("")
    : '<p class="muted">No harnesses yet. Connect your runtime, then describe your first world to the Core.</p>';
  for (const b of $("#inspector-body").querySelectorAll("[data-harness]"))
    b.onclick = () => {
      selected = b.dataset.harness;
      renderHarness(selected);
    };
  $("#inspector").showModal();
};
$("#activity-open").onclick = () => {
  selected = null;
  $("#inspector-eyebrow").textContent = "RUNTIME EVENT STREAM";
  $("#inspector-title").textContent = "Activity";
  $("#inspector-body").innerHTML = state?.events.length
    ? state.events
        .slice()
        .reverse()
        .map(
          (e) =>
            `<div class="activity-item"><time>${new Date(e.time * 1000).toLocaleString()}</time>${escapeHTML(e.message)}</div>`,
        )
        .join("")
    : '<p class="muted">The universe is quiet. Runtime events will appear here.</p>';
  $("#inspector").showModal();
};
$("#universe-button").onclick = () => {
  for (const d of document.querySelectorAll("dialog[open]")) d.close();
  window.scrollTo({ top: 0, behavior: "smooth" });
};
// Procedural worlds are built from the validated harness graph, never from executable model code.
function setupCanvas(canvas) {
  const r = canvas.getBoundingClientRect(),
    d = Math.min(devicePixelRatio || 1, 2);
  if (canvas.width !== Math.round(r.width * d) || canvas.height !== Math.round(r.height * d)) {
    canvas.width = Math.round(r.width * d);
    canvas.height = Math.round(r.height * d);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(d, 0, 0, d, 0, 0);
  ctx.clearRect(0, 0, r.width, r.height);
  return { ctx, w: r.width, h: r.height };
}
function drawWorld(canvas, h, time) {
  if (!canvas?.isConnected) return;
  const { ctx: c, w, h: height } = setupCanvas(canvas);
  const scale = Math.min(w / 160, height / 125);
  c.save();
  c.translate(w / 2, height * 0.53);
  c.scale(scale, scale);
  const color = h.world.color;
  const glow = c.createRadialGradient(0, 0, 8, 0, 0, 68);
  glow.addColorStop(0, color + "18");
  glow.addColorStop(1, color + "00");
  c.fillStyle = glow;
  c.fillRect(-80, -75, 160, 150);
  c.strokeStyle = color + "44";
  c.lineWidth = 0.7;
  c.beginPath();
  c.ellipse(0, 12, 65, 28, 0, 0, Math.PI * 2);
  c.stroke();
  const positions = h.agents.map((a, i) => {
    const angle = (i / h.agents.length) * Math.PI * 2 - 0.8;
    return { x: Math.cos(angle) * 43, y: Math.sin(angle) * 19 + 3, a };
  });
  for (const t of h.tasks) {
    const to = positions.find((p) => p.a.id === t.agent_id);
    for (const dep of t.depends_on) {
      const dt = h.tasks.find((t) => t.id === dep);
      const from = positions.find((p) => p.a.id === dt?.agent_id);
      if (from && to) {
        c.strokeStyle = color + "35";
        c.beginPath();
        c.moveTo(from.x, from.y);
        c.lineTo(to.x, to.y);
        c.stroke();
      }
    }
  }
  function polygon(points, fill) {
    c.fillStyle = fill;
    c.beginPath();
    points.forEach(([x, y], i) => (i ? c.lineTo(x, y) : c.moveTo(x, y)));
    c.closePath();
    c.fill();
  }
  for (const { x, y, a } of [...positions].sort((a, b) => a.y - b.y)) {
    polygon(
      [
        [x - 15, y],
        [x, y - 7],
        [x + 15, y],
        [x, y + 9],
      ],
      color + "55",
    );
    polygon(
      [
        [x - 15, y],
        [x, y + 9],
        [x, y + 17],
        [x - 13, y + 9],
      ],
      "#171c24",
    );
    polygon(
      [
        [x, y + 9],
        [x + 15, y],
        [x + 12, y + 10],
        [x, y + 17],
      ],
      color + "28",
    );
    c.strokeStyle = color;
    c.lineWidth = 0.8;
    switch (h.world.theme) {
      case "garden":
        c.fillStyle = color + "aa";
        for (let j = 0; j < 3; j++) {
          c.beginPath();
          c.ellipse(x + (j - 1) * 6, y - 12 - j * 2, 5, 10, (j - 1) * 0.6, 0, Math.PI * 2);
          c.fill();
        }
        break;
      case "observatory":
        c.beginPath();
        c.arc(x, y - 10, 10, Math.PI, Math.PI * 2);
        c.stroke();
        c.beginPath();
        c.moveTo(x - 10, y - 10);
        c.lineTo(x + 10, y - 10);
        c.moveTo(x, y - 20);
        c.lineTo(x + 9, y - 29);
        c.stroke();
        break;
      case "citadel":
      case "workshop":
        polygon(
          [
            [x - 8, y - 7],
            [x - 8, y - 26],
            [x + 3, y - 31],
            [x + 3, y - 12],
          ],
          color + "88",
        );
        polygon(
          [
            [x + 3, y - 31],
            [x + 11, y - 23],
            [x + 11, y - 7],
            [x + 3, y - 12],
          ],
          color + "44",
        );
        break;
      case "nebula":
        c.beginPath();
        c.ellipse(x, y - 16, 13, 5, time * 0.0002, 0, Math.PI * 2);
        c.stroke();
        c.fillStyle = color;
        c.beginPath();
        c.arc(x, y - 16, 4, 0, Math.PI * 2);
        c.fill();
        break;
      default:
        polygon(
          [
            [x - 10, y - 4],
            [x, y - 27],
            [x + 12, y - 3],
          ],
          color + "88",
        );
        polygon(
          [
            [x, y - 27],
            [x + 3, y - 4],
            [x + 12, y - 3],
          ],
          color + "44",
        );
    }
    const active = h.tasks.some((t) => t.agent_id === a.id && t.status === "running");
    const bob = active && !reducedMotion ? Math.sin(time * 0.004) * 1.5 : 0;
    const ax = x + 9,
      ay = y + 3 + bob;
    c.fillStyle = active ? "#fff0bf" : "#b9bcc2";
    c.beginPath();
    c.arc(ax, ay - 6, 2, 0, Math.PI * 2);
    c.fill();
    c.fillRect(ax - 1.5, ay - 3, 3, 5);
    if (active) {
      c.strokeStyle = color + "77";
      c.beginPath();
      c.ellipse(ax, ay + 3, 5 + Math.sin(time * 0.004), 2, 0, 0, Math.PI * 2);
      c.stroke();
    }
  }
  c.restore();
}
let stars = [];
function seedStars() {
  stars = Array.from({ length: Math.round((innerWidth * innerHeight) / 4800) }, () => ({
    x: Math.random() * innerWidth,
    y: Math.random() * innerHeight,
    r: Math.random() * 0.65 + 0.2,
    a: Math.random() * 0.55 + 0.12,
    p: Math.random() * 6.28,
  }));
}
seedStars();
let previousFrame = 0;
function frame(time) {
  requestAnimationFrame(frame);
  if (document.hidden || time - previousFrame < (reducedMotion ? 1000 : 50)) return;
  previousFrame = time;
  const { ctx: c } = setupCanvas($("#stars"));
  for (const s of stars) {
    c.fillStyle = `rgba(213,219,232,${s.a * (reducedMotion ? 1 : 0.75 + 0.25 * Math.sin(time * 0.0004 + s.p))})`;
    c.beginPath();
    c.arc(s.x, s.y, s.r, 0, Math.PI * 2);
    c.fill();
  }
  for (const item of worldCanvases) drawWorld(item.canvas, item.h, time);
  if (selected && $("#inspector").open) {
    const h = state?.harnesses.find((h) => h.id === selected);
    if (h) drawWorld($("#world-detail"), h, time);
  }
  if (jobs.size) {
    const cv = $("#build-canvas");
    const { ctx: c, w, h } = setupCanvas(cv);
    c.strokeStyle = "#c8ac6a55";
    c.fillStyle = "#d2b77b";
    for (let i = 0; i < 5; i++) {
      const x = w / 2 + (i - 2) * 37,
        y = h / 2 + Math.sin(i * 2) * 9;
      c.beginPath();
      c.moveTo(w / 2, h / 2);
      c.lineTo(x, y);
      c.stroke();
      c.beginPath();
      c.arc(x, y, 2, 0, Math.PI * 2);
      c.fill();
    }
    c.strokeStyle = "#e3c78c88";
    c.beginPath();
    c.arc(
      w / 2,
      h / 2,
      11,
      reducedMotion ? 0 : time * 0.002,
      (reducedMotion ? 0 : time * 0.002) + 4.5,
    );
    c.stroke();
  }
}
requestAnimationFrame(frame);
window.addEventListener("resize", () => {
  seedStars();
  renderWorlds(true);
});

$("#desktop-link").href =
  location.port === "8787"
    ? "http://localhost:4173/"
    : location.pathname.includes("/hub/")
      ? "../index.html"
      : "./desktop/";
