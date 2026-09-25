/* ============================== state & api ============================== */
let TOKEN = localStorage.getItem('js_token') || null;
let USER = JSON.parse(localStorage.getItem('js_user') || 'null');
let CURRENT_PAGE = null;

async function api(path, method = 'GET', body) {
  const headers = { 'Content-Type': 'application/json' };
  if (TOKEN) headers.Authorization = 'Bearer ' + TOKEN;
  const res = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Something went wrong');
  return data;
}

function toast(msg, err) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast' + (err ? ' err' : '');
  t.style.display = 'block';
  clearTimeout(toast._h);
  toast._h = setTimeout(() => (t.style.display = 'none'), 3000);
}

/* ============================== auth screen ============================== */
function setAuthMode(mode) {
  document.getElementById('tabLogin').classList.toggle('active', mode === 'login');
  document.getElementById('tabRegister').classList.toggle('active', mode === 'register');
  document.getElementById('loginForm').classList.toggle('hidden', mode !== 'login');
  document.getElementById('registerForm').classList.toggle('hidden', mode !== 'register');
  document.getElementById('authError').classList.add('hidden');
}

function onRoleChange() {
  const role = document.getElementById('regRole').value;
  document.getElementById('expertiseField').classList.toggle('hidden', role !== 'college');
}

function showAuthError(msg) {
  const e = document.getElementById('authError');
  e.textContent = msg;
  e.classList.remove('hidden');
}

async function handleLogin(e) {
  e.preventDefault();
  try {
    const data = await api('/api/login', 'POST', {
      email: document.getElementById('loginEmail').value,
      password: document.getElementById('loginPassword').value,
    });
    saveSession(data.token, data.user);
  } catch (err) {
    showAuthError(err.message);
  }
  return false;
}

async function handleRegister(e) {
  e.preventDefault();
  try {
    const data = await api('/api/register', 'POST', {
      name: document.getElementById('regName').value,
      email: document.getElementById('regEmail').value,
      password: document.getElementById('regPassword').value,
      role: document.getElementById('regRole').value,
      org: document.getElementById('regOrg').value,
      expertise: document.getElementById('regExpertise').value,
    });
    saveSession(data.token, data.user);
  } catch (err) {
    showAuthError(err.message);
  }
  return false;
}

function saveSession(token, user) {
  TOKEN = token; USER = user;
  localStorage.setItem('js_token', token);
  localStorage.setItem('js_user', JSON.stringify(user));
  boot();
}

function logout() {
  TOKEN = null; USER = null;
  localStorage.removeItem('js_token'); localStorage.removeItem('js_user');
  boot();
}

/* ============================== nav / shell ============================== */
const NAV = {
  citizen: [['dashboard', 'Dashboard'], ['report', 'Report Problem'], ['mine', 'My Problems']],
  expert: [['dashboard', 'Dashboard'], ['verify', 'Verify Problems']],
  college: [['dashboard', 'Dashboard'], ['matched', 'Matched Problems']],
  industry: [['dashboard', 'Dashboard'], ['support', 'Support Problems']],
  government: [['dashboard', 'Dashboard'], ['verify', 'Verify Problems'], ['decide', 'Approve & Implement']],
};
const ROLE_LABEL = { citizen: 'Citizen', expert: 'Expert', college: 'College', industry: 'Industry', government: 'Government' };

function boot() {
  if (TOKEN && USER) {
    document.getElementById('authScreen').classList.add('hidden');
    document.getElementById('appRoot').classList.remove('hidden');
    document.getElementById('whoAmI').textContent = `${USER.name} · ${ROLE_LABEL[USER.role]}`;
    const nav = document.getElementById('navList');
    nav.innerHTML = '';
    NAV[USER.role].forEach(([id, label]) => {
      const b = document.createElement('button');
      b.textContent = label;
      b.onclick = () => showPage(id, b);
      nav.appendChild(b);
    });
    showPage('dashboard', nav.firstChild);
  } else {
    document.getElementById('authScreen').classList.remove('hidden');
    document.getElementById('appRoot').classList.add('hidden');
  }
}

function showPage(id, btn) {
  CURRENT_PAGE = id;
  document.querySelectorAll('.nav button').forEach(b => b.classList.remove('active'));
  if (btn) btn.classList.add('active');
  const titles = {
    dashboard: 'Dashboard', report: 'Report a Problem', mine: 'My Problems',
    verify: 'Verify Problems', matched: 'Matched Problems', support: 'Support Problems',
    decide: 'Approve & Implement',
  };
  document.getElementById('title').textContent = titles[id] || 'Dashboard';
  const body = document.getElementById('pageBody');
  body.innerHTML = '<p class="muted">Loading…</p>';
  const renderers = {
    dashboard: renderDashboard, report: renderReport, mine: () => renderProblemList('mine'),
    verify: () => renderProblemList('verify'), matched: () => renderProblemList('matched'),
    support: () => renderProblemList('support'), decide: () => renderProblemList('decide'),
  };
  (renderers[id] || renderDashboard)().catch(err => {
    body.innerHTML = `<div class="panel">Could not load this page: ${escapeHtml(err.message)}</div>`;
  });
}

function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}
function fmtDate(t) { return new Date(t * 1000).toLocaleString(); }

const STATUS_COLOR = {
  submitted: 'blue', verified: 'blue', matched: 'blue', in_progress: 'orange',
  solution_submitted: 'orange', funded: 'orange', approved: 'green', implemented: 'green', rejected: 'red',
};
const STATUS_LABEL = {
  submitted: 'AI triaged', verified: 'Verified', matched: 'Matched', in_progress: 'Building',
  solution_submitted: 'Solution submitted', funded: 'Funded', approved: 'Approved',
  implemented: 'Implemented', rejected: 'Rejected',
};

/* ============================== dashboard ============================== */
async function renderDashboard() {
  const [stats, problems] = await Promise.all([api('/api/dashboard'), api('/api/problems')]);
  const s = stats.by_status || {};
  const cards = [
    [stats.total || 0, 'Total problems'],
    [(s.implemented || 0), 'Implemented'],
    [stats.avg_rating || '—', `Avg rating (${stats.feedback_count || 0})`],
    ['₹' + (stats.funding_total || 0).toLocaleString('en-IN'), 'Funding raised'],
  ];
  const recent = problems.slice(0, 5).map(p => `
    <div class="problem" onclick="openDetail(${p.id})">
      <b>${escapeHtml(p.title)}</b><br>
      <span class="muted">${escapeHtml(p.category)} • ${escapeHtml(p.priority)} priority</span><br>
      <span class="status ${STATUS_COLOR[p.status] || 'gray'}">${STATUS_LABEL[p.status] || p.status}</span>
    </div>`).join('') || '<p class="muted">No problems yet.</p>';

  document.getElementById('pageBody').innerHTML = `
    <div class="cards">${cards.map(c => `<div class="card"><div class="num">${escapeHtml(String(c[0]))}</div><div class="muted">${c[1]}</div></div>`).join('')}</div>
    <div class="grid">
      <div class="panel"><h2>Recent Problems</h2>${recent}</div>
      <div class="panel"><h2>Solution Pipeline</h2>
        <div class="flow">
          ${['Citizen Report', 'AI Triage', 'Expert', 'College', 'Industry', 'Govt.'].map(s => `<div class="step">${s}</div>`).join('<span class="arrow">→</span>')}
        </div>
        <p class="muted" style="margin-top:18px">Every status change is tracked so citizens can see where their problem stands.</p>
      </div>
    </div>
    <div id="detailSlot"></div>`;
}

/* ============================== report a problem (citizen) ============================== */
async function renderReport() {
  document.getElementById('pageBody').innerHTML = `
    <div class="panel" style="max-width:760px">
      <h2>Report a Local Problem</h2>
      <form onsubmit="return submitProblem(event)">
        <label>Problem title</label><input id="pTitle" required minlength="5" placeholder="e.g. Water shortage in village">
        <label>Location</label><input id="pLoc" placeholder="Village / District">
        <label>Description</label><textarea id="pDesc" required minlength="10" placeholder="Describe the problem and its impact..."></textarea>
        <button class="btn">Submit for AI Triage</button>
      </form>
    </div>`;
}
async function submitProblem(e) {
  e.preventDefault();
  try {
    const r = await api('/api/problems', 'POST', {
      title: document.getElementById('pTitle').value,
      location: document.getElementById('pLoc').value,
      description: document.getElementById('pDesc').value,
    });
    toast(`AI triage complete — ${r.category} / ${r.priority} priority`);
    document.querySelectorAll('.nav button')[2] && showPage('mine', document.querySelectorAll('.nav button')[2]);
  } catch (err) { toast(err.message, true); }
  return false;
}

/* ============================== generic problem list per role/page ============================== */
const LIST_CONFIG = {
  mine: { fetchStatus: null },
  verify: { fetchStatus: 'submitted' },
  matched: { fetchStatus: 'matched' },
  support: { fetchStatus: null, filter: p => ['solution_submitted', 'funded'].includes(p.status) },
  decide: { fetchStatus: null, filter: p => ['solution_submitted', 'funded', 'approved'].includes(p.status) },
};

async function renderProblemList(page) {
  const cfg = LIST_CONFIG[page];
  let problems = await api('/api/problems' + (cfg.fetchStatus ? `?status=${cfg.fetchStatus}` : ''));
  if (cfg.filter) problems = problems.filter(cfg.filter);
  const list = problems.map(p => `
    <div class="problem" onclick="openDetail(${p.id})">
      <b>${escapeHtml(p.title)}</b><br>
      <span class="muted">${escapeHtml(p.category)} • ${escapeHtml(p.priority)} priority • ${escapeHtml(p.location || '')}</span><br>
      <span class="status ${STATUS_COLOR[p.status] || 'gray'}">${STATUS_LABEL[p.status] || p.status}</span>
    </div>`).join('') || '<p class="muted">Nothing here right now.</p>';
  document.getElementById('pageBody').innerHTML = `<div class="panel">${list}</div><div id="detailSlot"></div>`;
}

/* ============================== problem detail + role actions ============================== */
async function openDetail(pid) {
  const slot = document.getElementById('detailSlot');
  if (!slot) return;
  slot.innerHTML = '<p class="muted">Loading details…</p>';
  try {
    const p = await api('/api/problems/' + pid);
    slot.innerHTML = buildDetailHtml(p);
    slot.scrollIntoView({ behavior: 'smooth', block: 'start' });
    wireDetailForms(p);
  } catch (err) {
    slot.innerHTML = `<div class="panel">${escapeHtml(err.message)}</div>`;
  }
}

function buildDetailHtml(p) {
  const matches = (p.matches || []).map(m => `
    <div class="match"><div><b>${escapeHtml(m.org || m.name)}</b><br><span class="muted">Match score ${m.score}</span></div>
    ${p.college_id === m.college_id ? '<span class="status green">Assigned</span>' : ''}</div>`).join('');
  const solutions = (p.solutions || []).map(s => `
    <div class="panel"><h2>Solution: ${escapeHtml(s.title)}</h2><p>${escapeHtml(s.description)}</p><span class="muted">${escapeHtml(s.college)} · Team: ${escapeHtml(s.team || '—')}</span></div>`).join('');
  const support = (p.support || []).map(s => `
    <div class="problem"><b>${escapeHtml(s.industry || s.industry_name)}</b> — ${escapeHtml(s.kind)}${s.kind === 'funding' ? ' ₹' + s.amount : ''} ${escapeHtml(s.note || '')}</div>`).join('');
  const feedback = (p.feedback || []).map(f => `<p>${'★'.repeat(f.rating)}${'☆'.repeat(5 - f.rating)} ${escapeHtml(f.comment || '')}</p>`).join('');
  const timeline = (p.events || []).map(e => `<li><b>${STATUS_LABEL[e.status] || e.status}</b> — ${escapeHtml(e.actor)} ${escapeHtml(e.note || '')}<div class="muted">${fmtDate(e.at)}</div></li>`).join('');

  return `
    <div class="panel" id="detailPanel" data-pid="${p.id}">
      <h2>${escapeHtml(p.title)}</h2>
      <span class="status ${STATUS_COLOR[p.status] || 'gray'}">${STATUS_LABEL[p.status] || p.status}</span>
      <span class="status gray">${escapeHtml(p.category)}</span>
      <span class="status gray">${escapeHtml(p.priority)} priority</span>
      <p style="margin-top:14px">${escapeHtml(p.description)}</p>
      <p class="muted">${escapeHtml(p.location || '')} · Reported by ${escapeHtml(p.citizen)} · ${fmtDate(p.created_at)}</p>
      <p class="muted"><b>AI summary:</b> ${escapeHtml(p.ai_summary || '')}</p>
      ${matches ? `<h2>Matched Colleges</h2>${matches}` : ''}
      ${solutions}
      ${support ? `<h2>Industry Support</h2>${support}` : ''}
      ${feedback ? `<h2>Citizen Feedback</h2>${feedback}` : ''}
      <div id="actionSlot">${actionFormHtml(p)}</div>
      <h2 style="margin-top:22px">History</h2>
      <ul class="timeline">${timeline}</ul>
    </div>`;
}

function actionFormHtml(p) {
  const role = USER.role, status = p.status;
  if ((role === 'expert' || role === 'government') && status === 'submitted') {
    return `
      <h2>Verify this problem</h2>
      <form id="verifyForm">
        <label>Note</label><input id="vNote" placeholder="optional">
        <div class="btn-row">
          <button class="btn" type="submit" data-approve="true">Verify &amp; approve</button>
          <button class="btn danger" type="submit" data-approve="false">Reject</button>
        </div>
      </form>`;
  }
  if (role === 'college' && status === 'matched' && (p.matches || []).some(m => m.college_id === USER.id)) {
    return `<button class="btn" id="acceptBtn">Accept this problem for our college</button>`;
  }
  if (role === 'college' && status === 'in_progress' && p.college_id === USER.id) {
    return `
      <h2>Submit your solution</h2>
      <form id="solutionForm">
        <label>Solution title</label><input id="sTitle" required>
        <label>Description / technology / prototype</label><textarea id="sDesc" required></textarea>
        <label>Team (students + faculty)</label><input id="sTeam">
        <button class="btn">Submit solution</button>
      </form>`;
  }
  if (role === 'industry' && ['solution_submitted', 'funded'].includes(status)) {
    return `
      <h2>Offer support</h2>
      <form id="supportForm">
        <label>Type</label>
        <select id="supKind"><option value="funding">Funding</option><option value="technology">Technology</option><option value="mentorship">Mentorship</option></select>
        <label>Amount ₹ (funding only)</label><input id="supAmount" type="number" min="0" value="0">
        <label>Note</label><input id="supNote">
        <button class="btn">Submit support</button>
      </form>`;
  }
  if (role === 'government' && ['solution_submitted', 'funded'].includes(status)) {
    return `
      <h2>Government decision</h2>
      <form id="decisionForm">
        <label>Note</label><input id="decNote">
        <div class="btn-row">
          <button class="btn" type="submit" data-action="approve">Approve</button>
          <button class="btn danger" type="submit" data-action="reject">Send back</button>
        </div>
      </form>`;
  }
  if (role === 'government' && status === 'approved') {
    return `
      <h2>Mark as implemented</h2>
      <form id="implementForm">
        <label>Note</label><input id="implNote">
        <button class="btn">Mark implemented</button>
      </form>`;
  }
  if (role === 'citizen' && status === 'implemented' && !(p.feedback || []).length) {
    return `
      <h2>Your feedback</h2>
      <form id="feedbackForm">
        <label>Rating</label>
        <select id="fbRating">${[5, 4, 3, 2, 1].map(n => `<option value="${n}">${n} / 5</option>`).join('')}</select>
        <label>Comment</label><textarea id="fbComment"></textarea>
        <button class="btn">Send feedback</button>
      </form>`;
  }
  return '';
}

function wireDetailForms(p) {
  const pid = p.id;
  const reload = () => openDetail(pid);

  const verifyForm = document.getElementById('verifyForm');
  if (verifyForm) verifyForm.addEventListener('submit', async e => {
    e.preventDefault();
    const approve = e.submitter.dataset.approve === 'true';
    try {
      await api(`/api/problems/${pid}/verify`, 'POST', { approve, note: document.getElementById('vNote').value });
      toast(approve ? 'Problem verified' : 'Problem rejected');
      reload();
    } catch (err) { toast(err.message, true); }
  });

  const acceptBtn = document.getElementById('acceptBtn');
  if (acceptBtn) acceptBtn.addEventListener('click', async () => {
    try { await api(`/api/problems/${pid}/accept`, 'POST'); toast('Problem accepted'); reload(); }
    catch (err) { toast(err.message, true); }
  });

  const solutionForm = document.getElementById('solutionForm');
  if (solutionForm) solutionForm.addEventListener('submit', async e => {
    e.preventDefault();
    try {
      await api(`/api/problems/${pid}/solution`, 'POST', {
        title: document.getElementById('sTitle').value,
        description: document.getElementById('sDesc').value,
        team: document.getElementById('sTeam').value,
      });
      toast('Solution submitted'); reload();
    } catch (err) { toast(err.message, true); }
  });

  const supportForm = document.getElementById('supportForm');
  if (supportForm) supportForm.addEventListener('submit', async e => {
    e.preventDefault();
    try {
      await api(`/api/problems/${pid}/support`, 'POST', {
        kind: document.getElementById('supKind').value,
        amount: Number(document.getElementById('supAmount').value || 0),
        note: document.getElementById('supNote').value,
      });
      toast('Support submitted'); reload();
    } catch (err) { toast(err.message, true); }
  });

  const decisionForm = document.getElementById('decisionForm');
  if (decisionForm) decisionForm.addEventListener('submit', async e => {
    e.preventDefault();
    const action = e.submitter.dataset.action;
    try {
      await api(`/api/problems/${pid}/decision`, 'POST', { action, note: document.getElementById('decNote').value });
      toast(action === 'approve' ? 'Approved' : 'Sent back for revision'); reload();
    } catch (err) { toast(err.message, true); }
  });

  const implementForm = document.getElementById('implementForm');
  if (implementForm) implementForm.addEventListener('submit', async e => {
    e.preventDefault();
    try {
      await api(`/api/problems/${pid}/decision`, 'POST', { action: 'implement', note: document.getElementById('implNote').value });
      toast('Marked as implemented'); reload();
    } catch (err) { toast(err.message, true); }
  });

  const feedbackForm = document.getElementById('feedbackForm');
  if (feedbackForm) feedbackForm.addEventListener('submit', async e => {
    e.preventDefault();
    try {
      await api(`/api/problems/${pid}/feedback`, 'POST', {
        rating: Number(document.getElementById('fbRating').value),
        comment: document.getElementById('fbComment').value,
      });
      toast('Thanks for your feedback'); reload();
    } catch (err) { toast(err.message, true); }
  });
}

/* ============================== boot ============================== */
boot();
