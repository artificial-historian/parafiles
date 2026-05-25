const mock = {
  admin: {
    name: "Admin Vale",
    username: "admin.parafiles",
    email: "admin@example.test",
    role: "Staff moderator",
    canUpload: true,
    twoFactor: "Verified",
  },
  quota: {
    used: 72.8 * 1024 * 1024,
    total: 500 * 1024 * 1024,
    maxFileSize: 80 * 1024 * 1024,
    maxFiles: 80,
    folders: 9,
  },
  folders: [
    { id: "root", name: "All files", path: "/", files: 8, shared: false },
    { id: "mods", name: "Mods", path: "/Mods", files: 4, shared: true },
    { id: "saves", name: "Saves", path: "/Saves", files: 2, shared: false },
    { id: "screens", name: "Screenshots", path: "/Screenshots", files: 2, shared: true },
  ],
  files: [
    {
      id: 1,
      name: "Parahouse Starter Kit.zip",
      title: "Parahouse Starter Kit",
      folder: "Mods",
      owner: "admin.parafiles",
      size: 42.3 * 1024 * 1024,
      status: "available",
      version: "1.4.0",
      game: "Early Access 0.2",
      downloads: 214,
      uploaded: "2026-05-22 14:20",
      sha: "9b6c4d20b7f6e313f2a8c5b5d04d6cba54891a0d0e12ef7d2ec00a1a49c090d8",
      description: "A compact starter bundle with build objects, recolors, and a sample seaside lot.",
      changelog: "Added curved-wall trim presets. Tuned object previews. Removed duplicate textures.",
    },
    {
      id: 2,
      name: "Garden Paths Pack.package",
      title: "Garden Paths Pack",
      folder: "Mods",
      owner: "mira",
      size: 7.9 * 1024 * 1024,
      status: "available",
      version: "0.9.3",
      game: "Early Access 0.2",
      downloads: 88,
      uploaded: "2026-05-20 09:14",
      sha: "0e271dd71526090a98429f72c12ad61b23a46d7aab0d91ea4241c3f8dbca2406",
      description: "Soft stone, brick, and moss path textures for cozy outdoor builds.",
      changelog: "Improved thumbnail contrast and added two moss variants.",
    },
    {
      id: 3,
      name: "Waterfront Save.parasave",
      title: "Waterfront Save",
      folder: "Saves",
      owner: "jules",
      size: 5.1 * 1024 * 1024,
      status: "review",
      version: "2.0",
      game: "Early Access 0.2",
      downloads: 18,
      uploaded: "2026-05-19 18:41",
      sha: "4703a07688c23fb9802ff6d16394a0626789b71a63836781394f3af7745af210",
      description: "A compact town save staged around a cliff road, train tunnel, and beach overlook.",
      changelog: "Pending staff review after automated metadata warning.",
    },
    {
      id: 4,
      name: "Cozy Town Objects.zip",
      title: "Cozy Town Objects",
      folder: "Mods",
      owner: "admin.parafiles",
      size: 18.4 * 1024 * 1024,
      status: "quarantined",
      version: "0.6.1",
      game: "Early Access 0.1",
      downloads: 0,
      uploaded: "2026-05-18 11:08",
      sha: "dbcf084562dff68a2816c2476af46dfab077c2b63c4ba3651be4d3dc12cc7f80",
      description: "Street signs, cafe details, flower planters, and compact facade decor.",
      changelog: "Quarantined while staff verifies a compressed archive warning.",
    },
    {
      id: 5,
      name: "Roses Courtyard Preview.png",
      title: "Roses Courtyard Preview",
      folder: "Screenshots",
      owner: "mira",
      size: 2.2 * 1024 * 1024,
      status: "available",
      version: "",
      game: "",
      downloads: 41,
      uploaded: "2026-05-16 16:09",
      sha: "65ccb887172a774ad42fc5ba216f76846f1a72d401354d7854fab37167e903ef",
      description: "Preview image for a garden courtyard public share.",
      changelog: "",
    },
  ],
  shares: [
    { type: "File", target: "Parahouse Starter Kit.zip", slug: "starter-kit", state: "live", expires: "No expiration", downloads: 214 },
    { type: "Folder", target: "/Screenshots", slug: "screenshots", state: "live", expires: "2026-06-08", downloads: 67 },
    { type: "File", target: "Waterfront Save.parasave", slug: "waterfront-save", state: "disabled", expires: "Paused during review", downloads: 18 },
  ],
  reports: [
    { id: 831, category: "Misleading file", status: "open", target: "Waterfront Save.parasave", message: "The description says beach lot but the archive appears to include a different save.", assigned: "Admin Vale" },
    { id: 832, category: "Broken download", status: "review", target: "Cozy Town Objects.zip", message: "Download returns a warning page after the latest update.", assigned: "Admin Vale" },
    { id: 833, category: "Spam", status: "resolved", target: "/Screenshots", message: "Duplicate report from an expired link.", assigned: "Nico" },
  ],
  users: [
    { username: "admin.parafiles", email: "admin@example.test", files: 8, storage: 72.8 * 1024 * 1024, shares: 3, active: true, uploader: true, staff: true },
    { username: "mira", email: "mira@example.test", files: 13, storage: 94.1 * 1024 * 1024, shares: 4, active: true, uploader: true, staff: false },
    { username: "jules", email: "jules@example.test", files: 3, storage: 16.4 * 1024 * 1024, shares: 1, active: true, uploader: false, staff: false },
    { username: "old-town", email: "old-town@example.test", files: 0, storage: 0, shares: 0, active: false, uploader: false, staff: false },
  ],
  downloads: [
    { file: "Parahouse Starter Kit.zip", outcome: "Served", bytes: 42.3 * 1024 * 1024, time: "2026-05-25 08:12" },
    { file: "Garden Paths Pack.package", outcome: "Served", bytes: 7.9 * 1024 * 1024, time: "2026-05-24 22:03" },
    { file: "Waterfront Save.parasave", outcome: "Blocked", bytes: 0, time: "2026-05-24 19:51" },
  ],
  scans: [
    { file: "Parahouse Starter Kit.zip", status: "available", engine: "Mock AV: clean", completed: "2026-05-22 14:22" },
    { file: "Cozy Town Objects.zip", status: "quarantined", engine: "Archive depth warning", completed: "2026-05-18 11:10" },
    { file: "Waterfront Save.parasave", status: "review", engine: "Metadata mismatch", completed: "2026-05-19 18:43" },
  ],
  audit: [
    { time: "2026-05-25 08:18", actor: "admin.parafiles", target: "Report #832", action: "Marked reviewing", reason: "Archive warning needs manual check" },
    { time: "2026-05-24 20:01", actor: "admin.parafiles", target: "Waterfront Save.parasave", action: "Disabled share", reason: "Report #831 open" },
    { time: "2026-05-23 16:45", actor: "nico", target: "old-town", action: "Suspended user", reason: "Expired uploader account" },
  ],
  operations: [
    { check: "Upload storage", status: "ok", detail: "8.4 GB free in mock storage pool" },
    { check: "Scanner queue", status: "warn", detail: "2 files waiting for manual review" },
    { check: "Download signing", status: "ok", detail: "Demo signatures generated locally" },
    { check: "Rate limit monitor", status: "ok", detail: "No recent anti-leech blocks" },
  ],
};

const state = {
  route: "home",
};

const routeMeta = {
  home: "Home",
  login: "Sign in",
  dashboard: "Dashboard",
  "quick-share": "Quick share",
  "public-file": "Public file",
  "public-folder": "Public folder",
  account: "Account",
  moderation: "Moderation",
  users: "Users",
  operations: "Operations",
  audit: "Audit log",
  style: "Theme",
};

const app = document.getElementById("app");
const toast = document.getElementById("toast");
const navToggle = document.querySelector(".nav-toggle");
const siteNav = document.querySelector(".site-nav");

function formatBytes(value) {
  if (!value) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function status(label, tone) {
  return `<span class="status ${tone}">${label}</span>`;
}

function pageTitle(title, text, actions = "") {
  return `
    <section class="toolbar">
      <div>
        <span class="section-label">Parafiles</span>
        <h1>${title}</h1>
        <p>${text}</p>
      </div>
      ${actions ? `<div class="actions">${actions}</div>` : ""}
    </section>
  `;
}

function metrics(items) {
  return `
    <section class="metrics">
      ${items.map((item) => `
        <div class="metric">
          <span>${item.label}</span>
          <strong>${item.value}</strong>
          <small>${item.note}</small>
        </div>
      `).join("")}
    </section>
  `;
}

function table(headers, rows, className = "") {
  return `
    <div class="table-wrap ${className}">
      <table>
        <thead>
          <tr>${headers.map((header) => `<th>${header}</th>`).join("")}</tr>
        </thead>
        <tbody>${rows.join("")}</tbody>
      </table>
    </div>
  `;
}

function actionButtons(target = "item") {
  return `
    <div class="table-actions">
      <button class="button-quiet" type="button" data-toast="Opened ${target} settings">Manage</button>
      <button class="button-quiet" type="button" data-toast="Copied ${target} link">Copy link</button>
    </div>
  `;
}

function adminTabs(active) {
  const tabs = [
    ["moderation", "Reports"],
    ["users", "Users"],
    ["operations", "Operations"],
    ["audit", "Audit log"],
  ];
  return `<nav class="route-tabs" aria-label="Moderation sections">${tabs.map(([route, label]) => `<a class="${active === route ? "is-active" : ""}" href="#${route}">${label}</a>`).join("")}</nav>`;
}

function publicTabs(active) {
  const tabs = [
    ["public-file", "File share"],
    ["public-folder", "Folder share"],
  ];
  return `<nav class="route-tabs" aria-label="Public share views">${tabs.map(([route, label]) => `<a class="${active === route ? "is-active" : ""}" href="#${route}">${label}</a>`).join("")}</nav>`;
}

function renderHome() {
  return `
    <section class="hero">
      <div class="hero-copy">
        <span class="section-label">Static prototype</span>
        <h1>Parafiles in a tighter Paralives mood</h1>
        <p>This second static mockup keeps the saved theme notes, but uses denser spacing, shorter controls, and rounded-rectangle buttons for a more operational feel.</p>
        <div class="hero-actions">
          <a class="button" href="#dashboard">Open dashboard</a>
          <a class="button-quiet" href="#moderation">Admin view</a>
        </div>
      </div>
      <div class="scene-panel">
        <img src="assets/town-scene.svg" alt="Pastel seaside town illustration">
      </div>
    </section>

    ${metrics([
      { label: "Pretend user", value: mock.admin.username, note: "staff, uploader, 2FA verified" },
      { label: "Storage", value: formatBytes(mock.quota.used), note: `of ${formatBytes(mock.quota.total)} used` },
      { label: "Public shares", value: String(mock.shares.filter((share) => share.state === "live").length), note: "demo links available" },
      { label: "Open reports", value: String(mock.reports.filter((report) => report.status !== "resolved").length), note: "moderation queue" },
    ])}

    <section class="grid-three">
      <article class="section-band gradient-mods">
        <span class="section-label">Mods</span>
        <h2>Creative library</h2>
        <p>Lavender, peach, white cards, and pill labels make file libraries feel friendly while preserving scannability.</p>
      </article>
      <article class="section-band gradient-simulator">
        <span class="section-label">Simulator</span>
        <h2>Tool surface</h2>
        <p>Sky and mint gradients work well for utility sections, search, upload progress, and operational summaries.</p>
      </article>
      <article class="section-band gradient-updates">
        <span class="section-label">Updates</span>
        <h2>Action areas</h2>
        <p>Coral is reserved for primary actions and alerts so the interface stays easy to read.</p>
      </article>
    </section>
  `;
}

function renderLogin() {
  return `
    ${pageTitle("Uploader sign in", "Static demo identity for the prototype.", '<a class="button-quiet" href="#dashboard">Continue as admin</a>')}
    <section class="grid-two">
      <form class="panel stack" aria-label="Mock sign in form">
        <label>Username<input value="${mock.admin.username}" autocomplete="username"></label>
        <label>Password<input value="demo-only" type="password" autocomplete="current-password"></label>
        <button type="button" data-toast="Signed in as ${mock.admin.name}">Sign in</button>
      </form>
      <aside class="panel tint">
        <h2>Pretend admin user</h2>
        <div class="meta-grid">
          <div><dt>Name</dt><dd>${mock.admin.name}</dd></div>
          <div><dt>Email</dt><dd>${mock.admin.email}</dd></div>
          <div><dt>Role</dt><dd>${mock.admin.role}</dd></div>
          <div><dt>2FA</dt><dd>${mock.admin.twoFactor}</dd></div>
        </div>
      </aside>
    </section>
  `;
}

function renderDashboard() {
  const quotaPercent = Math.round((mock.quota.used / mock.quota.total) * 100);
  const fileRows = mock.files.map((file) => `
    <tr>
      <td>
        <strong>${file.name}</strong>
        <p class="muted small">${file.folder} - ${file.title}</p>
      </td>
      <td>${formatBytes(file.size)}</td>
      <td>${status(file.status, file.status)}</td>
      <td>${file.downloads}</td>
      <td>${actionButtons(file.name)}</td>
    </tr>
  `);
  return `
    ${pageTitle("Dashboard", "Current folder: /Mods. Demo data is static and safe to click.", '<a class="button" href="#quick-share">Quick share</a>')}
    ${metrics([
      { label: "Storage used", value: `${quotaPercent}%`, note: `${formatBytes(mock.quota.used)} of ${formatBytes(mock.quota.total)}` },
      { label: "Files", value: String(mock.files.length), note: `limit ${mock.quota.maxFiles}` },
      { label: "Folders", value: String(mock.quota.folders), note: "depth limit 6" },
      { label: "Max upload", value: formatBytes(mock.quota.maxFileSize), note: "per file" },
    ])}
    <section class="grid-two">
      <div class="panel stack">
        <h2>Folders</h2>
        <div class="list">
          ${mock.folders.map((folder) => `
            <div class="list-row">
              <div class="chip-row">
                <span class="folder-icon" aria-hidden="true">F</span>
                <span><strong>${folder.name}</strong><span class="meta-note">${folder.path} - ${folder.files} files</span></span>
              </div>
              <div class="split-actions">
                ${folder.shared ? status("Shared", "live") : status("Private", "")}
                <button class="button-quiet" type="button" data-toast="Opened ${folder.name} folder">Open</button>
              </div>
            </div>
          `).join("")}
        </div>
      </div>
      <div class="panel stack">
        <h2>Upload</h2>
        <div class="drop-zone" role="button" tabindex="0" data-toast="Upload picker opened">
          <div>
            <strong>Drop a mod archive here</strong>
            <span class="muted">Static demo: upload progress is illustrative.</span>
          </div>
        </div>
        <div>
          <div class="split-actions">
            <strong>Parahouse Starter Kit.zip</strong>
            <span class="muted">${quotaPercent}%</span>
          </div>
          <div class="progress" aria-label="Storage usage"><span style="--value:${quotaPercent}%"></span></div>
        </div>
      </div>
    </section>
    <section class="panel">
      <h2>Files</h2>
      ${table(["Name", "Size", "Status", "Downloads", "Actions"], fileRows)}
    </section>
    <section class="panel">
      <h2>Active shares</h2>
      ${table(["Type", "Target", "State", "Expires", "Downloads"], mock.shares.map((share) => `
        <tr>
          <td>${share.type}</td>
          <td><a href="#${share.type === "File" ? "public-file" : "public-folder"}">${share.target}</a></td>
          <td>${status(share.state === "live" ? "Live" : "Disabled", share.state)}</td>
          <td>${share.expires}</td>
          <td>${share.downloads}</td>
        </tr>
      `))}
    </section>
  `;
}

function renderQuickShare() {
  return `
    ${pageTitle("Quick share", "Fast public links for a single file or folder.", '<button type="button" data-toast="Copied all demo links">Copy all links</button>')}
    <section class="grid-two">
      <div class="panel stack">
        <h2>Share queue</h2>
        <div class="drop-zone" role="button" tabindex="0" data-toast="Added mock file to queue">
          <div>
            <strong>Drop files to create shares</strong>
            <span class="muted">Links appear immediately after scan in this mockup.</span>
          </div>
        </div>
      </div>
      <div class="panel tint stack">
        <h2>Default settings</h2>
        <label>Target folder<select><option>/Mods</option><option>/Saves</option><option>/Screenshots</option></select></label>
        <label>Expiration<select><option>Never</option><option>7 days</option><option>30 days</option></select></label>
        <button type="button" data-toast="Saved mock quick-share defaults">Save defaults</button>
      </div>
    </section>
    <section class="panel">
      <h2>Recent quick shares</h2>
      <div class="list">
        ${mock.shares.filter((share) => share.state === "live").map((share) => `
          <div class="list-row">
            <span><strong>${share.target}</strong><span class="meta-note">https://parafiles.test/s/${share.slug}</span></span>
            <div class="split-actions">
              ${status("Live", "live")}
              <button class="button-quiet" type="button" data-toast="Copied https://parafiles.test/s/${share.slug}">Copy</button>
            </div>
          </div>
        `).join("")}
      </div>
    </section>
  `;
}

function renderPublicFile() {
  const file = mock.files[0];
  return `
    ${publicTabs("public-file")}
    ${pageTitle(file.title, `Shared by ${mock.admin.username} from /Mods.`, '<button type="button">Download</button><button type="button" class="button-quiet" data-toast="Downloaded mock signature">Download .sig</button>')}
    <section class="grid-two">
      <article class="panel">
        <p>${file.description}</p>
        <dl class="meta-grid">
          <div><dt>Filename</dt><dd>${file.name}</dd></div>
          <div><dt>Version</dt><dd>${file.version}</dd></div>
          <div><dt>Game</dt><dd>${file.game}</dd></div>
          <div><dt>Size</dt><dd>${formatBytes(file.size)}</dd></div>
          <div><dt>Scan</dt><dd>${status("Clean", "ok")}</dd></div>
          <div><dt>Downloads</dt><dd>${file.downloads}</dd></div>
        </dl>
        <div class="release-notes">
          <h2>Changelog</h2>
          <p>${file.changelog}</p>
        </div>
      </article>
      <aside class="panel tint stack">
        <h2>Report this file</h2>
        <label>Category<select><option>Broken download</option><option>Misleading file</option><option>Safety concern</option></select></label>
        <label>Message<textarea>Describe the issue here.</textarea></label>
        <button type="button" data-toast="Submitted mock report">Submit report</button>
      </aside>
    </section>
  `;
}

function renderPublicFolder() {
  return `
    ${publicTabs("public-folder")}
    ${pageTitle("Screenshots", `Shared by ${mock.admin.username}.`, '<button type="button" data-toast="Prepared folder download">Download folder</button>')}
    <section class="panel">
      <h2>Files</h2>
      <div class="list">
        ${mock.files.filter((file) => file.folder === "Screenshots" || file.folder === "Mods").slice(0, 4).map((file) => `
          <div class="list-row">
            <span><strong>${file.name}</strong><span class="meta-note">${formatBytes(file.size)} - ${file.downloads} downloads</span></span>
            <div class="split-actions">
              ${status(file.status, file.status)}
              <a class="button-quiet" href="#public-file">Open</a>
            </div>
          </div>
        `).join("")}
      </div>
    </section>
    <section class="panel tint">
      <h2>Report this folder</h2>
      <div class="form-grid">
        <label>Category<select><option>Broken link</option><option>Unsafe content</option><option>Other</option></select></label>
        <label>Contact email<input value="player@example.test"></label>
        <label class="full-width">Message<input value="One screenshot appears duplicated."></label>
        <button type="button" data-toast="Submitted mock folder report">Submit report</button>
      </div>
    </section>
  `;
}

function renderAccount() {
  return `
    ${pageTitle("Account", "Storage, quota, shares, and recent activity for the pretend admin.", '<button type="button" data-toast="Saved profile changes">Save profile</button>')}
    ${metrics([
      { label: "Storage used", value: formatBytes(mock.quota.used), note: `of ${formatBytes(mock.quota.total)}` },
      { label: "Files", value: String(mock.files.length), note: `limit ${mock.quota.maxFiles}` },
      { label: "Folders", value: String(mock.quota.folders), note: "depth limit 6" },
      { label: "Max file size", value: formatBytes(mock.quota.maxFileSize), note: "per upload" },
    ])}
    <section class="grid-two">
      <form class="panel stack">
        <h2>Profile</h2>
        <label>Display name<input value="${mock.admin.name}"></label>
        <label>Email<input value="${mock.admin.email}"></label>
        <label>Role<input value="${mock.admin.role}"></label>
      </form>
      <div class="panel tint">
        <h2>Active limits</h2>
        <dl class="meta-grid">
          <div><dt>Storage</dt><dd>${formatBytes(mock.quota.total)}</dd></div>
          <div><dt>File size</dt><dd>${formatBytes(mock.quota.maxFileSize)}</dd></div>
          <div><dt>File count</dt><dd>${mock.quota.maxFiles}</dd></div>
          <div><dt>Folder depth</dt><dd>6</dd></div>
        </dl>
      </div>
    </section>
    <section class="panel">
      <h2>Shares</h2>
      ${table(["Type", "Target", "State", "Actions"], mock.shares.map((share) => `
        <tr>
          <td>${share.type}</td>
          <td>${share.target}</td>
          <td>${status(share.state === "live" ? "Live" : "Disabled", share.state)}</td>
          <td>${actionButtons(share.target)}</td>
        </tr>
      `))}
    </section>
    <section class="grid-two">
      <div class="panel">
        <h2>Recent downloads</h2>
        ${table(["File", "Outcome", "Bytes", "Time"], mock.downloads.map((item) => `
          <tr><td>${item.file}</td><td>${item.outcome}</td><td>${formatBytes(item.bytes)}</td><td>${item.time}</td></tr>
        `))}
      </div>
      <div class="panel">
        <h2>Scan status</h2>
        ${table(["File", "Status", "Result"], mock.scans.map((item) => `
          <tr><td>${item.file}</td><td>${status(item.status, item.status)}</td><td>${item.engine}</td></tr>
        `))}
      </div>
    </section>
  `;
}

function renderModeration() {
  return `
    ${adminTabs("moderation")}
    ${pageTitle("Moderation", "Search reports, uploads, folders, and apply targeted actions.", '<button type="button" data-toast="Applied mock filters">Apply filters</button>')}
    ${metrics([
      { label: "Open reports", value: String(mock.reports.filter((r) => r.status === "open").length), note: "needs triage" },
      { label: "Reviewing", value: String(mock.reports.filter((r) => r.status === "review").length), note: "assigned or active" },
      { label: "Files in review", value: "2", note: "scanner or staff review" },
      { label: "Quarantined", value: "1", note: "blocked from download" },
    ])}
    <section class="panel">
      <h2>Filters</h2>
      <div class="filter-grid">
        <label>Query<input value="waterfront"></label>
        <label>Status<select><option>Open or reviewing</option><option>All</option><option>Resolved</option></select></label>
        <label>Category<select><option>Any category</option><option>Broken download</option><option>Safety concern</option></select></label>
        <button type="button" data-toast="Updated mock report filter">Apply filters</button>
      </div>
    </section>
    <section class="panel">
      <h2>Reports</h2>
      ${table(["ID", "Category", "Status", "Target", "Message", "Actions"], mock.reports.map((report) => `
        <tr>
          <td>#${report.id}</td>
          <td>${report.category}<p class="meta-note">Assigned to ${report.assigned}</p></td>
          <td>${status(report.status, report.status === "open" ? "warn" : report.status)}</td>
          <td>${report.target}</td>
          <td>${report.message}</td>
          <td><div class="table-actions"><button class="button-quiet" data-toast="Marked #${report.id} reviewing">Review</button><button class="button-quiet" data-toast="Resolved #${report.id}">Resolve</button></div></td>
        </tr>
      `))}
    </section>
    <section class="panel">
      <h2>Recent files</h2>
      ${table(["Name", "Owner", "Status", "Hash", "Actions"], mock.files.slice(0, 4).map((file) => `
        <tr>
          <td>${file.name}</td>
          <td>${file.owner}</td>
          <td>${status(file.status, file.status)}</td>
          <td class="hash">${file.sha.slice(0, 24)}...</td>
          <td><div class="table-actions"><button class="button-quiet" data-toast="Queued ${file.name} for rescan">Rescan</button><button class="danger" data-toast="Opened delete confirmation">Delete</button></div></td>
        </tr>
      `))}
    </section>
  `;
}

function renderUsers() {
  return `
    ${adminTabs("users")}
    ${pageTitle("Users", "Account-level moderation for uploaders and staff.", '<button type="button" data-toast="Created mock invitation">Invite uploader</button>')}
    <section class="panel">
      <h2>Accounts</h2>
      ${table(["User", "State", "Usage", "Actions"], mock.users.map((user) => `
        <tr>
          <td><strong>${user.username}</strong><p class="meta-note">${user.email}</p></td>
          <td>
            ${status(user.active ? "Active" : "Suspended", user.active ? "ok" : "error")}
            ${user.uploader ? status("Uploader", "uploader") : status("Uploads off", "warn")}
            ${user.staff ? status("Staff", "staff") : ""}
          </td>
          <td>${user.files} files<br>${formatBytes(user.storage)}<br>${user.shares} shares</td>
          <td><div class="table-actions"><button class="button-quiet" data-toast="Opened quota for ${user.username}">Quota</button><button class="button-quiet" data-toast="Disabled shares for ${user.username}">Disable shares</button><button class="danger" data-toast="Opened suspend confirmation for ${user.username}">Suspend</button></div></td>
        </tr>
      `))}
    </section>
  `;
}

function renderOperations() {
  return `
    ${adminTabs("operations")}
    ${pageTitle("Operations", "Health checks for the file-sharing backend, shown with static demo values.", '<button type="button" data-toast="Refreshed mock checks">Refresh checks</button>')}
    <section class="grid-two">
      <div class="panel">
        <h2>Checks</h2>
        ${table(["Check", "Status", "Detail"], mock.operations.map((item) => `
          <tr><td>${item.check}</td><td>${status(item.status === "ok" ? "OK" : "Warning", item.status)}</td><td>${item.detail}</td></tr>
        `))}
      </div>
      <div class="panel tint stack">
        <h2>Rate limits</h2>
        <div class="mini-card"><strong>Downloads per minute</strong><p class="muted">18 of 120 used</p><div class="progress"><span style="--value:15%"></span></div></div>
        <div class="mini-card"><strong>Upload starts per hour</strong><p class="muted">4 of 30 used</p><div class="progress"><span style="--value:13%"></span></div></div>
      </div>
    </section>
  `;
}

function renderAudit() {
  return `
    ${adminTabs("audit")}
    ${pageTitle("Audit log", "Recent staff actions and reasons.", '<button type="button" data-toast="Exported mock audit CSV">Export CSV</button>')}
    <section class="panel">
      <h2>Actions</h2>
      ${table(["Time", "Actor", "Target", "Action", "Reason"], mock.audit.map((item) => `
        <tr><td>${item.time}</td><td>${item.actor}</td><td>${item.target}</td><td>${item.action}</td><td>${item.reason}</td></tr>
      `))}
    </section>
  `;
}

function renderStyle() {
  const colors = [
    ["Cream", "#fff9f4"],
    ["Ink", "#2a3832"],
    ["Sage", "#5cb88a"],
    ["Mint", "#b8e8d4"],
    ["Peach", "#ffdac1"],
    ["Coral", "#ff7b6b"],
    ["Sky", "#9ee0f5"],
    ["Lavender", "#d4c4f5"],
    ["Lemon", "#fff3a0"],
    ["Official dark", "#3c342f"],
    ["Overlay", "#0f0606"],
    ["Gold link", "#d88518"],
  ];
  return `
    ${pageTitle("Theme", "Reusable tokens and component examples from the Paralives theme notes.", '<a class="button-quiet" href="README.md">Open README</a>')}
    <section class="panel">
      <h2>Palette</h2>
      <div class="color-grid">
        ${colors.map(([name, value]) => `
          <div class="swatch">
            <span style="--swatch:${value}"></span>
            <strong>${name}</strong>
            <small>${value}</small>
          </div>
        `).join("")}
      </div>
    </section>
    <section class="grid-two">
      <div class="panel stack">
        <h2>Controls</h2>
        <div class="chip-row">
          <button type="button">Primary action</button>
          <button type="button" class="button-quiet">Secondary</button>
          <button type="button" class="danger">Danger</button>
        </div>
        <label>Search<input value="starter kit"></label>
        <label>Status<select><option>Available</option><option>Review</option><option>Quarantined</option></select></label>
      </div>
      <div class="panel tint stack">
        <h2>Badges</h2>
        <div class="chip-row">
          ${status("Available", "available")}
          ${status("Review", "review")}
          ${status("Quarantined", "quarantined")}
          ${status("Staff", "staff")}
          ${status("Uploader", "uploader")}
        </div>
      </div>
    </section>
  `;
}

const renderers = {
  home: renderHome,
  login: renderLogin,
  dashboard: renderDashboard,
  "quick-share": renderQuickShare,
  "public-file": renderPublicFile,
  "public-folder": renderPublicFolder,
  account: renderAccount,
  moderation: renderModeration,
  users: renderUsers,
  operations: renderOperations,
  audit: renderAudit,
  style: renderStyle,
};

function getRoute() {
  const route = window.location.hash.replace(/^#/, "") || "home";
  return renderers[route] ? route : "home";
}

function setActiveNav(route) {
  document.querySelectorAll(".site-nav a").forEach((link) => {
    link.classList.toggle("is-active", link.getAttribute("href") === `#${route}`);
  });
}

function render() {
  state.route = getRoute();
  document.title = `${routeMeta[state.route]} - Parafiles Theme Mockup 2`;
  app.innerHTML = renderers[state.route]();
  setActiveNav(state.route);
  document.body.classList.remove("nav-open");
  navToggle.setAttribute("aria-expanded", "false");
  document.getElementById("main").focus({ preventScroll: true });
}

function showToast(message) {
  toast.textContent = message;
  toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    toast.hidden = true;
  }, 2600);
}

navToggle.addEventListener("click", () => {
  const open = !document.body.classList.contains("nav-open");
  document.body.classList.toggle("nav-open", open);
  navToggle.setAttribute("aria-expanded", String(open));
});

siteNav.addEventListener("click", () => {
  document.body.classList.remove("nav-open");
  navToggle.setAttribute("aria-expanded", "false");
});

document.addEventListener("click", (event) => {
  const toastTarget = event.target.closest("[data-toast]");
  if (!toastTarget) return;
  event.preventDefault();
  showToast(toastTarget.getAttribute("data-toast"));
});

document.addEventListener("keydown", (event) => {
  if ((event.key === "Enter" || event.key === " ") && event.target.matches(".drop-zone")) {
    event.preventDefault();
    showToast(event.target.getAttribute("data-toast"));
  }
});

window.addEventListener("hashchange", render);
render();
