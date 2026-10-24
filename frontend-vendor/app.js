/* Vendor Portal — separate website for marketplace vendors.
   Talks to the same /api backend as the customer site. */

const $ = (sel) => document.querySelector(sel);

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
/* v52: display name for a dish — Arabic name in AR mode when the dish has
   one (mirrors the bundle pattern), else the English name. */
function dname(d) { return (lang() === 'ar' && d && d.name_ar) ? d.name_ar : (d ? d.name : ''); }
/* v52: display name for an ORDER ITEM — the Arabic snapshot taken at order
   time; older orders have NULL there and fall back to the English snapshot. */
function iname(i) { return (lang() === 'ar' && i && i.dish_name_ar) ? i.dish_name_ar : (i ? i.dish_name : ''); }

function money(v) {
  const n = Number(v);
  return '$' + (isNaN(n) ? '0.00' : n.toFixed(2));
}
function discOf(d) { return Number(d.discount_percent) || 0; }
function saleOf(d) {
  if (d.sale_price != null && d.sale_price !== '') return Number(d.sale_price);
  return Math.round(Number(d.price) * (1 - discOf(d) / 100) * 100) / 100;
}
function vPriceHTML(d) {
  if (!discOf(d)) return money(d.price);
  return '<s style="color:var(--muted)">' + money(d.price) + '</s> <strong>' + money(saleOf(d)) + '</strong>';
}

function mapsUrl(addr) {
  // Official Google Maps universal URL — no API key needed.
  return 'https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(addr || '');
}

/* US states for the shop-address state dropdown: [code, English, Arabic]. */
const US_STATES = [
  ['AL', 'Alabama', 'ألاباما'], ['AK', 'Alaska', 'ألاسكا'], ['AZ', 'Arizona', 'أريزونا'],
  ['AR', 'Arkansas', 'أركنساس'], ['CA', 'California', 'كاليفورنيا'], ['CO', 'Colorado', 'كولورادو'],
  ['CT', 'Connecticut', 'كونيتيكت'], ['DE', 'Delaware', 'ديلاوير'], ['FL', 'Florida', 'فلوريدا'],
  ['GA', 'Georgia', 'جورجيا'], ['HI', 'Hawaii', 'هاواي'], ['ID', 'Idaho', 'أيداهو'],
  ['IL', 'Illinois', 'إلينوي'], ['IN', 'Indiana', 'إنديانا'], ['IA', 'Iowa', 'آيوا'],
  ['KS', 'Kansas', 'كانساس'], ['KY', 'Kentucky', 'كنتاكي'], ['LA', 'Louisiana', 'لويزيانا'],
  ['ME', 'Maine', 'مين'], ['MD', 'Maryland', 'ماريلاند'], ['MA', 'Massachusetts', 'ماساتشوستس'],
  ['MI', 'Michigan', 'ميشيغان'], ['MN', 'Minnesota', 'مينيسوتا'], ['MS', 'Mississippi', 'مسيسيبي'],
  ['MO', 'Missouri', 'ميزوري'], ['MT', 'Montana', 'مونتانا'], ['NE', 'Nebraska', 'نبراسكا'],
  ['NV', 'Nevada', 'نيفادا'], ['NH', 'New Hampshire', 'نيو هامبشير'], ['NJ', 'New Jersey', 'نيو جيرسي'],
  ['NM', 'New Mexico', 'نيو مكسيكو'], ['NY', 'New York', 'نيويورك'], ['NC', 'North Carolina', 'نورث كارولاينا'],
  ['ND', 'North Dakota', 'نورث داكوتا'], ['OH', 'Ohio', 'أوهايو'], ['OK', 'Oklahoma', 'أوكلاهوما'],
  ['OR', 'Oregon', 'أوريغون'], ['PA', 'Pennsylvania', 'بنسلفانيا'], ['RI', 'Rhode Island', 'رود آيلاند'],
  ['SC', 'South Carolina', 'ساوث كارولاينا'], ['SD', 'South Dakota', 'ساوث داكوتا'], ['TN', 'Tennessee', 'تينيسي'],
  ['TX', 'Texas', 'تكساس'], ['UT', 'Utah', 'يوتا'], ['VT', 'Vermont', 'فيرمونت'],
  ['VA', 'Virginia', 'فرجينيا'], ['WA', 'Washington', 'واشنطن'], ['WV', 'West Virginia', 'وست فرجينيا'],
  ['WI', 'Wisconsin', 'ويسكونسن'], ['WY', 'Wyoming', 'وايومنغ'],
];
function stateOptions(selected) {
  const ar = (typeof lang === 'function' && lang() === 'ar');
  return '<option value="">' + esc(t('addr_state_ph')) + '</option>' +
    US_STATES.map(s => '<option value="' + s[0] + '"' + (s[0] === selected ? ' selected' : '') + '>' +
      esc(ar ? s[2] : s[1]) + '</option>').join('');
}

function mapsLink(addr, label) {
  if (!addr) return '';
  return ' <a href="' + mapsUrl(addr) + '" target="_blank" rel="noopener">📍 ' +
    esc(label || t('maps_view')) + '</a>';
}

function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d)) return String(iso);
  return d.toLocaleString(lang() === 'ar' ? 'ar-EG' : 'en-US', {
    timeZone: 'America/Los_Angeles',
    dateStyle: 'medium',
    timeStyle: 'short',
  });
}
function fmtPickupDate(iso) {
  if (!iso) return '—';
  const value = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/.test(String(iso))
    ? String(iso) + 'Z'
    : iso;
  const d = new Date(value);
  if (isNaN(d)) return String(iso);
  return d.toLocaleString(lang() === 'ar' ? 'ar-EG' : 'en-US', {
    timeZone: 'America/Los_Angeles',
    dateStyle: 'medium',
    timeStyle: 'short',
  });
}

async function api(path, opts) {
  opts = opts || {};
  const headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
  if (S.token) headers['Authorization'] = 'Bearer ' + S.token;
  const res = await fetch('/api' + path, Object.assign({}, opts, { headers }));
  if (res.status === 401) { logout(true); throw new Error(t('session_expired')); }
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); if (j && j.detail) msg = j.detail; } catch (e) { /* ignore */ }
    const err = new Error(msg);
    err.status = res.status; // let callers distinguish 401/403 from transient failures
    throw err;
  }
  if (res.status === 204) return null;
  return res.json();
}

async function loadMe() {
  if (!S.token) { S.user = null; return; }
  try { S.user = await api('/auth/me'); }
  catch (e) {
    S.user = null;
    // Only wipe the stored session when the server positively rejects it
    // (401/403). A transient network failure (e.g. the dev server mid-restart
    // under --reload) must not destroy the session. Note: api() already calls
    // logout(true) on 401 before throwing, so this check mainly guards 403s.
    if (e && (e.status === 401 || e.status === 403)) { S.token = null; localStorage.removeItem('ehf_token'); }
  }
}

function logout(silent) {
  S.token = null; S.user = null;
  localStorage.removeItem('ehf_token');
  updateAuthArea();
  if (!silent) go('home');
}


const S = {
  token: localStorage.getItem('ehf_token') || null,
  user: null,
  route: 'home',
  routeArg: null,
  dishById: {},
  categories: [],
  portal: { vendorId: null, vendor: null, orders: [], earnings: null, menu: [], timer: null, currentOrder: null, currentEvents: null },
};

function updateAuthArea() {
  const area = $('#auth-area');
  if (S.user) {
    area.innerHTML = '<span class="user-chip">' + esc(S.user.name || S.user.email) + '</span> ' +
      '<a href="#" onclick="logout();return false;">' + esc(t('nav_logout')) + '</a>';
  } else {
    area.innerHTML = '<a href="#" data-go="login">' + esc(t('nav_login')) + '</a>';
  }
  document.querySelectorAll('#main-nav a').forEach(a => {
    a.classList.toggle('active', a.dataset.go === S.route);
  });
  const isVendor = S.user && S.user.role === 'vendor';
  const isAdmin = S.user && S.user.role === 'admin';
  const revLink = document.getElementById('nav-reviews');
  if (revLink) revLink.style.display = isVendor ? '' : 'none';
  const settingsLink = document.getElementById('nav-settings');
  if (settingsLink) settingsLink.style.display = isVendor ? '' : 'none';
  const reportsLink = document.getElementById('nav-reports');
  if (reportsLink) reportsLink.style.display = isVendor ? '' : 'none';
  const payoutsLink = document.getElementById('nav-payouts');
  if (payoutsLink) payoutsLink.style.display = isVendor ? '' : 'none';
  const problemsLink = document.getElementById('nav-problems'); // === F6 ===
  if (problemsLink) problemsLink.style.display = isVendor ? '' : 'none';
  const portalLink = document.getElementById('nav-portal');
  if (portalLink) portalLink.style.display = (isAdmin || isStaffUser()) ? 'none' : '';
  const stockLink = document.getElementById('nav-stock');
  if (stockLink) stockLink.style.display = isVendor ? '' : 'none';
  const supportLink = document.getElementById('nav-support');
  if (supportLink) supportLink.style.display = (isVendor || isAdmin || isStaffUser()) ? '' : 'none';
  const adminLink = document.getElementById('nav-admin');
  if (adminLink) adminLink.style.display = (isAdmin || isStaffUser()) ? '' : 'none';
}
window.logout = logout;

function go(route, arg) {
  stopPortalPoll();
  S.route = route;
  S.routeArg = (arg === undefined ? null : arg);
  window.scrollTo(0, 0);
  render();
  updateAuthArea();
}
window.go = go;

document.addEventListener('click', (e) => {
  const a = e.target.closest('[data-go]');
  if (a) { e.preventDefault(); go(a.dataset.go); }
});

function render() {
  stopPortalPoll();
  updateAuthArea();
  const appEl = $('#app');
  let html = '<div id="view"></div>';
  const isAdmin = S.user && S.user.role === 'admin';
  const bo = isBackOffice(); // === v40+: admins + staff land in the back-office ===
  if (S.route === 'home' && S.user && S.user.role === 'vendor') S.route = 'portal'; // logged-in vendors skip the landing
  if (S.route === 'home' && bo) S.route = 'admin'; // admins/staff land in the back-office
  if (bo && ['portal', 'order', 'settings', 'reports', 'payouts', 'reviews', 'problems', 'stock'].includes(S.route)) S.route = 'admin';
  if (!bo && S.route === 'admin') S.route = 'home';
  if (S.route === 'login') html = vLogin();
  else if (S.route === 'home') html = vVendorHome();
  else if (S.route !== 'portal' && S.route !== 'order' && S.route !== 'settings' && S.route !== 'reports' && S.route !== 'payouts' && S.route !== 'reviews' && S.route !== 'problems' && S.route !== 'support' && S.route !== 'admin' && S.route !== 'stock') S.route = 'home';
  appEl.innerHTML = html;
  if (S.route === 'portal') vPortal();
  else if (S.route === 'stock') vStock();
  else if (S.route === 'order') vOrderDetail(S.routeArg);
  else if (S.route === 'settings') vSettings();
  else if (S.route === 'reports') vReports();
  else if (S.route === 'payouts') vPayouts();
  else if (S.route === 'reviews') vReviews();
  else if (S.route === 'problems') vProblems(); // === F6: vendor problem reports ===
  else if (S.route === 'support') vSupport();
  else if (S.route === 'admin') vAdmin();
}

/* Vendor home / landing page. */
function vVendorHome() {
  return '<section class="hero"><div class="hero-overlay">' +
    '<h1>' + esc(t('land_title')) + '</h1>' +
    '<p>' + esc(t('land_sub')) + '</p>' +
    '<a class="btn" href="#" data-go="login">' + esc(t('land_login')) + '</a> ' +
    '<a class="btn secondary" href="/">' + esc(t('land_browse')) + '</a>' +
    '</div></section>' +
    '<h2 class="section-title">' + esc(t('land_how')) + '</h2>' +
    '<div class="grid">' +
    '<div class="vendor-card"><h3>' + esc(t('land_s1t')) + '</h3>' +
    '<p class="tagline">' + esc(t('land_s1d')) + '</p></div>' +
    '<div class="vendor-card"><h3>' + esc(t('land_s2t')) + '</h3>' +
    '<p class="tagline">' + esc(t('land_s2d')) + '</p></div>' +
    '<div class="vendor-card"><h3>' + esc(t('land_s3t')) + '</h3>' +
    '<p class="tagline">' + esc(t('land_s3d')) + '</p></div>' +
    '</div>';
}

/* Vendor login (vendors only here). */
function vLogin() {
  return '<div class="form-card"><h2>' + esc(t('login_title')) + '</h2>' +
    '<div class="hint">' + esc(t('login_demo')) + ' <code>vendor@demo.com</code> / <code>demo1234</code><br>' + esc(t('login_demo_admin')) + ' <code>admin@demo.com</code> / <code>demo1234</code></div>' +
    '<div id="login-err"></div>' +
    '<label class="field">' + esc(t('email_label')) + '</label><input type="email" id="li-email" autocomplete="email">' +
    '<label class="field">' + esc(t('password_label')) + '</label><input type="password" id="li-pass" autocomplete="current-password">' +
    '<div class="mt"><button class="btn" style="width:100%" onclick="doLogin()">' + esc(t('login_btn')) + '</button></div></div>';
}
window.doLogin = async function () {
  const err = $('#login-err');
  err.innerHTML = '';
  try {
    const r = await api('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email: $('#li-email').value.trim(), password: $('#li-pass').value }),
    });
    S.token = r.access_token;
    localStorage.setItem('ehf_token', S.token);
    await loadMe();
    updateAuthArea();
    go(isBackOffice() ? 'admin' : 'portal');
  } catch (e) { err.innerHTML = '<div class="error">' + esc(e.message) + '</div>'; }
};


/* ================= vendor portal ================= */
function stopPortalPoll() {
  if (S.portal.timer) { clearInterval(S.portal.timer); S.portal.timer = null; }
  stopMsgPoll();
}

async function vPortal() {
  const view = $('#view');
  if (!S.user || S.user.role !== 'vendor') {
    view.innerHTML = '<div class="empty"><span class="big">🔒</span>' + esc(t('vendor_only')) + '<br><br>' +
      '<button class="btn" onclick="go(\'login\')">' + esc(t('login_as_vendor')) + '</button></div>';
    return;
  }
  view.innerHTML = '<div class="empty"><span class="big">🏪</span>' + esc(t('portal_loading')) + '</div>';
  try {
    const vendors = await api('/vendors/mine');
    if (!vendors.length) { view.innerHTML = '<div class="empty">' + esc(t('no_shop')) + '</div>'; return; }
    S.portal.vendorId = vendors[0].id;
    S.portal.vendor = vendors[0];
    await portalReload(true);
    S.categories = [...new Set(S.portal.menu.map(d => d.category))].sort();
    renderPortalShell();
    stopPortalPoll();
    S.portal.timer = setInterval(() => portalReload(false), 15000);
  } catch (e) {
    view.innerHTML = '<div class="error">' + esc(t('portal_err')) + esc(e.message) + '</div>';
  }
}

async function portalReload(first) {
  const id = S.portal.vendorId;
  const [earnings, orders, menu, receivables] = await Promise.all([
    api('/vendors/' + id + '/earnings'),
    api('/orders?vendor_id=' + id),
    api('/dishes?vendor_id=' + id + '&available_only=false'),
    // v48: commission balance drives the direct-pay pause banner.
    api('/vendors/mine/commission-receivables').catch(() => []),
  ]);
  S.portal.earnings = earnings;
  S.portal.orders = orders;
  S.portal.menu = menu;
  S.portal.receivables = receivables;
  menu.forEach(d => { S.dishById[d.id] = d; });
  if (!first) portalRefreshDynamic();
}

function statusLabel(s) { return t('status_' + s); }
function fulfillLabel(f) { return t('fulfill_' + f); }
function catLabel(c) { return lang() === 'ar' ? (CAT_AR[c] || c) : c; }

/* ============ red-list shared helpers ============ */
function paidBadgeHTML(paid) {
  return paid
    ? '<span class="paid-badge yes">' + esc(t('paid_badge_yes')) + '</span>'
    : '<span class="paid-badge no">' + esc(t('paid_badge_no')) + '</span>';
}
/* v41: card brand + last4 on the admin order detail — from Stripe only.
   Raw card numbers, expiry dates, and CVCs are never stored or displayed
   anywhere in this app. Admin-only data (order detail view); who can see
   it is unchanged. */
function cardPaidHTML(o) {
  const b = String((o && o.card_brand) || '').trim();
  const l = String((o && o.card_last4) || '').trim();
  if (!b && !l) return '';
  const brand = b ? b.charAt(0).toUpperCase() + b.slice(1) : '';
  return ' · 💳 ' + esc((brand + (l ? ' •••• ' + l : '')).trim());
}
function vStars(n) {
  n = Math.max(0, Math.min(5, Math.round(Number(n) || 0)));
  return '<span class="stars">' + '★'.repeat(n) + '☆'.repeat(5 - n) + '</span>';
}
/* closed_weekdays: "5" or "5,6" or null — 0=Sunday … 6=Saturday. */
function closedDays(v) {
  return String((v && v.closed_weekdays) || '').split(',')
    .map(s => parseInt(s.trim(), 10)).filter(n => n >= 0 && n <= 6);
}

/* ---- order messages (vendor ↔ customer): plain text, oldest first ---- */
function msgSenderLabel(role, viewer) {
  if (role === viewer) return t('msg_you');
  if (role === 'vendor') return t('msg_vendor');
  if (role === 'customer') return t('msg_customer');
  return String(role || '');
}
function renderMsgThread(msgs, viewer) {
  const el = $('#msg-thread');
  if (!el) return;
  el.innerHTML = (msgs && msgs.length)
    ? msgs.map(m => '<div class="msg"><div class="msg-head"><strong>' + esc(msgSenderLabel(m.sender_role, viewer)) +
        '</strong> <small>' + esc(fmtDate(m.created_at)) + '</small></div><p>' + esc(m.text) + '</p></div>').join('')
    : '<div class="empty">' + esc(t('msg_empty')) + '</div>';
}
async function refreshMsgThread(orderId, viewer) {
  try { renderMsgThread(await api('/orders/' + orderId + '/messages'), viewer); }
  catch (e) { /* messages are a bonus — never break the page */ }
}
function stopMsgPoll() { if (S.portal.msgTimer) { clearInterval(S.portal.msgTimer); S.portal.msgTimer = null; } }
function startMsgPoll(orderId, viewer) {
  stopMsgPoll();
  refreshMsgThread(orderId, viewer);
  S.portal.msgTimer = setInterval(() => {
    if (!$('#msg-thread')) { stopMsgPoll(); return; } // navigated away
    refreshMsgThread(orderId, viewer);
  }, 15000);
}
window.sendOrderMessage = async function (orderId, viewer) {
  const inp = $('#msg-input');
  const text = (inp && inp.value || '').trim();
  if (!text) return;
  inp.value = '';
  try {
    await api('/orders/' + orderId + '/messages', { method: 'POST', body: JSON.stringify({ text }) });
    await refreshMsgThread(orderId, viewer);
  } catch (e) { alert(errText(e)); }
};

/* ---- dish customizations: option groups + ingredients (edit-dish modal) ----
   Groups: GET/POST /dishes/{id}/options, PATCH/DELETE /dishes/{id}/options/{oid}.
   Ingredients: GET/POST /dishes/{id}/ingredients, PATCH/DELETE .../{iid}.
   custGroups / custIngs cache the last-fetched lists for the inline editors. */
let custGroups = [];
let custIngs = [];

async function loadCustSection(dishId) {
  const box = document.getElementById('ed-cust');
  if (!box) return;
  let groups = [], ings = [];
  try {
    const res = await Promise.all([
      api('/dishes/' + dishId + '/options'),
      api('/dishes/' + dishId + '/ingredients'),
    ]);
    groups = Array.isArray(res[0]) ? res[0] : [];
    ings = Array.isArray(res[1]) ? res[1] : [];
  } catch (e) {
    box.innerHTML = '<div class="error">' + esc(t('v_ing_load_err')) + esc(errText(e)) + '</div>';
    return;
  }
  custGroups = groups;
  custIngs = ings;
  renderCustSection(dishId, groups, ings);
}

function optMinMaxTxt(g) {
  const mn = Number(g.min_select) || 0;
  const rawMx = (g.max_select === null || g.max_select === undefined || g.max_select === '') ? null : Number(g.max_select);
  if (mn > 0 && rawMx !== null) return mn + '–' + rawMx;
  if (mn > 0) return '≥' + mn;
  if (rawMx !== null) return '≤' + rawMx;
  return '—';
}

function renderCustSection(dishId, groups, ings) {
  const box = document.getElementById('ed-cust');
  if (!box) return;
  let h = '<h4 class="section-title">' + esc(t('cust_h')) + '</h4>';
  h += '<div class="cust-sub">' + esc(t('opt_groups_h')) + '</div><div id="cust-groups">';
  if (!groups.length) h += '<div class="hint">' + esc(t('opt_none')) + '</div>';
  groups.forEach(function (g) {
    const ch = (g.choices || []).map(function (c) {
      const link = c.dish_id ? ' 🔗' : '';
      return esc(c.label) + link + (Number(c.delta) ? ' (+' + money(c.delta) + ')' : '');
    }).join(', ');
    h += '<div class="cust-group"><div class="cust-group-head"><strong>' + esc(g.name || '') + '</strong> ' +
      '<span class="type-badge">' + esc(g.selection_type === 'multiple' ? t('opt_type_multi') : t('opt_type_single')) + '</span>' +
      ' <span class="vendor-tag">' + esc(optMinMaxTxt(g)) + '</span></div>' +
      '<div class="cust-choices">' + (ch || '<span class="hint">—</span>') + '</div>' +
      '<div class="cust-group-form" id="cgf-' + g.id + '" style="display:none"></div>' +
      '<div class="order-actions"><button type="button" class="btn small secondary" onclick="editOptGroup(' + dishId + ',' + g.id + ')">' +
      esc(t('opt_edit')) + '</button> ' +
      '<button type="button" class="btn small danger" onclick="delOptGroup(' + dishId + ',' + g.id + ')">' +
      esc(t('opt_delete')) + '</button></div></div>';
  });
  h += '</div>';
  h += '<div class="order-actions" style="margin:.4rem 0"><button type="button" class="btn small secondary" onclick="addOptGroupUI(' + dishId + ')">' +
    esc(t('opt_add_group')) + '</button> ' +
    '<button type="button" class="btn small secondary" onclick="addSidesTemplate(' + dishId + ')">' +
    esc(t('opt_sides_template')) + '</button></div>';
  h += '<div id="cust-new-group"></div>';
  h += '<div class="cust-sub">' + esc(t('ing_rows_h')) + '</div><div id="cust-ings">';
  if (!ings.length) h += '<div class="hint">' + esc(t('ing_none')) + '</div>';
  ings.forEach(function (ig) { h += ingRowHTML(dishId, ig); });
  h += '</div><div id="cust-new-ing"></div>';
  h += '<div class="order-actions" style="margin:.4rem 0"><button type="button" class="btn small secondary" onclick="addIngRowUI(' + dishId + ')">' +
    esc(t('ing_add_row')) + '</button></div>';
  box.innerHTML = h;
}

function optChoiceRowHTML(dishId, fid, i, label, delta, linkDishId, labelAr) {
  return '<div class="opt-row"><input type="text" maxlength="60" data-clabel placeholder="' + esc(t('opt_choice_lbl')) + ' ' + (i + 1) +
    '" value="' + esc(label || '') + '">' +
    '<input type="text" maxlength="40" data-clabel-ar placeholder="اسم الخيار بالعربية" value="' + esc(labelAr || '') + '">' +
    '<select data-cdish onchange="onChoiceDishLink(this)" title="' + esc(t('opt_link_dish')) + '">' +
    dishLinkOptionsHTML(linkDishId, dishId) + '</select>' +
    '<span class="opt-delta-lbl">' + esc(t('opt_delta_lbl')) + '</span>' +
    '<input type="number" step="0.01" data-cdelta placeholder="0.00" value="' + (Number(delta) || '') + '">' +
    '<button type="button" class="btn small danger" onclick="this.parentElement.remove()">✕</button></div>';
}

/* Options for the per-choice "link a dish" picker: the vendor's own dishes
   except the one being edited. Picking one fills the choice label. */
function dishLinkOptionsHTML(selectedId, excludeId) {
  const menu = (S.portal && S.portal.menu) || [];
  let h = '<option value="">' + esc(t('opt_link_dish')) + '</option>';
  menu.forEach(function (d) {
    if (d.id === excludeId) return;
    h += '<option value="' + d.id + '"' + (Number(selectedId) === d.id ? ' selected' : '') + '>' +
      esc(dname(d)) + '</option>';
  });
  return h;
}

window.onChoiceDishLink = function (sel) {
  const row = sel.closest('.opt-row');
  const inp = row && row.querySelector('[data-clabel]');
  const opt = sel.options[sel.selectedIndex];
  if (inp && opt && opt.value) inp.value = opt.text;
};

/* Inline add/edit form for one option group; gid null = new group. */
function optGroupFormHTML(dishId, g) {
  const isNew = !g;
  g = g || { name: '', selection_type: 'single', min_select: 0, max_select: null, choices: [] };
  const fid = isNew ? 'new' : g.id;
  const choices = (g.choices || []).map(function (c, i) {
    return optChoiceRowHTML(dishId, fid, i, c.label, c.delta, c.dish_id, c.label_ar);
  }).join('');
  return '<div class="opt-editor">' +
    '<label class="field">' + esc(t('opt_grp_name_ph')) + '</label>' +
    '<input type="text" id="og-name-' + fid + '" maxlength="80" value="' + esc(g.name || '') + '">' +
    '<label class="field">اسم المجموعة (العربية)</label><input type="text" id="og-name-ar-' + fid + '" maxlength="80" dir="rtl" value="' + esc(g.name_ar || '') + '">' +
    '<div class="row2"><div><label class="field">' + esc(t('opt_type_single')) + ' / ' + esc(t('opt_type_multi')) + '</label>' +
    '<select id="og-type-' + fid + '">' +
    '<option value="single"' + (g.selection_type !== 'multiple' ? ' selected' : '') + '>' + esc(t('opt_type_single')) + '</option>' +
    '<option value="multiple"' + (g.selection_type === 'multiple' ? ' selected' : '') + '>' + esc(t('opt_type_multi')) + '</option>' +
    '</select></div><div><label class="field">' + esc(t('opt_min')) + ' / ' + esc(t('opt_maxn')) + '</label>' +
    '<div class="row2"><input type="number" id="og-min-' + fid + '" min="0" step="1" value="' + (Number(g.min_select) || 0) + '">' +
    '<input type="number" id="og-max-' + fid + '" min="0" step="1" placeholder="—" value="' +
    ((g.max_select === null || g.max_select === undefined) ? '' : esc(g.max_select)) + '"></div></div></div>' +
    '<label class="field">' + esc(t('opt_choice_lbl')) + '</label>' +
    '<div id="og-choices-' + fid + '">' + choices + '</div>' +
    '<button type="button" class="btn small secondary" onclick="ogAddChoice(\'' + fid + '\',' + dishId + ')">' + esc(t('opt_add_choice')) + '</button> ' +
    '<span class="hint">' + esc(t('opt_max')) + '</span>' +
    '<div class="order-actions" style="margin-top:.5rem"><button type="button" class="btn small" onclick="saveOptGroup(' + dishId + ',' +
    (isNew ? 'null' : g.id) + ')">' + esc(t('opt_save')) + '</button> ' +
    '<button type="button" class="btn small secondary" onclick="cancelOptGroupUI(' + (isNew ? 'null' : g.id) + ')">' +
    esc(t('cancel')) + '</button></div></div>';
}

window.addOptGroupUI = function (dishId) {
  const host = document.getElementById('cust-new-group');
  if (host) host.innerHTML = optGroupFormHTML(dishId, null);
};
window.editOptGroup = function (dishId, gid) {
  const host = document.getElementById('cgf-' + gid);
  if (!host) return;
  if (host.style.display !== 'none' && host.innerHTML) { // toggle closed
    host.style.display = 'none'; host.innerHTML = ''; return;
  }
  const g = custGroups.find(function (x) { return x.id === gid; });
  if (!g) { loadCustSection(dishId); return; }
  host.innerHTML = optGroupFormHTML(dishId, g);
  host.style.display = '';
};
window.cancelOptGroupUI = function (gid) {
  if (gid === null || gid === undefined) {
    const host = document.getElementById('cust-new-group');
    if (host) host.innerHTML = '';
  } else {
    const host = document.getElementById('cgf-' + gid);
    if (host) { host.style.display = 'none'; host.innerHTML = ''; }
  }
};
window.ogAddChoice = function (fid, dishId) {
  const box = document.getElementById('og-choices-' + fid);
  if (!box || box.children.length >= 6) return;
  const row = document.createElement('div');
  row.innerHTML = optChoiceRowHTML(dishId || null, fid, box.children.length, '', '', null);
  if (row.firstChild) box.appendChild(row.firstChild);
};
window.saveOptGroup = async function (dishId, gid) {
  const fid = (gid === null || gid === undefined) ? 'new' : gid;
  const nameEl = document.getElementById('og-name-' + fid);
  const name = (nameEl && nameEl.value || '').trim();
  if (!name) { alert(t('opt_need_name')); return; }
  const typeEl = document.getElementById('og-type-' + fid);
  const minEl = document.getElementById('og-min-' + fid);
  const maxEl = document.getElementById('og-max-' + fid);
  const min = Math.max(0, parseInt((minEl && minEl.value) || '0', 10) || 0);
  const maxRaw = ((maxEl && maxEl.value) || '').trim();
  const max = maxRaw === '' ? null : Math.max(0, parseInt(maxRaw, 10) || 0);
  const choices = [];
  const box = document.getElementById('og-choices-' + fid);
  if (box) box.querySelectorAll('.opt-row').forEach(function (r) {
    const label = (((r.querySelector('[data-clabel]') || {}).value) || '').trim();
    if (!label) return;
    const linkSel = r.querySelector('[data-cdish]');
    const linkId = linkSel && linkSel.value ? Number(linkSel.value) : null;
    choices.push({ label: label, label_ar: (((r.querySelector('[data-clabel-ar]') || {}).value) || '').trim() || null, delta: Number((r.querySelector('[data-cdelta]') || {}).value) || 0, dish_id: linkId });
  });
  const nameArEl = document.getElementById('og-name-ar-' + fid);
  const body = { name: name, name_ar: (nameArEl && nameArEl.value || '').trim() || null, selection_type: typeEl ? typeEl.value : 'single', min_select: min, max_select: max, choices: choices };
  try {
    if (gid === null || gid === undefined) {
      await api('/dishes/' + dishId + '/options', { method: 'POST', body: JSON.stringify(body) });
    } else {
      await api('/dishes/' + dishId + '/options/' + gid, { method: 'PATCH', body: JSON.stringify(body) });
    }
    await loadCustSection(dishId);
  } catch (e) { alert(t('upd_failed') + errText(e)); }
};
window.delOptGroup = async function (dishId, gid) {
  if (!confirm(t('opt_del_confirm'))) return;
  try {
    await api('/dishes/' + dishId + '/options/' + gid, { method: 'DELETE' });
    await loadCustSection(dishId);
  } catch (e) { alert(t('upd_failed') + errText(e)); }
};
/* One-click "Sides" template: pick-many, 1–2, Rice/Fries/Salad/Bread — the
   vendor edits names/prices afterwards. Labels follow the portal language. */
window.addSidesTemplate = async function (dishId) {
  const body = {
    name: t('tmpl_sides'),
    selection_type: 'multiple',
    min_select: 1,
    max_select: 2,
    choices: [t('tmpl_rice'), t('tmpl_fries'), t('tmpl_salad'), t('tmpl_bread')]
      .map(function (l) { return { label: l, delta: 0 }; }),
  };
  try {
    await api('/dishes/' + dishId + '/options', { method: 'POST', body: JSON.stringify(body) });
    await loadCustSection(dishId);
  } catch (e) { alert(t('upd_failed') + errText(e)); }
};

function checklineHTML(id, checked, label) {
  return '<label class="checkline"><input type="checkbox" id="' + id + '"' + (checked ? ' checked' : '') + '> ' +
    esc(label) + '</label>';
}
/* Inline add/edit row for one ingredient; iid null = new row. */
function ingRowHTML(dishId, ig) {
  const isNew = !ig || ig.id === undefined || ig.id === null;
  ig = ig || {
    name: '', included_by_default: true, removable: true, extra_price: 0,
    is_vegetarian: false, is_vegan: false, is_allergen: false, allergen_name: '',
  };
  const fid = isNew ? 'new' : ig.id;
  return '<div class="ing-editor" id="ing-' + fid + '">' +
    '<div class="row2"><div><label class="field">' + esc(t('ing_name')) + '</label>' +
    '<input type="text" id="ig-name-' + fid + '" maxlength="120" value="' + esc(ig.name || '') + '"></div>' +
    '<div><label class="field">' + esc(t('ing_name')) + ' (العربية)</label><input type="text" id="ig-name-ar-' + fid + '" maxlength="80" dir="rtl" value="' + esc(ig.name_ar || '') + '"></div>' +
    '<div><label class="field">' + esc(t('ing_extra_price')) + '</label>' +
    '<input type="number" id="ig-price-' + fid + '" step="0.01" min="0" value="' + (Number(ig.extra_price) || '') + '"></div></div>' +
    '<div class="check-grid">' +
    checklineHTML('ig-inc-' + fid, ig.included_by_default, t('ing_included')) +
    checklineHTML('ig-rem-' + fid, ig.removable, t('ing_removable')) +
    checklineHTML('ig-veg-' + fid, ig.is_vegetarian, t('ing_veg')) +
    checklineHTML('ig-vgn-' + fid, ig.is_vegan, t('ing_vegan')) +
    checklineHTML('ig-alg-' + fid, ig.is_allergen, t('ing_allergen')) +
    '</div>' +
    '<label class="field">' + esc(t('ing_allergen_ph')) + '</label>' +
    '<input type="text" id="ig-algname-' + fid + '" maxlength="120" value="' + esc(ig.allergen_name || '') + '">' +
    '<label class="field">' + esc(t('ing_allergen_ph')) + ' (العربية)</label>' +
    '<input type="text" id="ig-algname-ar-' + fid + '" maxlength="80" dir="rtl" value="' + esc(ig.allergen_name_ar || '') + '">' +
    '<div class="order-actions" style="margin-top:.4rem"><button type="button" class="btn small" onclick="saveIngRow(' + dishId + ',' +
    (isNew ? 'null' : ig.id) + ')">' + esc(t('opt_save')) + '</button> ' +
    (isNew
      ? '<button type="button" class="btn small secondary" onclick="document.getElementById(\'cust-new-ing\').innerHTML=\'\'">' +
        esc(t('cancel')) + '</button>'
      : '<button type="button" class="btn small danger" onclick="delIngRow(' + dishId + ',' + ig.id + ')">' +
        esc(t('opt_delete')) + '</button>') +
    '</div></div>';
}
window.addIngRowUI = function (dishId) {
  const host = document.getElementById('cust-new-ing');
  if (host) host.innerHTML = ingRowHTML(dishId, null);
};
window.saveIngRow = async function (dishId, iid) {
  const fid = (iid === null || iid === undefined) ? 'new' : iid;
  const val = function (id) { const el = document.getElementById(id); return el ? el.value : ''; };
  const chk = function (id) { const el = document.getElementById(id); return !!(el && el.checked); };
  const name = (val('ig-name-' + fid) || '').trim();
  if (!name) { alert(t('ing_need_name')); return; }
  const body = {
    name: name,
    name_ar: (val('ig-name-ar-' + fid) || '').trim() || null,
    included_by_default: chk('ig-inc-' + fid),
    removable: chk('ig-rem-' + fid),
    extra_price: Number(val('ig-price-' + fid)) || 0,
    is_vegetarian: chk('ig-veg-' + fid),
    is_vegan: chk('ig-vgn-' + fid),
    is_allergen: chk('ig-alg-' + fid),
    allergen_name: (val('ig-algname-' + fid) || '').trim() || null,
    allergen_name_ar: (val('ig-algname-ar-' + fid) || '').trim() || null,
  };
  try {
    if (iid === null || iid === undefined) {
      await api('/dishes/' + dishId + '/ingredients', { method: 'POST', body: JSON.stringify(body) });
    } else {
      await api('/dishes/' + dishId + '/ingredients/' + iid, { method: 'PATCH', body: JSON.stringify(body) });
    }
    await loadCustSection(dishId);
  } catch (e) { alert(t('upd_failed') + errText(e)); }
};
window.delIngRow = async function (dishId, iid) {
  if (!confirm(t('ing_del_confirm'))) return;
  try {
    await api('/dishes/' + dishId + '/ingredients/' + iid, { method: 'DELETE' });
    await loadCustSection(dishId);
  } catch (e) { alert(t('upd_failed') + errText(e)); }
};

/* ---- optional Google Analytics: inject gtag.js when the backend configures an ID ---- */
async function loadAnalytics() {
  try {
    const c = await api('/config');
    const id = c && String(c.analytics_id || '').trim();
    if (!id) return; // empty = no-op
    const s = document.createElement('script');
    s.async = true;
    s.src = 'https://www.googletagmanager.com/gtag/js?id=' + encodeURIComponent(id);
    document.head.appendChild(s);
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    window.gtag('js', new Date());
    window.gtag('config', id);
  } catch (e) { /* analytics must never break the app */ }
}

/* Dish-photo rules — mirrors frontend/app.js (same name->photo mapping
   the customer site uses). Photos live in frontend/img/, so the vendor
   portal (served at /vendor/) references them with absolute /img/ paths. */
/* Dish-photo rules: keyword fragments (lowercase) -> verified Wikimedia
   Commons file + emoji fallback tile. First matching rule wins.
   Rules with tile:true render an emoji tile directly (used for groceries,
   which have no photos). */
const PHOTO_RULES = [
  /* ---- v50 fix: Koshary + Hummus dishes — must precede the grocery
     'chickpeas' rule below: both dishes' descriptions mention chickpeas,
     so the grocery rule stole their photos (a bag of chickpeas). Keys
     pair the dish name with the first word of its description, so
     grocery items that merely mention the dishes ("For hummus and
     koshary") keep their own grocery photos. ---- */
  { k: ['koshary rice', 'koshari', 'kushari'], img: 'koshary.jpg', emoji: '🍚' },
  { k: ['hummus chickpeas'], img: 'hummus.jpg', emoji: '🧆' },
  /* ---- grocery photos (checked first) ---- */
  { k: ['frozen molokhia'], img: 'g_frozen_molokhia.jpg', emoji: '\u2744\ufe0f' },
  { k: ['frozen okra'], img: 'g_frozen_okra.jpg', emoji: '\u2744\ufe0f' },
  { k: ['frozen green fava', 'frozen fava'], img: 'g_frozen_fava.jpg', emoji: '\u2744\ufe0f' },
  { k: ['canned ful'], img: 'g_canned_ful.jpg', emoji: '\U0001f962' },
  { k: ['short-grain rice'], img: 'g_shortgrain_rice.jpg', emoji: '\U0001f35a' },
  { k: ['red lentils'], img: 'g_red_lentils.jpg', emoji: '\U0001fab2' },
  { k: ['chickpeas'], img: 'g_chickpeas.jpg', emoji: '\U0001fab2' },
  { k: ['white beans', 'fasolia'], img: 'g_white_beans.jpg', emoji: '\U0001fab2' },
  { k: ['fava beans', 'ful medames'], img: 'g_fava_beans.jpg', emoji: '\U0001fab2' },
  { k: ['dried molokhia'], img: 'g_dried_molokhia.jpg', emoji: '\U0001f33f' },
  { k: ['dried okra'], img: 'g_dried_okra.jpg', emoji: '\U0001f33f' },
  { k: ['macaroni'], img: 'g_macaroni.jpg', emoji: '\U0001f35d' },
  { k: ['grape leaves jar'], img: 'g_grape_leaves_jar.jpg', emoji: '\U0001fad9' },
  { k: ['torshi', 'egyptian pickles'], img: 'g_torshi.jpg', emoji: '\U0001f952' },
  { k: ['olives'], img: 'g_green_olives.jpg', emoji: '\U0001fad2' },
  { k: ['cumin'], img: 'g_cumin.jpg', emoji: '\U0001f9c2' },
  { k: ['coriander'], img: 'g_coriander.jpg', emoji: '\U0001f33f' },
  { k: ['dukkah'], img: 'g_dukkah.jpg', emoji: '\U0001f95c' },
  { k: ['baharat', '7-spice'], img: 'g_baharat.jpg', emoji: '\U0001f9c2' },
  { k: ['black seed', 'habat el baraka'], img: 'g_black_seed.jpg', emoji: '\U0001f331' },
  { k: ['dried mint'], img: 'g_dried_mint.jpg', emoji: '\U0001f33f' },
  { k: ['hibiscus', 'karkadeh'], img: 'g_karkadeh.jpg', emoji: '\U0001f33a' },
  { k: ['fenugreek', 'helba'], img: 'g_fenugreek.jpg', emoji: '\U0001f331' },
  { k: ['turmeric'], img: 'g_turmeric.jpg', emoji: '\U0001f7e1' },
  { k: ['white cheese', 'gibna beida'], img: 'g_white_cheese.jpg', emoji: '\U0001f9c0' },
  { k: ['mish cheese', 'aged mish'], img: 'g_mish_cheese.jpg', emoji: '\U0001f9c0' },
  { k: ['karish'], img: 'g_karish.jpg', emoji: '\U0001f9c0' },
  { k: ['halva'], img: 'g_halva.jpg', emoji: '\U0001f36c' },
  { k: ['molasses', 'asal eswed'], img: 'g_molasses.jpg', emoji: '\U0001f36f' },
  { k: ['dates', 'medjool'], img: 'g_medjool_dates.jpg', emoji: '\U0001f334' },
  { k: ['qamar al-din', 'apricot paste'], img: 'g_qamar_aldin.jpg', emoji: '\U0001f351' },
  { k: ['black tea', 'el arosa'], img: 'g_black_tea.jpg', emoji: '\U0001f375' },
  { k: ['sahlab'], img: 'g_sahlab.jpg', emoji: '\U0001f95b' },
/* ---- cooked-food photo rules ---- */
/* ---- Um Sohaib's Kitchen (Oct 2026) — checked before the generic rules ---- */
  { k: ['mansaf'], img: 'um_mansaf.jpg', emoji: '🍚' },
  { k: ['maqlouba'], img: 'um_maqlouba.jpg', emoji: '🍚' },
  { k: ['musakhan'], img: 'um_musakhan.jpg', emoji: '🍗' },
  { k: ['ouzi'], img: 'um_ouzi.jpg', emoji: '🍚' },
  { k: ['biryani'], img: 'um_biryani.jpg', emoji: '🍚' },
  { k: ['shish barak'], img: 'um_shishbarak.jpg', emoji: '🥟' },
  { k: ['freekeh'], img: 'um_freekeh.jpg', emoji: '🍲' },
  { k: ['yalanji'], img: 'um_yalanji.jpg', emoji: '🫔' },
  { k: ['kibbeh'], img: 'um_kibbeh.jpg', emoji: '🧆' },
  { k: ['sfiha'], img: 'um_sfiha.jpg', emoji: '🫓' },
  { k: ['spinach pastry'], img: 'um_spinach_pastry.jpg', emoji: '🥬' },
  { k: ['cheese pastry'], img: 'um_cheese_pastry.jpg', emoji: '🧀' },
  { k: ['mini pizza'], img: 'um_mini_pizza.jpg', emoji: '🍕' },
  { k: ['chicken tray'], img: 'um_chicken_tray.jpg', emoji: '🍗' },
  /* ---- v50: Egypt best sellers (Konafa / Qatayef / Ta'ameya) — before
     the generic rules: Ta'ameya's description mentions tahini + salad,
     which would otherwise steal the match. ---- */
  { k: ['konafa', 'kunafa', 'kenafa'], img: 'konafa.jpg', emoji: '🥮' },
  { k: ['qatayef', 'katayef', 'atayef'], img: 'qatayef.jpg', emoji: '🥟' },
  { k: ["ta'ameya", 'taameya', 'falafel'], img: 'taameya.jpg', emoji: '🧆' },
  { k: ['whole grilled fish', 'grilled fish'], img: 'grilled_fish.jpg', emoji: '🐟' },
  { k: ['fried fish'], img: 'fried_fish.jpg', emoji: '🐟' },
  { k: ['fish fillet'], img: 'fried_fish.jpg', emoji: '🐟' },
  { k: ['tilapia'], img: 'grilled_tilapia.jpg', emoji: '🐟' },
  /* ---- image-fix: specific dish photos — must precede the generic
     rules below (first match wins): one generic photo was serving unlike
     dishes (kebab skewer on liver/sausage/pane, shrimp skewers on fried
     shrimp/pasta/rice, meze plate on salads). ---- */
  { k: ['baba ghanoush', 'baba ghanouj', 'ghanoush'], img: 'baba_ghanoush.jpg', emoji: '🍆' },
  { k: ['fried shrimp'], img: 'fried_shrimp.jpg', emoji: '🍤' },
  { k: ['shrimp & calamari'], img: 'shrimp_calamari_platter.jpg', emoji: '🍤' },
  { k: ['shrimp rice'], img: 'shrimp_rice.jpg', emoji: '🍚' },
  { k: ['grilled calamari'], img: 'grilled_calamari.jpg', emoji: '🦑' },
  { k: ['king crab'], img: 'crab_legs.jpg', emoji: '🦀' },
  { k: ['deluxe platter'], img: 'deluxe_platter.jpg', emoji: '🍽️' },
  { k: ['seafood soup'], img: 'seafood_soup.jpg', emoji: '🍲' },
  { k: ['seafood pasta'], img: 'seafood_pasta.jpg', emoji: '🍝' },
  { k: ['beet salad'], img: 'beet_salad.jpg', emoji: '🥗' },
  { k: ['corn salad'], img: 'corn_salad.jpg', emoji: '🥗' },
  { k: ['cucumber yogurt'], img: 'yogurt_cucumber_salad.jpg', emoji: '🥗' },
  { k: ['potato salad'], img: 'potato_salad.jpg', emoji: '🥗' },
  { k: ['extra sauce'], img: 'sauce_bowls.jpg', emoji: '🥣' },
  { k: ['mombar'], img: 'mombar.jpg', emoji: '🫔' },
  { k: ['stuffed cabbage'], img: 'cabbage_rolls.jpg', emoji: '🫔' },
  { k: ['stuffed grape leaves'], img: 'grape_leaves.jpg', emoji: '🫔' },
  { k: ['trotters casserole'], img: 'kaware_casserole.jpg', emoji: '🍲' },
  { k: ['bechamel', 'macarona'], img: 'bechamel_pasta.jpg', emoji: '🍝' },
  { k: ['oxtail', 'akawi'], img: 'oxtail_casserole.jpg', emoji: '🍲' },
  { k: ['shrimp'], img: 'grilled_shrimp.jpg', emoji: '🍤' },
  { k: ['calamari'], img: 'fried_calamari.jpg', emoji: '🦑' },
  { k: ['crab'], img: 'blue_crab.jpg', emoji: '🦀' },
  { k: ['seafood platter', 'platter'], img: 'seafood.jpg', emoji: '🦐' },
  { k: ['fish rice'], img: 'fish_rice.jpg', emoji: '🍚' },
  { k: ['seafood rice'], img: 'seafood_rice.jpg', emoji: '🍚' },
  { k: ['shrimp rice'], img: 'shrimp_rice.jpg', emoji: '🍚' },
  { k: ['seafood'], img: 'seafood.jpg', emoji: '🦐' },
  { k: ['tahini'], img: 'tahini.jpg', emoji: '🥣' },
  { k: ['hummus'], img: 'hummus.jpg', emoji: '🧆' },
  { k: ['baladi salad'], img: 'tomato_salad.jpg', emoji: '🥗' },
  { k: ['fattoush'], img: 'fattoush.jpg', emoji: '🥗' },
  { k: ['tabbouleh', 'tabouli'], img: 'tabbouleh.jpg', emoji: '🥗' },
  { k: ['greek salad'], img: 'greek_salad.jpg', emoji: '🥗' },
  { k: ['caesar'], img: 'caesar_salad.jpg', emoji: '🥗' },
  { k: ['coleslaw'], img: 'coleslaw.jpg', emoji: '🥗' },
  { k: ['pickle'], img: 'pickled_eggplant.jpg', emoji: '🥒' },
  { k: ['koshary', 'koshari', 'kushari'], img: 'koshary.jpg', emoji: '🍚' },
  { k: ['kofta'], img: 'kofta.jpg', emoji: '🍢' },
  { k: ['kebab'], img: 'adana_kebab.jpg', emoji: '🍢' },
  { k: ['hawawshi'], img: 'hawawshi.jpg', emoji: '🫓' },
  { k: ['feteer'], img: 'feteer.jpg', emoji: '🫓' },
  { k: ['baladi bread'], img: 'baladi_bread.jpg', emoji: '🫓' },
  { k: ['garlic bread'], img: 'garlic_bread.jpg', emoji: '🍞' },
  { k: ['sausage'], img: 'grilled_sausage.jpg', emoji: '🌭' },
  { k: ['liver'], img: 'liver.jpg', emoji: '🍢' },
  { k: ['grilled beef'], img: 'grilled_beef.jpg', emoji: '🍖' },
  { k: ['grilled chicken'], img: 'grilled_chicken.jpg', emoji: '🍖' },
  { k: ['chicken pane'], img: 'chicken_pane.jpg', emoji: '🍗' },
  { k: ['molokhia'], img: 'molokhia.jpg', emoji: '🍲' },
  { k: ['bamia', 'okra'], img: 'bamia_stew.jpg', emoji: '🍲' },
  { k: ['kahk', 'kaak'], img: 'kahk.jpg', emoji: '🍪' },
  { k: ['basbousa'], img: 'basbousa.jpg', emoji: '🍰' },
  { k: ['om ali', 'omali', 'umm ali'], img: 'om_ali.jpg', emoji: '🍮' },
  { k: ['dolma', 'grape leaves'], img: 'dolma.jpg', emoji: '🫔' },
  { k: ['mahshi', 'mombar'], img: 'dolma.jpg', emoji: '🫔' },
  { k: ['stuffed cabbage', 'stuffed zucchini', 'stuffed eggplant', 'stuffed tomato', 'stuffed pepper'], img: 'dolma.jpg', emoji: '🫔' },
  { k: ['kaware', 'broth'], img: 'lentil_soup.jpg', emoji: '🍲' },
  { k: ['orzo', 'lisan asfour'], img: 'orzo_soup.jpg', emoji: '🍲' },
  { k: ['lentil soup'], img: 'lentil_soup.jpg', emoji: '🍲' },
  { k: ['soup'], img: 'lentil_soup.jpg', emoji: '🍲' },
  { k: ['fries'], img: 'french_fries.jpg', emoji: '🍟' },
  { k: ['fatta'], img: 'fatta.jpg', emoji: '🍚' },
  { k: ['rice'], img: 'cooked_rice.jpg', emoji: '🍚' },
  { k: ['salad'], img: 'green_salad.jpg', emoji: '🥗' },
  { k: ['appetizer', 'meze'], img: 'meze.jpg', emoji: '🫒' },
];
const AR_PHOTO_RULES = [
  // Arabic catalog names -> the same item-specific photos as the English names.
  /* ---- image-fix: specific Arabic-name photos before the generic
     dolma rule (first match wins). ---- */
  { k: ['\u0628\u0627\u0628\u0627 \u063a\u0646\u0648\u062c'], img: 'baba_ghanoush.jpg', emoji: '\u{1F346}' },
  { k: ['\u0645\u062d\u0634\u064a \u0643\u0631\u0646\u0628'], img: 'cabbage_rolls.jpg', emoji: '\u{1F9EB}' },
  { k: ['\u0645\u062d\u0634\u064a \u0648\u0631\u0642 \u0639\u0646\u0628'], img: 'grape_leaves.jpg', emoji: '\u{1F9EB}' },
  { k: ['\u0645\u062d\u0634\u064a \u0628\u062a\u0646\u062c\u0627\u0646', '\u0645\u062d\u0634\u064a \u0643\u0648\u0633\u0629', '\u0645\u062d\u0634\u064a \u0637\u0645\u0627\u0637\u0645', '\u0645\u062d\u0634\u064a \u0645\u0634\u0643\u0644', '\u062f\u0648\u0644\u0645\u0629'], img: 'dolma.jpg', emoji: '\u{1F9EB}' },
  { k: ['\u0645\u0643\u0631\u0648\u0646\u0629 \u0643\u0627\u0644\u064a\u0645\u0627\u0631\u064a'], img: 'calamari_pasta.jpg', emoji: '\u{1F990}' },
  { k: ['\u0645\u0643\u0631\u0648\u0646\u0629 \u062c\u0645\u0628\u0631\u064a'], img: 'shrimp_pasta.jpg', emoji: '\u{1F990}' },
  { k: ['\u0645\u0643\u0631\u0648\u0646\u0629 \u0633\u064a \u0641\u0648\u062f'], img: 'seafood_pasta.jpg', emoji: '\u{1F990}' },
  { k: ['\u0645\u0644\u0648\u062e\u064a\u0629 \u0645\u062c\u0645\u062f\u0629'], img: 'g_frozen_molokhia.jpg', emoji: '\u2744\ufe0f' },
  { k: ['\u0628\u0627\u0645\u064a\u0629 \u0645\u062c\u0645\u062f\u0629'], img: 'g_frozen_okra.jpg', emoji: '\u2744\ufe0f' },
  { k: ['\u0641\u0648\u0644 \u0623\u062e\u0636\u0631 \u0645\u062c\u0645\u062f'], img: 'g_frozen_fava.jpg', emoji: '\u{1FAD8}' },
  { k: ['\u0641\u0648\u0644 \u0645\u062f\u0645\u0633 \u0645\u0639\u0644\u0628'], img: 'g_canned_ful.jpg', emoji: '\u{1F963}' },
  { k: ['\u0631\u0632 \u0645\u0635\u0631\u064a'], img: 'g_shortgrain_rice.jpg', emoji: '\u{1F35A}' },
  { k: ['\u0639\u062f\u0633 \u0623\u062d\u0645\u0631'], img: 'g_red_lentils.jpg', emoji: '\u{1FAD8}' },
  { k: ['\u062d\u0645\u0635 \u062c\u0627\u0641'], img: 'g_chickpeas.jpg', emoji: '\u{1FAD8}' },
  { k: ['\u0641\u0627\u0635\u0648\u0644\u064a\u0627 \u0628\u064a\u0636\u0627\u0621'], img: 'g_white_beans.jpg', emoji: '\u{1FAD8}' },
  { k: ['\u0641\u0648\u0644 \u0645\u062f\u0645\u0633'], img: 'g_fava_beans.jpg', emoji: '\u{1FAD8}' },
  { k: ['\u0648\u0631\u0642 \u0645\u0644\u0648\u062e\u064a\u0629 \u062c\u0627\u0641'], img: 'g_dried_molokhia.jpg', emoji: '\u{1F33F}' },
  { k: ['\u0628\u0627\u0645\u064a\u0629 \u062c\u0627\u0641\u0629'], img: 'g_dried_okra.jpg', emoji: '\u{1F33F}' },
  { k: ['\u0648\u0631\u0642 \u0639\u0646\u0628'], img: 'g_grape_leaves_jar.jpg', emoji: '\u{1FAD9}' },
  { k: ['\u0637\u0631\u0634\u064a \u0645\u0635\u0631\u064a'], img: 'g_torshi.jpg', emoji: '\u{1F952}' },
  { k: ['\u0632\u064a\u062a\u0648\u0646 \u0623\u062e\u0636\u0631'], img: 'g_green_olives.jpg', emoji: '\u{1FAD2}' },
  { k: ['\u0643\u0645\u0648\u0646'], img: 'g_cumin.jpg', emoji: '\u{1F9C2}' },
  { k: ['\u0643\u0632\u0628\u0631\u0629'], img: 'g_coriander.jpg', emoji: '\u{1F33F}' },
  { k: ['\u062f\u0642\u0629'], img: 'g_dukkah.jpg', emoji: '\u{1F95C}' },
  { k: ['\u0628\u0647\u0627\u0631\u0627\u062a'], img: 'g_baharat.jpg', emoji: '\u{1F9C2}' },
  { k: ['\u062d\u0628\u0629 \u0627\u0644\u0628\u0631\u0643\u0629'], img: 'g_black_seed.jpg', emoji: '\u{1F331}' },
  { k: ['\u0646\u0639\u0646\u0627\u0639 \u0645\u062c\u0641\u0641'], img: 'g_dried_mint.jpg', emoji: '\u{1F33F}' },
  { k: ['\u0643\u0631\u0643\u062f\u064a\u0647'], img: 'g_karkadeh.jpg', emoji: '\u{1F33A}' },
  { k: ['\u062d\u0644\u0628\u0629'], img: 'g_fenugreek.jpg', emoji: '\u{1F331}' },
  { k: ['\u0643\u0631\u0643\u0645'], img: 'g_turmeric.jpg', emoji: '\u{1F7E1}' },
  { k: ['\u062c\u0628\u0646\u0629 \u0628\u064a\u0636\u0627\u0621 \u0645\u0635\u0631\u064a\u0629'], img: 'g_white_cheese.jpg', emoji: '\u{1F9C0}' },
  { k: ['\u062c\u0628\u0646\u0629 \u0645\u0634'], img: 'g_mish_cheese.jpg', emoji: '\u{1F9C0}' },
  { k: ['\u062c\u0628\u0646\u0629 \u0642\u0631\u064a\u0634'], img: 'g_karish.jpg', emoji: '\u{1F9C0}' },
  { k: ['\u062d\u0644\u0627\u0648\u0629 \u0637\u062d\u064a\u0646\u064a\u0629'], img: 'g_halva.jpg', emoji: '\u{1F36C}' },
  { k: ['\u0639\u0633\u0644 \u0623\u0633\u0648\u062f'], img: 'g_molasses.jpg', emoji: '\u{1F36F}' },
  { k: ['\u062a\u0645\u0631'], img: 'g_medjool_dates.jpg', emoji: '\u{1F334}' },
  { k: ['\u0642\u0645\u0631 \u0627\u0644\u062f\u064a\u0646'], img: 'g_qamar_aldin.jpg', emoji: '\u{1F351}' },
  { k: ['\u0634\u0627\u064a \u0623\u0633\u0648\u062f \u0645\u0635\u0631\u064a'], img: 'g_black_tea.jpg', emoji: '\u{1F375}' },
  { k: ['\u062e\u0644\u0637\u0629 \u0633\u062d\u0644\u0628'], img: 'g_sahlab.jpg', emoji: '\u{1F95B}' },
  { k: ['\u0643\u0634\u0631\u064a', '\u0643\u0634\u0627\u0631\u064a'], img: 'koshary.jpg', emoji: '\u{1F35A}' },
  { k: ['\u062d\u0645\u0635'], img: 'hummus.jpg', emoji: '\u{1F9C6}' },
  { k: ['\u0643\u0646\u0627\u0641\u0629'], img: 'konafa.jpg', emoji: '\u{1F96E}' },
  { k: ['\u0642\u0637\u0627\u064a\u0641'], img: 'qatayef.jpg', emoji: '\u{1F95F}' },
  { k: ['\u0637\u0639\u0645\u064a\u0629'], img: 'taameya.jpg', emoji: '\u{1F9C6}' },
  { k: ['\u0645\u0646\u0633\u0641'], img: 'um_mansaf.jpg', emoji: '\u{1F35A}' },
  { k: ['\u0645\u0642\u0644\u0648\u0628\u0629'], img: 'um_maqlouba.jpg', emoji: '\u{1F35A}' },
  { k: ['\u0645\u0633\u062e\u0646'], img: 'um_musakhan.jpg', emoji: '\u{1F357}' },
  { k: ['\u0628\u0631\u064a\u0627\u0646\u064a'], img: 'um_biryani.jpg', emoji: '\u{1F35A}' },
  { k: ['\u0634\u064a\u0634\u0628\u0631\u0643'], img: 'um_shishbarak.jpg', emoji: '\u{1F95F}' },
  { k: ['\u0641\u0631\u064a\u0643\u0629'], img: 'um_freekeh.jpg', emoji: '\u{1F372}' },
  { k: ['\u064a\u0627\u0644\u0646\u062c\u064a'], img: 'um_yalanji.jpg', emoji: '\u{1F9C6}' },
  { k: ['\u0643\u0628\u0629'], img: 'um_kibbeh.jpg', emoji: '\u{1F9C6}' },
  { k: ['\u0635\u0641\u064a\u062d\u0629 \u0644\u062d\u0645\u0629'], img: 'um_sfiha.jpg', emoji: '\u{1FAD3}' },
  { k: ['\u0641\u0637\u0627\u064a\u0631 \u0633\u0628\u0627\u0646\u062e'], img: 'um_spinach_pastry.jpg', emoji: '\u{1F96C}' },
  { k: ['\u0641\u0637\u0627\u064a\u0631 \u062c\u0628\u0646\u0629'], img: 'um_cheese_pastry.jpg', emoji: '\u{1F9C0}' },
  { k: ['\u0645\u064a\u0646\u064a \u0628\u064a\u062a\u0632\u0627'], img: 'um_mini_pizza.jpg', emoji: '\u{1F355}' },
  { k: ['\u0635\u064a\u0646\u064a\u0629 \u0641\u0631\u0627\u062e \u0628\u0627\u0644\u0631\u0632'], img: 'um_chicken_tray.jpg', emoji: '\u{1F357}' },
  { k: ['\u062d\u0648\u0627\u0648\u0634\u064a'], img: 'hawawshi.jpg', emoji: '\u{1FAD3}' },
  { k: ['\u0643\u0641\u062a\u0629'], img: 'kofta.jpg', emoji: '\u{1F362}' },
  { k: ['\u0643\u0628\u0627\u0628'], img: 'adana_kebab.jpg', emoji: '\u{1F362}' },
  { k: ['\u0643\u0628\u062f\u0629'], img: 'liver.jpg', emoji: '\u{1F362}' },
  { k: ['\u0633\u062c\u0642'], img: 'grilled_sausage.jpg', emoji: '\u{1F32d}' },
  { k: ['\u0645\u0644\u0648\u062e\u064a\u0629'], img: 'molokhia.jpg', emoji: '\u{1F372}' },
  { k: ['\u0628\u0627\u0645\u064a\u0629'], img: 'bamia_stew.jpg', emoji: '\u{1F372}' },
  { k: ['\u0643\u062d\u0643'], img: 'kahk.jpg', emoji: '\u{1F36A}' },
  { k: ['\u0628\u0633\u0628\u0648\u0633\u0629'], img: 'basbousa.jpg', emoji: '\u{1F370}' },
  { k: ['\u0623\u0645 \u0639\u0644\u064a'], img: 'om_ali.jpg', emoji: '\u{1F36E}' },
  { k: ['\u0641\u062a\u0629'], img: 'fatta.jpg', emoji: '\u{1F35A}' },
  { k: ['\u0633\u0645\u0643\u0629 \u0643\u0627\u0645\u0644\u0629 \u0645\u0634\u0648\u064a\u0629'], img: 'grilled_fish.jpg', emoji: '\u{1F41F}' },
  { k: ['\u0633\u0645\u0643\u0629 \u0643\u0627\u0645\u0644\u0629 \u0645\u0642\u0644\u064a\u0629'], img: 'whole_fried_fish.jpg', emoji: '\u{1F41F}' },
  { k: ['\u0634\u0648\u0631\u0628\u0629 \u0639\u062f\u0633'], img: 'lentil_soup_cooked.jpg', emoji: '\u{1F372}' },
  { k: ['\u0628\u0637\u0627\u0637\u0633 \u0645\u0642\u0644\u064a\u0629'], img: 'french_fries.jpg', emoji: '\u{1F35F}' },
  { k: ['\u0633\u0644\u0637\u0629 \u0633\u064a\u0632\u0631'], img: 'caesar_salad.jpg', emoji: '\u{1F957}' },
  { k: ['\u0641\u062a\u0648\u0634'], img: 'fattoush.jpg', emoji: '\u{1F957}' },
  { k: ['\u062a\u0628\u0648\u0644\u0629'], img: 'tabbouleh.jpg', emoji: '\u{1F957}' },
  { k: ['\u0633\u0644\u0637\u0629 \u064a\u0648\u0646\u0627\u0646\u064a\u0629'], img: 'greek_salad.jpg', emoji: '\u{1F957}' },
];
const DEFAULT_PHOTO = { img: 'meze.jpg', emoji: '🍽️' };
function photoFor(dish) {
  // Prefer the product's own name (English or Arabic) so an ingredient in
  // its description cannot select a different product's photo.
  const name = ((dish.name || '') + ' ' + (dish.name_ar || '')).toLowerCase();
  const text = (name + ' ' + (dish.description || '') + ' ' + (dish.description_ar || '')).toLowerCase();
  for (const source of [name, text]) {
    for (const r of AR_PHOTO_RULES.concat(PHOTO_RULES)) {
      for (const k of r.k) { if (source.indexOf(k) !== -1) return r; }
    }
  }
  return DEFAULT_PHOTO;
}
function vendorImg(file) { return '/img/' + file; }
/* Thumbnail for the dashboard menu table: vendor photo first,
   then the same name-matched food photo the customer site shows. */
function dishThumb(d) {
  if (d.photo_url) {
    return '<img class="dish-thumb" src="' + esc(d.photo_url) + '" alt="" loading="lazy" onerror="thumbFallback(this)">';
  }
  var p = photoFor(d);
  if (p.tile) return '<div class="dish-thumb fallback">' + esc(p.emoji || '\U0001f37d\ufe0f') + '</div>';
  return '<img class="dish-thumb" src="' + vendorImg(p.img) + '" alt="" loading="lazy" data-emoji="' + esc(p.emoji || '') + '" onerror="thumbFallback(this)">';
}
window.thumbFallback = function (el) {
  var emo = el.getAttribute('data-emoji') || '\U0001f37d\ufe0f';
  var div = document.createElement('div');
  div.className = 'dish-thumb fallback';
  div.textContent = emo;
  el.replaceWith(div);
};
/* Live photo preview under a photo-URL field: the typed URL wins;
   otherwise the name-matched food photo for the dish being edited/added
   (the same picture the customer site shows) — never the logo. */
window.previewDishPhoto = function (inputId, imgId, nameId) {
  var inp = document.getElementById(inputId), img = document.getElementById(imgId);
  if (!inp || !img) return;
  var v = inp.value.trim();
  var nm = (nameId && document.getElementById(nameId)) ? document.getElementById(nameId).value : '';
  if (v) { img.src = v; }
  else if (nm.trim()) { img.src = vendorImg(photoFor({ name: nm, description: '' }).img); }
  else { img.style.display = 'none'; return; }
  img.style.display = '';
};
window.previewDishPhotoErr = function (el) { el.onerror = null; el.src = '/img/meze.jpg'; };
window.dishThumb = dishThumb;

/* Photo file picker: show a local preview immediately; the file is uploaded
   when the form is submitted (uploadDishPhoto), which returns the URL. */
window.photoFilePicked = function (fileId, urlId, imgId) {
  var inp = document.getElementById(fileId), img = document.getElementById(imgId);
  if (!inp || !img || !inp.files || !inp.files[0]) return;
  img.src = URL.createObjectURL(inp.files[0]);
  img.style.display = '';
  var urlInp = document.getElementById(urlId);
  if (urlInp) { urlInp.value = ''; } // the uploaded file wins over a pasted URL
};
/* Uploads the chosen file (if any) to /api/dishes/photo-upload and returns the
   URL. Throws on failure. Uses raw fetch: api() forces JSON content-type,
   which breaks multipart uploads. */
async function uploadDishPhoto(fileId) {
  var inp = document.getElementById(fileId);
  if (!inp || !inp.files || !inp.files[0]) return null;
  var fd = new FormData();
  fd.append('file', inp.files[0]);
  var headers = {};
  if (S.token) headers['Authorization'] = 'Bearer ' + S.token;
  var res = await fetch('/api/dishes/photo-upload', { method: 'POST', headers: headers, body: fd });
  if (!res.ok) {
    var msg = res.statusText;
    try { var j = await res.json(); if (j && j.detail) msg = j.detail; } catch (e) { /* ignore */ }
    throw new Error(t('upload_failed') + msg);
  }
  var j = await res.json();
  return j.photo_url;
}

/* === v46: delivery photo proof — uploads the picked file straight to the
   order's delivery-photo endpoint (same raw-fetch/FormData approach as
   uploadDishPhoto: api() forces JSON, which breaks multipart), then
   reloads the order detail so the thumbnail shows. === */
window.deliveryPhotoPicked = async function (orderId) {
  var inp = document.getElementById('delphoto-file');
  var errEl = document.getElementById('delphoto-err');
  if (!inp || !inp.files || !inp.files[0]) return;
  var fd = new FormData();
  fd.append('file', inp.files[0]);
  var headers = {};
  if (S.token) headers['Authorization'] = 'Bearer ' + S.token;
  try {
    var res = await fetch('/api/orders/' + orderId + '/delivery-photo', { method: 'POST', headers: headers, body: fd });
    if (!res.ok) {
      var msg = res.statusText;
      try { var j = await res.json(); if (j && j.detail) msg = j.detail; } catch (e) { /* ignore */ }
      throw new Error(msg);
    }
    await vOrderDetail(orderId);
  } catch (e) {
    if (errEl) errEl.textContent = t('upload_failed') + e.message;
  }
};
/* === END v46 === */

/* ---- video upload plumbing (dishes + vendor intro) ----
   Mirrors the photo flow: validate client-side for a friendly message
   (server enforces mp4/webm + 25MB too), show a local preview immediately,
   upload on form submit. uploadVideo() returns the URL. Uses raw fetch:
   api() forces JSON content-type, which breaks multipart uploads. */
const VIDEO_MAX_BYTES = 25 * 1024 * 1024;
window.videoFilePicked = function (fileId, prevId, urlId, errId) {
  var inp = document.getElementById(fileId), vid = document.getElementById(prevId);
  var errEl = errId && document.getElementById(errId);
  if (errEl) errEl.textContent = '';
  if (!inp || !inp.files || !inp.files[0]) return;
  var f = inp.files[0];
  var okType = /^(video\/mp4|video\/webm)$/i.test(f.type) || /\.(mp4|webm)$/i.test(f.name);
  if (!okType) {
    if (errEl) errEl.textContent = t('video_bad_type');
    inp.value = '';
    return;
  }
  if (f.size > VIDEO_MAX_BYTES) {
    if (errEl) errEl.textContent = t('video_too_big');
    inp.value = '';
    return;
  }
  if (vid) { vid.src = URL.createObjectURL(f); vid.style.display = ''; }
  var urlInp = urlId && document.getElementById(urlId);
  if (urlInp) urlInp.value = ''; // the uploaded file wins over a past URL
};
/* Clear a picked/uploaded video (file input + hidden URL + preview). */
window.removeVideo = function (fileId, prevId, urlId) {
  var inp = document.getElementById(fileId);
  if (inp) inp.value = '';
  var urlInp = urlId && document.getElementById(urlId);
  if (urlInp) urlInp.value = '';
  var vid = prevId && document.getElementById(prevId);
  if (vid) { vid.removeAttribute('src'); vid.style.display = 'none'; }
};
/* Uploads the chosen video file (if any) to /api/uploads/video and returns
   the URL. Throws on failure. */
async function uploadVideo(fileId) {
  var inp = document.getElementById(fileId);
  if (!inp || !inp.files || !inp.files[0]) return null;
  var fd = new FormData();
  fd.append('file', inp.files[0]);
  var headers = {};
  if (S.token) headers['Authorization'] = 'Bearer ' + S.token;
  var res = await fetch('/api/uploads/video', { method: 'POST', headers: headers, body: fd });
  if (!res.ok) {
    var msg = res.statusText;
    try { var j = await res.json(); if (j && j.detail) msg = j.detail; } catch (e) { /* ignore */ }
    throw new Error(t('upload_failed') + msg);
  }
  var j2 = await res.json();
  return j2.url;
}


/* ---- low-stock alerts (in-portal only) ---- */
function stockThreshold(d) { return d.low_stock_threshold == null ? 5 : d.low_stock_threshold; }
function isLowStock(d) { return d.stock_quantity != null && d.stock_quantity <= stockThreshold(d); }
function lowStockDishes() { return (S.portal.menu || []).filter(isLowStock); }

function renderPortalShell() {
  const v = S.portal.vendor;
  const e = S.portal.earnings;
  const fresh = S.portal.orders.filter(o => o.status === 'new').length;
  const paused = !!(v && v.is_paused);
  let html = '<h2 class="section-title">🏪 ' + esc(v.name) + ' <span class="sub">' + esc(t('portal_sub')) + '</span></h2>';
  // Big prominent pause/resume switch at the top of the dashboard.
  if (paused) html += '<div class="paused-banner">' + esc(t('paused_notice')) + '</div>';
  // === v48: direct-pay pause banner (weekly commission automation) ===
  if (v && v.direct_pay_paused) {
    const rec = (S.portal.receivables || []).find(r => r.vendor_id === v.id);
    html += '<div class="paused-banner">⏸ ' +
      esc(t('direct_paused_banner', { amount: rec ? money(rec.outstanding_commission) : '—' })) + '</div>';
  }
  // === END v48 ===
  html += '<button class="btn pause-btn' + (paused ? '' : ' danger') + '" style="width:100%;margin:.4rem 0 .8rem;font-size:1.05rem;padding:.7rem" onclick="togglePause()">' +
    esc(paused ? t('resume_shop') : t('pause_shop')) + '</button>';
  html += '<div class="stat-cards">' +
    '<div class="stat-card"><div class="num">' + money(e.total_revenue) + '</div><div class="lbl">' + esc(t('stat_revenue')) + '</div></div>' +
    '<div class="stat-card"><div class="num">' + e.order_count + '</div><div class="lbl">' + esc(t('stat_orders')) + '</div></div>' +
    '<div class="stat-card"><div class="num">' + S.portal.menu.length + '</div><div class="lbl">' + esc(t('stat_dishes')) + '</div></div></div>';
  html += '<div id="portal-alert"></div>';
  // Low-stock section: dishes at/below their threshold (default 5).
  const low = lowStockDishes();
  if (low.length) {
    html += '<div class="low-stock-box"><h3 class="section-title">⚠️ ' + esc(t('low_stock_title')) + '</h3>' +
      '<ul>' + low.map(d => '<li><strong>' + esc(dname(d)) + '</strong> — ' +
        esc(t('low_stock_left', { n: d.stock_quantity, t: stockThreshold(d) })) + '</li>').join('') + '</ul>' +
      '<button class="btn" onclick="go(\'stock\')">' + esc(t('low_stock_goto')) + '</button></div>';
  }
  html += '<h3 class="section-title">' + esc(t('orders_h')) + '</h3>' +
    '<div class="order-filters"><input id="order-q" placeholder="' + esc(t('order_search_ph')) + '" oninput="setOrderFilter()">' +
    '<select id="order-status" onchange="setOrderFilter()"><option value="all">' + esc(t('status_all')) + '</option>' +
    ['new', 'preparing', 'ready', 'on_the_way', 'completed', 'cancelled'].map(s =>
      '<option value="' + s + '">' + esc(statusLabel(s)) + '</option>').join('') + '</select></div>' +
    '<div id="portal-orders"></div>';
  // === FEATURE 2: share link + referral earnings ===
  html += shareMenuHTML();
  html += '<div id="ref-earnings"><div class="empty">' + esc(t('portal_loading')) + '</div></div>';
  // === END FEATURE 2 ===
  html += '<h3 class="section-title">' + esc(t('menu_h')) + '</h3><div style="margin:-.3rem 0 .8rem"><button class="btn" onclick="openBarcodeScanner()">' + esc(t('scan_barcode')) + '</button></div><div id="portal-menu"></div>';
  html += '<h3 class="section-title">' + esc(t('add_dish_h')) + '</h3><div id="dish-ann-msg"></div>' + bulkImportPanel() + addDishForm();
  // === F5/F8: family bundles + weekly pickup slots ===
  html += '<h3 class="section-title">' + esc(t('bundles_h')) + '</h3><div id="portal-bundles"><div class="empty">' + esc(t('v_loading')) + '</div></div>';
  html += '<h3 class="section-title">' + esc(t('slots_h')) + '</h3><div id="portal-slots"><div class="empty">' + esc(t('v_loading')) + '</div></div>';
  // === END F5/F8 ===
  // === Community drops (Oct 2026) ===
  html += '<h3 class="section-title">📦 ' + esc(t('drops_title')) + '</h3><div id="portal-drops"><div class="empty">' + esc(t('v_loading')) + '</div></div>';
  // === END community drops ===
  $('#view').innerHTML = html;
  portalRefreshDynamic();
  loadPortalBundles(); // === F5 ===
  loadPortalSlots();   // === F8 ===
  loadPortalDrops();   // === community drops ===
  loadReferralEarnings(); // === FEATURE 2 ===
}

/* ================= F2: share my menu + referral earnings =================
   "Share my menu" copies the vendor's unique /v/<code> link; attributed
   orders + the computed rebate (display only, no money moves in v1) load
   below. */
function shareMenuHTML() {
  const v = S.portal.vendor;
  const url = location.origin + '/v/' + (v.referral_code || '');
  return '<h3 class="section-title">' + esc(t('share_menu_h')) + '</h3>' +
    '<div class="form-card"><p class="hint" style="margin-top:0">' + esc(t('share_menu_hint')) + '</p>' +
    '<div class="row2"><div><input type="text" id="share-url" readonly value="' + esc(url) + '" onclick="this.select()"></div>' +
    '<div><label class="field">&nbsp;</label><button class="btn secondary" type="button" style="width:100%" onclick="copyShareLink()">' + esc(t('share_copy')) + '</button></div></div>' +
    '<div id="share-msg"></div></div>';
}
window.copyShareLink = function () {
  const el = $('#share-url');
  const url = el ? el.value : '';
  const done = () => { const m = $('#share-msg'); if (m) m.innerHTML = '<div class="success">' + esc(t('link_copied')) + '</div>'; };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(url).then(done, () => { try { el.select(); document.execCommand('copy'); } catch (e) {} done(); });
  } else {
    try { el.select(); document.execCommand('copy'); } catch (e) {}
    done();
  }
};
async function loadReferralEarnings() {
  const el = $('#ref-earnings');
  if (!el) return;
  try {
    const data = await api('/vendors/' + S.portal.vendorId + '/referrals');
    const pct = Number(data.rebate_percent);
    let html = '<h3 class="section-title">' + esc(t('ref_earn_h')) + '</h3><div class="form-card">';
    html += '<p class="hint" style="margin-top:0">' + esc(t('ref_earn_hint', { pct: pct })) + '</p>';
    const rows = data.attributed_orders || [];
    if (!rows.length) {
      html += '<div class="empty">' + esc(t('ref_no_orders')) + '</div>';
    } else {
      html += '<div class="table-wrap"><table class="menu-table"><thead><tr>' +
        '<th>' + esc(t('ref_th_order')) + '</th><th>' + esc(t('ref_th_date')) + '</th>' +
        '<th>' + esc(t('ref_th_subtotal')) + '</th><th>' + esc(t('ref_th_rebate')) + '</th>' +
        '</tr></thead><tbody>' +
        rows.map(o => '<tr><td>#' + o.id + '</td><td>' + esc((o.created_at || '').slice(0, 10)) + '</td>' +
          '<td>' + money(o.subtotal) + '</td><td>' + money(o.rebate) + '</td></tr>').join('') +
        '</tbody></table></div>';
      html += '<p><strong>' + esc(t('ref_total_rebate')) + ':</strong> ' + money(data.total_rebate) + '</p>';
    }
    html += '</div>';
    el.innerHTML = html;
  } catch (e) { el.innerHTML = ''; }
}
/* ================= END F2 ================= */

window.togglePause = async function () {
  const v = S.portal.vendor;
  if (!v) return;
  const toPaused = !v.is_paused;
  if (!confirm(t(toPaused ? 'pause_confirm' : 'pause_resume_q'))) return;
  try {
    const updated = await api('/vendors/' + v.id, { method: 'PATCH', body: JSON.stringify({ is_paused: toPaused }) });
    S.portal.vendor = updated;
    renderPortalShell();
  } catch (e) { alert(t('upd_failed') + errText(e)); }
};

function portalRefreshDynamic() {
  const alertEl = $('#portal-alert');
  const ordersEl = $('#portal-orders');
  const menuEl = $('#portal-menu');
  if (!alertEl) return; // left the page
  const fresh = S.portal.orders.filter(o => o.status === 'new');
  alertEl.innerHTML = fresh.length
    ? '<div class="alert-banner">' + t('new_orders', { n: fresh.length, list: fresh.map(o => '#' + o.id).join(', ') }) + '</div>'
    : '';
  const badge = $('#portal-badge');
  if (badge) {
    badge.textContent = fresh.length;
    badge.classList.toggle('hidden', fresh.length === 0);
    badge.classList.toggle('alert', fresh.length > 0);
  }

  ordersEl.innerHTML = S.portal.orders.length
    ? filteredPortalOrders().map(portalOrderCard).join('')
    : '<div class="empty">' + esc(t('no_orders')) + '</div>';

  menuEl.innerHTML = '<div class="table-wrap">' + '<table class="menu-table"><thead><tr><th>' + esc(t('th_photo')) + '</th><th>' + esc(t('th_dish')) + '</th><th>' + esc(t('th_category')) + '</th><th>' + esc(t('th_price')) + '</th>' +
    '<th>' + esc(t('th_discount')) + '</th>' +
    '<th>' + esc(t('th_stock')) + '</th>' +
    '<th>' + esc(t('th_available')) + '</th><th></th></tr></thead><tbody>' +
    S.portal.menu.map(d =>
      '<tr><td>' + dishThumb(d) + '</td><td><strong>' + esc(dname(d)) + '</strong><br><small style="color:var(--muted)">' + esc(d.description || '') + '</small></td>' +
      '<td>' + esc(catLabel(d.category)) + '</td><td>' + vPriceHTML(d) + '</td>' +
      '<td>' + (discOf(d) > 0 ? '<span class="disc-badge">-' + discOf(d) + '%</span>' : '—') + (d.sale_active ? ' ⚡' : '') + '</td>' +
      '<td>' + (d.stock_quantity == null ? '—' : esc(d.stock_quantity) + (isLowStock(d) ? ' ⚠️' : '')) + '</td>' +
      '<td><label class="switch"><input type="checkbox" ' + (d.available ? 'checked' : '') +
      ' onchange="toggleAvail(' + d.id + ', this.checked)"><span class="slider"></span></label></td>' +
      '<td style="white-space:nowrap"><button class="btn small" onclick="editDish(' + d.id + ')">' + esc(t('edit')) + '</button> ' +
      '<button class="btn small danger" onclick="deleteDish(' + d.id + ')">' + esc(t('delete')) + '</button></td></tr>'
    ).join('') + '</tbody></table>' + '</div>';
}

/* ================= F5: vendor bundle management =================
   Family combos: 3–5 of the vendor's OWN dishes at a fixed price.
   Count is enforced server-side (400); the portal pre-checks too. */
async function loadPortalBundles() {
  const box = document.getElementById('portal-bundles');
  if (!box) return;
  const vid = S.portal.vendorId;
  try {
    S.portal.bundles = await api('/bundles?vendor_id=' + vid + '&available_only=false');
    S.portal.editingBundle = null;
    renderPortalBundles();
  } catch (e) {
    box.innerHTML = '<div class="error">' + esc(errText(e)) + '</div>';
  }
}
function renderPortalBundles() {
  const box = document.getElementById('portal-bundles');
  if (!box) return;
  const bundles = S.portal.bundles || [];
  let html = '';
  if (bundles.length) {
    html += '<div class="table-wrap"><table class="menu-table"><thead><tr><th>' + esc(t('th_photo')) + '</th><th>' +
      esc(t('th_bundle')) + '</th><th>' + esc(t('th_items')) + '</th><th>' + esc(t('th_price')) + '</th><th>' +
      esc(t('th_available')) + '</th><th></th></tr></thead><tbody>' +
      bundles.map(b =>
        '<tr><td>' + (b.photo_url
          ? '<img class="thumb" src="' + esc(b.photo_url) + '" alt="" onerror="this.style.display=\'none\'">'
          : '🎁') + '</td>' +
        '<td><strong>' + esc(b.name) + '</strong>' + (b.ended ? ' <span class="ended-badge">' + esc(t('feast_ended')) + '</span>' : '') + (b.name_ar ? '<br><small>' + esc(b.name_ar) + '</small>' : '') + '</td>' +
        '<td><small>' + esc((b.items || []).map(i => ((lang() === 'ar' && i.dish_name_ar) ? i.dish_name_ar : i.dish_name) + ((i.quantity || 1) > 1 ? ' ×' + i.quantity : '')).join(', ')) + '</small></td>' +
        '<td>' + money(b.price) + '</td>' +
        '<td><label class="switch"><input type="checkbox" ' + (b.available ? 'checked' : '') +
        ' onchange="toggleBundleAvail(' + b.id + ', this.checked)"><span class="slider"></span></label></td>' +
        '<td style="white-space:nowrap"><button class="btn small" onclick="editBundle(' + b.id + ')">' + esc(t('edit')) + '</button> ' +
        '<button class="btn small danger" onclick="deleteBundle(' + b.id + ')">' + esc(t('delete')) + '</button></td></tr>'
      ).join('') + '</tbody></table></div>';
  } else {
    html += '<div class="empty">' + esc(t('bundles_none')) + '</div>';
  }
  html += bundleFormHTML(S.portal.editingBundle || null);
  box.innerHTML = html;
}
function bundleFormHTML(b) {
  const menu = (S.portal.menu || []).filter(d => d.available);
  const sel = b ? (b.items || []).map(i => i.dish_id) : [];
  return '<div class="form-card"><h4>' + esc(t(b ? 'bundle_edit_h' : 'bundle_new_h')) + '</h4>' +
    '<div class="row2"><div><label class="field">' + esc(t('f_dish')) + '</label>' +
    '<input type="text" id="bd-name" maxlength="160" value="' + esc(b ? b.name : '') + '"></div>' +
    '<div><label class="field">' + esc(t('f_name_ar')) + '</label>' +
    '<input type="text" id="bd-name-ar" maxlength="160" value="' + esc(b && b.name_ar ? b.name_ar : '') + '"></div></div>' +
    '<label class="field">' + esc(t('f_desc')) + '</label><textarea id="bd-desc" rows="2" maxlength="2000">' +
    esc(b && b.description ? b.description : '') + '</textarea>' +
    '<div class="row2"><div><label class="field">' + esc(t('f_price')) + '</label>' +
    '<input type="number" id="bd-price" min="0.01" step="0.01" value="' + esc(b ? b.price : '') + '"></div>' +
    '<div><label class="field">' + esc(t('f_photo')) + '</label>' +
    '<input type="url" id="bd-photo" maxlength="2000" value="' + esc(b && b.photo_url ? b.photo_url : '') + '"></div></div>' +
    '<label class="field">' + esc(t('bundle_pick_dishes')) + '</label>' +
    '<div class="check-list">' + (menu.length ? menu.map(d =>
      '<label class="check"><input type="checkbox" class="bd-dish" value="' + d.id + '"' +
      (sel.indexOf(d.id) >= 0 ? ' checked' : '') + '> ' + esc(dname(d)) + ' <small>' + money(d.price) + '</small></label>'
    ).join('') : '<div class="empty">' + esc(t('bundles_none')) + '</div>') + '</div>' +
    '<div class="hint">' + esc(t('bundle_pick_hint')) + '</div>' +
    // === Holiday feast (Oct 2026) — toggle reveals holiday fields ===
    '<h4 style="margin:1rem 0 .4rem">🎉 ' + esc(t('feast_h')) + '</h4>' +
    '<label><input type="checkbox" id="bd-feast"' + ((b && b.holiday_name) ? ' checked' : '') + ((b && b.ended) ? ' disabled' : '') + ' onchange="toggleFeastFields()"> ' + esc(t('feast_toggle')) + '</label>' +
    '<div id="bd-feast-fields"' + ((b && b.holiday_name) ? '' : ' style="display:none"') + '>' +
    ((b && b.ended)
      ? '<div class="hint" style="margin-top:.5rem">' + esc(t('feast_ended')) + '</div>'
      : '<div class="row2"><div><label class="field">' + esc(t('feast_name')) + '</label>' +
        '<input type="text" id="bd-holiday" maxlength="80" placeholder="' + esc(t('feast_name_ph')) + '" value="' + esc(b && b.holiday_name ? b.holiday_name : '') + '"></div>' +
        '<div><label class="field">' + esc(t('feast_order_by')) + '</label>' +
        '<input type="date" id="bd-orderby" value="' + esc(b && b.order_by ? b.order_by : '') + '"></div></div>' +
        '<label class="field">' + esc(t('feast_max')) + '</label>' +
        '<input type="number" id="bd-maxorders" min="1" step="1" value="' + (b && b.max_orders != null ? esc(b.max_orders) : '') + '">' +
        '<div class="hint">' + esc(t('feast_hint')) + '</div>') +
    '</div>' +
    // === END Holiday feast ===
    '<div class="order-actions"><button class="btn" onclick="saveBundle(' + (b ? b.id : 'null') + ')">' + esc(t('v_save')) + '</button>' +
    (b ? ' <button class="btn secondary" onclick="S.portal.editingBundle=null;renderPortalBundles()">' + esc(t('cancel')) + '</button>' : '') +
    '</div></div>';
}
window.saveBundle = async function (bundleId) {
  const vid = S.portal.vendorId;
  const dishIds = Array.prototype.slice.call(document.querySelectorAll('.bd-dish:checked'))
    .map(x => Number(x.value)).filter(n => n > 0);
  if (dishIds.length < 3 || dishIds.length > 5) { alert(t('bundle_count_err')); return; }
  const name = ($('#bd-name') && $('#bd-name').value || '').trim();
  if (!name) { alert(t('bundle_name_err')); return; }
  const price = Number($('#bd-price') && $('#bd-price').value);
  if (!(price > 0)) { alert(t('bundle_price_err')); return; }
  const body = {
    name: name,
    name_ar: (($('#bd-name-ar') && $('#bd-name-ar').value) || '').trim() || null,
    description: (($('#bd-desc') && $('#bd-desc').value) || '').trim(),
    price: price,
    photo_url: (($('#bd-photo') && $('#bd-photo').value) || '').trim() || null,
    items: dishIds.map(id => ({ dish_id: id, quantity: 1 })),
  };
  // === Holiday feast (Oct 2026): only read the fields when they exist
  // (an ended feast renders them read-only) and the toggle is on. ===
  const feastCb = $('#bd-feast');
  const feastOn = feastCb && !feastCb.disabled && feastCb.checked && $('#bd-holiday');
  if (feastOn) {
    const holiday = $('#bd-holiday').value.trim();
    if (!holiday) { alert(t('feast_name_err')); return; }
    let maxOrders = null;
    const moRaw = ($('#bd-maxorders').value || '').trim();
    if (moRaw !== '') {
      maxOrders = parseInt(moRaw, 10);
      if (isNaN(maxOrders) || maxOrders < 1) { alert(t('feast_max_err')); return; }
    }
    body.holiday_name = holiday;
    body.order_by = $('#bd-orderby').value || null; // <input type="date"> -> 'YYYY-MM-DD'
    body.max_orders = maxOrders;
  } else if (feastCb && !feastCb.checked) {
    // Toggle off: clear any previous holiday-feast data on this bundle.
    body.holiday_name = null;
    body.order_by = null;
    body.max_orders = null;
  }
  // === END Holiday feast ===
  try {
    if (bundleId) await api('/bundles/' + bundleId, { method: 'PATCH', body: JSON.stringify(body) });
    else await api('/bundles?vendor_id=' + vid, { method: 'POST', body: JSON.stringify(body) });
    S.portal.editingBundle = null;
    await loadPortalBundles();
  } catch (e) { alert(errText(e)); }
};
window.editBundle = function (id) {
  S.portal.editingBundle = (S.portal.bundles || []).find(b => b.id === id) || null;
  renderPortalBundles();
};
/* Holiday feast toggle: reveal/hide the holiday-name, order-by and
   max-orders fields in the bundle form. */
window.toggleFeastFields = function () {
  const box = document.getElementById('bd-feast-fields');
  const cb = document.getElementById('bd-feast');
  if (box && cb) box.style.display = cb.checked ? '' : 'none';
};
window.toggleBundleAvail = async function (id, on) {
  try {
    await api('/bundles/' + id, { method: 'PATCH', body: JSON.stringify({ available: on }) });
  } catch (e) { alert(errText(e)); }
  await loadPortalBundles();
};
window.deleteBundle = async function (id) {
  if (!confirm(t('v_delete_confirm'))) return;
  try {
    await api('/bundles/' + id, { method: 'DELETE' });
    await loadPortalBundles();
  } catch (e) { alert(errText(e)); }
};
/* ================= END F5 ================= */

/* ================= F8: vendor pickup slot management =================
   Weekly windows (0=Monday..6=Sunday). While at least one slot is ACTIVE,
   pickup checkout requires the customer to pick one; with no slots the
   checkout behaves exactly as today. */
function slotDayName(wd) {
  const keys = ['slot_day_mon', 'slot_day_tue', 'slot_day_wed', 'slot_day_thu', 'slot_day_fri', 'slot_day_sat', 'slot_day_sun'];
  return t(keys[wd] || keys[0]);
}
async function loadPortalSlots() {
  const box = document.getElementById('portal-slots');
  if (!box) return;
  const vid = S.portal.vendorId;
  try {
    S.portal.slots = await api('/pickup-slots/mine?vendor_id=' + vid);
    renderPortalSlots();
  } catch (e) {
    box.innerHTML = '<div class="error">' + esc(errText(e)) + '</div>';
  }
}
function renderPortalSlots() {
  const box = document.getElementById('portal-slots');
  if (!box) return;
  const slots = S.portal.slots || [];
  let html = '<div class="hint">' + esc(t('slots_hint')) + '</div>';
  if (slots.length) {
    html += '<div class="table-wrap"><table class="menu-table"><thead><tr><th>' + esc(t('th_day')) + '</th><th>' +
      esc(t('th_time')) + '</th><th>' + esc(t('th_active')) + '</th><th></th></tr></thead><tbody>' +
      slots.map(s =>
        '<tr><td><strong>' + esc(slotDayName(s.weekday)) + '</strong></td>' +
        '<td>' + esc(s.label) + '</td>' +
        '<td><label class="switch"><input type="checkbox" ' + (s.active ? 'checked' : '') +
        ' onchange="toggleSlot(' + s.id + ', this.checked)"><span class="slider"></span></label></td>' +
        '<td><button class="btn small danger" onclick="deleteSlot(' + s.id + ')">' + esc(t('delete')) + '</button></td></tr>'
      ).join('') + '</tbody></table></div>';
  } else {
    html += '<div class="empty">' + esc(t('slots_none')) + '</div>';
  }
  html += '<div class="form-card"><h4>' + esc(t('slot_new_h')) + '</h4>' +
    '<div class="row2"><div><label class="field">' + esc(t('th_day')) + '</label>' +
    '<select id="sl-day">' + [0, 1, 2, 3, 4, 5, 6].map(d =>
      '<option value="' + d + '">' + esc(slotDayName(d)) + '</option>').join('') + '</select></div>' +
    '<div><label class="field">' + esc(t('th_time')) + '</label>' +
    '<div class="row2"><input type="time" id="sl-start" value="14:00"><input type="time" id="sl-end" value="18:00"></div></div></div>' +
    '<div class="order-actions"><button class="btn" onclick="addSlot()">' + esc(t('v_add')) + '</button></div></div>';
  box.innerHTML = html;
}
window.addSlot = async function () {
  const vid = S.portal.vendorId;
  try {
    await api('/pickup-slots/mine?vendor_id=' + vid, {
      method: 'POST',
      body: JSON.stringify({
        weekday: Number($('#sl-day').value),
        start_time: $('#sl-start').value,
        end_time: $('#sl-end').value,
      }),
    });
    await loadPortalSlots();
  } catch (e) { alert(errText(e)); }
};
window.toggleSlot = async function (id, on) {
  try {
    await api('/pickup-slots/mine/' + id, { method: 'PATCH', body: JSON.stringify({ active: on }) });
  } catch (e) { alert(errText(e)); }
  await loadPortalSlots();
};
window.deleteSlot = async function (id) {
  if (!confirm(t('v_delete_confirm'))) return;
  try {
    await api('/pickup-slots/mine/' + id, { method: 'DELETE' });
    await loadPortalSlots();
  } catch (e) { alert(errText(e)); }
};
/* ================= END F8 ================= */

/* ================= community drops (Oct 2026) =================
   Vendor-managed neighborhood batch drop-offs: a form (label, address,
   zips, date, start, end, max, active, save), a list with edit/delete,
   and a "Drop batches" view showing each drop's orders with counts. */
async function loadPortalDrops() {
  const box = document.getElementById('portal-drops');
  if (!box) return;
  try {
    S.portal.drops = await api('/vendors/' + S.portal.vendorId + '/drops');
    S.dropEdit = null;
    renderPortalDrops();
  } catch (e) { box.innerHTML = '<div class="error">' + esc(errText(e)) + '</div>'; }
}
function dropCardHTML(d) {
  return '<div class="order-card"><div class="order-head"><div><strong>' + esc(d.label) + '</strong>' +
    (d.is_active ? '' : ' <span class="status-pill">⏸</span>') + '</div>' +
    '<span class="vendor-tag">' + esc(d.drop_date) + ' · ' + esc(d.time_start) + '–' + esc(d.time_end) + '</span></div>' +
    '<div class="vendor-tag">📍 ' + esc(d.address_text || '—') + '</div>' +
    '<div class="vendor-tag">🧾 ' + esc(d.zip_codes) +
    (d.max_orders != null ? ' · ' + esc(t('drop_max')) + ': ' + esc(d.max_orders) : '') + '</div>' +
    '<div class="order-actions">' +
    '<button class="btn small secondary" onclick="toggleDropOrders(' + d.id + ')">' + esc(t('drop_batches')) + '</button> ' +
    '<button class="btn small secondary" onclick="editDrop(' + d.id + ')">' + esc(t('edit')) + '</button> ' +
    '<button class="btn small danger" onclick="deleteDrop(' + d.id + ')">' + esc(t('drop_delete')) + '</button></div>' +
    '<div id="drop-orders-' + d.id + '"></div></div>';
}
function dropFormHTML() {
  const ed = S.dropEdit || null;
  const val = function (k, dflt) { return (ed && ed[k] != null) ? ed[k] : dflt; };
  const today = new Date().toISOString().slice(0, 10);
  return '<div class="form-card"><h4>' + esc(ed ? t('edit') + ': ' + ed.label : t('drop_new')) + '</h4>' +
    '<label class="field">' + esc(t('drop_label')) + '</label>' +
    '<input type="text" id="drop-f-label" maxlength="120" value="' + esc(val('label', '')) + '">' +
    '<label class="field">' + esc(t('drop_address')) + '</label>' +
    '<input type="text" id="drop-f-address" maxlength="2000" value="' + esc(val('address_text', '')) + '">' +
    '<label class="field">' + esc(t('drop_zips')) + '</label>' +
    '<input type="text" id="drop-f-zips" maxlength="2000" placeholder="98052, 98201" value="' + esc(val('zip_codes', '')) + '">' +
    '<div class="row2"><div><label class="field">' + esc(t('drop_date')) + '</label>' +
    '<input type="date" id="drop-f-date" value="' + esc(val('drop_date', today)) + '"></div>' +
    '<div><label class="field">' + esc(t('drop_start')) + ' / ' + esc(t('drop_end')) + '</label>' +
    '<div class="row2"><input type="time" id="drop-f-start" value="' + esc(val('time_start', '14:00')) + '">' +
    '<input type="time" id="drop-f-end" value="' + esc(val('time_end', '18:00')) + '"></div></div></div>' +
    '<div class="row2"><div><label class="field">' + esc(t('drop_max')) + '</label>' +
    '<input type="number" id="drop-f-max" min="1" step="1" value="' +
    (val('max_orders', null) != null ? esc(val('max_orders', '')) : '') + '"></div>' +
    '<div><label class="field">&nbsp;</label><label><input type="checkbox" id="drop-f-active"' +
    (val('is_active', true) ? ' checked' : '') + '> ' + esc(t('drop_active')) + '</label></div></div>' +
    '<div class="order-actions"><button class="btn" onclick="saveDrop()">' + esc(t('drop_save')) + '</button>' +
    (ed ? ' <button class="btn secondary" onclick="cancelDropEdit()">' + esc(t('cancel')) + '</button>' : '') +
    '</div></div>';
}
function renderPortalDrops() {
  const box = document.getElementById('portal-drops');
  if (!box) return;
  const drops = S.portal.drops || [];
  let html = drops.length
    ? drops.map(dropCardHTML).join('')
    : '<div class="empty">' + esc(t('no_match')) + '</div>';
  html += dropFormHTML();
  box.innerHTML = html;
}
window.saveDrop = async function () {
  const vid = S.portal.vendorId;
  const maxRaw = document.getElementById('drop-f-max').value.trim();
  const body = {
    label: document.getElementById('drop-f-label').value.trim(),
    address_text: document.getElementById('drop-f-address').value.trim() || null,
    zip_codes: document.getElementById('drop-f-zips').value.trim(),
    drop_date: document.getElementById('drop-f-date').value,
    time_start: document.getElementById('drop-f-start').value,
    time_end: document.getElementById('drop-f-end').value,
    max_orders: maxRaw === '' ? null : parseInt(maxRaw, 10),
    is_active: document.getElementById('drop-f-active').checked,
  };
  try {
    if (S.dropEdit) {
      await api('/vendors/' + vid + '/drops/' + S.dropEdit.id,
        { method: 'PATCH', body: JSON.stringify(body) });
    } else {
      await api('/vendors/' + vid + '/drops', { method: 'POST', body: JSON.stringify(body) });
    }
    await loadPortalDrops();
  } catch (e) { alert(errText(e)); }
};
window.editDrop = function (id) {
  S.dropEdit = (S.portal.drops || []).find(function (d) { return d.id === id; }) || null;
  renderPortalDrops();
};
window.cancelDropEdit = function () {
  S.dropEdit = null;
  renderPortalDrops();
};
window.deleteDrop = async function (id) {
  if (!confirm(t('v_delete_confirm'))) return;
  try {
    await api('/vendors/' + S.portal.vendorId + '/drops/' + id, { method: 'DELETE' });
    await loadPortalDrops();
  } catch (e) { alert(errText(e)); }
};
/* Drop batches: per drop, the orders riding it, with counts. */
window.toggleDropOrders = async function (id) {
  const box = document.getElementById('drop-orders-' + id);
  if (!box) return;
  if (box.dataset.loaded === '1') { box.innerHTML = ''; box.dataset.loaded = ''; return; }
  box.innerHTML = '<div class="empty">' + esc(t('detail_loading')) + '</div>';
  try {
    const r = await api('/vendors/' + S.portal.vendorId + '/drops/' + id + '/orders');
    const orders = (r && r.orders) || [];
    let html = '<h4 style="margin:.6rem 0 .4rem">📦 ' + esc(t('drop_batches')) + ' — ' +
      esc(t('drop_orders_count', { n: (r && r.count) || 0 })) + '</h4>';
    if (!orders.length) {
      html += '<div class="empty">' + esc(t('no_match')) + '</div>';
    } else {
      html += '<ul class="order-items">' + orders.map(function (o) {
        const items = (o.items || []).map(function (i) { return i.quantity + ' × ' + iname(i); }).join(', ');
        return '<li><strong>#' + o.id + '</strong> · ' + esc(o.customer_name || t('customer_fb')) +
          ' · <span class="status-pill status-' + esc(o.status) + '">' + esc(statusLabel(o.status)) + '</span>' +
          ' · <strong>' + money(o.total) + '</strong><br><small>' + esc(items) + '</small></li>';
      }).join('') + '</ul>';
    }
    box.innerHTML = html;
    box.dataset.loaded = '1';
  } catch (e) { box.innerHTML = '<div class="error">' + esc(errText(e)) + '</div>'; }
};
/* ================= END community drops ================= */

/* ================= vendor stock view (inventory) =================
   Bulk stock table (editable quantities + Save all), per-dish Restock
   (reason 'restock') and movement history. */
async function vStock() {
  const view = $('#view');
  if (!S.user || S.user.role !== 'vendor') {
    view.innerHTML = '<div class="empty"><span class="big">🔒</span>' + esc(t('vendor_only')) + '<br><br>' +
      '<button class="btn" onclick="go(\'login\')">' + esc(t('login_as_vendor')) + '</button></div>';
    return;
  }
  view.innerHTML = '<div class="empty"><span class="big">📦</span>' + esc(t('portal_loading')) + '</div>';
  try {
    const vendors = await api('/vendors/mine');
    if (!vendors.length) { view.innerHTML = '<div class="empty">' + esc(t('no_shop')) + '</div>'; return; }
    S.portal.vendorId = vendors[0].id;
    S.portal.vendor = vendors[0];
    S.portal.menu = await api('/dishes?vendor_id=' + vendors[0].id + '&available_only=false');
    S.portal.menu.forEach(d => { S.dishById[d.id] = d; });
    renderStockView();
  } catch (e) {
    view.innerHTML = '<div class="error">' + esc(t('portal_err')) + esc(e.message) + '</div>';
  }
}

function renderStockView() {
  const menu = S.portal.menu || [];
  let html = '<h2 class="section-title">📦 ' + esc(t('stock_h')) + '</h2>' +
    '<p class="hint">' + esc(t('stock_hint')) + '</p>';
  if (!menu.length) {
    html += '<div class="empty">' + esc(t('no_dishes')) + '</div>';
  } else {
    html += '<div class="table-wrap"><table class="menu-table"><thead><tr><th>' + esc(t('th_dish')) + '</th>' +
      '<th>' + esc(t('stock_qty')) + '</th><th>' + esc(t('stock_threshold')) + '</th><th>' + esc(t('stock_status')) +
      '</th><th></th></tr></thead><tbody>' +
      menu.map(d => {
        const low = isLowStock(d);
        const status = d.stock_quantity == null ? t('stock_untracked')
          : low ? '⚠️ ' + t('stock_low') : '✅ ' + t('stock_ok');
        return '<tr><td><strong>' + esc(dname(d)) + '</strong><br><small style="color:var(--muted)">' + esc(catLabel(d.category)) + '</small></td>' +
          '<td><input type="number" class="stock-qty" data-dish="' + d.id + '" min="0" step="1" style="width:5rem" value="' +
          (d.stock_quantity != null ? esc(d.stock_quantity) : '') + '" placeholder="' + esc(t('stock_untracked_short')) + '"></td>' +
          '<td><input type="number" class="stock-thr" data-dish="' + d.id + '" min="0" step="1" style="width:4rem" value="' +
          (d.low_stock_threshold != null ? esc(d.low_stock_threshold) : '') + '" placeholder="5"></td>' +
          '<td>' + esc(status) + '</td>' +
          '<td style="white-space:nowrap"><button class="btn small" onclick="restockDish(' + d.id + ')">' + esc(t('stock_restock')) + '</button> ' +
          '<button class="btn small secondary" onclick="showStockHistory(' + d.id + ')">' + esc(t('stock_history')) + '</button></td></tr>';
      }).join('') + '</tbody></table></div>' +
      '<div class="mt"><button class="btn" onclick="saveAllStock()">' + esc(t('stock_save_all')) + '</button> ' +
      '<span class="hint">' + esc(t('stock_save_hint')) + '</span></div>';
  }
  html += '<div id="stock-history"></div>';
  $('#view').innerHTML = html;
}

window.saveAllStock = async function () {
  const qtyEls = Array.from(document.querySelectorAll('.stock-qty'));
  const items = [];
  for (const el of qtyEls) {
    const raw = el.value.trim();
    if (raw !== '' && (isNaN(parseInt(raw, 10)) || parseInt(raw, 10) < 0)) {
      alert(t('stock_qty_invalid')); return;
    }
    items.push({ dish_id: parseInt(el.dataset.dish, 10), stock_quantity: raw === '' ? null : parseInt(raw, 10) });
  }
  try {
    await api('/dishes/bulk-stock', {
      method: 'POST',
      body: JSON.stringify({ vendor_id: S.portal.vendorId, items }),
    });
    // Thresholds ride along as individual PATCHes (only the changed ones).
    const thrEls = Array.from(document.querySelectorAll('.stock-thr'));
    for (const el of thrEls) {
      const id = parseInt(el.dataset.dish, 10);
      const d = S.portal.menu.find(x => x.id === id);
      if (!d) continue;
      const raw = el.value.trim();
      const val = raw === '' ? null : parseInt(raw, 10);
      if (val !== null && (isNaN(val) || val < 0)) { alert(t('stock_qty_invalid')); return; }
      if ((d.low_stock_threshold ?? null) !== val) {
        await api('/dishes/' + id, { method: 'PATCH', body: JSON.stringify({ low_stock_threshold: val }) });
      }
    }
    S.portal.menu = await api('/dishes?vendor_id=' + S.portal.vendorId + '&available_only=false');
    renderStockView();
    alert(t('stock_saved'));
  } catch (e) { alert(t('upd_failed') + errText(e)); }
};

window.restockDish = async function (id) {
  const d = S.portal.menu.find(x => x.id === id);
  const q = prompt(t('stock_restock_prompt', { name: d ? dname(d) : '' }));
  if (q === null) return;
  const n = parseInt(q, 10);
  if (isNaN(n) || n <= 0) { alert(t('stock_restock_invalid')); return; }
  try {
    await api('/dishes/' + id + '/restock', { method: 'POST', body: JSON.stringify({ quantity: n }) });
    S.portal.menu = await api('/dishes?vendor_id=' + S.portal.vendorId + '&available_only=false');
    renderStockView();
  } catch (e) { alert(t('upd_failed') + errText(e)); }
};

window.showStockHistory = async function (id) {
  const d = S.portal.menu.find(x => x.id === id);
  const el = $('#stock-history');
  el.innerHTML = '<div class="empty">' + esc(t('detail_loading')) + '</div>';
  try {
    const moves = await api('/dishes/' + id + '/stock-movements');
    let html = '<h3 class="section-title">' + esc(t('stock_history_h', { name: d ? dname(d) : '' })) + '</h3>';
    if (!moves.length) {
      html += '<div class="empty">' + esc(t('stock_no_history')) + '</div>';
    } else {
      html += '<div class="table-wrap"><table class="menu-table"><thead><tr><th>' + esc(t('tbl_date')) + '</th><th>' +
        esc(t('stock_reason')) + '</th><th>' + esc(t('stock_delta')) + '</th><th>' + esc(t('stock_after')) +
        '</th><th>' + esc(t('tbl_id')) + '</th></tr></thead><tbody>' +
        moves.map(m => '<tr><td>' + esc(fmtDate(m.created_at)) + '</td><td>' + esc(t('stock_reason_' + m.reason)) + '</td>' +
          '<td>' + (m.delta >= 0 ? '+' : '') + esc(m.delta) + '</td><td>' + (m.stock_after == null ? '—' : esc(m.stock_after)) + '</td>' +
          '<td>' + (m.order_id ? '#' + m.order_id : '—') + '</td></tr>').join('') + '</tbody></table></div>';
    }
    el.innerHTML = html;
    el.scrollIntoView({ behavior: 'smooth' });
  } catch (e) { el.innerHTML = '<div class="error">' + esc(e.message) + '</div>'; }
};

/* ---- vendor order search + status filter ---- */
function filteredPortalOrders() {
  const q = ($('#order-q') && $('#order-q').value || '').trim().toLowerCase();
  const st = ($('#order-status') && $('#order-status').value) || 'all';
  return S.portal.orders.filter(o => {
    if (st !== 'all' && o.status !== st) return false;
    if (!q) return true;
    const hay = ('#' + o.id + ' ' + (o.customer_name || '') + ' ' +
      (o.items || []).map(i => (i.dish_name || '') + ' ' + (i.dish_name_ar || '')).join(' ')).toLowerCase();
    return hay.indexOf(q) !== -1;
  });
}
window.setOrderFilter = function () {
  const ordersEl = $('#portal-orders');
  if (!ordersEl) return;
  const list = filteredPortalOrders();
  ordersEl.innerHTML = list.length
    ? list.map(portalOrderCard).join('')
    : '<div class="empty">' + esc(t('no_match')) + '</div>';
};

function portalOrderCard(o) {
  return '<div class="order-card clickable" onclick="go(\'order\',' + o.id + ')"><div class="order-head">' +
    '<div><strong>' + esc(t('order_num')) + o.id + '</strong> · ' + esc(o.customer_name || t('customer_fb')) + ' ' + paidBadgeHTML(o.paid) + '</div>' +
    '<span class="status-pill status-' + esc(o.status) + '">' + esc(statusLabel(o.status)) + '</span></div>' +
    '<ul class="order-items">' + o.items.map(i =>
      '<li>' + i.quantity + ' × ' + esc(iname(i)) +
      vendorItemExtraHTML(i, null) +
      ' — ' + money(Number(i.unit_price) * i.quantity) + '</li>').join('') + '</ul>' +
    '<div class="vendor-tag">' +
    // === Community drops (Oct 2026): drop orders show the drop label ===
    (o.fulfillment === 'drop'
      ? '📦 ' + esc(o.drop_label || t('drops_title'))
      : (o.fulfillment === 'pickup' ? '🛍️ ' + esc(t('pickup')) + (o.pickup_at ? ' · ' + esc(fmtPickupDate(o.pickup_at)) : '') : '🛵 ' + esc(t('delivery')))) +
    // === END community drops ===
    ' · ' + money(o.total) + ' · <small>' + esc(fmtDate(o.created_at)) + '</small></div>' +
    '<div class="open-hint">' + esc(t('open_order')) + '</div></div>';
}

window.advanceOrder = async function (id, status) {
  try {
    await api('/orders/' + id + '/status', { method: 'PATCH', body: JSON.stringify({ status }) });
    await portalReload(false);
  } catch (e) { alert(t('upd_failed') + e.message); }
};
window.cancelOrder = async function (id) {
  if (!confirm(t('cancel_order_q', { id: id }))) return;
  try {
    await api('/orders/' + id + '/status', { method: 'PATCH', body: JSON.stringify({ status: 'cancelled' }) });
    await portalReload(false);
  } catch (e) { alert(t('cancel_failed') + e.message); }
};

/* ---- order-item customizations (vendor view) ----
   The customer's picks (sides, options) render as a highlighted "cook card"
   so the kitchen can't miss them. Removed ingredients render as a bold red
   warning; added extras show with their +$X. */
function vendorModHighlightHTML(i) {
  const det = i.modifier_detail || [];
  if (det.length) {
    let h = '<div class="cook-highlight"><div class="cook-highlight-title">🧩 ' + esc(t('cook_picks')) + '</div>';
    det.forEach(function (m) {
      const chs = (m.labels || []).map(function (lb, ix) {
        const d = (m.deltas || [])[ix];
        return esc(lb) + (Number(d) ? ' (+' + money(d) + ')' : '');
      }).join(', ');
      if (chs) h += '<div class="cook-highlight-line"><strong>' + esc(m.option_name) + ':</strong> ' + chs + '</div>';
    });
    return h + '</div>';
  }
  if (i.modifier_label) {
    return '<div class="cook-highlight"><div class="cook-highlight-line">🧩 <strong>' +
      esc(t('cook_picks')) + ':</strong> ' + esc(i.modifier_label) + '</div></div>';
  }
  return '';
}
async function orderIngPrices(items) {
  const map = {}; // dish_id -> {ingredient name: extra_price}
  const ids = [...new Set((items || []).map(i => i.dish_id).filter(Boolean))];
  await Promise.all(ids.map(async (did) => {
    try {
      const ings = await api('/dishes/' + did + '/ingredients');
      const m = {};
      (Array.isArray(ings) ? ings : []).forEach(function (x) {
        if (x && x.name) m[String(x.name)] = Number(x.extra_price) || 0;
      });
      map[did] = m;
    } catch (e) { map[did] = {}; }
  }));
  return map;
}
function vendorItemExtraHTML(i, priceMap) {
  let h = vendorModHighlightHTML(i);
  (i.removed_ingredients || []).forEach(function (n) {
    const txt = t('no_x', { name: n });
    h += '<div class="error" style="font-weight:700;margin:.25rem 0">⚠️ ' +
      esc(lang() === 'ar' ? txt : txt.toUpperCase()) + '</div>';
  });
  (i.added_ingredients || []).forEach(function (n) {
    const nm = String(n);
    const pm = (priceMap && i.dish_id && priceMap[i.dish_id]) || {};
    const d = Number(pm[nm]) || 0;
    h += '<div class="vendor-tag">' + esc(d ? t('added_x', { name: nm, delta: money(d) }) : '➕ ' + nm) + '</div>';
  });
  return h;
}

/* ================= vendor order detail ================= */
const ORDER_FLOW = ['new', 'preparing', 'ready', 'on_the_way', 'completed'];
const EVENT_ICON = { placed: '🧾', status: '🔄', email: '📧', note: '📝' };

async function vOrderDetail(orderId) {
  const view = $('#view');
  if (!S.user || S.user.role !== 'vendor') {
    view.innerHTML = '<div class="empty"><span class="big">🔒</span>' + esc(t('vendor_only')) + '</div>';
    return;
  }
  view.innerHTML = '<div class="empty"><span class="big">🧾</span>' + esc(t('detail_loading')) + '</div>';
  try {
    const [order, events] = await Promise.all([
      api('/orders/' + orderId),
      api('/orders/' + orderId + '/events'),
    ]);
    S.portal.currentOrder = order;
    S.portal.currentEvents = events;
    // Added-extras prices for the +$X display (best-effort lookup).
    S.portal.ingPrices = await orderIngPrices(order.items).catch(() => ({}));
    renderOrderDetail();
  } catch (e) {
    view.innerHTML = '<div class="error">' + esc(t('detail_err')) + esc(e.message) + '</div>';
  }
}

function renderOrderDetail() {
  const o = S.portal.currentOrder;
  const events = S.portal.currentEvents || [];
  if (!o) return;
  const flowIdx = ORDER_FLOW.indexOf(o.status);
  const emailEv = events.find(e => e.event_type === 'email');

  let statusBtns = '';
  ORDER_FLOW.forEach(s => {
    // on_the_way is delivery-only: pickup orders go ready → completed.
    if (s === 'on_the_way' && o.fulfillment !== 'delivery') return;
    const isCurrent = s === o.status;
    const canMove = !isCurrent && flowIdx >= 0 && ORDER_FLOW.indexOf(s) > flowIdx;
    statusBtns += '<button class="btn small' + (isCurrent ? ' current' : '') + '"' +
      (canMove ? ' onclick="setOrderStatus(' + o.id + ',\'' + s + '\')"' : ' disabled') + '>' +
      (isCurrent ? '✓ ' : '') + esc(statusLabel(s)) + '</button>';
  });
  if (o.status !== 'completed' && o.status !== 'cancelled') {
    statusBtns += '<button class="btn small danger" onclick="setOrderStatus(' + o.id + ',\'cancelled\')">' + esc(t('cancel_order')) + '</button>';
  }

  let html = '<button class="btn small ghost" onclick="go(\'portal\')">' + esc(t('back_portal')) + '</button>';
  html += '<h2 class="section-title">🧾 ' + esc(t('order_num')) + o.id +
    ' <span class="status-pill status-' + esc(o.status) + '">' + esc(statusLabel(o.status)) + '</span> ' + paidBadgeHTML(o.paid) + '</h2>';

  // Prominent one-tap "Mark on the way" for delivery orders sitting at ready.
  if (o.status === 'ready' && o.fulfillment === 'delivery') {
    html += '<button class="btn" style="width:100%;margin-bottom:.8rem;font-size:1.05rem;padding:.7rem" onclick="setOrderStatus(' +
      o.id + ',\'on_the_way\')">' + esc(t('mark_on_the_way')) + '</button>';
  }

  html += '<div class="order-card"><div class="order-head"><div><strong>' +
    esc(o.customer_name || t('customer_fb')) + '</strong></div><div class="vendor-tag">' +
    esc(fmtDate(o.created_at)) + '</div></div>' +
    '<ul class="order-items">' + o.items.map(i =>
      '<li>' + i.quantity + ' × ' + esc(iname(i)) +
      vendorItemExtraHTML(i, S.portal.ingPrices) +
      ' — ' + money(Number(i.unit_price) * i.quantity) + '</li>').join('') + '</ul>' +
    '<div class="vendor-tag">' +
    // === Community drops (Oct 2026): drop orders show the drop label ===
    (o.fulfillment === 'drop'
      ? '📦 ' + esc(o.drop_label || t('drops_title'))
      : (o.fulfillment === 'pickup'
      ? '🛍️ ' + esc(t('pickup')) + (o.pickup_at ? ' · ' + esc(fmtPickupDate(o.pickup_at)) : '')
      : '🛵 ' + esc(t('delivery')))) +
    // === END community drops ===
    ' · 💳 ' + esc(o.payment_method || '—') + ' ' + esc(t('recorded_only')) +
    ' · <strong>' + esc(t('total_w')) + money(o.total) + '</strong></div>' +
    (o.fulfillment === 'delivery' && o.delivery_address
      ? '<div class="delivery-addr">📍 <strong>' + esc(t('deliver_to')) + '</strong> ' + esc(o.delivery_address) +
        '<br><a class="btn small" style="margin-top:.4rem" href="' + mapsUrl(o.delivery_address) +
        '" target="_blank" rel="noopener">' + esc(t('maps_open')) + '</a></div>' : '') +
    (o.notes ? '<div class="vendor-tag">📝 <strong>' + esc(t('cust_notes')) + '</strong> ' + esc(o.notes) + '</div>' : '') +
    // === F8: chosen weekly pickup slot snapshot ===
    (o.pickup_slot_label ? '<div class="vendor-tag">🕐 <strong>' + esc(t('slot_label')) + ':</strong> ' + esc(o.pickup_slot_label) + '</div>' : '') +
    // === END F8 ===
    '</div>';

  html += '<h3 class="section-title">' + esc(t('change_status')) + '</h3>' +
    '<div class="status-options">' + statusBtns + '</div>';

  // === v46: delivery photo proof — attach once on_the_way / completed ===
  if (o.fulfillment === 'delivery' && (o.status === 'on_the_way' || o.status === 'completed')) {
    html += '<h3 class="section-title">📸 ' + esc(t('delphoto_h')) + '</h3><div class="order-card">' +
      (o.delivery_photo_url
        ? '<a href="' + esc(o.delivery_photo_url) + '" target="_blank" rel="noopener">' +
          '<img src="' + esc(o.delivery_photo_url) + '" alt="" style="max-height:180px;max-width:100%;border-radius:10px"></a>' +
          '<div class="hint">' + esc(t('delphoto_attached')) + '</div>'
        : '<div class="hint">' + esc(t('delphoto_none')) + '</div>') +
      '<label class="field upload-label">' + esc(o.delivery_photo_url ? t('delphoto_replace') : t('delphoto_add')) + ' ' +
      '<input type="file" id="delphoto-file" accept="image/jpeg,image/png,image/webp,image/gif" onchange="deliveryPhotoPicked(' + o.id + ')"></label>' +
      '<div id="delphoto-err" style="color:#b3261e"></div></div>';
  }
  // === END v46 ===

  if (emailEv) {
    let meta = {};
    try { meta = JSON.parse(emailEv.meta || '{}'); } catch (e) { /* ignore */ }
    html += '<h3 class="section-title">' + esc(t('email_h')) + '</h3><div class="email-card">' +
      '<div class="email-head">' + esc(t('email_sent')) + ' <small>' + esc(fmtDate(emailEv.created_at)) + '</small></div>' +
      (meta.to ? '<div class="vendor-tag">' + esc(t('email_to')) + esc(meta.to) + '</div>' : '') +
      (meta.subject ? '<div class="email-subject"><strong>' + esc(meta.subject) + '</strong></div>' : '') +
      (meta.body ? '<pre class="email-body">' + esc(meta.body) + '</pre>' : '') + '</div>';
  }

  html += '<h3 class="section-title">' + esc(t('activity')) + ' <span class="sub">' + esc(t('events_count', { count: events.length })) + '</span></h3>';
  html += events.length
    ? '<div class="timeline">' + events.map(e =>
        '<div class="tl-event"><div class="tl-dot">' + (EVENT_ICON[e.event_type] || '•') + '</div>' +
        '<div class="tl-body"><div class="tl-msg">' + esc(e.message) + '</div>' +
        '<div class="tl-time">' + esc(fmtDate(e.created_at)) + '</div></div></div>').join('') + '</div>'
    : '<div class="empty">' + esc(t('no_activity')) + '</div>';

  // Vendor ↔ customer messages: plain text, oldest first, polled every 15s.
  html += '<h3 class="section-title">' + esc(t('msg_title')) + '</h3>' +
    '<div id="msg-thread"><div class="empty">' + esc(t('msg_empty')) + '</div></div>' +
    '<div class="msg-input-row"><input type="text" id="msg-input" maxlength="2000" placeholder="' + esc(t('msg_ph')) + '">' +
    '<button class="btn small" onclick="sendOrderMessage(' + o.id + ',\'vendor\')">' + esc(t('msg_send')) + '</button></div>';

  $('#view').innerHTML = html;
  startMsgPoll(o.id, 'vendor');
}

window.setOrderStatus = async function (id, status) {
  const label = status === 'cancelled'
    ? t('cancel_order_q', { id: id })
    : t('move_q', { id: id, status: statusLabel(status) }) +
      (status === 'completed' ? t('move_email_note') : '');
  if (!confirm(label)) return;
  try {
    await api('/orders/' + id + '/status', { method: 'PATCH', body: JSON.stringify({ status }) });
    await vOrderDetail(id); // reload detail (order + fresh activity log)
    await portalReload(true).catch(() => {});
  } catch (e) { alert(t('upd_failed') + e.message); }
};
window.toggleAvail = async function (id, available) {
  try {
    const d = await api('/dishes/' + id, { method: 'PATCH', body: JSON.stringify({ available }) });
    S.dishById[id] = d;
    const m = S.portal.menu.find(x => x.id === id);
    if (m) m.available = d.available;
  } catch (e) { alert(t('avail_failed') + e.message); portalReload(false); }
};
window.deleteDish = async function (id) {
  if (!confirm(t('del_confirm'))) return;
  try {
    await api('/dishes/' + id, { method: 'DELETE' });
    await portalReload(false);
    renderPortalShell();
  } catch (e) { alert(t('del_failed') + e.message); }
};

/* ---- advance ordering / weekly specials (Oct 2026) ----
   Available-day checkboxes use the API convention 0=Monday..6=Sunday — NOT
   the portal's Sunday-first day_0..day_6 keys (shop-hours convention), so
   day names come from Intl here to avoid mislabeling. */
var _V_MONDAY_UTC = Date.UTC(2026, 9, 12); // 2026-10-12 was a Monday
function vendorDayName(wd) {
  var loc = lang() === 'ar' ? 'ar' : 'en';
  return new Intl.DateTimeFormat(loc, { weekday: 'short', timeZone: 'UTC' })
    .format(new Date(_V_MONDAY_UTC + wd * 864e5));
}
function availDaysCheckboxes(prefix, selected) {
  // selected: array of weekday ints, or null (= all checked = every day)
  var html = '<div class="day-checks">';
  for (var wd = 0; wd < 7; wd++) {
    var checked = (!selected || selected.indexOf(wd) !== -1) ? ' checked' : '';
    html += '<label class="day-check"><input type="checkbox" id="' + prefix + '-day-' + wd + '"' +
      checked + '> ' + esc(vendorDayName(wd)) + '</label>';
  }
  return html + '</div>';
}
function readAvailDays(prefix) {
  var days = [];
  for (var wd = 0; wd < 7; wd++) {
    var cb = document.getElementById(prefix + '-day-' + wd);
    if (cb && cb.checked) days.push(wd);
  }
  // All checked (or none) = every day -> null (no restriction stored).
  if (days.length === 0 || days.length === 7) return null;
  return days;
}
function readCutoff(prefix) {
  var el = document.getElementById(prefix + '-cutoff');
  var raw = el ? el.value.trim() : '';
  if (raw === '') return null;
  var n = parseInt(raw, 10);
  return (isNaN(n) || n < 0) ? null : Math.min(n, 720);
}
function availDaysFields(prefix, dish) {
  return '<label class="field">' + esc(t('f_avail_days')) + '</label>' +
    availDaysCheckboxes(prefix, dish && dish.available_days) +
    '<div class="hint">' + esc(t('f_avail_days_hint')) + '</div>' +
    '<label class="field">' + esc(t('f_cutoff')) + '</label>' +
    '<input type="number" id="' + prefix + '-cutoff" min="0" max="720" step="1"' +
    ' placeholder="' + esc(t('f_cutoff_ph')) + '"' +
    (dish && dish.order_cutoff_hours != null ? ' value="' + esc(dish.order_cutoff_hours) + '"' : '') + '>' +
    '<div class="hint">' + esc(t('f_cutoff_hint')) + '</div>';
}

/* ---- bulk CSV dish import (Oct 2026) ----
   Panel under the "add dish" heading: downloads a CSV template (headers in
   the vendor's language + one example row) and uploads a filled CSV to
   POST /api/dishes/bulk-import. The result summary survives the portal
   re-render via S.bulkResult. Uses raw fetch: api() forces JSON content-type,
   which breaks multipart uploads. */
function bulkImportPanel() {
  return '<div class="bulk-panel" style="margin-bottom:1rem;padding:.8rem;border:1px dashed #b9a;border-radius:10px;background:#fffdf8">' +
    '<div style="font-weight:700;margin-bottom:.4rem">' + esc(t('bulk_title')) + '</div>' +
    '<div style="display:flex;gap:.5rem;flex-wrap:wrap;margin-bottom:.4rem">' +
    '<button type="button" class="btn secondary" onclick="downloadDishTemplate()">📥 ' + esc(t('bulk_template')) + '</button>' +
    '<label class="btn secondary" style="cursor:pointer;margin:0">📤 ' + esc(t('bulk_upload')) +
    '<input type="file" id="bulk-file" accept=".csv,text/csv,text/plain" style="display:none" onchange="bulkFilePicked()"></label>' +
    '</div>' +
    '<div class="hint">' + esc(t('bulk_hint')) + '</div>' +
    '<div id="bulk-result" style="margin-top:.4rem">' + (S.bulkResult || '') + '</div>' +
    '</div>';
}

function bulkCsvCell(v) {
  return '"' + String(v == null ? '' : v).replace(/"/g, '""') + '"';
}

window.downloadDishTemplate = function () {
  const ar = (localStorage.getItem('ehf_lang') || 'en') === 'ar';
  const headers = ar
    ? ['الاسم', 'الاسم بالعربية', 'السعر', 'الفئة', 'الوصف', 'متاح', 'الكمية بالمخزون']
    : ['name', 'name_ar', 'price', 'category', 'description', 'available', 'stock_quantity'];
  const example = ar
    ? ['كشري', 'Koshary', '45', 'أطباق رئيسية', 'عدس وأرز ومكرونة', 'نعم', '']
    : ['Koshary', 'كشري', '45', 'Mains', 'Lentils, rice and pasta', 'yes', ''];
  // BOM first so Excel/Sheets open Arabic correctly.
  const csv = '﻿' + headers.map(bulkCsvCell).join(',') + '\n' + example.map(bulkCsvCell).join(',') + '\n';
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'dishes-template.csv';
  document.body.appendChild(a);
  a.click();
  setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
};

function bulkErrText(e) {
  const k = 'bulk_err_' + e.code;
  const s = t(k);
  return s === k ? e.message : s; // t() returns the key itself when missing
}

window.bulkFilePicked = async function () {
  const inp = document.getElementById('bulk-file');
  if (!inp || !inp.files || !inp.files[0]) return;
  const box = document.getElementById('bulk-result');
  box.innerHTML = '<div class="hint">' + esc(t('bulk_uploading')) + '</div>';
  try {
    const fd = new FormData();
    fd.append('file', inp.files[0]);
    const headers = {};
    if (S.token) headers['Authorization'] = 'Bearer ' + S.token;
    const res = await fetch('/api/dishes/bulk-import?vendor_id=' + S.portal.vendorId,
      { method: 'POST', headers: headers, body: fd });
    if (!res.ok) {
      let msg = res.statusText;
      try { const j = await res.json(); if (j && j.detail) msg = j.detail; } catch (e2) { /* ignore */ }
      throw new Error(msg);
    }
    const r = await res.json();
    let h = '<div>✅ ' + esc(t('bulk_done', { created: r.created, failed: r.failed })) + '</div>';
    if (r.errors && r.errors.length) {
      h += '<ul style="margin:.4rem 0;padding-inline-start:1.2rem;color:#8a1f1f">' +
        r.errors.map(e => '<li>' + esc(t('bulk_row_err', { row: e.row })) + ' ' + esc(bulkErrText(e)) + '</li>').join('') +
        '</ul>';
    }
    S.bulkResult = h;
    inp.value = '';
    await portalReload(false);
    renderPortalShell();
  } catch (e) {
    S.bulkResult = '<div style="color:#8a1f1f">❌ ' + esc(e.message) + '</div>';
    renderPortalShell();
  }
};

function addDishForm() {
  return '<form class="add-dish-form" onsubmit="return submitDish(event)">' +
    '<div class="row2"><div><label class="field">' + esc(t('f_dish')) + '</label><input type="text" id="nd-name" required maxlength="160" oninput="previewDishPhoto(\'nd-photo\',\'nd-preview\',\'nd-name\')"></div>' +
    '<div><label class="field">' + esc(t('f_cat')) + '</label><input type="text" id="nd-cat" value="Mains" maxlength="60" list="cat-list">' +
    '<datalist id="cat-list">' + S.categories.map(c => '<option value="' + esc(c) + '">').join('') + '</datalist></div></div>' +
    // v52 + PR #12: optional Arabic dish name (shown to customers in Arabic mode).
    '<label class="field">' + esc(t('f_name_ar')) + '</label><input type="text" id="nd-name-ar" maxlength="200" dir="rtl" placeholder="مثال: كشري">' +
    '<label class="field">' + esc(t('f_desc')) + '</label><textarea id="nd-desc" rows="2" maxlength="2000"></textarea>' +
    '<label class="field">' + esc(t('f_desc')) + ' (العربية)</label><textarea id="nd-desc-ar" rows="2" maxlength="2000" dir="rtl"></textarea>' +
    '<label class="field">' + esc(t('f_photo')) + '</label>' +
    '<input type="url" id="nd-photo" maxlength="2000" placeholder="' + esc(t('f_photo_ph')) + '" oninput="previewDishPhoto(\'nd-photo\',\'nd-preview\',\'nd-name\')">' +
    '<label class="field upload-label">' + esc(t('f_upload_or')) + ' <input type="file" id="nd-file" accept="image/jpeg,image/png,image/webp,image/gif" onchange="photoFilePicked(\'nd-file\',\'nd-photo\',\'nd-preview\')"></label>' +
    '<img id="nd-preview" class="photo-preview" src="/img/meze.jpg" alt="" style="display:none" onerror="previewDishPhotoErr(this)">' +
    '<div class="row2"><div><label class="field">' + esc(t('f_price')) + '</label><input type="number" id="nd-price" step="0.01" min="0" required></div>' +
    '<div><label class="field">' + esc(t('f_discount')) + '</label><input type="number" id="nd-disc" step="1" min="0" max="100" value="0"></div></div>' +
    '<label class="field">' + esc(t('f_stock')) + '</label><input type="number" id="nd-stock" min="0" step="1">' +
    '<label class="field">' + esc(t('f_low_stock')) + '</label><input type="number" id="nd-lowstock" min="0" step="1" placeholder="5">' +
    '<div class="row2"><div><label class="field">' + esc(t('f_barcode')) + '</label><input type="text" id="nd-barcode" maxlength="64" placeholder="' + esc(t('f_barcode_ph')) + '"></div>' +
    '<div><label class="field">&nbsp;</label><button class="btn secondary" type="button" style="width:100%" onclick="openBarcodeScanner()">' + esc(t('scan_barcode')) + '</button></div></div>' +
    availDaysFields('nd', null) +
    '<div class="hint">' + esc(t('cust_after_create')) + '</div>' +
    '<div class="row2"><div><label><input type="checkbox" id="nd-veg"> ' + esc(t('dish_veg')) + '</label></div>' +
    '<div><label><input type="checkbox" id="nd-vegan"> ' + esc(t('dish_vegan')) + '</label></div></div>' +
    '<div class="row2"><div><label class="field">' + esc(t('f_calories')) + '</label><input type="number" id="nd-cal" step="1" min="0" max="10000" placeholder="' + esc(t('f_cal_ph')) + '"></div>' +
    '<div><label class="field">' + esc(t('f_serving')) + '</label><input type="text" id="nd-serv" maxlength="120" placeholder="' + esc(t('f_serv_ph')) + '"></div></div>' +
    '<div class="row2"><div><label class="field">' + esc(t('f_prep')) + '</label><input type="number" id="nd-prep" step="1" min="0" max="1440" placeholder="' + esc(t('f_prep_ph')) + '"></div><div></div></div>' +
    '<label class="field">' + esc(t('f_ing')) + '</label><textarea id="nd-ing" rows="2" maxlength="5000" placeholder="' + esc(t('f_ing_ph')) + '"></textarea>' +
    '<label class="field">' + esc(t('f_ing')) + ' (العربية)</label><textarea id="nd-ing-ar" rows="2" maxlength="5000" dir="rtl"></textarea>' +
    '<label class="field">' + esc(t('f_allergens')) + '</label><input type="text" id="nd-all" maxlength="255" placeholder="' + esc(t('f_all_ph')) + '">' +
    '<label class="field">' + esc(t('f_allergens')) + ' (العربية)</label><input type="text" id="nd-all-ar" maxlength="255" dir="rtl">' +
    '<div><label class="field">&nbsp;</label><button class="btn" type="submit" style="width:100%">' + esc(t('f_add')) + '</button></div>' +
    '</form>';
}
window.submitDish = async function (ev) {
  ev.preventDefault();
  const disc = parseInt($('#nd-disc').value, 10);
  if (isNaN(disc) || disc < 0 || disc > 100) { alert(t('disc_invalid')); return false; }
  try {
    const uploaded = await uploadDishPhoto('nd-file'); // null when no file chosen
    if (uploaded) $('#nd-photo').value = uploaded;
    const stockRaw = $('#nd-stock').value.trim();
    const body = {
      name: $('#nd-name').value.trim(),
      // v52: optional Arabic name (empty -> null).
      name_ar: $('#nd-name-ar').value.trim() || null,
      description: $('#nd-desc').value.trim(),
      description_ar: $('#nd-desc-ar').value.trim() || null,
      price: parseFloat($('#nd-price').value),
      category: $('#nd-cat').value.trim() || 'Mains',
      photo_url: $('#nd-photo').value.trim(),
      discount_percent: disc,
      stock_quantity: stockRaw === '' ? null : parseInt(stockRaw, 10),
      low_stock_threshold: $('#nd-lowstock').value.trim() === '' ? null : parseInt($('#nd-lowstock').value, 10),
      barcode: $('#nd-barcode').value.trim() || null,
      available_days: readAvailDays('nd'),
      order_cutoff_hours: readCutoff('nd'),
      calories: $('#nd-cal').value === '' ? null : parseInt($('#nd-cal').value, 10),
      serving_size: $('#nd-serv').value.trim() || null,
      prep_minutes: $('#nd-prep').value === '' ? null : parseInt($('#nd-prep').value, 10),
      ingredients: $('#nd-ing').value.trim() || null,
      ingredients_ar: $('#nd-ing-ar').value.trim() || null,
      allergens: $('#nd-all').value.trim() || null,
      allergens_ar: $('#nd-all-ar').value.trim() || null,
      is_vegetarian: $('#nd-veg').checked,
      is_vegan: $('#nd-vegan').checked,
    };
    await api('/dishes?vendor_id=' + S.portal.vendorId, { method: 'POST', body: JSON.stringify(body) })
      .then(function (created) {
        // === New-dish announcements (Oct 2026): the backend reports how
        // many past customers the announcement went to. ===
        S.dishAnnouncedTo = (created && typeof created.announced_to === 'number') ? created.announced_to : null;
      });
    await portalReload(false);
    renderPortalShell();
    if (S.dishAnnouncedTo !== null && S.dishAnnouncedTo !== undefined) {
      const m = document.getElementById('dish-ann-msg');
      if (m) {
        m.innerHTML = '<div class="success">' + esc(t('vendor_announced', { n: S.dishAnnouncedTo })) + '</div>';
        m.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
      S.dishAnnouncedTo = null;
    }
  } catch (e) { alert(t('add_failed') + e.message); }
  return false;
};

/* ---- edit an existing dish (name, desc, price, category, photo, discount) ----
   Opens as a centered modal overlay: no scrolling down the page, and the
   photo preview shows the same food picture the customer site uses. */
window.editDish = function (id) {
  const d = S.portal.menu.find(x => x.id === id);
  if (!d) return;
  const startSrc = d.photo_url || vendorImg(photoFor(d).img);
  const modal = $('#dish-modal');
  modal.innerHTML = '<div class="modal-card">' +
    '<h3 class="section-title">' + esc(t('edit_dish_h')) + '</h3>' +
    '<form class="add-dish-form" onsubmit="return submitDishEdit(event,' + d.id + ')">' +
    '<div class="row2"><div><label class="field">' + esc(t('f_dish')) + '</label><input type="text" id="ed-name" required maxlength="160" value="' + esc(d.name) + '" oninput="previewDishPhoto(\'ed-photo\',\'ed-preview\',\'ed-name\')"></div>' +
    '<div><label class="field">' + esc(t('f_cat')) + '</label><input type="text" id="ed-cat" maxlength="60" value="' + esc(d.category || 'Mains') + '" list="cat-list"></div></div>' +
    // v52 + PR #12: optional Arabic dish name (shown to customers in Arabic mode).
    '<label class="field">' + esc(t('f_name_ar')) + '</label><input type="text" id="ed-name-ar" maxlength="200" dir="rtl" value="' + esc(d.name_ar || '') + '" placeholder="مثال: كشري">' +
    '<label class="field">' + esc(t('f_desc')) + '</label><textarea id="ed-desc" rows="2" maxlength="2000">' + esc(d.description || '') + '</textarea>' +
    '<label class="field">' + esc(t('f_desc')) + ' (العربية)</label><textarea id="ed-desc-ar" rows="2" maxlength="2000" dir="rtl">' + esc(d.description_ar || '') + '</textarea>' +
    '<label class="field">' + esc(t('f_photo')) + '</label><input type="url" id="ed-photo" maxlength="2000" placeholder="' + esc(t('f_photo_ph')) + '" value="' + esc(d.photo_url || '') + '" oninput="previewDishPhoto(\'ed-photo\',\'ed-preview\',\'ed-name\')">' +
    '<label class="field upload-label">' + esc(t('f_upload_or')) + ' <input type="file" id="ed-file" accept="image/jpeg,image/png,image/webp,image/gif" onchange="photoFilePicked(\'ed-file\',\'ed-photo\',\'ed-preview\')"></label>' +
    '<img id="ed-preview" class="photo-preview" src="' + esc(startSrc) + '" alt="" onerror="previewDishPhotoErr(this)">' +
    // === VENDOR MEDIA (Oct 2026): food-prep video — mp4/webm, 25MB (server enforces) ===
    '<h4 style="margin:1rem 0 .4rem">🎬 ' + esc(t('dish_video_h')) + '</h4>' +
    '<div class="hint" style="margin-top:0">' + esc(t('dish_video_hint')) + '</div>' +
    '<input type="hidden" id="ed-videourl" value="' + esc(d.video_url || '') + '">' +
    '<video id="ed-videoprev" class="video-preview" controls preload="metadata"' +
    (d.video_url ? ' src="' + esc(d.video_url) + '"' : ' style="display:none"') + '></video>' +
    '<label class="field upload-label">' + esc(t('video_upload')) + ' ' +
    '<input type="file" id="ed-videofile" accept="video/mp4,video/webm" onchange="videoFilePicked(\'ed-videofile\',\'ed-videoprev\',\'ed-videourl\',\'ed-videoerr\')"></label>' +
    '<div class="row2" style="margin-top:.3rem"><div><button class="btn small secondary" type="button" onclick="removeVideo(\'ed-videofile\',\'ed-videoprev\',\'ed-videourl\')">' + esc(t('video_remove')) + '</button></div><div></div></div>' +
    '<div class="hint" id="ed-videoerr" style="color:#b3261e"></div>' +
    // === END VENDOR MEDIA ===
    // === SIGNATURE DISH (Oct 2026): toggle + optional rank; server caps at 5 ===
    '<div class="row2"><div><label><input type="checkbox" id="ed-sig"' + (d.is_signature ? ' checked' : '') + '> ' + esc(t('dish_sig')) + '</label></div>' +
    '<div><label class="field">' + esc(t('dish_sig_rank')) + '</label>' +
    '<input type="number" id="ed-sigrank" min="1" step="1" value="' + (d.signature_rank != null ? esc(d.signature_rank) : '') + '"></div></div>' +
    '<div class="hint">' + esc(t('dish_sig_hint')) + '</div>' +
    // === END SIGNATURE DISH ===
    '<div class="row2"><div><label class="field">' + esc(t('f_price')) + '</label><input type="number" id="ed-price" step="0.01" min="0" required value="' + esc(d.price) + '"></div>' +
    '<div><label class="field">' + esc(t('f_discount')) + '</label><input type="number" id="ed-disc" step="1" min="0" max="100" value="' + discOf(d) + '"></div></div>' +
    // === FEATURE 7: timed flash sale ===
    '<h4 style="margin:1rem 0 .4rem">⚡ ' + esc(t('flash_h')) + '</h4>' +
    '<div class="hint" style="margin-top:0">' + esc(t('flash_hint')) + '</div>' +
    '<div class="row2"><div><label class="field">' + esc(t('flash_percent')) + '</label>' +
    '<input type="number" id="ed-sale-pct" step="1" min="1" max="90" placeholder="20" value="' + (d.sale_percent != null ? esc(d.sale_percent) : '') + '"></div>' +
    '<div><label class="field">&nbsp;</label><button class="btn secondary" type="button" style="width:100%" onclick="clearFlashSale()">' + esc(t('flash_clear')) + '</button></div></div>' +
    '<div class="row2"><div><label class="field">' + esc(t('flash_start')) + '</label>' +
    '<input type="datetime-local" id="ed-sale-start" value="' + esc(toLocalInput(d.sale_start)) + '"></div>' +
    '<div><label class="field">' + esc(t('flash_end')) + '</label>' +
    '<input type="datetime-local" id="ed-sale-end" value="' + esc(toLocalInput(d.sale_end)) + '"></div></div>' +
    // === END FEATURE 7 ===
    '<label class="field">' + esc(t('f_stock')) + '</label><input type="number" id="ed-stock" min="0" step="1" value="' + (d.stock_quantity != null ? esc(d.stock_quantity) : '') + '">' +
    '<label class="field">' + esc(t('f_low_stock')) + '</label><input type="number" id="ed-lowstock" min="0" step="1" placeholder="5" value="' + (d.low_stock_threshold != null ? esc(d.low_stock_threshold) : '') + '">' +
    '<label class="field">' + esc(t('f_barcode')) + '</label><input type="text" id="ed-barcode" maxlength="64" placeholder="' + esc(t('f_barcode_ph')) + '" value="' + esc(d.barcode || '') + '">' +
    availDaysFields('ed', d) +
    '<div class="row2"><div><label><input type="checkbox" id="ed-veg"' + (d.is_vegetarian ? ' checked' : '') + '> ' + esc(t('dish_veg')) + '</label></div>' +
    '<div><label><input type="checkbox" id="ed-vegan"' + (d.is_vegan ? ' checked' : '') + '> ' + esc(t('dish_vegan')) + '</label></div></div>' +
    '<div id="ed-cust"><div class="empty">' + esc(t('detail_loading')) + '</div></div>' +
    '<div class="row2"><div><label class="field">' + esc(t('f_calories')) + '</label><input type="number" id="ed-cal" step="1" min="0" max="10000" placeholder="' + esc(t('f_cal_ph')) + '" value="' + (d.calories != null ? esc(d.calories) : '') + '"></div>' +
    '<div><label class="field">' + esc(t('f_serving')) + '</label><input type="text" id="ed-serv" maxlength="120" placeholder="' + esc(t('f_serv_ph')) + '" value="' + esc(d.serving_size || '') + '"></div></div>' +
    '<div class="row2"><div><label class="field">' + esc(t('f_prep')) + '</label><input type="number" id="ed-prep" step="1" min="0" max="1440" placeholder="' + esc(t('f_prep_ph')) + '" value="' + (d.prep_minutes != null ? esc(d.prep_minutes) : '') + '"></div><div></div></div>' +
    '<label class="field">' + esc(t('f_ing')) + '</label><textarea id="ed-ing" rows="2" maxlength="5000" placeholder="' + esc(t('f_ing_ph')) + '">' + esc(d.ingredients || '') + '</textarea>' +
    '<label class="field">' + esc(t('f_ing')) + ' (العربية)</label><textarea id="ed-ing-ar" rows="2" maxlength="5000" dir="rtl">' + esc(d.ingredients_ar || '') + '</textarea>' +
    '<label class="field">' + esc(t('f_allergens')) + '</label><input type="text" id="ed-all" maxlength="255" placeholder="' + esc(t('f_all_ph')) + '" value="' + esc(d.allergens || '') + '">' +
    '<label class="field">' + esc(t('f_allergens')) + ' (العربية)</label><input type="text" id="ed-all-ar" maxlength="255" dir="rtl" value="' + esc(d.allergens_ar || '') + '">' +
    '<div class="row2"><div><label class="field">&nbsp;</label><button class="btn" type="submit" style="width:100%">' + esc(t('save_changes')) + '</button></div>' +
    '<div><label class="field">&nbsp;</label><button class="btn secondary" type="button" style="width:100%" onclick="cancelDishEdit()">' + esc(t('cancel')) + '</button></div></div>' +
    '</form></div>';
  modal.classList.remove('hidden');
  document.body.style.overflow = 'hidden'; // keep the page behind the modal still
  document.addEventListener('keydown', dishModalEsc);
  loadCustSection(d.id); // option groups + ingredients editors (async)
};
function dishModalEsc(e) { if (e.key === 'Escape') cancelDishEdit(); }
window.cancelDishEdit = function () {
  const modal = $('#dish-modal');
  if (modal) { modal.classList.add('hidden'); modal.innerHTML = ''; }
  document.body.style.overflow = '';
  document.removeEventListener('keydown', dishModalEsc);
};
window.submitDishEdit = async function (ev, id) {
  ev.preventDefault();
  const disc = parseInt($('#ed-disc').value, 10);
  if (isNaN(disc) || disc < 0 || disc > 100) { alert(t('disc_invalid')); return false; }
  // === FEATURE 7: timed flash sale — percent + LA-timezone window ===
  const salePctRaw = $('#ed-sale-pct').value.trim();
  let sale_percent = null, sale_start = null, sale_end = null;
  if (salePctRaw !== '') {
    sale_percent = parseInt(salePctRaw, 10);
    if (isNaN(sale_percent) || sale_percent < 1 || sale_percent > 90) { alert(t('flash_bad_pct')); return false; }
    const sRaw = $('#ed-sale-start').value, eRaw = $('#ed-sale-end').value;
    if (!sRaw || !eRaw) { alert(t('flash_need_window')); return false; }
    const sDt = new Date(sRaw), eDt = new Date(eRaw);
    if (isNaN(sDt) || isNaN(eDt) || sDt >= eDt) { alert(t('flash_bad_window')); return false; }
    sale_start = sDt.toISOString();
    sale_end = eDt.toISOString();
  }
  // === END FEATURE 7 ===
  try {
    const uploaded = await uploadDishPhoto('ed-file'); // null when no file chosen
    if (uploaded) $('#ed-photo').value = uploaded;
    // === VENDOR MEDIA (Oct 2026): food-prep video upload ===
    const uploadedVid = await uploadVideo('ed-videofile'); // null when no file chosen
    if (uploadedVid) $('#ed-videourl').value = uploadedVid;
    // === END VENDOR MEDIA ===
    const stockRaw = $('#ed-stock').value.trim();
    // === SIGNATURE DISH (Oct 2026): toggle + optional rank (server caps at 5) ===
    const sigChecked = $('#ed-sig').checked;
    let sigRank = null;
    const rankRaw = $('#ed-sigrank').value.trim();
    if (rankRaw !== '') {
      sigRank = parseInt(rankRaw, 10);
      if (isNaN(sigRank) || sigRank < 1) { alert(t('sig_rank_bad')); return false; }
    }
    // === END SIGNATURE DISH ===
    const body = {
      name: $('#ed-name').value.trim(),
      // v52: optional Arabic name (empty -> null clears it).
      name_ar: $('#ed-name-ar').value.trim() || null,
      description: $('#ed-desc').value.trim(),
      description_ar: $('#ed-desc-ar').value.trim() || null,
      price: parseFloat($('#ed-price').value),
      category: $('#ed-cat').value.trim() || 'Mains',
      photo_url: $('#ed-photo').value.trim(),
      discount_percent: disc,
      stock_quantity: stockRaw === '' ? null : parseInt(stockRaw, 10),
      low_stock_threshold: $('#ed-lowstock').value.trim() === '' ? null : parseInt($('#ed-lowstock').value, 10),
      barcode: $('#ed-barcode').value.trim() || null,
      available_days: readAvailDays('ed'),
      order_cutoff_hours: readCutoff('ed'),
      calories: $('#ed-cal').value === '' ? null : parseInt($('#ed-cal').value, 10),
      serving_size: $('#ed-serv').value.trim() || null,
      prep_minutes: $('#ed-prep').value === '' ? null : parseInt($('#ed-prep').value, 10),
      ingredients: $('#ed-ing').value.trim() || null,
      ingredients_ar: $('#ed-ing-ar').value.trim() || null,
      allergens: $('#ed-all').value.trim() || null,
      allergens_ar: $('#ed-all-ar').value.trim() || null,
      is_vegetarian: $('#ed-veg').checked,
      is_vegan: $('#ed-vegan').checked,
      // === FEATURE 7: timed flash sale (nulls clear it) ===
      sale_percent: sale_percent,
      sale_start: sale_start,
      sale_end: sale_end,
      // === END FEATURE 7 ===
      // === VENDOR MEDIA + SIGNATURE DISH (Oct 2026) ===
      video_url: $('#ed-videourl').value.trim() || null,
      is_signature: sigChecked,
      signature_rank: sigRank,
      // === END ===
    };
    await api('/dishes/' + id, { method: 'PATCH', body: JSON.stringify(body) });
    cancelDishEdit();
    await portalReload(false);
    renderPortalShell();
  } catch (e) {
    // The server caps signature dishes at 5 per vendor — turn its 422 into a
    // friendly, actionable message; everything else stays as-is.
    if (errText(e).toLowerCase().indexOf('signature') !== -1) alert(t('sig_cap_err'));
    else alert(t('edit_failed') + errText(e));
  }
  return false;
};

/* ================= F7: flash sale helpers ================= */
/* ISO datetime -> datetime-local input value (vendor's local timezone). */
function toLocalInput(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return '';
  const p = n => String(n).padStart(2, '0');
  return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) +
    'T' + p(d.getHours()) + ':' + p(d.getMinutes());
}
window.clearFlashSale = function () {
  const p = $('#ed-sale-pct'), s = $('#ed-sale-start'), e = $('#ed-sale-end');
  if (p) p.value = '';
  if (s) s.value = '';
  if (e) e.value = '';
};
/* ================= END F7 ================= */

/* ================= barcode scan (groceries + stock) =================
   Scan a package barcode → if the item is already in this shop, open a
   quick stock-adjust; if not, look it up on Open Food Facts (free, no key)
   and prefill the add-dish form for the vendor to confirm before saving.
   Camera uses the native BarcodeDetector API (Chrome/Edge); every other
   browser gets the manual-entry fallback. No libraries. */

let scanState = { stream: null, raf: 0, running: false };

function stopScanCamera() {
  scanState.running = false;
  if (scanState.raf) cancelAnimationFrame(scanState.raf);
  scanState.raf = 0;
  if (scanState.stream) scanState.stream.getTracks().forEach(tr => tr.stop());
  scanState.stream = null;
}

window.closeBarcodeScanner = function () {
  stopScanCamera();
  const modal = $('#dish-modal');
  if (modal) { modal.classList.add('hidden'); modal.innerHTML = ''; }
  document.body.style.overflow = '';
  document.removeEventListener('keydown', dishModalEsc);
};

window.openBarcodeScanner = function () {
  const modal = $('#dish-modal');
  const hasDetector = typeof window.BarcodeDetector === 'function';
  modal.innerHTML = '<div class="modal-card">' +
    '<h3 class="section-title">' + esc(t('scan_title')) + '</h3>' +
    '<div class="hint">' + esc(t('scan_hint')) + '</div>' +
    '<div id="scan-cam-wrap" style="margin:.6rem 0">' +
    (hasDetector
      ? '<video id="scan-video" playsinline muted style="width:100%;max-height:280px;background:#111;border-radius:8px"></video>' +
        '<div id="scan-cam-msg" class="hint"></div>'
      : '<div class="hint">' + esc(t('scan_no_camera')) + '</div>') +
    '</div>' +
    '<div class="row2"><div><label class="field">' + esc(t('f_barcode')) + '</label>' +
    '<input type="text" id="scan-manual" maxlength="64" placeholder="' + esc(t('scan_manual_ph')) + '" inputmode="numeric"></div>' +
    '<div><label class="field">&nbsp;</label><button class="btn" type="button" style="width:100%" onclick="manualBarcodeLookup()">' + esc(t('scan_lookup')) + '</button></div></div>' +
    '<div id="scan-msg" class="hint"></div>' +
    '<div><label class="field">&nbsp;</label><button class="btn secondary" type="button" style="width:100%" onclick="closeBarcodeScanner()">' + esc(t('scan_cancel')) + '</button></div>' +
    '</div>';
  modal.classList.remove('hidden');
  document.body.style.overflow = 'hidden';
  document.addEventListener('keydown', dishModalEsc);
  const manual = $('#scan-manual');
  if (manual) manual.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); manualBarcodeLookup(); } });
  if (hasDetector) startScanCamera();
};

async function startScanCamera() {
  const video = $('#scan-video');
  const msg = $('#scan-cam-msg');
  if (!video) return;
  try {
    scanState.stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false });
    video.srcObject = scanState.stream;
    await video.play();
    const detector = new window.BarcodeDetector({ formats: ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'code_128', 'code_39', 'qr_code'] });
    scanState.running = true;
    const tick = async () => {
      if (!scanState.running) return;
      try {
        const codes = await detector.detect(video);
        if (codes && codes.length) {
          const code = (codes[0].rawValue || '').trim();
          if (code) { stopScanCamera(); processBarcode(code); return; }
        }
      } catch (e) { /* transient decode error — keep scanning */ }
      scanState.raf = requestAnimationFrame(tick);
    };
    scanState.raf = requestAnimationFrame(tick);
  } catch (e) {
    if (msg) msg.textContent = t('scan_camera_err');
  }
}

window.manualBarcodeLookup = function () {
  const code = ($('#scan-manual').value || '').trim();
  if (!code) return;
  stopScanCamera();
  processBarcode(code);
};

/* Pure mapping: Open Food Facts product JSON → add-dish form values.
   Kept side-effect-free so it can be unit-tested with a real API payload. */
function offToDishForm(product) {
  if (!product) return null;
  const name = (product.product_name || product.product_name_en || '').trim();
  if (!name) return null;
  const brands = (product.brands || '').trim();
  const cats = (product.categories || '').split(',').map(s => s.trim().replace(/^[a-z]{2}:/, '')).filter(Boolean);
  const img = product.image_url || product.image_front_url || '';
  const qty = (product.quantity || '').trim();
  const ing = (product.ingredients_text_en || product.ingredients_text || '').trim();
  return {
    name: name,
    description: brands || '',
    category: cats[0] || 'Groceries',
    photo_url: img,
    serving_size: qty || null,
    ingredients: ing ? ing.slice(0, 5000) : null,
  };
}

async function processBarcode(code) {
  const msg = $('#scan-msg');
  const vendorId = S.portal.vendorId;
  if (!vendorId) { if (msg) msg.textContent = t('no_shop'); return; }
  // 1. Already in this shop? → stock-adjust, never a duplicate.
  try {
    const existing = await api('/dishes/by-barcode?vendor_id=' + vendorId + '&barcode=' + encodeURIComponent(code));
    if (msg) msg.textContent = t('scan_exists');
    openStockAdjust(existing);
    return;
  } catch (e) { /* 404 = new item, fall through to product lookup */ }
  // 2. New item — look it up on Open Food Facts, then prefill the add form.
  let prefill = null;
  try {
    const res = await fetch('https://world.openfoodfacts.org/api/v2/product/' + encodeURIComponent(code) + '.json');
    const data = await res.json();
    if (data && data.status === 1 && data.product) prefill = offToDishForm(data.product);
    if (prefill && msg) msg.textContent = t('scan_found');
    else if (msg) msg.textContent = t('scan_not_found');
  } catch (e) {
    if (msg) msg.textContent = t('scan_offline');
  }
  closeBarcodeScanner();
  prefillAddDishForm(code, prefill);
  const form = document.querySelector('.add-dish-form');
  if (form) form.scrollIntoView({ behavior: 'smooth', block: 'start' });
  const priceEl = $('#nd-price');
  if (priceEl) priceEl.focus();
}

function prefillAddDishForm(code, prefill) {
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.value = v == null ? '' : v; };
  set('nd-barcode', code);
  if (!prefill) return;
  set('nd-name', prefill.name);
  set('nd-desc', prefill.description);
  set('nd-cat', prefill.category);
  set('nd-photo', prefill.photo_url);
  set('nd-serv', prefill.serving_size);
  set('nd-ing', prefill.ingredients);
  const preview = $('#nd-preview');
  if (preview && prefill.photo_url) { preview.src = prefill.photo_url; preview.style.display = ''; }
}

/* ---- quick stock-adjust for an already-listed item ---- */
function openStockAdjust(dish) {
  const modal = $('#dish-modal');
  modal.innerHTML = '<div class="modal-card">' +
    '<h3 class="section-title">' + esc(t('scan_stock_h')) + '</h3>' +
    '<div style="display:flex;gap:.6rem;align-items:center;margin-bottom:.6rem">' +
    '<img src="' + esc(dish.photo_url || vendorImg(photoFor(dish).img)) + '" style="width:64px;height:64px;object-fit:cover;border-radius:8px" onerror="this.style.display=\'none\'">' +
    '<div><strong>' + esc(dname(dish)) + '</strong><br><small>' + esc(t('scan_stock_now')) + ': ' +
    (dish.stock_quantity != null ? esc(dish.stock_quantity) : esc(t('scan_stock_unlimited'))) + '</small></div></div>' +
    '<label class="field">' + esc(t('scan_delta')) + '</label>' +
    '<input type="number" id="stock-delta" step="1" placeholder="+5">' +
    '<div class="row2" style="margin-top:.6rem"><div><button class="btn" type="button" style="width:100%" onclick="submitStockAdjust(' + dish.id + ')">' + esc(t('scan_apply')) + '</button></div>' +
    '<div><button class="btn secondary" type="button" style="width:100%" onclick="closeBarcodeScanner()">' + esc(t('scan_close')) + '</button></div></div>' +
    '<div id="stock-msg" class="hint"></div></div>';
  modal.classList.remove('hidden');
  document.body.style.overflow = 'hidden';
  document.addEventListener('keydown', dishModalEsc);
  const input = $('#stock-delta');
  if (input) input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); submitStockAdjust(dish.id); } });
}

window.submitStockAdjust = async function (dishId) {
  const delta = parseInt(($('#stock-delta').value || '').trim(), 10);
  if (isNaN(delta) || delta === 0) { alert(t('scan_delta')); return; }
  try {
    await api('/dishes/' + dishId + '/stock-adjust', { method: 'POST', body: JSON.stringify({ delta }) });
    const msg = $('#stock-msg');
    if (msg) msg.textContent = t('scan_saved');
    await portalReload(false);
    renderPortalShell();
    closeBarcodeScanner();
  } catch (e) { alert(t('edit_failed') + errText(e)); }
};

/* ================= shop settings ================= */

function errText(e) {
  // Backend 422s come back as an array of {msg}; 400s as a plain string.
  const m = e && e.message;
  if (Array.isArray(m)) return m.map(x => (x && x.msg) || JSON.stringify(x)).join('; ');
  return String(m || 'Something went wrong.');
}

async function vSettings() {
  const view = $('#view');
  if (!S.user || S.user.role !== 'vendor') {
    view.innerHTML = '<div class="empty"><span class="big">🔒</span>' + esc(t('vendor_only')) + '<br><br>' +
      '<button class="btn" onclick="go(\'login\')">' + esc(t('login_as_vendor')) + '</button></div>';
    return;
  }
  view.innerHTML = '<div class="empty"><span class="big">⚙️</span>' + esc(t('set_loading')) + '</div>';
  try {
    if (!S.portal.vendor) {
      const vendors = await api('/vendors/mine');
      if (!vendors.length) { view.innerHTML = '<div class="empty">' + esc(t('no_shop')) + '</div>'; return; }
      S.portal.vendorId = vendors[0].id;
      S.portal.vendor = vendors[0];
    }
    renderSettings();
  } catch (e) {
    view.innerHTML = '<div class="error">' + esc(t('set_err')) + esc(errText(e)) + '</div>';
  }
}

function renderSettings() {
  const v = S.portal.vendor;
  let html = '<button class="btn small ghost" onclick="go(\'portal\')">' + esc(t('back_portal')) + '</button>';
  html += '<h2 class="section-title">' + esc(t('set_title')) + '</h2><div id="settings-msg"></div>';

  html += '<div class="form-card settings-form"><h3>' + esc(t('set_profile')) + '</h3>' +
    '<div id="settings-err"></div>' +
    '<label class="field">' + esc(t('set_name')) + '</label><input type="text" id="set-name" maxlength="120" value="' + esc(v.name || '') + '">' +
    '<label class="field">' + esc(t('set_name_ar')) + '</label><input type="text" id="set-name-ar" maxlength="120" dir="rtl" placeholder="مثال: مطبخ ماما سامية" value="' + esc(v.name_ar || '') + '">' +
    '<label class="field">' + esc(t('set_tagline')) + '</label><input type="text" id="set-tagline" maxlength="255" value="' + esc(v.tagline || '') + '">' +
    '<div class="row2"><div><label class="field">' + esc(t('set_area')) + '</label>' +
    '<input type="text" id="set-area" maxlength="120" placeholder="' + esc(t('set_area_ph')) + '" value="' + esc(v.area || '') + '"></div>' +
    '<div><label class="field">' + esc(t('set_phone')) + '</label><input type="tel" id="set-phone" maxlength="40" value="' + esc(v.phone || '') + '" autocomplete="tel"></div></div>' +
    '<h4 style="margin:1rem 0 .4rem">' + esc(t('set_addr_h')) + '</h4>' +
    '<label class="field">' + esc(t('addr_street')) + '</label>' +
    '<input type="text" id="set-street" maxlength="120" autocomplete="street-address" value="' + esc(v.street_address || '') + '">' +
    '<div class="row2"><div><label class="field">' + esc(t('addr_apt')) + '</label>' +
    '<input type="text" id="set-apt" maxlength="40" autocomplete="address-line2" placeholder="' + esc(t('addr_apt_ph')) + '" value="' + esc(v.apt || '') + '"></div>' +
    '<div><label class="field">' + esc(t('addr_city')) + '</label>' +
    '<input type="text" id="set-city" maxlength="80" autocomplete="address-level2" value="' + esc(v.city || '') + '"></div></div>' +
    '<div class="row2"><div><label class="field">' + esc(t('addr_state')) + '</label>' +
    '<select id="set-state" autocomplete="address-level1">' + stateOptions(v.state || '') + '</select></div>' +
    '<div><label class="field">' + esc(t('addr_zip')) + '</label>' +
    '<input type="text" id="set-zip" maxlength="10" inputmode="numeric" autocomplete="postal-code" placeholder="98201" value="' + esc(v.zipcode || '') + '"></div></div>' +
    '<h4 style="margin:1rem 0 .4rem">' + esc(t('set_pay_h')) + '</h4>' +
    '<p class="hint" style="margin-top:0">' + esc(t('set_pay_hint')) + '</p>' +
    '<div class="row2"><div><label class="field">' + esc(t('set_zelle')) + '</label>' +
    '<input type="text" id="set-zelle" maxlength="120" placeholder="' + esc(t('set_zelle_ph')) + '" value="' + esc(v.zelle_handle || '') + '"></div>' +
    '<div><label class="field">' + esc(t('set_venmo')) + '</label>' +
    '<input type="text" id="set-venmo" maxlength="120" placeholder="' + esc(t('set_venmo_ph')) + '" value="' + esc(v.venmo_handle || '') + '"></div></div>' +
    '<div class="row2"><div><label class="field">' + esc(t('set_fulfill')) + '</label><select id="set-fulfillment">' +
    ['pickup', 'delivery', 'both'].map(f =>
      '<option value="' + f + '"' + (v.fulfillment === f ? ' selected' : '') + '>' + esc(fulfillLabel(f)) + '</option>').join('') +
    '</select></div>' +
    '<div><label class="field">' + esc(t('set_fee')) + '</label><input type="number" id="set-fee" step="0.01" min="0" placeholder="0.00" value="' +
    esc(v.delivery_fee === null || v.delivery_fee === undefined ? '' : v.delivery_fee) + '"></div></div>' +
    // === v46: free-delivery threshold (blank = off) ===
    '<div class="row2"><div><label class="field">' + esc(t('set_freedel')) + '</label>' +
    '<input type="number" id="set-freedel" step="0.01" min="0" placeholder="' + esc(t('set_freedel_ph')) + '" value="' +
    esc(v.free_delivery_over === null || v.free_delivery_over === undefined ? '' : v.free_delivery_over) + '"></div>' +
    '<div><div class="hint" style="margin-top:1.7rem">' + esc(t('set_freedel_hint')) + '</div></div></div>' +
    // === END v46 ===
    '<div class="mt"><button class="btn" onclick="saveSettings()">' + esc(t('set_save')) + '</button></div></div>';

  // === VENDOR MEDIA/DELIVERY (Oct 2026): delivery ZIP coverage ===
  html += '<div class="form-card settings-form"><h3>' + esc(t('set_delivery_h')) + '</h3>' +
    '<div class="hint" style="margin-top:0">' + esc(t('set_delivery_hint')) + '</div>' +
    '<label class="field">' + esc(t('set_delzips')) + '</label>' +
    '<textarea id="set-delzips" rows="2" maxlength="2000" placeholder="' + esc(t('set_delzips_ph')) + '">' + esc(v.delivery_zips || '') + '</textarea>' +
    '<div class="hint">' + esc(t('set_delzips_hint')) + '</div>' +
    '<div class="mt"><button class="btn" onclick="saveSettings()">' + esc(t('set_save')) + '</button></div></div>';
  // === END VENDOR MEDIA/DELIVERY ===

  // === FEATURE 9: pickup-point card — shown to customers at checkout ===
  html += '<div class="form-card settings-form"><h3>' + esc(t('pickup_h')) + '</h3>' +
    '<div class="hint" style="margin-top:0">' + esc(t('pickup_hint')) + '</div>' +
    '<label class="field">' + esc(t('pickup_address')) + '</label>' +
    '<textarea id="set-pickup-addr" rows="2" maxlength="2000" placeholder="' + esc(t('pickup_address_ph')) + '">' + esc(v.pickup_address || '') + '</textarea>' +
    '<label class="field">' + esc(t('pickup_map_url')) + '</label>' +
    '<input type="url" id="set-pickup-map" maxlength="500" placeholder="https://maps.google.com/…" value="' + esc(v.pickup_map_url || '') + '">' +
    '<label class="field">' + esc(t('pickup_instructions')) + '</label>' +
    '<textarea id="set-pickup-instr" rows="3" maxlength="2000" placeholder="' + esc(t('pickup_instructions_ph')) + '">' + esc(v.pickup_instructions || '') + '</textarea>' +
    '<div class="mt"><button class="btn" onclick="saveSettings()">' + esc(t('set_save')) + '</button></div></div>';
  // === END FEATURE 9 ===

  // === VENDOR MEDIA/DELIVERY (Oct 2026): Meet the Chef — shown publicly on the storefront ===
  html += '<div class="form-card settings-form"><h3>' + esc(t('chef_h')) + '</h3>' +
    '<div class="hint" style="margin-top:0">' + esc(t('chef_hint')) + '</div>' +
    '<label class="field">' + esc(t('chef_name')) + '</label>' +
    '<input type="text" id="set-chefname" maxlength="120" value="' + esc(v.chef_name || '') + '">' +
    '<label class="field">' + esc(t('chef_photo')) + '</label>' +
    '<input type="url" id="set-chefphoto" maxlength="2000" placeholder="' + esc(t('chef_photo_ph')) + '" value="' + esc(v.chef_photo_url || '') + '" oninput="previewDishPhoto(\'set-chefphoto\',\'set-chefpreview\')">' +
    '<label class="field upload-label">' + esc(t('f_upload_or')) + ' ' +
    '<input type="file" id="set-cheffile" accept="image/jpeg,image/png,image/webp,image/gif" onchange="photoFilePicked(\'set-cheffile\',\'set-chefphoto\',\'set-chefpreview\')"></label>' +
    '<img id="set-chefpreview" class="photo-preview" alt=""' +
    (v.chef_photo_url ? ' src="' + esc(v.chef_photo_url) + '"' : ' style="display:none"') + ' onerror="previewDishPhotoErr(this)">' +
    '<label class="field">' + esc(t('chef_bio')) + '</label>' +
    '<textarea id="set-chefbio" rows="3" maxlength="2000" placeholder="' + esc(t('chef_bio_ph')) + '">' + esc(v.chef_bio || '') + '</textarea>' +
    '<label class="field">' + esc(t('chef_bio_ar')) + '</label>' +
    '<textarea id="set-chefbioar" rows="3" maxlength="2000" placeholder="' + esc(t('chef_bio_ph')) + '">' + esc(v.chef_bio_ar || '') + '</textarea>' +
    '<div class="mt"><button class="btn" onclick="saveSettings()">' + esc(t('set_save')) + '</button></div></div>';
  // === END VENDOR MEDIA/DELIVERY ===

  // === VENDOR MEDIA/DELIVERY (Oct 2026): intro video upload ===
  html += '<div class="form-card settings-form"><h3>' + esc(t('intro_h')) + '</h3>' +
    '<div class="hint" style="margin-top:0">' + esc(t('intro_hint')) + '</div>' +
    '<input type="hidden" id="set-introvideourl" value="' + esc(v.intro_video_url || '') + '">' +
    '<video id="set-introprev" class="video-preview" controls preload="metadata"' +
    (v.intro_video_url ? ' src="' + esc(v.intro_video_url) + '"' : ' style="display:none"') + '></video>' +
    '<label class="field upload-label">' + esc(t('video_upload')) + ' ' +
    '<input type="file" id="set-introfile" accept="video/mp4,video/webm" onchange="videoFilePicked(\'set-introfile\',\'set-introprev\',\'set-introvideourl\',\'set-introerr\')"></label>' +
    '<div class="row2" style="margin-top:.3rem"><div><button class="btn small secondary" type="button" onclick="removeVideo(\'set-introfile\',\'set-introprev\',\'set-introvideourl\')">' + esc(t('video_remove')) + '</button></div><div></div></div>' +
    '<div class="hint" id="set-introerr" style="color:#b3261e"></div>' +
    '<div class="mt"><button class="btn" onclick="saveSettings()">' + esc(t('set_save')) + '</button></div></div>';
  // === END VENDOR MEDIA/DELIVERY ===

  // Opening hours: prep time, open/close times, closed weekdays.
  html += '<div class="form-card settings-form"><h3>' + esc(t('set_hours_h')) + '</h3>' +
    '<label class="field">' + esc(t('set_prep')) + '</label>' +
    '<input type="number" id="set-prep" min="0" max="1440" step="5" placeholder="30" value="' +
    esc(v.prep_minutes != null ? v.prep_minutes : '') + '">' +
    '<div class="hint">' + esc(t('set_prep_hint')) + '</div>' +
    '<div class="row2"><div><label class="field">' + esc(t('set_open')) + '</label>' +
    '<input type="time" id="set-open" value="' + esc(v.open_time || '') + '"></div>' +
    '<div><label class="field">' + esc(t('set_close')) + '</label>' +
    '<input type="time" id="set-close" value="' + esc(v.close_time || '') + '"></div></div>' +
    '<label class="field">' + esc(t('set_closed_days')) + '</label><div class="day-checks">' +
    [0, 1, 2, 3, 4, 5, 6].map(d =>
      '<label class="day-check"><input type="checkbox" id="set-closed-' + d + '"' +
      (closedDays(v).indexOf(d) !== -1 ? ' checked' : '') + '> ' + esc(t('day_' + d)) + '</label>').join('') +
    '</div>' +
    '<div class="mt"><button class="btn" onclick="saveSettings()">' + esc(t('set_save')) + '</button></div></div>';

  html += '<div class="form-card settings-form"><h3>' + esc(t('set_pw')) + '</h3>' +
    '<div id="pw-msg"></div>' +
    '<label class="field">' + esc(t('set_cur')) + '</label><input type="password" id="pw-current" autocomplete="current-password">' +
    '<label class="field">' + esc(t('set_new')) + '</label><input type="password" id="pw-new" autocomplete="new-password">' +
    '<label class="field">' + esc(t('set_confirm')) + '</label><input type="password" id="pw-confirm" autocomplete="new-password">' +
    '<div class="mt"><button class="btn" onclick="changeVendorPassword()">' + esc(t('set_update')) + '</button></div></div>';

  $('#view').innerHTML = html;
}

window.saveSettings = async function () {
  const errEl = $('#settings-err'), msgEl = $('#settings-msg');
  errEl.innerHTML = ''; msgEl.innerHTML = '';
  const name = $('#set-name').value.trim();
  if (!name) { errEl.innerHTML = '<div class="error">' + esc(t('set_need_name')) + '</div>'; $('#set-name').focus(); return; }
  const feeRaw = $('#set-fee').value.trim();
  const body = {
    name,
    name_ar: $('#set-name-ar').value.trim() || null,
    tagline: $('#set-tagline').value.trim(),
    area: $('#set-area').value.trim(),
    phone: $('#set-phone').value.trim(),
    fulfillment: $('#set-fulfillment').value,
    street_address: $('#set-street').value.trim() || null,
    apt: $('#set-apt').value.trim() || null,
    city: $('#set-city').value.trim() || null,
    state: $('#set-state').value || null,
    zipcode: $('#set-zip').value.trim() || null,
    zelle_handle: $('#set-zelle').value.trim() || null,
    venmo_handle: $('#set-venmo').value.trim() || null,
    // === FEATURE 9: pickup-point card ===
    pickup_address: $('#set-pickup-addr').value.trim() || null,
    pickup_map_url: $('#set-pickup-map').value.trim() || null,
    pickup_instructions: $('#set-pickup-instr').value.trim() || null,
    // === END FEATURE 9 ===
  };
  // === VENDOR MEDIA/DELIVERY (Oct 2026): delivery ZIP coverage ===
  // Blank = pickup only. Each ZIP must be exactly 5 digits (server 422s otherwise).
  const zipRaw = $('#set-delzips').value;
  const zips = zipRaw.split(',').map(z => z.trim()).filter(z => z !== '');
  const badZip = zips.find(z => !/^\d{5}$/.test(z));
  if (badZip) {
    errEl.innerHTML = '<div class="error">' + esc(t('set_bad_zips')) + '</div>';
    $('#set-delzips').focus();
    return;
  }
  body.delivery_zips = zips.length ? zips.join(',') : null;
  // === END VENDOR MEDIA/DELIVERY ===
  if (body.zipcode && !/^\d{5}(-\d{4})?$/.test(body.zipcode)) {
    errEl.innerHTML = '<div class="error">' + esc(t('addr_zip_bad')) + '</div>';
    $('#set-zip').focus();
    return;
  }
  if (feeRaw !== '') {
    const fee = Number(feeRaw);
    if (!isFinite(fee) || fee < 0) {
      errEl.innerHTML = '<div class="error">' + esc(t('set_bad_fee')) + '</div>';
      $('#set-fee').focus();
      return;
    }
    body.delivery_fee = fee;
  }
  // === v46: free-delivery threshold — always sent (blank = null = off) so
  // clearing the field actually turns the feature off. ===
  const fdoRaw = $('#set-freedel').value.trim();
  if (fdoRaw === '') { body.free_delivery_over = null; }
  else {
    const fdo = Number(fdoRaw);
    if (!isFinite(fdo) || fdo < 0) {
      errEl.innerHTML = '<div class="error">' + esc(t('set_bad_freedel')) + '</div>';
      $('#set-freedel').focus();
      return;
    }
    body.free_delivery_over = fdo;
  }
  // === END v46 ===
  // Opening hours.
  const prepRaw = $('#set-prep').value.trim();
  if (prepRaw === '') { body.prep_minutes = null; }
  else {
    const pm = parseInt(prepRaw, 10);
    if (isNaN(pm) || pm < 0) {
      errEl.innerHTML = '<div class="error">' + esc(t('set_bad_prep')) + '</div>';
      $('#set-prep').focus();
      return;
    }
    body.prep_minutes = pm;
  }
  body.open_time = $('#set-open').value || null;
  body.close_time = $('#set-close').value || null;
  const cd = [0, 1, 2, 3, 4, 5, 6].filter(d => { const c = $('#set-closed-' + d); return c && c.checked; });
  body.closed_weekdays = cd.length ? cd.join(',') : null;
  try {
    // === VENDOR MEDIA/DELIVERY (Oct 2026): upload chef photo + intro video
    // before saving, reusing the existing image/video upload plumbing. ===
    const chefUploaded = await uploadDishPhoto('set-cheffile'); // null when no file chosen
    if (chefUploaded) $('#set-chefphoto').value = chefUploaded;
    const introUploaded = await uploadVideo('set-introfile'); // null when no file chosen
    if (introUploaded) $('#set-introvideourl').value = introUploaded;
    body.chef_name = $('#set-chefname').value.trim() || null;
    body.chef_photo_url = $('#set-chefphoto').value.trim() || null;
    body.chef_bio = $('#set-chefbio').value.trim() || null;
    body.chef_bio_ar = $('#set-chefbioar').value.trim() || null;
    body.intro_video_url = $('#set-introvideourl').value.trim() || null;
    // === END VENDOR MEDIA/DELIVERY ===
    const updated = await api('/vendors/' + S.portal.vendorId, { method: 'PATCH', body: JSON.stringify(body) });
    S.portal.vendor = updated; // dashboard header + stat cards pick up the new name immediately
    msgEl.innerHTML = '<div class="success">' + esc(t('set_saved')) + '</div>';
    window.scrollTo(0, 0);
  } catch (e) { errEl.innerHTML = '<div class="error">' + esc(errText(e)) + '</div>'; }
};

window.changeVendorPassword = async function () {
  const msgEl = $('#pw-msg');
  msgEl.innerHTML = '';
  const cur = $('#pw-current').value, nw = $('#pw-new').value, cf = $('#pw-confirm').value;
  if (!cur || !nw) { msgEl.innerHTML = '<div class="error">' + esc(t('set_need_pw')) + '</div>'; return; }
  if (nw !== cf) { msgEl.innerHTML = '<div class="error">' + esc(t('set_pw_mismatch')) + '</div>'; return; }
  try {
    const r = await api('/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ current_password: cur, new_password: nw }),
    });
    // Fresh token: the backend invalidates all old tokens on password change.
    if (r && r.access_token) { S.token = r.access_token; localStorage.setItem('ehf_token', S.token); }
    $('#pw-current').value = $('#pw-new').value = $('#pw-confirm').value = '';
    msgEl.innerHTML = '<div class="success">' + esc(t('set_pw_done')) + '</div>';
  } catch (e) { msgEl.innerHTML = '<div class="error">' + esc(errText(e)) + '</div>'; }
};

/* ================= sales reports ================= */

async function vReports() {
  const view = $('#view');
  if (!S.user || S.user.role !== 'vendor') {
    view.innerHTML = '<div class="empty"><span class="big">🔒</span>' + esc(t('vendor_only')) + '<br><br>' +
      '<button class="btn" onclick="go(\'login\')">' + esc(t('login_as_vendor')) + '</button></div>';
    return;
  }
  view.innerHTML = '<div class="empty"><span class="big">📊</span>' + esc(t('rep_loading')) + '</div>';
  try {
    if (!S.portal.vendor) {
      const vendors = await api('/vendors/mine');
      if (!vendors.length) { view.innerHTML = '<div class="empty">' + esc(t('no_shop')) + '</div>'; return; }
      S.portal.vendorId = vendors[0].id;
      S.portal.vendor = vendors[0];
    }
    if (!S.reports) S.reports = { days: 30, data: null };
    await loadReports();
  } catch (e) {
    view.innerHTML = '<div class="error">' + esc(t('rep_err')) + esc(errText(e)) + '</div>';
  }
}

async function loadReports() {
  const days = S.reports.days;
  const data = await api('/vendors/' + S.portal.vendorId + '/reports/summary?days=' + days);
  S.reports.data = data;
  // === F4 (Oct 2026): what customers searched for — top zero-result queries, last 7 days ===
  try { S.reports.demand = await api('/search/zero-results'); }
  catch (e) { S.reports.demand = []; }
  // === END F4 ===
  renderReports();
}
window.setReportDays = async function (days) {
  if (!S.reports || S.reports.days === days) return;
  S.reports.days = days;
  const view = $('#view');
  try { await loadReports(); }
  catch (e) { view.innerHTML = '<div class="error">' + esc(t('rep_err')) + esc(errText(e)) + '</div>'; }
};

function renderReports() {
  const data = S.reports.data;
  const days = S.reports.days;
  const perDay = data.per_day || [];
  const totalRev = perDay.reduce((s, d) => s + Number(d.revenue || 0), 0);
  const totalOrders = perDay.reduce((s, d) => s + Number(d.orders || 0), 0);
  const maxRev = Math.max.apply(null, perDay.map(d => Number(d.revenue || 0)).concat([0]));

  let html = '<button class="btn small ghost" onclick="go(\'portal\')">' + esc(t('back_portal')) + '</button>';
  html += '<h2 class="section-title">' + esc(t('rep_title')) + '</h2>';

  html += '<div class="rep-toolbar"><span class="rep-range-lbl">' + esc(t('rep_range')) + '</span>' +
    [7, 30, 90].map(n =>
      '<button class="btn small' + (days === n ? ' current' : '') + '" onclick="setReportDays(' + n + ')">' +
      esc(t('rep_d' + n)) + '</button>').join(' ') +
    '<button class="btn small" style="margin-inline-start:auto" onclick="exportReportCSV()">' + esc(t('rep_export')) + '</button></div>';

  html += '<div class="stat-cards">' +
    '<div class="stat-card"><div class="num">' + money(totalRev) + '</div><div class="lbl">' + esc(t('rep_revenue')) + '</div></div>' +
    '<div class="stat-card"><div class="num">' + totalOrders + '</div><div class="lbl">' + esc(t('rep_orders')) + '</div></div></div>';

  html += '<h3 class="section-title">' + esc(t('rep_daily')) + '</h3>';
  if (maxRev > 0) {
    html += '<div class="rep-chart">' + perDay.map(d => {
      const r = Number(d.revenue || 0);
      const h = Math.max(2, Math.round((r / maxRev) * 100));
      return '<div class="rep-bar" style="height:' + h + '%" title="' + esc(d.date) + ': ' + money(r) + '"></div>';
    }).join('') + '</div>' +
    '<div class="rep-axis"><span>' + esc(perDay[0].date) + '</span><span>' + esc(perDay[perDay.length - 1].date) + '</span></div>';
  } else {
    html += '<div class="empty">' + esc(t('rep_no_data')) + '</div>';
  }

  html += '<h3 class="section-title">' + esc(t('rep_by_status')) + '</h3>';
  const byStatus = data.by_status || {};
  const statusKeys = Object.keys(byStatus);
  html += statusKeys.length
    ? '<div class="table-wrap">' + '<table class="menu-table"><tbody>' + statusKeys.map(s =>
        '<tr><td><span class="status-pill status-' + esc(s) + '">' + esc(statusLabel(s)) + '</span></td>' +
        '<td style="text-align:end"><strong>' + byStatus[s] + '</strong></td></tr>').join('') + '</tbody></table>' + '</div>'
    : '<div class="empty">' + esc(t('rep_no_data')) + '</div>';

  html += '<h3 class="section-title">' + esc(t('rep_top')) + '</h3>';
  const top = data.top_dishes || [];
  html += top.length
    ? '<div class="table-wrap">' + '<table class="menu-table"><thead><tr><th>' + esc(t('th_dish')) + '</th><th>' + esc(t('rep_th_qty')) +
      '</th><th style="text-align:end">' + esc(t('rep_th_rev')) + '</th></tr></thead><tbody>' +
      top.map(dish =>
        '<tr><td><strong>' + esc(dish.name) + '</strong></td><td>' + dish.qty + '</td>' +
        '<td style="text-align:end">' + money(dish.revenue) + '</td></tr>').join('') + '</tbody></table>' + '</div>'
    : '<div class="empty">' + esc(t('rep_no_top')) + '</div>';

  // === F4 (Oct 2026): what customers searched for — top zero-result queries
  // (last 7 days, global aggregate). Cooks see what dishes customers want.
  const demand = S.reports.demand || [];
  html += '<h3 class="section-title">' + esc(t('rep_search_demand')) +
    ' <span class="sub">' + esc(t('rep_search_demand_sub')) + '</span></h3>';
  html += demand.length
    ? '<div class="table-wrap"><table class="menu-table"><tbody>' + demand.map(function (q) {
        return '<tr><td><strong>🔍 ' + esc(q.query) + '</strong></td>' +
          '<td style="text-align:end">' + esc(t('rep_search_times', { n: q.count })) + '</td></tr>';
      }).join('') + '</tbody></table></div>'
    : '<div class="empty">' + esc(t('rep_search_none')) + '</div>';
  // === END F4 ===

  $('#view').innerHTML = html;
}

window.exportReportCSV = function () {
  const data = S.reports && S.reports.data;
  if (!data || !(data.per_day || []).length) return;
  const rows = [['date', 'revenue', 'orders']];
  data.per_day.forEach(d => rows.push([d.date, Number(d.revenue || 0).toFixed(2), d.orders]));
  const csv = rows.map(r => r.join(',')).join('\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'sales-report-' + new Date().toISOString().slice(0, 10) + '.csv';
  document.body.appendChild(a);
  a.click();
  setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
};

/* ================= vendor reviews + replies =================
   Every review on this vendor's dishes gets a reply box: textarea + send
   when there's no reply yet, the existing reply with an edit option when
   there is. */
async function vReviews() {
  const view = $('#view');
  if (!S.user || S.user.role !== 'vendor') {
    view.innerHTML = '<div class="empty"><span class="big">🔒</span>' + esc(t('vendor_only')) + '<br><br>' +
      '<button class="btn" onclick="go(\'login\')">' + esc(t('login_as_vendor')) + '</button></div>';
    return;
  }
  view.innerHTML = '<div class="empty"><span class="big">⭐</span>' + esc(t('rev_loading')) + '</div>';
  try {
    if (!S.portal.vendor) {
      const vendors = await api('/vendors/mine');
      if (!vendors.length) { view.innerHTML = '<div class="empty">' + esc(t('no_shop')) + '</div>'; return; }
      S.portal.vendorId = vendors[0].id;
      S.portal.vendor = vendors[0];
    }
    const rev = await api('/vendors/mine/reviews');
    const list = Array.isArray(rev) ? rev : (rev.reviews || []);
    S.portal.reviews = list;
    view.innerHTML = '<h2 class="section-title">' + esc(t('rev_title')) +
      ' <span class="sub">' + (rev.count != null ? rev.count : list.length) + '</span></h2>' +
      (list.length ? list.map(vReviewCard).join('') : '<div class="empty">' + esc(t('rev_empty')) + '</div>');
  } catch (e) {
    view.innerHTML = '<div class="error">' + esc(t('rev_loading')) + esc(errText(e)) + '</div>';
  }
}

function vReviewCard(r) {
  const boxId = 'rev-' + r.id + '-edit';
  let replyHTML;
  if (r.vendor_reply) {
    replyHTML = '<div class="vendor-reply"><strong>' + esc(t('rev_replied_on', { date: fmtDate(r.replied_at) })) +
      '</strong><p>' + esc(r.vendor_reply) + '</p>' +
      '<button class="btn small secondary" onclick="editReviewReply(' + r.id + ')">' + esc(t('rev_edit')) + '</button></div>' +
      '<div id="' + boxId + '"></div>';
  } else {
    replyHTML = '<div id="' + boxId + '"><label class="field">' + esc(t('rev_reply_ph')) + '</label>' +
      '<textarea id="rev-' + r.id + '-text" rows="2" maxlength="2000"></textarea>' +
      '<div class="mt"><button class="btn small" onclick="sendReviewReply(' + r.id + ')">' + esc(t('rev_send')) + '</button></div></div>';
  }
  return '<div class="review-card"><div class="review-head"><strong>' + esc(r.user_name || t('customer_fb')) +
    '</strong>' + vStars(r.rating) +
    (r.status && r.status !== 'approved' ? ' <span class="vendor-tag">' + esc(t('rev_status_' + r.status)) + '</span>' : '') + '</div>' +
    (r.dish_name ? '<div class="vendor-tag">' + esc(t('rev_on_dish', { dish: r.dish_name })) + '</div>' : '') +
    (r.text ? '<p>' + esc(r.text) + '</p>' : '') +
    '<div class="vendor-tag">' + esc(fmtDate(r.created_at)) + '</div>' + replyHTML + '</div>';
}

window.editReviewReply = function (id) {
  const r = (S.portal.reviews || []).find(x => x.id === id);
  const box = document.getElementById('rev-' + id + '-edit');
  if (!box) return;
  box.innerHTML = '<label class="field">' + esc(t('rev_reply_ph')) + '</label>' +
    '<textarea id="rev-' + id + '-text" rows="2" maxlength="2000">' + esc(r ? r.vendor_reply || '' : '') + '</textarea>' +
    '<div class="mt"><button class="btn small" onclick="sendReviewReply(' + id + ')">' + esc(t('rev_save')) + '</button></div>';
};

window.sendReviewReply = async function (id) {
  const ta = document.getElementById('rev-' + id + '-text');
  const text = (ta && ta.value || '').trim();
  if (!text) return;
  try {
    await api('/reviews/' + id + '/reply', { method: 'PATCH', body: JSON.stringify({ text }) });
    vReviews();
  } catch (e) { alert(t('rev_reply_err') + errText(e)); }
};

/* === F6 (Oct 2026): report-a-problem — vendor view ===
   Problem reports on this vendor's own orders. Private: the reporting
   customer, the vendor, and the admin only — never public. */
async function vProblems() {
  const view = $('#view');
  if (!S.user || S.user.role !== 'vendor') {
    view.innerHTML = '<div class="empty"><span class="big">🔒</span>' + esc(t('vendor_only')) + '<br><br>' +
      '<button class="btn" onclick="go(\'login\')">' + esc(t('login_as_vendor')) + '</button></div>';
    return;
  }
  view.innerHTML = '<div class="empty"><span class="big">🚨</span>' + esc(t('portal_loading')) + '</div>';
  try {
    if (!S.portal.vendor) {
      const vendors = await api('/vendors/mine');
      if (!vendors.length) { view.innerHTML = '<div class="empty">' + esc(t('no_shop')) + '</div>'; return; }
      S.portal.vendorId = vendors[0].id;
      S.portal.vendor = vendors[0];
    }
    const st = S.probStatus || '';
    const list = await api('/problems/vendor' + (st ? '?status=' + encodeURIComponent(st) : ''));
    let html = '<h2 class="section-title">' + esc(t('prob_title')) +
      ' <span class="sub">' + esc(t('prob_sub')) + '</span></h2>';
    html += '<div class="order-filters"><select id="prob-status" onchange="setProbStatus()">' +
      '<option value="">' + esc(t('prob_status_all')) + '</option>' +
      ['new', 'in_review', 'resolved'].map(function (s) {
        return '<option value="' + s + '"' + (st === s ? ' selected' : '') + '>' +
          esc(t('prob_st_' + s)) + '</option>';
      }).join('') + '</select></div>';
    html += list.length
      ? '<div class="grid">' + list.map(probVendorCard).join('') + '</div>'
      : '<div class="empty">' + esc(t('prob_empty')) + '</div>';
    view.innerHTML = html;
  } catch (e) {
    view.innerHTML = '<div class="error">' + esc(t('prob_err')) + esc(errText(e)) + '</div>';
  }
}
window.setProbStatus = function () {
  const sel = $('#prob-status');
  S.probStatus = sel ? sel.value : '';
  vProblems();
};
function probVendorCard(p) {
  return '<div class="vendor-card"><div class="order-head"><strong>' + esc(t('prob_order', { id: p.order_id })) + '</strong> ' +
    (p.dish_name ? '<span class="vendor-tag">🍽️ ' + esc(p.dish_name) + '</span>' : '') +
    ' <span class="status-pill status-' + esc(p.status) + '">' + esc(t('prob_st_' + p.status)) + '</span></div>' +
    '<div class="vendor-tag">🏷️ ' + esc(t('prob_cat_' + p.category)) +
    (p.customer_name ? ' · 👤 ' + esc(p.customer_name) : '') +
    ' · <small>' + esc(fmtDate(p.created_at)) + '</small></div>' +
    '<p>' + esc(p.description) + '</p>' +
    (p.photo_url ? '<img src="' + esc(p.photo_url) + '" class="prob-photo" alt="">' : '') +
    (p.desired_outcome ? '<div class="vendor-tag">🎯 ' + esc(t('prob_outcome', { x: p.desired_outcome })) + '</div>' : '') +
    '<div class="order-actions"><button class="btn small secondary" onclick="go(\'order\',' + p.order_id + ')">' +
    esc(t('view_order')) + '</button></div></div>';
}
/* === END F6 === */

/* ================= support tickets =================
   Vendors: file complaints + track their own tickets.
   Admin: inbox of every ticket with reply + close. */
const SUP_CATS = ['order', 'vendor', 'payment', 'account', 'technical', 'other'];

function supCatLabel(c) { return t('sup_cat_' + c); }
function supStatusLabel(s) { return t('sup_st_' + s); }
function supStatusPill(s) {
  return '<span class="status-pill status-' + esc(s) + '">' + esc(supStatusLabel(s)) + '</span>';
}

async function vSupport() {
  const view = $('#view');
  const isAdmin = S.user && S.user.role === 'admin';
  // === v40+: staff handle the support inbox too ===
  if (!S.user || (S.user.role !== 'vendor' && !isAdmin && !isStaffUser())) {
    view.innerHTML = '<div class="empty"><span class="big">🔒</span>' + esc(t('vendor_only')) + '<br><br>' +
      '<button class="btn" onclick="go(\'login\')">' + esc(t('login_as_vendor')) + '</button></div>';
    return;
  }
  if (isAdmin) return vSupportAdmin();
  return vSupportVendor();
}

/* ---- vendor: my tickets + new complaint form ---- */
async function vSupportVendor() {
  const view = $('#view');
  view.innerHTML = '<h2 class="section-title">' + esc(t('sup_title')) + '</h2><div id="sup-msg"></div>' +
    '<div class="form-card"><h3>' + esc(t('sup_new')) + '</h3>' +
    '<div id="sup-err"></div>' +
    '<label class="field">' + esc(t('sup_cat')) + '</label><select id="sup-cat">' +
    SUP_CATS.map(c => '<option value="' + c + '">' + esc(supCatLabel(c)) + '</option>').join('') + '</select>' +
    '<label class="field">' + esc(t('sup_subject')) + '</label><input type="text" id="sup-subject" maxlength="160">' +
    '<label class="field">' + esc(t('sup_message')) + '</label><textarea id="sup-message" rows="4" maxlength="5000"></textarea>' +
    '<div class="mt"><button class="btn" onclick="submitComplaint()">' + esc(t('sup_send')) + '</button></div></div>' +
    '<h3 class="section-title">' + esc(t('sup_mine')) + '</h3><div id="sup-list"><div class="empty">' + esc(t('portal_loading')) + '</div></div>';
  try {
    const list = await api('/complaints/mine');
    $('#sup-list').innerHTML = list.length ? list.map(supTicketCard).join('') : '<div class="empty">' + esc(t('sup_none')) + '</div>';
  } catch (e) { $('#sup-list').innerHTML = '<div class="error">' + esc(errText(e)) + '</div>'; }
}

function supTicketCard(c) {
  return '<div class="order-card"><div class="order-head"><strong>#' + c.id + ' — ' + esc(c.subject) + '</strong> ' +
    supStatusPill(c.status) + '</div>' +
    '<div class="vendor-tag">' + esc(supCatLabel(c.category)) + ' · <small>' + esc(fmtDate(c.created_at)) + '</small>' +
    (c.order_id ? ' · ' + esc(t('sup_order')) + ' #' + c.order_id : '') +
    (c.vendor_name ? ' · ' + esc(c.vendor_name) : '') + '</div>' +
    '<p style="white-space:pre-wrap">' + esc(c.message) + '</p>' +
    (c.admin_reply ? '<div class="notice"><strong>' + esc(t('sup_reply')) + ':</strong><br>' + esc(c.admin_reply) + '</div>' : '') +
    '</div>';
}

window.submitComplaint = async function () {
  const errEl = $('#sup-err'), msgEl = $('#sup-msg');
  errEl.innerHTML = ''; msgEl.innerHTML = '';
  const subject = $('#sup-subject').value.trim(), message = $('#sup-message').value.trim();
  if (!subject || !message) { errEl.innerHTML = '<div class="error">' + esc(t('sup_need_both')) + '</div>'; return; }
  try {
    await api('/complaints', { method: 'POST', body: JSON.stringify({
      category: $('#sup-cat').value, subject, message,
    }) });
    msgEl.innerHTML = '<div class="success">' + esc(t('sup_sent')) + '</div>';
    window.scrollTo(0, 0);
    vSupportVendor();
  } catch (e) { errEl.innerHTML = '<div class="error">' + esc(errText(e)) + '</div>'; }
};

/* ---- admin: inbox of all tickets ---- */
let supFilter = 'open';
window.setSupFilter = function (s) { supFilter = s; vSupportAdmin(); };

async function vSupportAdmin() {
  const view = $('#view');
  view.innerHTML = '<h2 class="section-title">🎧 ' + esc(t('sup_inbox')) +
    ' <span class="sub">' + esc(t('sup_inbox_sub')) + '</span></h2>' +
    '<div class="order-filters">' +
    ['open', 'answered', 'closed', 'all'].map(s =>
      '<button class="btn small' + (supFilter === s ? '' : ' secondary') + '" onclick="setSupFilter(\'' + s + '\')">' +
      esc(s === 'all' ? t('status_all') : supStatusLabel(s)) + '</button>').join(' ') + '</div>' +
    '<div id="sup-list"><div class="empty">' + esc(t('portal_loading')) + '</div></div>' +
    '<div id="sup-detail"></div>';
  await supLoadAdmin();
}

async function supLoadAdmin() {
  try {
    const q = supFilter === 'all' ? '' : '?status=' + supFilter;
    const list = await api('/complaints' + q);
    $('#sup-list').innerHTML = list.length
      ? list.map(c =>
        '<div class="order-card" style="cursor:pointer" onclick="supOpenTicket(' + c.id + ')">' +
        '<div class="order-head"><strong>#' + c.id + ' — ' + esc(c.subject) + '</strong> ' + supStatusPill(c.status) + '</div>' +
        '<div class="vendor-tag">' + esc(c.reporter_name || '') + ' (' + esc(c.reporter_role || '') + ')' +
        (c.reporter_email ? ' · ' + esc(c.reporter_email) : '') + ' · ' + esc(supCatLabel(c.category)) +
        ' · <small>' + esc(fmtDate(c.created_at)) + '</small></div>' +
        '<p>' + esc((c.message || '').slice(0, 140)) + ((c.message || '').length > 140 ? '…' : '') + '</p></div>'
      ).join('')
      : '<div class="empty">' + esc(t('sup_none')) + '</div>';
    list.forEach(c => { S['sup_c_' + c.id] = c; });
  } catch (e) { $('#sup-list').innerHTML = '<div class="error">' + esc(errText(e)) + '</div>'; }
}

window.supOpenTicket = function (id) {
  const c = S['sup_c_' + id];
  if (!c) return;
  const el = $('#sup-detail');
  el.innerHTML = '<div class="form-card"><h3>#' + c.id + ' — ' + esc(c.subject) + ' ' + supStatusPill(c.status) + '</h3>' +
    '<div class="vendor-tag">' + esc(c.reporter_name || '') + ' (' + esc(c.reporter_role || '') + ')' +
    (c.reporter_email ? ' · <a href="mailto:' + esc(c.reporter_email) + '">' + esc(c.reporter_email) + '</a>' : '') +
    ' · ' + esc(supCatLabel(c.category)) +
    (c.order_id ? ' · ' + esc(t('sup_order')) + ' #' + c.order_id : '') +
    (c.vendor_name ? ' · ' + esc(c.vendor_name) : '') +
    ' · <small>' + esc(fmtDate(c.created_at)) + '</small></div>' +
    '<p style="white-space:pre-wrap"><strong>' + esc(t('sup_message')) + ':</strong><br>' + esc(c.message) + '</p>' +
    (c.admin_reply ? '<div class="notice"><strong>' + esc(t('sup_reply')) + ':</strong><br>' + esc(c.admin_reply) + '</div>' : '') +
    '<div id="sup-reply-err"></div>' +
    '<label class="field">' + esc(t('sup_your_reply')) + '</label><textarea id="sup-reply" rows="4" maxlength="5000">' + esc(c.admin_reply || '') + '</textarea>' +
    '<div class="row2"><div><label class="field">' + esc(t('sup_set_status')) + '</label><select id="sup-status">' +
    ['answered', 'closed'].map(s => '<option value="' + s + '"' + (c.status === s ? ' selected' : '') + '>' + esc(supStatusLabel(s)) + '</option>').join('') +
    '</select></div><div><label class="field">&nbsp;</label>' +
    '<button class="btn" style="width:100%" onclick="supSendReply(' + c.id + ')">' + esc(t('sup_send_reply')) + '</button></div></div>' +
    '<div class="mt"><button class="btn small secondary" onclick="document.getElementById(\'sup-detail\').innerHTML=\'\'">' + esc(t('cancel')) + '</button></div></div>';
  el.scrollIntoView({ behavior: 'smooth', block: 'start' });
};

window.supSendReply = async function (id) {
  const errEl = $('#sup-reply-err');
  errEl.innerHTML = '';
  const reply = $('#sup-reply').value.trim();
  if (!reply) { errEl.innerHTML = '<div class="error">' + esc(t('sup_need_reply')) + '</div>'; return; }
  try {
    const updated = await api('/complaints/' + id, { method: 'PATCH',
      body: JSON.stringify({ admin_reply: reply, status: $('#sup-status').value }) });
    S['sup_c_' + id] = updated;
    await supLoadAdmin();
    supOpenTicket(id);
  } catch (e) { errEl.innerHTML = '<div class="error">' + esc(errText(e)) + '</div>'; }
};

/* ================= init ================= */
(function initI18n() {
  const toggle = document.getElementById('lang-toggle');
  if (toggle) toggle.addEventListener('click', function () {
    setLang(lang() === 'ar' ? 'en' : 'ar');
  });
})();
(async function init() {
  // v43: show the running build version in the footer (support/debugging).
  fetch('/api/version').then(r => r.json()).then(j => {
    const el = document.getElementById('app-version');
    if (el && j && j.version) el.textContent = 'Build ' + j.version;
  }).catch(() => {});
  await loadMe();
  applyLang();
  loadAnalytics(); // fire-and-forget: a missing analytics ID is a no-op
})();

/* ---------- vendor payouts: own history, read-only ---------- */
async function vPayouts() {
  const view = $('#view');
  if (!S.user || S.user.role !== 'vendor') {
    view.innerHTML = '<div class="empty"><span class="big">🔒</span>' + esc(t('vendor_only')) + '<br><br>' +
      '<button class="btn" onclick="go(\'login\')">' + esc(t('login_as_vendor')) + '</button></div>';
    return;
  }
  view.innerHTML = '<div class="empty"><span class="big">💰</span>' + esc(t('payout_loading')) + '</div>';
  try {
    const [payouts, receivables, settlements, statements] = await Promise.all([
      api('/vendors/mine/payouts'),
      api('/vendors/mine/commission-receivables'),
      api('/vendors/mine/settlements'),
      api('/vendors/mine/commission-statements').catch(() => []),
    ]);
    let html = '<h2 class="section-title">' + esc(t('payout_title')) + '</h2>' +
      '<p class="hint">' + esc(t('payout_vendor_sub')) + '</p>';
    html += '<h3 class="section-title">' + esc(t('comm_balance_h')) + '</h3>' +
      '<p class="hint">' + esc(t('comm_vendor_hint')) + '</p>';
    html += receivables.length
      ? '<div class="table-wrap"><table class="menu-table"><thead><tr><th>' + esc(t('comm_shop')) + '</th><th>' + esc(t('comm_direct_orders')) + '</th><th>' + esc(t('comm_accrued')) + '</th><th>' + esc(t('comm_collected')) + '</th><th>' + esc(t('comm_outstanding')) + '</th></tr></thead><tbody>' +
        receivables.map(r => '<tr><td><b>' + esc(r.vendor_name) + '</b></td><td>' + esc(r.direct_order_count) +
          '</td><td>' + money(r.commission_due) + '</td><td>' + money(r.commission_collected) +
          '</td><td><strong>' + money(r.outstanding_commission) + '</strong></td></tr>').join('') +
        '</tbody></table></div>'
      : '<div class="empty">No shops are linked to this vendor account.</div>';
    const commissionRows = settlements.filter(s => s.source === 'commission_collection');
    html += '<h3 class="section-title">' + esc(t('comm_history_h')) + '</h3>';
    html += commissionRows.length
      ? '<div class="table-wrap"><table class="menu-table"><thead><tr><th>Date</th><th>Shop</th><th>Amount</th><th>Method</th><th>Reference / note</th></tr></thead><tbody>' +
        commissionRows.map(s => '<tr><td>' + esc(fmtDate(s.created_at)) + '</td><td>' + esc(s.vendor_name) +
          '</td><td><strong>' + money(s.amount) + '</strong></td><td>' + esc(s.method) +
          '</td><td>' + esc(s.note || '—') + '</td></tr>').join('') + '</tbody></table></div>'
      : '<div class="empty">' + esc(t('comm_history_none')) + '</div>';
    // === v48: weekly commission statements (cycle snapshots) ===
    html += '<h3 class="section-title">' + esc(t('comm_statements_h')) + '</h3>';
    html += statements.length
      ? '<div class="table-wrap"><table class="menu-table"><thead><tr><th>' + esc(t('comm_stmt_week')) + '</th><th>' + esc(t('comm_stmt_period')) + '</th><th>' + esc(t('comm_shop')) + '</th><th>' + esc(t('comm_direct_sales')) + '</th><th>' + esc(t('comm_accrued')) + '</th><th>' + esc(t('comm_collected')) + '</th><th>' + esc(t('comm_outstanding')) + '</th><th>' + esc(t('comm_stmt_status')) + '</th></tr></thead><tbody>' +
        statements.map(s => '<tr><td><b>' + esc(s.week_key) + '</b></td><td>' + esc(s.period_start || '') + ' – ' + esc(s.period_end || '') +
          '</td><td>' + esc(s.vendor_name) + '</td><td>' + money(s.direct_sales) + '</td><td>' + money(s.commission_due) +
          '</td><td>' + money(s.commission_collected) + '</td><td><strong>' + money(s.outstanding) + '</strong></td><td>' +
          (s.pause_applied ? '<span class="vendor-tag">' + esc(t('comm_stmt_paused')) + '</span>'
            : s.reminded ? '<span class="vendor-tag">' + esc(t('comm_stmt_reminded')) + '</span>' : '—') +
          '</td></tr>').join('') + '</tbody></table></div>'
      : '<div class="empty">' + esc(t('comm_statements_none')) + '</div>';
    // === END v48 ===
    html += '<h3 class="section-title">' + esc(t('comm_payouts_to_you')) + '</h3>';
    html += payouts.length
      ? '<div class="table-wrap"><table class="menu-table"><thead><tr><th>' + esc(t('tbl_date')) + '</th><th>' +
        esc(t('tbl_amount')) + '</th><th>' + esc(t('tbl_note')) + '</th></tr></thead><tbody>' +
        payouts.map(p => '<tr><td>' + esc(fmtDate(p.created_at)) + '</td><td><strong>' + money(p.amount) + '</strong></td>' +
          '<td>' + esc(p.note || t('tbl_never')) + '</td></tr>').join('') + '</tbody></table></div>'
      : '<div class="empty">' + esc(t('payout_none')) + '</div>';
    view.innerHTML = html;
  } catch (e) {
    view.innerHTML = '<div class="error">' + esc(t('payout_err')) + esc(errText(e)) + '</div>';
  }
}

/* ---------- Admin back-office (admin role only) ---------- */
const ADM_TABS = ['overview', 'analytics', 'orders', 'customers', 'vendors', 'dishes', 'reviews', 'promos', 'retention', 'payouts', 'applications', 'loyalty', 'catering', 'problems', 'users', 'settings', 'audit_log', 'delivery']; // === F6: problems tab === // === v40: analytics tab ===
// === v40+: broadcasts + scorecards tabs (appended; staff sees a subset) ===
const ADM_TABS_EXTRA = ['broadcasts', 'scorecards'];
const ADM_TABS_ALL = ADM_TABS.concat(ADM_TABS_EXTRA);
// Staff may only touch: overview, orders, vendors, dishes, problems (+ complaints inbox).
const STAFF_TABS = ['overview', 'orders', 'vendors', 'dishes', 'problems'];
function admVisibleTabs() {
  const isStaff = S.user && S.user.role === 'staff';
  return (isStaff ? ADM_TABS_ALL.filter(t => STAFF_TABS.includes(t)) : ADM_TABS_ALL);
}
// === v40+: staff back-office access helpers ===
function isStaffUser() { return !!(S.user && S.user.role === 'staff'); }
function isBackOffice() { return !!(S.user && (S.user.role === 'admin' || S.user.role === 'staff')); }
// === END v40+ ===
const ADM_STATUSES = ['new', 'preparing', 'ready', 'on_the_way', 'completed', 'cancelled'];

async function vAdmin() {
  const view = $('#view');
  // === v40+: staff accounts land on the back-office too (subset of tabs). ===
  if (!S.user || (S.user.role !== 'admin' && S.user.role !== 'staff')) {
    view.innerHTML = '<div class="empty"><span class="big">🔒</span>' + esc(t('adm_admin_only')) + '<br><br>' +
      '<button class="btn" onclick="go(\'login\')">' + esc(t('nav_login')) + '</button></div>';
    return;
  }
  const visTabs = admVisibleTabs();
  if (!visTabs.includes(S.adminTab)) S.adminTab = 'overview';
  const tabs = visTabs.map(x =>
    '<button class="tab' + (S.adminTab === x ? ' active' : '') + '" onclick="setAdminTab(\'' + x + '\')">' +
    esc(t('adm_tab_' + x)) + '</button>').join('');
  view.innerHTML = '<h2 class="section-title">' + esc(t('adm_title')) + '</h2>' +
    '<div class="tabs">' + tabs + '</div><div id="adm-body"><div class="empty">' + esc(t('adm_loading')) + '</div></div>';
  try {
    if (S.adminTab === 'overview') await admOverview();
    else if (S.adminTab === 'analytics') await admAnalytics(); // === v40 ===
    else if (S.adminTab === 'broadcasts') await admBroadcasts(); // === v40+ ===
    else if (S.adminTab === 'scorecards') await admScorecards(); // === v40+ ===
    else if (S.adminTab === 'orders') await admOrders();
    else if (S.adminTab === 'customers') await admCustomers();
    else if (S.adminTab === 'vendors') await admVendors();
    else if (S.adminTab === 'dishes') await admDishes();
    else if (S.adminTab === 'reviews') await admReviewsTab();
    else if (S.adminTab === 'promos') await admPromos();
    else if (S.adminTab === 'retention') await admRetention();
    else if (S.adminTab === 'payouts') await admPayouts();
    else if (S.adminTab === 'loyalty') await admLoyalty();
    else if (S.adminTab === 'catering') await admCatering();
    else if (S.adminTab === 'problems') await admProblems(); // === F6: problem reports inbox ===
    else if (S.adminTab === 'users') await admUsers();
    else if (S.adminTab === 'settings') await admSettings();
    else if (S.adminTab === 'audit_log') await admAuditLog();
    else if (S.adminTab === 'delivery') await vDeliveryAdmin('#adm-body');
    else await admApplications();
  } catch (e) {
    $('#adm-body').innerHTML = '<div class="error">' + esc(e.message) + '</div>';
  }
}
window.setAdminTab = function (x) { S.adminTab = x; vAdmin(); };

async function admOverview() {
  const s = await api('/admin/stats');
  const cards = [
    // v48: revenue is null for staff (money is admin eyes only) — show '—'.
    [isStaffUser() ? '—' : money(s.revenue), t('adm_stat_revenue')],
    [s.orders, t('adm_stat_orders')],
    [s.new_orders, t('stat_new_orders')],
    [s.customers, t('stat_customers')],
    [s.vendors, t('stat_vendors')],
    [s.dishes, t('adm_stat_dishes')],
    [s.open_complaints, t('stat_open_tickets')],
  ];
  $('#adm-body').innerHTML = '<div class="stat-grid">' +
    cards.map(c => '<div class="stat-card"><div class="num">' + c[0] + '</div><div class="lbl">' + esc(c[1]) + '</div></div>').join('') +
    '</div>';
}

/* ---------- v40: admin analytics ---------- */
function _anBarChart(rows, labelFn, valFn, fmtFn) {
  // Simple CSS bar chart: rows = [{...}], labelFn/valFn extract; fmtFn formats the value.
  const max = Math.max.apply(null, rows.map(valFn).concat([1]));
  return '<div class="an-chart">' + rows.map(r => {
    const v = valFn(r), pct = Math.round(v / max * 100);
    return '<div class="an-bar-row"><span class="an-bar-lbl">' + esc(labelFn(r)) + '</span>' +
      '<span class="an-bar-track"><span class="an-bar-fill" style="width:' + pct + '%"></span></span>' +
      '<span class="an-bar-val">' + esc(fmtFn(v, r)) + '</span></div>';
  }).join('') + '</div>';
}
function _anWeekdayName(w) {
  // w: 0=Monday..6=Sunday. 2026-10-19 is a Monday.
  const loc = (localStorage.getItem('ehf_lang') || 'en') === 'ar' ? 'ar-EG' : 'en-US';
  return new Date(2026, 9, 19 + w).toLocaleDateString(loc, { weekday: 'short' });
}
async function admAnalytics() {
  const days = S.admAnDays || 30;
  const a = await api('/admin/analytics?days=' + days);
  const t = a.totals;
  const dayBtns = [7, 30, 90].map(d =>
    '<button class="tab' + (days === d ? ' active' : '') + '" onclick="S.admAnDays=' + d + ';vAdmin()">' +
    esc(t('an_days', { n: d })) + '</button>').join('');
  let html = '<h3 class="section-title">' + esc(t('adm_tab_analytics')) + '</h3>' +
    '<div class="tabs">' + dayBtns + '</div>';
  // Hero totals
  const cards = [
    [money(t.gross), t('an_gross')],
    [t.orders, t('an_orders')],
    [money(t.avg_order), t('an_avg_order')],
    [t.customers, t('an_customers')],
    [a.repeat_rate + '%', t('an_repeat_rate')],
    [a.new_customers + ' / ' + a.returning_customers, t('an_new_returning')],
  ];
  html += '<div class="stat-grid">' +
    cards.map(c => '<div class="stat-card"><div class="num">' + c[0] + '</div><div class="lbl">' + esc(c[1]) + '</div></div>').join('') +
    '</div>';
  // Revenue over time
  html += '<h4>' + esc(t('an_rev_time')) + '</h4>' +
    _anBarChart(a.revenue_over_time, r => r.date.slice(5), r => r.gross, v => money(v));
  // Revenue by vendor
  if (a.revenue_by_vendor.length) {
    html += '<h4>' + esc(t('an_rev_vendor')) + '</h4>' +
      _anBarChart(a.revenue_by_vendor, r => r.vendor_name, r => r.gross,
        (v, r) => money(v) + ' · ' + r.orders + ' ' + t('an_orders'));
  }
  // Top dishes
  if (a.top_dishes.length) {
    html += '<h4>' + esc(t('an_top_dishes')) + '</h4><div class="table-wrap"><table class="menu-table"><thead><tr><th>' +
      esc(t('th_dish')) + '</th><th>' + esc(t('tbl_vendor')) + '</th><th>' + esc(t('an_units')) +
      '</th><th>' + esc(t('tbl_revenue')) + '</th></tr></thead><tbody>' +
      a.top_dishes.map(d => '<tr><td><b>' + esc(d.dish_name) + '</b></td><td>' + esc(d.vendor_name) +
        '</td><td>' + d.units + '</td><td><strong>' + money(d.revenue) + '</strong></td></tr>').join('') +
      '</tbody></table></div>';
  }
  // Peak hours + days
  html += '<h4>' + esc(t('an_peak_hours')) + '</h4>' +
    _anBarChart(a.peak_hours, r => String(r.hour).padStart(2, '0') + ':00', r => r.orders, v => String(v));
  html += '<h4>' + esc(t('an_peak_days')) + '</h4>' +
    _anBarChart(a.peak_days, r => _anWeekdayName(r.weekday), r => r.orders, v => String(v));
  $('#adm-body').innerHTML = html;
}

/* ---------- v40+: admin broadcasts ---------- */
async function admBroadcasts() {
  const [history, vendors] = await Promise.all([
    api('/admin/broadcasts?limit=20'),
    api('/admin/vendors'),
  ]);
  vendors.sort((a, b) => String(a.name).localeCompare(String(b.name)));
  let html = '<h3 class="section-title">' + esc(t('adm_tab_broadcasts')) + '</h3>' +
    '<div class="form-card"><h3>' + esc(t('bc_compose_h')) + '</h3><div id="bc-err"></div>' +
    '<div class="row2"><div><label class="field">' + esc(t('bc_title_en')) + '</label>' +
    '<input type="text" id="bc-title-en" maxlength="200"></div>' +
    '<div><label class="field">' + esc(t('bc_title_ar')) + '</label>' +
    '<input type="text" id="bc-title-ar" maxlength="200" dir="rtl"></div></div>' +
    '<div class="row2"><div><label class="field">' + esc(t('bc_body_en')) + '</label>' +
    '<textarea id="bc-body-en" rows="3" maxlength="2000"></textarea></div>' +
    '<div><label class="field">' + esc(t('bc_body_ar')) + '</label>' +
    '<textarea id="bc-body-ar" rows="3" maxlength="2000" dir="rtl"></textarea></div></div>' +
    '<div class="row2"><div><label class="field">' + esc(t('bc_audience')) + '</label>' +
    '<select id="bc-audience" onchange="document.getElementById(\'bc-vendor-wrap\').style.display=this.value===\'vendor\'?\'\':\'none\'">' +
    '<option value="all">' + esc(t('bc_aud_all')) + '</option>' +
    '<option value="vendor">' + esc(t('bc_aud_vendor')) + '</option></select></div>' +
    '<div id="bc-vendor-wrap" style="display:none"><label class="field">' + esc(t('tbl_vendor')) + '</label>' +
    '<select id="bc-vendor">' +
    vendors.map(v => '<option value="' + v.id + '">' + esc(v.name) + '</option>').join('') +
    '</select></div></div>' +
    '<p class="hint">' + esc(t('bc_limit_hint')) + '</p>' +
    '<div class="mt"><button class="btn" onclick="sendBroadcast()">' + esc(t('bc_send')) + '</button></div></div>';
  html += '<h3 class="section-title">' + esc(t('bc_history_h')) + '</h3>';
  html += history.length
    ? '<div class="table-wrap"><table class="menu-table"><thead><tr><th>' + esc(t('tbl_date')) + '</th><th>' +
      esc(t('bc_title')) + '</th><th>' + esc(t('bc_audience')) + '</th><th>' + esc(t('bc_push_sent')) +
      '</th></tr></thead><tbody>' +
      history.map(b => '<tr><td>' + esc(fmtDate(b.created_at)) + '</td><td><b>' + esc(b.title_en) +
        '</b><br><small>' + esc(b.title_ar) + '</small><br><small>' + esc((b.body_en || '').slice(0, 120)) +
        '</small></td><td>' + esc(b.audience === 'vendor' ? t('bc_aud_vendor') + ': ' + (b.vendor_name || '') : t('bc_aud_all')) +
        '</td><td>' + b.push_sent + '</td></tr>').join('') + '</tbody></table></div>'
    : '<div class="empty">' + esc(t('bc_none')) + '</div>';
  $('#adm-body').innerHTML = html;
}
window.sendBroadcast = async function () {
  const errEl = $('#bc-err');
  errEl.innerHTML = '';
  const payload = {
    title_en: $('#bc-title-en').value.trim(),
    title_ar: $('#bc-title-ar').value.trim(),
    body_en: $('#bc-body-en').value.trim(),
    body_ar: $('#bc-body-ar').value.trim(),
    audience: $('#bc-audience').value,
  };
  if (payload.audience === 'vendor') payload.vendor_id = Number($('#bc-vendor').value);
  if (!payload.title_en || !payload.title_ar || !payload.body_en || !payload.body_ar) {
    errEl.innerHTML = '<div class="error">' + esc(t('bc_fill_all')) + '</div>';
    return;
  }
  if (!confirm(t('bc_confirm'))) return;
  try {
    await api('/admin/broadcasts', { method: 'POST', body: JSON.stringify(payload) });
    vAdmin();
  } catch (e) { errEl.innerHTML = '<div class="error">' + esc(errText(e)) + '</div>'; }
};

/* ---------- v40+: vendor scorecards ---------- */
async function admScorecards() {
  const sc = await api('/admin/scorecards');
  const flagBadge = f => '<span class="status-cancelled">' +
    esc(f === 'high_cancellation' ? t('sc_flag_cancel') : t('sc_flag_rating')) + '</span>';
  let html = '<h3 class="section-title">' + esc(t('adm_tab_scorecards')) + '</h3>' +
    '<p class="hint">' + esc(t('sc_hint')) + '</p>';
  html += '<div class="table-wrap"><table class="menu-table"><thead><tr><th>' + esc(t('tbl_vendor')) + '</th><th>' +
    esc(t('sc_rating')) + '</th><th>' + esc(t('sc_orders')) + '</th><th>' + esc(t('sc_cancel_rate')) + '</th><th>' +
    esc(t('sc_response')) + '</th><th>' + esc(t('sc_prep')) + '</th><th>' + esc(t('sc_flags')) +
    '</th></tr></thead><tbody>' +
    sc.map(v => '<tr' + (v.flags.length ? ' class="row-flagged"' : '') + '><td><b>' + esc(v.vendor_name) + '</b>' +
      (v.is_paused ? ' ⏸️' : '') + '</td>' +
      '<td>' + (v.avg_rating != null ? '⭐ ' + v.avg_rating + ' <small>(' + v.rating_count + ')</small>' : esc(t('tbl_never'))) + '</td>' +
      '<td>' + v.total_orders + ' <small>(' + v.completed_orders + ' ✓ / ' + v.cancelled_orders + ' ✗)</small></td>' +
      '<td>' + v.cancellation_rate + '%</td>' +
      '<td>' + (v.avg_response_minutes != null ? v.avg_response_minutes + ' ' + esc(t('sc_min')) : esc(t('tbl_never'))) + '</td>' +
      '<td>' + (v.avg_prep_minutes != null ? v.avg_prep_minutes + ' ' + esc(t('sc_min')) : esc(t('tbl_never'))) +
      ' <small>/ ' + esc(t('sc_quoted', { n: v.quoted_prep_minutes })) + '</small></td>' +
      '<td>' + (v.flags.length ? v.flags.map(flagBadge).join(' ') : '<span class="status-paid">' + esc(t('sc_ok')) + '</span>') + '</td></tr>').join('') +
    '</tbody></table></div>';
  $('#adm-body').innerHTML = html;
}

async function admOrders() {
  const vendors = await api('/admin/vendors');
  const q = S.admOrderStatus || '', qv = S.admOrderVendor || '';
  let url = '/admin/orders?';
  if (q) url += 'status=' + encodeURIComponent(q) + '&';
  if (qv) url += 'vendor_id=' + encodeURIComponent(qv);
  const orders = await api(url);
  let html = '<div class="adm-toolbar">' +
    '<label>' + esc(t('adm_filter_status')) + ' <select onchange="S.admOrderStatus=this.value;vAdmin()">' +
    '<option value="">' + esc(t('adm_all')) + '</option>' +
    ADM_STATUSES.map(s => '<option value="' + s + '"' + (q === s ? ' selected' : '') + '>' + esc(s) + '</option>').join('') +
    '</select></label>' +
    '<label>' + esc(t('adm_filter_vendor')) + ' <select onchange="S.admOrderVendor=this.value;vAdmin()">' +
    '<option value="">' + esc(t('adm_all')) + '</option>' +
    vendors.map(v => '<option value="' + v.id + '"' + (String(qv) === String(v.id) ? ' selected' : '') + '>' + esc(v.name) + '</option>').join('') +
    '</select></label></div>';
  if (!orders.length) {
    html += '<div class="empty">0</div>';
  } else {
    html += '<div class="table-wrap">' + '<table class="menu-table"><thead><tr><th>' + esc(t('tbl_id')) + '</th><th>' + esc(t('tbl_date')) +
      '</th><th>' + esc(t('tbl_customer')) + '</th><th>' + esc(t('tbl_vendor')) + '</th><th>' + esc(t('tbl_total')) +
      '</th><th>' + esc(t('tbl_status')) + '</th><th>' + esc(t('tbl_set_status')) + '</th><th></th></tr></thead><tbody>' +
      orders.map(o => '<tr><td>#' + o.id + '</td><td>' + esc(fmtDate(o.created_at)) + '</td>' +
        '<td>' + esc(o.customer_name || '') + '</td><td>' + esc(o.vendor_name || '') + '</td>' +
        '<td>' + money(o.total) + '</td><td>' + esc(o.status) + '</td>' +
        '<td><select onchange="admSetStatus(' + o.id + ', this.value)">' +
        ADM_STATUSES.map(s => '<option value="' + s + '"' + (o.status === s ? ' selected' : '') + '>' + esc(s) + '</option>').join('') +
        '</select></td>' +
        '<td><button class="btn small" onclick="admOrderDetail(' + o.id + ')">' + esc(t('adm_view')) + '</button></td></tr>').join('') + '</tbody></table>' + '</div>';
  }
  $('#adm-body').innerHTML = html;
}
window.admSetStatus = async function (id, status) {
  try {
    await api('/admin/orders/' + id + '/status', { method: 'PATCH', body: JSON.stringify({ status }) });
  } catch (e) { alert(e.message); }
  vAdmin();
};

/* ---- admin order detail: timeline + message thread + standalone refund ---- */
window.admOrderDetail = async function (id) {
  const body = $('#adm-body');
  body.innerHTML = '<div class="empty">' + esc(t('adm_loading')) + '</div>';
  try {
    const det = await api('/admin/orders/' + id);
    const o = det.order;
    let html = '<button class="btn secondary" onclick="S.adminTab=\'orders\';vAdmin()">← ' + esc(t('adm_back_orders')) + '</button>' +
      '<h3 class="section-title">' + esc(t('order_num')) + o.id + ' · ' + esc(o.status) + '</h3>' +
      '<p>' + esc(o.customer_name || '') + ' · ' + esc(o.vendor_name || '') + ' · ' + money(o.total) +
      (o.paid ? ' · ' + esc(t('paid_badge_yes')) : ' · ' + esc(t('paid_badge_no'))) + cardPaidHTML(o) +
      (Number(o.refunded_amount) > 0 ? ' · ' + esc(t('adm_refunded', { amount: money(o.refunded_amount) })) : '') + '</p>';
    html += '<h4>' + esc(t('adm_items')) + '</h4><ul class="order-items">' +
      o.items.map(i => '<li>' + i.quantity + ' × ' + esc(iname(i)) + ' — ' + money(Number(i.unit_price) * i.quantity) + '</li>').join('') + '</ul>';
    html += '<h4>' + esc(t('adm_timeline')) + '</h4><ul class="order-items">' +
      (det.events.length ? det.events.map(e => '<li><small>' + esc(fmtDate(e.created_at)) + '</small> — ' + esc(e.message || e.event_type) + '</li>').join('')
        : '<li>' + esc(t('adm_no_events')) + '</li>') + '</ul>';
    html += '<h4>' + esc(t('adm_messages')) + '</h4><div id="msg-thread">' +
      (det.messages.length ? det.messages.map(m => '<div class="msg"><div class="msg-head"><strong>' + esc(m.sender_role) +
        '</strong> <small>' + esc(fmtDate(m.created_at)) + '</small></div><p>' + esc(m.text) + '</p></div>').join('')
        : '<div class="empty">' + esc(t('msg_empty')) + '</div>') + '</div>';
    // Standalone refund: full or partial, WITHOUT changing the order status.
    if (o.paid) {
      html += '<h4>💸 ' + esc(t('adm_refund_h')) + '</h4>' +
        '<div class="row2"><div><label class="field">' + esc(t('adm_refund_amount')) + '</label>' +
        '<input type="number" id="adm-refund-amt" step="0.01" min="0.01" max="' + esc(o.total) + '" value="' + esc(o.total) + '"></div>' +
        '<div><label class="field">&nbsp;</label><button class="btn danger" onclick="admRefund(' + o.id + ')">' + esc(t('adm_refund_btn')) + '</button></div></div>' +
        '<p class="hint">' + esc(t('adm_refund_hint')) + '</p>';
    }
    body.innerHTML = html;
  } catch (e) { body.innerHTML = '<div class="error">' + esc(e.message) + '</div>'; }
};

window.admRefund = async function (id) {
  const amt = parseFloat(($('#adm-refund-amt') || {}).value || '');
  if (isNaN(amt) || amt <= 0) { alert(t('adm_refund_invalid')); return; }
  if (!confirm(t('adm_refund_confirm', { amount: money(amt), id }))) return;
  try {
    const r = await api('/admin/orders/' + id + '/refund', { method: 'POST', body: JSON.stringify({ amount: amt }) });
    alert(t(r.result === 'issued' ? 'adm_refund_done' : 'adm_refund_manual', { amount: money(amt) }));
    admOrderDetail(id);
  } catch (e) { alert(e.message); }
};

async function admCustomers() {
  const cs = await api('/admin/customers');
  cs.sort((a, b) => b.total_spent - a.total_spent);
  let html = '<div class="table-wrap">' + '<table class="menu-table"><thead><tr><th>' + esc(t('tbl_customer')) + '</th><th>' + esc(t('tbl_phone')) +
    '</th><th>' + esc(t('tbl_orders')) + '</th><th>' + esc(t('tbl_spent')) + '</th><th>' + esc(t('tbl_last_order')) +
    '</th></tr></thead><tbody>' +
    cs.map(c => '<tr><td><b>' + esc(c.name) + '</b><br><small>' + esc(c.email) + '</small></td>' +
      '<td>' + esc(c.phone || t('tbl_never')) + '</td><td>' + c.orders + '</td><td>' + money(c.total_spent) + '</td>' +
      '<td>' + (c.last_order ? esc(fmtDate(c.last_order)) : esc(t('tbl_never'))) + '</td></tr>').join('') +
    '</tbody></table>' + '</div>';
  $('#adm-body').innerHTML = html;
}

async function admVendors() {
  const vs = await api('/admin/vendors');
  // v48: staff rows carry null money (admin eyes only) — sort null-safely
  // and render '—' in every money cell instead of a misleading $0.00.
  const staffView = isStaffUser();
  vs.sort((a, b) => (Number(b.revenue) || 0) - (Number(a.revenue) || 0));
  let html = '<div class="table-wrap">' + '<table class="menu-table"><thead><tr><th>' + esc(t('tbl_vendor')) + '</th><th>' + esc(t('tbl_owner')) +
    '</th><th>' + esc(t('tbl_phone')) + '</th><th>' + esc(t('tbl_dishes')) + '</th><th>' + esc(t('tbl_orders')) +
    '</th><th>' + esc(t('tbl_revenue')) + '</th><th>' + esc(t('an_gross')) + '</th><th>' + esc(t('an_commission')) +
    '</th><th>' + esc(t('an_paid')) + '</th><th>' + esc(t('an_owed')) + '</th><th>' + esc(t('tbl_last_order')) + '</th><th>' + esc(t('tbl_address')) +
    '</th><th>' + esc(t('adm_vendor_status')) + '</th><th></th></tr></thead><tbody>' +
    vs.map(v => '<tr><td><b>' + esc(v.name) + '</b></td>' +
      '<td>' + esc(v.owner_name || t('tbl_never')) + '<br><small>' + esc(v.owner_email || '') + '</small></td>' +
      '<td>' + esc(v.phone || t('tbl_never')) + '</td><td>' + v.dishes + '</td><td>' + v.orders + '</td>' +
      '<td>' + (staffView ? '—' : money(v.revenue)) + '</td>' +
      '<td>' + (staffView ? '—' : money(v.gross || 0)) + '</td>' +
      '<td>' + (staffView ? '—' : money(v.commission || 0) + '<br><small>' + esc(t('an_rate', { n: v.commission_rate })) + '</small>') + '</td>' +
      '<td>' + (staffView ? '—' : money(v.paid || 0)) + '</td>' +
      '<td>' + (staffView ? '—' : '<strong>' + money(v.owed || 0) + '</strong>') + '</td>' +
      '<td>' + (v.last_order ? esc(fmtDate(v.last_order)) : esc(t('tbl_never'))) + '</td>' +
      '<td><small>' + esc(v.address || v.area || t('tbl_never')) + '</small></td>' +
      '<td>' + (v.is_paused ? '⏸️ ' + esc(t('adm_vendor_paused')) : '✅ ' + esc(t('adm_vendor_active'))) + '</td>' +
      '<td style="white-space:nowrap"><button class="btn small" onclick="admVendorEdit(' + v.id + ')">' + esc(t('edit')) + '</button> ' +
      '<button class="btn small' + (v.is_paused ? '' : ' danger') + '" onclick="admVendorPause(' + v.id + ',' + (!!v.is_paused) + ')">' +
      esc(v.is_paused ? t('adm_vendor_resume') : t('adm_vendor_pause')) + '</button></td></tr>').join('') +
    '</tbody></table>' + '</div>';
  $('#adm-body').innerHTML = html;
}
window.admVendorPause = async function (id, currentlyPaused) {
  if (!confirm(t(currentlyPaused ? 'adm_vendor_resume_q' : 'adm_vendor_pause_q'))) return;
  try {
    await api('/admin/vendors/' + id, { method: 'PATCH', body: JSON.stringify({ is_paused: !currentlyPaused }) });
    vAdmin();
  } catch (e) { alert(e.message); }
};
window.admVendorEdit = async function (id) {
  const vs = await api('/admin/vendors');
  const v = vs.find(x => x.id === id);
  if (!v) return;
  const modal = $('#dish-modal');
  modal.innerHTML = '<div class="modal-card"><h3 class="section-title">' + esc(t('adm_vendor_edit_h')) + '</h3>' +
    '<form class="add-dish-form" onsubmit="return admVendorSave(event,' + v.id + ')">' +
    '<label class="field">' + esc(t('f_vendor_name')) + '</label><input type="text" id="av-name" required maxlength="160" value="' + esc(v.name || '') + '">' +
    '<label class="field">' + esc(t('f_vendor_name_ar')) + '</label><input type="text" id="av-name-ar" maxlength="160" dir="rtl" placeholder="مثال: مطبخ ماما سامية" value="' + esc(v.name_ar || '') + '">' +
    '<label class="field">' + esc(t('f_tagline')) + '</label><input type="text" id="av-tagline" maxlength="300" value="' + esc(v.tagline || '') + '">' +
    '<label class="field">' + esc(t('f_area')) + '</label><input type="text" id="av-area" maxlength="200" value="' + esc(v.area || '') + '">' +
    '<label class="field">' + esc(t('f_phone')) + '</label><input type="text" id="av-phone" maxlength="40" value="' + esc(v.phone || '') + '">' +
    '<label class="field">' + esc(t('an_commission_rate')) + '</label>' +
    '<input type="number" id="av-comm" step="0.1" min="0" max="100" placeholder="' + esc(t('an_commission_ph')) + '" value="' +
    (v.commission_rate != null ? esc(v.commission_rate) : '') + '">' +
    '<p class="hint">' + esc(t('an_commission_hint')) + '</p>' +
    '<div><label><input type="checkbox" id="av-paused"' + (v.is_paused ? ' checked' : '') + '> ' + esc(t('adm_vendor_paused')) + '</label></div>' +
    '<div class="row2"><div><label class="field">&nbsp;</label><button class="btn" type="submit" style="width:100%">' + esc(t('save_changes')) + '</button></div>' +
    '<div><label class="field">&nbsp;</label><button class="btn secondary" type="button" style="width:100%" onclick="cancelDishEdit()">' + esc(t('cancel')) + '</button></div></div>' +
    '</form></div>';
  modal.classList.remove('hidden');
  document.body.style.overflow = 'hidden';
  document.addEventListener('keydown', dishModalEsc);
};
window.admVendorSave = async function (ev, id) {
  ev.preventDefault();
  const commRaw = $('#av-comm').value.trim();
  const comm = commRaw === '' ? null : parseFloat(commRaw);
  if (comm !== null && (isNaN(comm) || comm < 0 || comm > 100)) {
    alert(t('an_commission_bad'));
    return false;
  }
  try {
    await api('/admin/vendors/' + id, {
      method: 'PATCH',
      body: JSON.stringify({
        name: $('#av-name').value.trim(),
        name_ar: $('#av-name-ar').value.trim() || null,
        tagline: $('#av-tagline').value.trim() || null,
        area: $('#av-area').value.trim() || null,
        phone: $('#av-phone').value.trim() || null,
        is_paused: $('#av-paused').checked,
        commission_rate: comm,
      }),
    });
    cancelDishEdit();
    vAdmin();
  } catch (e) { alert(e.message); }
  return false;
};

async function admRetention() {
  const r = await api('/admin/retention');
  const c = r.customers, v = r.vendors;
  const ccards = [
    [c.repeat_rate + '%', t('ret_repeat_rate')],
    [c.repeat, t('ret_repeat')],
    [c.one_time, t('ret_one_time')],
    [c.new_30d, t('ret_new_30d')],
    [c.returning_30d, t('ret_returning_30d')],
    [c.avg_orders, t('ret_avg_orders')],
  ];
  const vcards = [
    [v.active_rate + '%', t('ret_active_rate')],
    [v.active_30d + ' / ' + v.total, t('ret_active_30d')],
    [v.with_orders, t('ret_with_orders')],
  ];
  let html = '<h3 class="section-title">' + esc(t('ret_cust_title')) + '</h3><div class="stat-grid">' +
    ccards.map(x => '<div class="stat-card"><div class="num">' + x[0] + '</div><div class="lbl">' + esc(x[1]) + '</div></div>').join('') +
    '</div><h3 class="section-title">' + esc(t('ret_vend_title')) + '</h3><div class="stat-grid">' +
    vcards.map(x => '<div class="stat-card"><div class="num">' + x[0] + '</div><div class="lbl">' + esc(x[1]) + '</div></div>').join('') +
    '</div>';
  if (v.idle.length) {
    html += '<h4>' + esc(t('ret_idle')) + '</h4><ul>' +
      v.idle.map(x => '<li>' + esc(x.name) + '</li>').join('') + '</ul>';
  } else {
    html += '<div class="empty">' + esc(t('ret_none_idle')) + '</div>';
  }
  $('#adm-body').innerHTML = html;
}

/* ================= Admin: hybrid delivery management ================= */
const DELIVERY_STATUSES = ['pending', 'assigned', 'picked_up', 'delivered', 'failed', 'cancelled'];
const DELIVERY_STATUS_LABELS = {
  pending: 'Pending', assigned: 'Assigned', picked_up: 'Picked up',
  delivered: 'Delivered', failed: 'Failed', cancelled: 'Cancelled'
};
let _deliveryAdminCache = { jobs: [], orders: [], filter: 'all', loading: false, error: '' };

function deliveryMoney(value) {
  const n = Number(value);
  return money(Number.isFinite(n) ? n : 0);
}
function deliveryStatusPill(status) {
  const s = DELIVERY_STATUSES.includes(status) ? status : 'pending';
  return '<span class="delivery-status-pill status-' + esc(s) + '">' +
    esc(DELIVERY_STATUS_LABELS[s] || s) + '</span>';
}
function deliveryOrderLabel(order) {
  const customer = order.customer_name || order.customer?.name || order.customer_email || '';
  const date = order.created_at ? new Date(order.created_at).toLocaleDateString() : '';
  return 'Order #' + order.id + (customer ? ' · ' + customer : '') + (date ? ' · ' + date : '');
}
function deliveryJobOrder(job) {
  return _deliveryAdminCache.orders.find(o => Number(o.id) === Number(job.order_id)) || { id: job.order_id };
}
function deliveryAdminSummary(jobs) {
  const active = jobs.filter(j => ['pending', 'assigned', 'picked_up'].includes(j.status)).length;
  const delivered = jobs.filter(j => j.status === 'delivered').length;
  const subsidy = jobs.reduce((sum, j) => sum + Math.max(0, Number(j.platform_subsidy) || 0), 0);
  const actual = jobs.reduce((sum, j) => sum + Math.max(0, Number(j.actual_cost) || 0), 0);
  return '<div class="delivery-kpis">' +
    '<div class="delivery-kpi"><span>Active deliveries</span><strong>' + active + '</strong></div>' +
    '<div class="delivery-kpi"><span>Delivered</span><strong>' + delivered + '</strong></div>' +
    '<div class="delivery-kpi"><span>Actual delivery cost</span><strong>' + esc(deliveryMoney(actual)) + '</strong></div>' +
    '<div class="delivery-kpi"><span>Platform subsidy</span><strong>' + esc(deliveryMoney(subsidy)) + '</strong></div>' +
    '</div>';
}
function deliveryCreateForm() {
  const jobsOrderIds = new Set(_deliveryAdminCache.jobs.map(j => Number(j.order_id)));
  const eligible = _deliveryAdminCache.orders.filter(o =>
    String(o.fulfillment || '').toLowerCase() === 'delivery' &&
    !jobsOrderIds.has(Number(o.id)) &&
    String(o.status || '').toLowerCase() !== 'cancelled'
  );
  return '<section class="delivery-panel"><div class="delivery-panel-heading"><div><h2>Create a delivery job</h2>' +
    '<p class="hint">Select an existing delivery order that does not already have a delivery job.</p></div></div>' +
    (eligible.length
      ? '<div class="delivery-create-grid"><label class="field">Delivery order<select id="delivery-new-order">' +
        eligible.map(o => '<option value="' + Number(o.id) + '">' + esc(deliveryOrderLabel(o)) + '</option>').join('') +
        '</select></label><label class="field">Delivery mode<select id="delivery-new-mode"><option value="third_party">Third-party delivery</option><option value="vendor">Vendor delivery</option></select></label>' +
        '<label class="field">Provider<input id="delivery-new-provider" maxlength="40" value="manual" placeholder="e.g. in-house, courier name"></label>' +
        '<label class="field">Provider reference<input id="delivery-new-reference" maxlength="120" placeholder="Optional tracking/reference ID"></label>' +
        '<label class="field">Quoted cost ($)<input id="delivery-new-quoted" type="number" min="0" step="0.01" value="0"></label>' +
        '<label class="field">Customer delivery fee ($)<input id="delivery-new-fee" type="number" min="0" step="0.01" placeholder="Use order fee if blank"></label>' +
        '<label class="field delivery-notes-field">Notes<textarea id="delivery-new-notes" rows="2" maxlength="2000" placeholder="Optional dispatch notes"></textarea></label>' +
        '</div><div class="delivery-actions"><button class="btn" type="button" onclick="createDeliveryJob()">Create delivery job</button><span id="delivery-create-msg" role="status"></span></div>'
      : '<div class="notice">No eligible delivery orders found. A job may already exist for each delivery order, or no delivery orders are available.</div>') +
    '</section>';
}
function deliveryJobCard(job) {
  const order = deliveryJobOrder(job);
  const id = Number(job.id);
  const mode = job.mode === 'vendor' ? 'vendor' : 'third_party';
  const provider = job.provider || 'manual';
  const status = DELIVERY_STATUSES.includes(job.status) ? job.status : 'pending';
  return '<article class="delivery-job-card" data-delivery-job="' + id + '">' +
    '<div class="delivery-job-top"><div><div class="delivery-order-id">Order #' + Number(job.order_id) +
      ' <span class="delivery-job-id">· Job #' + id + '</span></div><div class="delivery-order-meta">' +
      esc(order.customer_name || order.customer?.name || order.customer_email || 'Customer details unavailable') +
      (order.created_at ? ' · ' + esc(new Date(order.created_at).toLocaleDateString()) : '') +
      '</div></div>' + deliveryStatusPill(status) + '</div>' +
    '<div class="delivery-edit-grid">' +
      '<label class="field">Status<select data-delivery-field="status">' +
        DELIVERY_STATUSES.map(s => '<option value="' + s + '"' + (s === status ? ' selected' : '') + '>' + esc(DELIVERY_STATUS_LABELS[s]) + '</option>').join('') +
      '</select></label>' +
      '<label class="field">Delivery mode<select data-delivery-field="mode"><option value="third_party"' + (mode === 'third_party' ? ' selected' : '') + '>Third-party</option><option value="vendor"' + (mode === 'vendor' ? ' selected' : '') + '>Vendor</option></select></label>' +
      '<label class="field">Provider<input data-delivery-field="provider" maxlength="40" value="' + esc(provider) + '"></label>' +
      '<label class="field">Provider reference<input data-delivery-field="provider_reference" maxlength="120" value="' + esc(job.provider_reference || '') + '" placeholder="Tracking/reference"></label>' +
      '<label class="field">Quoted cost ($)<input data-delivery-field="quoted_cost" type="number" min="0" step="0.01" value="' + esc(job.quoted_cost ?? '0') + '"></label>' +
      '<label class="field">Actual cost ($)<input data-delivery-field="actual_cost" type="number" min="0" step="0.01" value="' + esc(job.actual_cost ?? '0') + '"></label>' +
      '<label class="field">Customer fee ($)<input data-delivery-field="customer_fee" type="number" min="0" step="0.01" value="' + esc(job.customer_fee ?? '0') + '"></label>' +
      '<label class="field">Cost payment status<select data-delivery-field="payment_status">' +
        ['unpaid', 'paid', 'waived'].map(s => '<option value="' + s + '"' + (s === job.payment_status ? ' selected' : '') + '>' + esc(s.charAt(0).toUpperCase() + s.slice(1)) + '</option>').join('') +
      '</select></label>' +
      '<label class="field delivery-notes-field">Notes<textarea data-delivery-field="notes" rows="2" maxlength="2000">' + esc(job.notes || '') + '</textarea></label>' +
    '</div>' +
    '<div class="delivery-financials"><span>Actual cost <strong>' + esc(deliveryMoney(job.actual_cost)) + '</strong></span>' +
      '<span>Customer fee <strong>' + esc(deliveryMoney(job.customer_fee)) + '</strong></span>' +
      '<span>Platform subsidy <strong>' + esc(deliveryMoney(job.platform_subsidy)) + '</strong></span></div>' +
    '<div class="delivery-actions"><button class="btn small" type="button" onclick="saveDeliveryJob(' + id + ')">Save changes</button>' +
      '<span class="delivery-save-msg" id="delivery-save-msg-' + id + '" role="status"></span></div>' +
    '</article>';
}
async function vDeliveryAdmin(containerSelector) {
  const view = $(containerSelector || '#view');
  if (!view) return;
  if (!S.user || S.user.role !== 'admin') {
    S.flash = 'Please sign in with an administrator account to manage deliveries.';
    go('login');
    return;
  }
  view.innerHTML = '<section class="delivery-admin"><div class="delivery-page-header"><div><p class="eyebrow">ADMINISTRATION</p><h1>Delivery Management</h1><p class="hint">Dispatch orders and track delivery costs and platform subsidies.</p></div>' +
    '<button class="btn secondary" type="button" onclick="refreshDeliveryAdmin()">↻ Refresh</button></div><div id="delivery-admin-content"><p class="hint">Loading delivery data…</p></div></section>';
  await refreshDeliveryAdmin();
}
window.refreshDeliveryAdmin = async function () {
  const content = document.getElementById('delivery-admin-content');
  if (!content) return;
  content.innerHTML = '<p class="hint">Loading delivery data…</p>';
  try {
    const result = await Promise.all([
      api('/delivery/jobs'),
      api('/admin/orders')
    ]);
    _deliveryAdminCache.jobs = Array.isArray(result[0]) ? result[0] : [];
    _deliveryAdminCache.orders = Array.isArray(result[1]) ? result[1] : [];
    _deliveryAdminCache.error = '';
    const jobs = _deliveryAdminCache.filter === 'all'
      ? _deliveryAdminCache.jobs
      : _deliveryAdminCache.jobs.filter(j => j.status === _deliveryAdminCache.filter);
    content.innerHTML = deliveryAdminSummary(_deliveryAdminCache.jobs) +
      deliveryCreateForm() +
      '<section class="delivery-panel"><div class="delivery-panel-heading"><div><h2>Delivery jobs</h2><p class="hint">' +
      _deliveryAdminCache.jobs.length + ' total job' + (_deliveryAdminCache.jobs.length === 1 ? '' : 's') +
      '</p></div><label class="delivery-filter-label">Filter by status<select id="delivery-status-filter" onchange="filterDeliveryJobs(this.value)">' +
      [['all','All statuses'], ...DELIVERY_STATUSES.map(s => [s, DELIVERY_STATUS_LABELS[s]])]
        .map(([v,l]) => '<option value="' + v + '"' + (v === _deliveryAdminCache.filter ? ' selected' : '') + '>' + esc(l) + '</option>').join('') +
      '</select></label></div>' +
      (jobs.length ? '<div class="delivery-job-list">' + jobs.map(deliveryJobCard).join('') + '</div>' :
        '<div class="delivery-empty"><span>🚚</span><strong>No delivery jobs' +
        (_deliveryAdminCache.filter === 'all' ? ' yet' : ' with this status') +
        '</strong><p class="hint">Create a job above for an existing delivery order.</p></div>') +
      '</section>';
  } catch (e) {
    content.innerHTML = '<div class="error">' + esc(errText(e)) + '</div>' +
      '<button class="btn" type="button" onclick="refreshDeliveryAdmin()">Try again</button>';
  }
};
window.filterDeliveryJobs = function (status) {
  _deliveryAdminCache.filter = DELIVERY_STATUSES.includes(status) ? status : 'all';
  refreshDeliveryAdmin();
};
window.createDeliveryJob = async function () {
  const msg = document.getElementById('delivery-create-msg');
  if (msg) msg.textContent = '';
  const orderEl = document.getElementById('delivery-new-order');
  const modeEl = document.getElementById('delivery-new-mode');
  const providerEl = document.getElementById('delivery-new-provider');
  const referenceEl = document.getElementById('delivery-new-reference');
  const quotedEl = document.getElementById('delivery-new-quoted');
  const feeEl = document.getElementById('delivery-new-fee');
  const notesEl = document.getElementById('delivery-new-notes');
  if (!orderEl) return;
  const quoted = Number(quotedEl.value);
  const fee = feeEl.value.trim() === '' ? null : Number(feeEl.value);
  if (!Number.isFinite(quoted) || quoted < 0 || (fee !== null && (!Number.isFinite(fee) || fee < 0))) {
    if (msg) msg.textContent = 'Enter valid non-negative costs.';
    return;
  }
  const button = document.querySelector('#delivery-create-msg')?.previousElementSibling;
  if (button) button.disabled = true;
  try {
    await api('/delivery/orders/' + Number(orderEl.value) + '/job', {
      method: 'POST',
      body: JSON.stringify({
        mode: modeEl.value,
        provider: providerEl.value.trim() || 'manual',
        provider_reference: referenceEl.value.trim() || null,
        quoted_cost: quoted,
        customer_fee: fee,
        notes: notesEl.value.trim() || null
      })
    });
    await refreshDeliveryAdmin();
  } catch (e) {
    if (msg) msg.textContent = errText(e);
    if (button) button.disabled = false;
  }
};
window.saveDeliveryJob = async function (jobId) {
  const card = document.querySelector('[data-delivery-job="' + Number(jobId) + '"]');
  const msg = document.getElementById('delivery-save-msg-' + Number(jobId));
  if (!card) return;
  const payload = {};
  card.querySelectorAll('[data-delivery-field]').forEach(el => {
    const key = el.getAttribute('data-delivery-field');
    if (['quoted_cost', 'actual_cost', 'customer_fee'].includes(key)) {
      payload[key] = Number(el.value);
    } else {
      payload[key] = el.value.trim();
    }
  });
  if (['quoted_cost', 'actual_cost', 'customer_fee'].some(k => !Number.isFinite(payload[k]) || payload[k] < 0)) {
    if (msg) msg.textContent = 'Enter valid non-negative costs.';
    return;
  }
  const button = card.querySelector('button.btn');
  if (button) button.disabled = true;
  if (msg) msg.textContent = 'Saving…';
  try {
    await api('/delivery/jobs/' + Number(jobId), {
      method: 'PATCH',
      body: JSON.stringify(payload)
    });
    await refreshDeliveryAdmin();
  } catch (e) {
    if (msg) msg.textContent = errText(e);
    if (button) button.disabled = false;
  }
};
/* ================= END Admin: hybrid delivery management ================= */

/* ---------- admin: vendor applications inbox ---------- */
/* WA permits block on an application card. All permit fields are null for
   pre-gate applications — those show "permits not on file", never an error. */
function permitExpiryState(expiry) {
  if (!expiry) return 'app_permits_no_expiry';
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(expiry));
  if (!match) return 'app_permits_no_expiry';
  const todayParts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Los_Angeles',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date());
  const today = {};
  todayParts.forEach(function (part) { today[part.type] = part.value; });
  const expiryDay = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  const todayDay = Date.UTC(Number(today.year), Number(today.month) - 1, Number(today.day));
  const daysRemaining = Math.floor((expiryDay - todayDay) / 86400000);
  if (daysRemaining < 0) return 'app_permits_expired';
  if (daysRemaining <= 30) return 'app_permits_expiring';
  return 'app_permits_current';
}
function formatPermitExpiry(expiry) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(expiry || ''))) return String(expiry || '');
  return new Date(String(expiry) + 'T00:00:00Z').toLocaleDateString(
    lang() === 'ar' ? 'ar-EG' : 'en-US',
    { timeZone: 'UTC' }
  );
}
function admAppPermits(a) {
  const keys = ['permits_food_worker_card', 'permits_establishment', 'permits_cottage', 'permits_business_license'];
  const any = keys.some(k => a[k] !== null && a[k] !== undefined) || a.permits_attested != null;
  if (!any) return '<div class="vendor-tag">⚠️ ' + esc(t('app_permits_none')) + '</div>';
  let html = '<div style="margin-top:.4em"><strong>' + esc(t('app_permits_h')) + '</strong>';
  const row = (held, label, num, exp) => {
    const expiryState = held ? permitExpiryState(exp) : null;
    const expiryClass = expiryState === 'app_permits_expired'
      ? ' permit-expiry-expired'
      : expiryState === 'app_permits_expiring' ? ' permit-expiry-soon' : '';
    html += '<div class="vendor-tag">' + (held ? '✅ ' : '⬜ ') + esc(label) +
      (num ? ' · ' + esc(t('app_permits_num')) + ' ' + esc(num) : '') +
      (exp ? ' · ' + esc(t('app_permits_exp')) + ' ' + esc(formatPermitExpiry(exp)) : '') +
      (expiryState ? ' <span class="permit-expiry' + expiryClass + '">' + esc(t(expiryState)) + '</span>' : '') +
      '</div>';
  };
  row(a.permits_food_worker_card, t('app_permits_fwc'), a.permits_food_worker_card_number, a.permits_food_worker_card_expiry);
  row(a.permits_establishment, t('app_permits_est'), a.permits_establishment_number, a.permits_establishment_expiry);
  row(a.permits_cottage, t('app_permits_cottage'), a.permits_cottage_number, a.permits_cottage_expiry);
  row(a.permits_business_license, t('app_permits_biz'), a.permits_business_license_ubi, null);
  html += '<div class="vendor-tag">' + (a.permits_attested ? '✅ ' : '❌ ') + esc(t('app_permits_attest')) + '</div></div>';
  return html;
}
async function admApplications() {
  const apps = await api('/admin/applications');
  let html = '<h3 class="section-title">' + esc(t('adm_tab_applications')) + '</h3>';
  html += apps.length
    ? apps.map(a =>
      '<div class="order-card"><div class="order-head"><strong>' + esc(a.name) + '</strong> ' +
      '<span class="status-pill status-' + esc(a.status || 'pending') + '">' + esc(a.status || 'pending') + '</span></div>' +
      '<div class="vendor-tag">📞 ' + esc(a.phone || '—') + (a.email ? ' · ✉️ ' + esc(a.email) : '') +
      (a.city ? ' · 📍 ' + esc(a.city) : '') + '</div>' +
      (a.cooking ? '<div class="vendor-tag">🍳 <strong>' + esc(t('app_cooking')) + ':</strong> ' + esc(a.cooking) + '</div>' : '') +
      (a.message ? '<p style="white-space:pre-wrap">' + esc(a.message) + '</p>' : '') +
      admAppPermits(a) +
      '<div class="vendor-tag"><small>' + esc(fmtDate(a.created_at)) + '</small></div>' +
      '<div class="order-actions"><button class="btn small" onclick="admAppStatus(' + a.id + ',\'approved\')">' +
      esc(t('app_approve')) + '</button> ' +
      '<button class="btn small danger" onclick="admAppStatus(' + a.id + ',\'declined\')">' +
      esc(t('app_decline')) + '</button></div></div>').join('')
    : '<div class="empty">' + esc(t('app_none')) + '</div>';
  $('#adm-body').innerHTML = html;
}
window.admAppStatus = async function (id, status) {
  try {
    await api('/admin/applications/' + id, { method: 'PATCH', body: JSON.stringify({ status }) });
    admApplications();
  } catch (e) { alert(errText(e)); }
};

/* ---------- admin: record and view vendor payouts ---------- */
async function admPayouts() {
  const [payouts, vendors, receivables, settlements, cycleStatus, siteSettings] = await Promise.all([
    api('/admin/payouts'),
    api('/admin/vendors'),
    api('/admin/commission-receivables'),
    api('/admin/settlements'),
    api('/admin/commission-cycle/status').catch(() => null),
    api('/admin/settings').catch(() => null),
  ]);
  vendors.sort((a, b) => String(a.name).localeCompare(String(b.name)));
  let html = '<div class="form-card"><h3>' + esc(t('payout_record_h')) + '</h3><div id="payout-err"></div>' +
    '<label class="field">' + esc(t('tbl_vendor')) + '</label><select id="payout-vendor" onchange="payoutVendorPick()">' +
    vendors.map(v => '<option value="' + v.id + '">' + esc(v.name) + '</option>').join('') + '</select>' +
    '<div class="row2"><div><label class="field">' + esc(t('payout_amount')) + '</label>' +
    '<input type="number" id="payout-amount" step="0.01" min="0.01" placeholder="0.00"></div>' +
    '<div><label class="field">' + esc(t('tbl_note')) + '</label>' +
    '<input type="text" id="payout-note" maxlength="255" placeholder="' + esc(t('payout_note_ph')) + '"></div></div>' +
    '<div class="mt"><button class="btn" onclick="recordPayout()">' + esc(t('payout_record_btn')) + '</button></div></div>';
  // === v40: per-vendor money summary (completed orders only) + prefill ===
  html += '<h3 class="section-title">' + esc(t('an_vendor_balances')) + '</h3>';
  html += '<div class="table-wrap"><table class="menu-table"><thead><tr><th>' + esc(t('tbl_vendor')) + '</th><th>' +
    esc(t('an_gross')) + '</th><th>' + esc(t('an_commission')) + '</th><th>' + esc(t('an_paid')) + '</th><th>' +
    esc(t('an_owed')) + '</th><th></th></tr></thead><tbody>' +
    vendors.map(v => {
      const owed = Number(v.owed || 0);
      const directOut = Number(v.direct_commission_outstanding || 0);
      return '<tr><td><b>' + esc(v.name) + '</b><br><small>' + esc(t('an_rate', { n: v.commission_rate })) + '</small></td>' +
        '<td>' + money(v.gross || 0) + '</td><td>' + money(v.commission || 0) + '</td>' +
        '<td>' + money(v.paid || 0) + '</td><td><strong>' + money(owed) + '</strong>' +
        (directOut > 0 ? '<br><small>' + esc(t('an_incl_direct', { amount: money(directOut) })) + '</small>' : '') + '</td>' +
        '<td>' + (owed > 0
          ? '<button class="btn small" onclick="payoutPrefill(' + v.id + ',' + owed.toFixed(2) + ')">' +
            esc(t('payout_prefill_btn')) + '</button>'
          : owed < 0
            ? '<span class="vendor-tag">' + esc(t('an_vendor_owes')) + '</span>'
            : '<span class="vendor-tag">' + esc(t('an_settled')) + '</span>') + '</td></tr>';
    }).join('') + '</tbody></table></div>';
  // === END v40 ===
  // === v48: weekly commission cycle panel (reminders -> auto-pause) ===
  if (cycleStatus) {
    const pausedByVendor = {};
    (cycleStatus.vendors || []).forEach(v => { pausedByVendor[v.vendor_id] = !!v.direct_pay_paused; });
    S.cyclePausedByVendor = pausedByVendor;
    const dayKeys = ['slot_day_mon', 'slot_day_tue', 'slot_day_wed', 'slot_day_thu', 'slot_day_fri', 'slot_day_sat', 'slot_day_sun'];
    const curLimit = cycleStatus.pause_limit != null ? cycleStatus.pause_limit : (siteSettings ? Number(siteSettings.commission_pause_limit || 0) : 0);
    const curDay = cycleStatus.statement_weekday != null ? cycleStatus.statement_weekday : 0;
    const lr = cycleStatus.last_run;
    html += '<h3 class="section-title">🔁 ' + esc(t('cyc_h')) + '</h3>' +
      '<p class="hint">' + esc(t('cyc_hint')) + '</p>' +
      '<div class="form-card"><div id="cycle-err"></div>' +
      '<div class="row2"><div><label class="field">' + esc(t('cyc_limit')) + '</label>' +
      '<input type="number" id="cyc-limit" min="0" step="0.01" placeholder="' + esc(t('cyc_limit_ph')) + '" value="' + (curLimit ? esc(curLimit) : '') + '"></div>' +
      '<div><label class="field">' + esc(t('cyc_weekday')) + '</label><select id="cyc-weekday">' +
      dayKeys.map((k, i) => '<option value="' + i + '"' + (i === curDay ? ' selected' : '') + '>' + esc(t(k)) + '</option>').join('') +
      '</select></div></div>' +
      '<div class="mt"><button class="btn" onclick="cycleSaveSettings()">' + esc(t('cyc_save')) + '</button> ' +
      '<button class="btn secondary" onclick="cycleRunNow()">' + esc(t('cyc_run_now')) + '</button></div>' +
      '<p class="hint" style="margin-top:.5rem">' +
      (lr
        ? esc(t('cyc_last_run', {
            when: fmtDate(lr.ran_at), week: lr.week_key || '',
            created: lr.statements_created || 0,
            reminded: (lr.reminded || []).length,
            paused: (lr.paused || []).length,
            unpaused: (lr.unpaused || []).length,
          }))
        : esc(t('cyc_never_run'))) +
      '</p></div>';
  }
  // === END v48 ===
  // Weekly commission collection is a receivable, not a vendor payout.
  html += '<h3 class="section-title">' + esc(t('comm_weekly_h')) + '</h3>' +
    '<p class="hint">' + esc(t('comm_admin_hint')) + '</p>' +
    '<div class="form-card"><div id="commission-err"></div>' +
    '<label class="field">Vendor</label><select id="commission-vendor">' +
    vendors.map(v => '<option value="' + v.id + '">' + esc(v.name) + '</option>').join('') + '</select>' +
    '<div class="row2"><div><label class="field">Amount collected ($)</label><input type="number" id="commission-amount" min="0.01" step="0.01" placeholder="0.00"></div>' +
    '<div><label class="field">Collection method</label><select id="commission-method"><option value="cash">Cash</option><option value="zelle">Zelle</option><option value="venmo">Venmo</option><option value="bank_transfer">Bank transfer</option><option value="other">Other</option></select></div></div>' +
    '<label class="field">Reference / note</label><input type="text" id="commission-note" maxlength="2000" placeholder="Weekly settlement date, receipt number, or note">' +
    '<div class="mt"><button class="btn" onclick="recordCommissionCollection()">Record commission collection</button></div></div>';
  html += '<div class="table-wrap"><table class="menu-table"><thead><tr><th>' + esc(t('tbl_vendor')) + '</th><th>' + esc(t('comm_direct_orders')) + '</th><th>' + esc(t('comm_direct_sales')) + '</th><th>' + esc(t('comm_accrued')) + '</th><th>' + esc(t('comm_collected')) + '</th><th>' + esc(t('comm_outstanding')) + '</th><th></th></tr></thead><tbody>' +
    receivables.map(r => {
      const isPaused = !!((S.cyclePausedByVendor || {})[r.vendor_id]);
      return '<tr><td><b>' + esc(r.vendor_name) + '</b>' +
      (isPaused ? '<br><span class="vendor-tag">' + esc(t('cyc_paused_tag')) + '</span>' : '') +
      '</td><td>' + esc(r.direct_order_count) +
      '</td><td>' + money(r.direct_sales) + '</td><td>' + money(r.commission_due) + '</td><td>' +
      money(r.commission_collected) + '</td><td><strong>' + money(r.outstanding_commission) + '</strong></td><td>' +
      (r.outstanding_commission > 0 ? '<button class="btn small" onclick="commissionPrefill(' + r.vendor_id + ',' + Number(r.outstanding_commission).toFixed(2) + ')">Collect</button>' : '<span class="vendor-tag">Settled</span>') +
      ' <button class="btn small secondary" onclick="cycleSetPause(' + r.vendor_id + ',' + (isPaused ? 'false' : 'true') + ')">' +
      esc(t(isPaused ? 'cyc_resume_btn' : 'cyc_pause_btn')) + '</button>' +
      '</td></tr>';
    }).join('') + '</tbody></table></div>';
  const commissionOrders = receivables.flatMap(r => (r.orders || []).map(o => ({
    vendor_name: r.vendor_name, order_id: o.order_id, created_at: o.created_at,
    payment_method: o.payment_method,
    total: o.total, commission_due: o.commission_due, refunded_amount: o.refunded_amount,
  })));
  html += '<h3 class="section-title">' + esc(t('comm_detail_h')) + '</h3>';
  html += commissionOrders.length
    ? '<div class="table-wrap"><table class="menu-table"><thead><tr><th>Order</th><th>Vendor</th><th>Completed</th><th>' + esc(t('comm_method')) + '</th><th>Order total</th><th>Refunded</th><th>Commission due</th></tr></thead><tbody>' +
      commissionOrders.map(o => '<tr><td>#' + esc(o.order_id) + '</td><td>' + esc(o.vendor_name) +
        '</td><td>' + esc(fmtDate(o.created_at)) + '</td><td>' + esc(o.payment_method || '—') +
        '</td><td>' + money(o.total) +
        '</td><td>' + money(o.refunded_amount) + '</td><td><strong>' + money(o.commission_due) +
        '</strong></td></tr>').join('') + '</tbody></table></div>'
    : '<div class="empty">' + esc(t('comm_detail_none')) + '</div>';
  const commissionHistory = settlements.filter(s => s.source === 'commission_collection');
  html += '<h3 class="section-title">' + esc(t('comm_history_h')) + '</h3>';
  html += commissionHistory.length
    ? '<div class="table-wrap"><table class="menu-table"><thead><tr><th>Date</th><th>Vendor</th><th>Amount</th><th>Method</th><th>Reference / note</th></tr></thead><tbody>' +
      commissionHistory.map(s => '<tr><td>' + esc(fmtDate(s.created_at)) + '</td><td>' + esc(s.vendor_name) +
        '</td><td><strong>' + money(s.amount) + '</strong></td><td>' + esc(s.method) +
        '</td><td>' + esc(s.note || '—') + '</td></tr>').join('') + '</tbody></table></div>'
    : '<div class="empty">' + esc(t('comm_history_none')) + '</div>';
  html += '<h3 class="section-title">' + esc(t('payout_history_h')) + '</h3>';
  html += payouts.length
    ? '<div class="table-wrap"><table class="menu-table"><thead><tr><th>' + esc(t('tbl_id')) + '</th><th>' + esc(t('tbl_date')) +
      '</th><th>' + esc(t('tbl_vendor')) + '</th><th>' + esc(t('tbl_amount')) + '</th><th>' + esc(t('tbl_note')) + '</th></tr></thead><tbody>' +
      payouts.map(p => '<tr><td>#' + p.id + '</td><td>' + esc(fmtDate(p.created_at)) + '</td><td>' +
        esc(p.vendor_name) + '</td><td><strong>' + money(p.amount) + '</strong></td><td>' +
        esc(p.note || t('tbl_never')) + '</td></tr>').join('') + '</tbody></table></div>'
    : '<div class="empty">' + esc(t('payout_none')) + '</div>';
  $('#adm-body').innerHTML = html;
}
// === v48: weekly commission cycle — settings save, manual run, and the
// per-vendor direct-pay pause / resume override buttons. ===
window.cycleSaveSettings = async function () {
  const raw = ($('#cyc-limit').value || '').trim();
  const limit = raw === '' ? 0 : Math.max(0, Number(raw) || 0);
  const weekday = parseInt($('#cyc-weekday').value, 10);
  try {
    await api('/admin/settings', {
      method: 'PUT',
      body: JSON.stringify({
        commission_pause_limit: limit,
        commission_statement_weekday: isNaN(weekday) ? 0 : weekday,
      }),
    });
    toast(t('cyc_saved'));
    admPayouts();
  } catch (e) { errInto($('#cycle-err'), e); }
};

window.cycleRunNow = async function () {
  try {
    await api('/admin/commission-cycle/run', { method: 'POST' });
    toast(t('cyc_ran'));
    admPayouts();
  } catch (e) { errInto($('#cycle-err'), e); }
};

window.cycleSetPause = async function (vendorId, paused) {
  try {
    await api('/admin/vendors/' + vendorId + '/direct-pay-pause', {
      method: 'POST',
      body: JSON.stringify({ paused: !!paused }),
    });
    admPayouts();
  } catch (e) { alert(e.message); }
};
// === END v48 ===

window.commissionPrefill = function (vendorId, outstanding) {
  const sel = $('#commission-vendor'), amount = $('#commission-amount');
  if (!sel || !amount) return;
  sel.value = String(vendorId);
  amount.value = Number(outstanding).toFixed(2);
  amount.focus();
  amount.scrollIntoView({ behavior: 'smooth', block: 'center' });
};
window.recordCommissionCollection = async function () {
  const errEl = $('#commission-err');
  errEl.innerHTML = '';
  const vendorId = Number($('#commission-vendor').value);
  const amount = Number($('#commission-amount').value);
  const method = $('#commission-method').value;
  const note = $('#commission-note').value.trim();
  if (!vendorId) { errEl.innerHTML = '<div class="error">Select a vendor.</div>'; return; }
  if (!Number.isFinite(amount) || amount <= 0) {
    errEl.innerHTML = '<div class="error">Enter a collection amount greater than zero.</div>';
    $('#commission-amount').focus();
    return;
  }
  if (!confirm('Record ' + money(amount) + ' commission collected from this vendor?')) return;
  try {
    await api('/admin/settlements', {
      method: 'POST',
      body: JSON.stringify({
        vendor_id: vendorId,
        source: 'commission_collection',
        amount,
        method,
        note: note || null,
      }),
    });
    await admPayouts();
  } catch (e) {
    errEl.innerHTML = '<div class="error">' + esc(errText(e)) + '</div>';
  }
};

window.payoutVendorPick = function () {
  // Clear a stale prefill when the admin picks a different vendor manually.
  const amt = $('#payout-amount');
  if (amt && amt.dataset.prefilled) { amt.value = ''; delete amt.dataset.prefilled; }
};
window.payoutPrefill = function (vendorId, owed) {
  const sel = $('#payout-vendor'), amt = $('#payout-amount'), note = $('#payout-note');
  if (!sel || !amt) return;
  sel.value = String(vendorId);
  amt.value = owed.toFixed(2);
  amt.dataset.prefilled = '1';
  if (note && !note.value.trim()) note.value = t('payout_note_ph');
  amt.focus();
  amt.scrollIntoView({ behavior: 'smooth', block: 'center' });
};
window.recordPayout = async function () {
  const errEl = $('#payout-err');
  errEl.innerHTML = '';
  const vendorId = Number($('#payout-vendor').value);
  const amount = Number($('#payout-amount').value);
  const note = $('#payout-note').value.trim();
  if (!vendorId) { errEl.innerHTML = '<div class="error">' + esc(t('payout_need_vendor')) + '</div>'; return; }
  if (!isFinite(amount) || amount <= 0) {
    errEl.innerHTML = '<div class="error">' + esc(t('payout_bad_amount')) + '</div>';
    $('#payout-amount').focus();
    return;
  }
  try {
    await api('/admin/payouts', {
      method: 'POST',
      body: JSON.stringify({ vendor_id: vendorId, amount, note: note || null }),
    });
    await admPayouts(); // refresh the table so the new payout shows up
  } catch (e) { errEl.innerHTML = '<div class="error">' + esc(errText(e)) + '</div>'; }
};

/* ---------- admin: loyalty points ---------- */
async function admLoyalty() {
  const [stats, settings] = await Promise.all([
    api('/admin/loyalty/stats'),
    api('/admin/loyalty/settings'),
  ]);
  const cards = [
    [stats.total_earned || 0, t('loy_stat_earned')],
    [stats.total_redeemed || 0, t('loy_stat_redeemed')],
    [stats.total_outstanding || 0, t('loy_stat_outstanding')],
  ];
  let html = '<h3 class="section-title">' + esc(t('adm_tab_loyalty')) + '</h3><div class="stat-grid">' +
    cards.map(c => '<div class="stat-card"><div class="num">' + c[0] + '</div><div class="lbl">' + esc(c[1]) + '</div></div>').join('') +
    '</div>';
  html += '<div class="form-card"><h3>' + esc(t('loy_rates_h')) + '</h3><div id="loy-rates-msg"></div>' +
    '<div class="row2"><div><label class="field">' + esc(t('loy_rate_earn')) + '</label>' +
    '<input type="number" id="loy-earn" min="0" step="1" value="' + esc(settings.points_per_dollar) + '"></div>' +
    '<div><label class="field">' + esc(t('loy_rate_redeem')) + '</label>' +
    '<input type="number" id="loy-redeem" min="1" step="1" value="' + esc(settings.points_per_dollar_redeem) + '"></div></div>' +
    '<div class="mt"><button class="btn" onclick="saveLoyRates()">' + esc(t('save_changes')) + '</button></div></div>';
  html += '<div class="form-card"><h3>' + esc(t('loy_adjust_h')) + '</h3><div id="loy-adj-msg"></div>' +
    '<label class="field">' + esc(t('loy_user')) + '</label><input type="text" id="loy-user" maxlength="160" placeholder="' + esc(t('loy_user_ph')) + '">' +
    '<div class="row2"><div><label class="field">' + esc(t('loy_delta')) + '</label>' +
    '<input type="number" id="loy-delta" step="1" placeholder="e.g. 50 or -50"></div>' +
    '<div><label class="field">' + esc(t('loy_note')) + '</label><input type="text" id="loy-note" maxlength="255"></div></div>' +
    '<div class="mt"><button class="btn" onclick="loyaltyAdjust()">' + esc(t('loy_adjust_btn')) + '</button></div></div>';
  $('#adm-body').innerHTML = html;
}
window.saveLoyRates = async function () {
  const msg = $('#loy-rates-msg');
  msg.innerHTML = '';
  const earn = Number($('#loy-earn').value), redeem = Number($('#loy-redeem').value);
  if (!(isFinite(earn) && earn >= 0) || !(isFinite(redeem) && redeem > 0)) {
    msg.innerHTML = '<div class="error">' + esc(t('loy_bad_rates')) + '</div>';
    return;
  }
  try {
    await api('/admin/loyalty/settings', {
      method: 'PUT',
      body: JSON.stringify({ points_per_dollar: earn, points_per_dollar_redeem: redeem }),
    });
    msg.innerHTML = '<div class="success">' + esc(t('loy_saved')) + '</div>';
  } catch (e) { msg.innerHTML = '<div class="error">' + esc(errText(e)) + '</div>'; }
};
window.loyaltyAdjust = async function () {
  const msg = $('#loy-adj-msg');
  msg.innerHTML = '';
  const who = $('#loy-user').value.trim();
  const delta = Number($('#loy-delta').value);
  const note = $('#loy-note').value.trim();
  if (!who || !isFinite(delta) || delta === 0 || !note) {
    msg.innerHTML = '<div class="error">' + esc(t('loy_need')) + '</div>';
    return;
  }
  try {
    let userId = Number(who);
    if (!/^\d+$/.test(who)) {
      // Email → resolve to a user id via the admin customers list.
      const cs = await api('/admin/customers');
      const c = cs.find(x => String(x.email || '').toLowerCase() === who.toLowerCase());
      if (!c) { msg.innerHTML = '<div class="error">' + esc(t('loy_user_notfound')) + '</div>'; return; }
      userId = c.id;
    }
    await api('/admin/loyalty/adjust', {
      method: 'POST',
      body: JSON.stringify({ user_id: userId, delta: delta, note: note }),
    });
    msg.innerHTML = '<div class="success">' + esc(t('loy_adjusted')) + '</div>';
    $('#loy-user').value = ''; $('#loy-delta').value = ''; $('#loy-note').value = '';
  } catch (e) { msg.innerHTML = '<div class="error">' + esc(errText(e)) + '</div>'; }
};

/* ---------- admin: catering requests inbox ---------- */
const CAT_STATUSES = ['new', 'contacted', 'closed'];
const CAT_TYPES = ['birthday', 'wedding', 'corporate', 'other'];
function catTypeLabel(x) { return t('cat_type_' + x); }

async function admCatering() {
  const q = S.catStatus || '';
  let url = '/admin/catering';
  if (q) url += '?status=' + encodeURIComponent(q);
  const reqs = await api(url);
  let html = '<h3 class="section-title">' + esc(t('adm_tab_catering')) + '</h3>' +
    '<div class="adm-toolbar"><label>' + esc(t('adm_filter_status')) + ' <select onchange="S.catStatus=this.value;vAdmin()">' +
    '<option value="">' + esc(t('adm_all')) + '</option>' +
    CAT_STATUSES.map(s => '<option value="' + s + '"' + (q === s ? ' selected' : '') + '>' +
      esc(t('cat_st_' + s)) + '</option>').join('') +
    '</select></label></div>';
  html += reqs.length
    ? '<div class="table-wrap"><table class="menu-table"><thead><tr><th>' + esc(t('tbl_id')) + '</th><th>' +
      esc(t('tbl_date')) + '</th><th>' + esc(t('cat_tbl_type')) + '</th><th>' + esc(t('cat_tbl_event_date')) + '</th><th>' +
      esc(t('cat_tbl_contact')) + '</th><th>' + esc(t('tbl_phone')) + '</th><th>' + esc(t('tbl_status')) + '</th></tr></thead><tbody>' +
      reqs.map(r => '<tr style="cursor:pointer" onclick="admCateringDetail(' + r.id + ')"><td>#' + r.id + '</td><td>' +
        esc(fmtDate(r.created_at)) + '</td><td>' + esc(catTypeLabel(r.event_type)) + '</td><td>' +
        esc(r.event_date || '—') + '</td><td>' + esc(r.contact_name || '') + '</td><td>' +
        esc(r.phone || '') + '</td><td>' + esc(t('cat_st_' + (r.status || 'new'))) + '</td></tr>').join('') +
      '</tbody></table></div>'
    : '<div class="empty">' + esc(t('cat_none')) + '</div>';
  $('#adm-body').innerHTML = html;
}
window.admCateringDetail = async function (id) {
  try {
    const r = await api('/admin/catering/' + id);
    const rows = [
      [t('cat_f_type'), catTypeLabel(r.event_type)],
      [t('cat_f_date'), r.event_date || '—'],
      [t('cat_f_location'), r.location || '—'],
      [t('cat_f_name'), r.contact_name || '—'],
      [t('tbl_phone'), r.phone || '—'],
      [t('cat_f_email'), r.email || '—'],
      [t('cat_f_food'), r.food_type || '—'],
      [t('cat_f_guests'), r.guest_count != null ? r.guest_count : '—'],
      [t('tbl_date'), fmtDate(r.created_at)],
    ];
    let html = '<button class="btn small secondary" onclick="vAdmin()">← ' + esc(t('cat_back')) + '</button>' +
      '<h3 class="section-title">' + esc(t('cat_detail_h')) + ' #' + r.id +
      ' <span class="status-pill status-' + esc(r.status || 'new') + '">' + esc(t('cat_st_' + (r.status || 'new'))) + '</span></h3>' +
      '<div class="form-card">' +
      rows.map(x => '<p><strong>' + esc(x[0]) + ':</strong> ' + esc(String(x[1])) + '</p>').join('') +
      (r.notes ? '<p><strong>' + esc(t('cat_f_notes')) + ':</strong><br><span style="white-space:pre-wrap">' + esc(r.notes) + '</span></p>' : '') +
      '<label class="field">' + esc(t('cat_admin_notes')) + '</label>' +
      '<textarea id="cat-notes" rows="3" maxlength="2000">' + esc(r.admin_notes || '') + '</textarea>' +
      '<label class="field">' + esc(t('tbl_status')) + '</label><select id="cat-status">' +
      CAT_STATUSES.map(s => '<option value="' + s + '"' + (r.status === s ? ' selected' : '') + '>' +
        esc(t('cat_st_' + s)) + '</option>').join('') + '</select>' +
      '<div class="mt"><button class="btn" onclick="saveCatering(' + r.id + ')">' + esc(t('save_changes')) + '</button></div>' +
      '<div id="cat-save-msg"></div></div>';
    $('#adm-body').innerHTML = html;
  } catch (e) {
    $('#adm-body').innerHTML = '<div class="error">' + esc(errText(e)) + '</div>';
  }
};
window.saveCatering = async function (id) {
  try {
    await api('/admin/catering/' + id, {
      method: 'PATCH',
      body: JSON.stringify({ status: $('#cat-status').value, admin_notes: $('#cat-notes').value.trim() || null }),
    });
    await admCateringDetail(id); // reload the detail view on the saved state
    const m = $('#cat-save-msg');
    if (m) m.innerHTML = '<div class="success">' + esc(t('cat_saved')) + '</div>';
  } catch (e) { alert(errText(e)); }
};

/* ---------- admin: promo codes ---------- */
/* === F6 (Oct 2026): report-a-problem — admin back-office ===
   Every customer problem report with a status changer
   (new → in_review → resolved). Status changes are audit-logged server-side. */
async function admProblems() {
  const st = S.admProbStatus || '';
  const list = await api('/admin/problem-reports' + (st ? '?status=' + encodeURIComponent(st) : ''));
  let html = '<h3 class="section-title">' + esc(t('adm_tab_problems')) + '</h3>';
  html += '<div class="order-filters"><select id="adm-prob-status" onchange="setAdmProbStatus()">' +
    '<option value="">' + esc(t('prob_status_all')) + '</option>' +
    ['new', 'in_review', 'resolved'].map(function (s) {
      return '<option value="' + s + '"' + (st === s ? ' selected' : '') + '>' +
        esc(t('prob_st_' + s)) + '</option>';
    }).join('') + '</select></div>';
  html += list.length
    ? '<div class="grid">' + list.map(admProbCard).join('') + '</div>'
    : '<div class="empty">' + esc(t('prob_empty')) + '</div>';
  $('#adm-body').innerHTML = html;
}
window.setAdmProbStatus = function () {
  const sel = $('#adm-prob-status');
  S.admProbStatus = sel ? sel.value : '';
  admProblems();
};
function admProbCard(p) {
  return '<div class="vendor-card"><div class="order-head"><strong>' + esc(t('prob_order', { id: p.order_id })) + '</strong> ' +
    '<span class="vendor-tag">🏪 ' + esc(p.vendor_name || '') + '</span> ' +
    '<span class="vendor-tag">👤 ' + esc(p.customer_name || '') + '</span></div>' +
    (p.dish_name ? '<div class="vendor-tag">🍽️ ' + esc(p.dish_name) + '</div>' : '') +
    '<div class="vendor-tag">🏷️ ' + esc(t('prob_cat_' + p.category)) + ' · <small>' + esc(fmtDate(p.created_at)) + '</small></div>' +
    '<p>' + esc(p.description) + '</p>' +
    (p.photo_url ? '<img src="' + esc(p.photo_url) + '" class="prob-photo" alt="">' : '') +
    (p.desired_outcome ? '<div class="vendor-tag">🎯 ' + esc(t('prob_outcome', { x: p.desired_outcome })) + '</div>' : '') +
    '<label class="field">' + esc(t('prob_st_set')) + ' <select onchange="setAdmProbReportStatus(' + p.id + ', this.value)">' +
    ['new', 'in_review', 'resolved'].map(function (s) {
      return '<option value="' + s + '"' + (p.status === s ? ' selected' : '') + '>' +
        esc(t('prob_st_' + s)) + '</option>';
    }).join('') + '</select></label></div>';
}
window.setAdmProbReportStatus = async function (id, status) {
  try {
    await api('/admin/problem-reports/' + id, { method: 'PATCH', body: JSON.stringify({ status: status }) });
    admProblems();
  } catch (e) { alert(errText(e)); }
};
/* === END F6 === */

async function admPromos() {
  const promos = await api('/admin/promo-codes');
  let html = '<h3 class="section-title">' + esc(t('adm_tab_promos')) + '</h3>' +
    '<div class="form-card"><h3>' + esc(t('adm_promo_new')) + '</h3><div id="promo-msg"></div>' +
    '<input type="hidden" id="promo-id" value="">' +
    '<div class="row2"><div><label class="field">' + esc(t('adm_promo_code')) + '</label>' +
    '<input type="text" id="promo-code" maxlength="40" placeholder="SAVE10"></div>' +
    '<div><label class="field">' + esc(t('adm_promo_percent')) + '</label>' +
    '<input type="number" id="promo-percent" min="1" max="100" step="1"></div></div>' +
    '<div class="row2"><div><label class="field">' + esc(t('adm_promo_max')) + '</label>' +
    '<input type="number" id="promo-max" min="1" step="1" placeholder="' + esc(t('adm_promo_max_ph')) + '"></div>' +
    '<div><label class="field">' + esc(t('adm_promo_expires')) + '</label>' +
    '<input type="datetime-local" id="promo-expires"></div></div>' +
    '<div><label><input type="checkbox" id="promo-active" checked> ' + esc(t('adm_promo_active')) + '</label></div>' +
    '<div class="mt"><button class="btn" onclick="savePromo()">' + esc(t('save_changes')) + '</button> ' +
    '<button class="btn secondary" onclick="resetPromoForm()">' + esc(t('cancel')) + '</button></div></div>';
  html += promos.length
    ? '<div class="table-wrap"><table class="menu-table"><thead><tr><th>' + esc(t('adm_promo_code')) + '</th><th>' +
      esc(t('adm_promo_percent')) + '</th><th>' + esc(t('adm_promo_uses')) + '</th><th>' + esc(t('adm_promo_expires')) +
      '</th><th>' + esc(t('adm_promo_active')) + '</th><th></th></tr></thead><tbody>' +
      promos.map(p => '<tr><td><b>' + esc(p.code) + '</b></td><td>' + esc(p.percent_off) + '%</td>' +
        '<td>' + esc(p.uses_count || 0) + (p.max_uses ? ' / ' + esc(p.max_uses) : '') + '</td>' +
        '<td>' + (p.expires_at ? esc(fmtDate(p.expires_at)) : '—') + '</td>' +
        '<td>' + (p.active ? '✅' : '—') + '</td>' +
        '<td style="white-space:nowrap"><button class="btn small" onclick="editPromo(' + p.id + ')">' + esc(t('edit')) + '</button> ' +
        '<button class="btn small danger" onclick="deletePromo(' + p.id + ')">' + esc(t('delete')) + '</button></td></tr>').join('') +
      '</tbody></table></div>'
    : '<div class="empty">' + esc(t('adm_promo_none')) + '</div>';
  $('#adm-body').innerHTML = html;
}
window.resetPromoForm = function () {
  ['promo-id', 'promo-code', 'promo-percent', 'promo-max', 'promo-expires'].forEach(id => { const el = $('#' + id); if (el) el.value = ''; });
  const act = $('#promo-active'); if (act) act.checked = true;
};
window.editPromo = async function (id) {
  const promos = await api('/admin/promo-codes');
  const p = promos.find(x => x.id === id);
  if (!p) return;
  $('#promo-id').value = p.id;
  $('#promo-code').value = p.code;
  $('#promo-percent').value = p.percent_off;
  $('#promo-max').value = p.max_uses != null ? p.max_uses : '';
  $('#promo-expires').value = p.expires_at ? String(p.expires_at).slice(0, 16) : '';
  $('#promo-active').checked = !!p.active;
  window.scrollTo(0, 0);
};
window.savePromo = async function () {
  const msg = $('#promo-msg');
  msg.innerHTML = '';
  const code = $('#promo-code').value.trim();
  const percent = parseInt($('#promo-percent').value, 10);
  if (!code || isNaN(percent) || percent < 1 || percent > 100) {
    msg.innerHTML = '<div class="error">' + esc(t('adm_promo_bad')) + '</div>';
    return;
  }
  const maxRaw = $('#promo-max').value.trim();
  const expRaw = $('#promo-expires').value;
  const body = {
    code,
    percent_off: percent,
    max_uses: maxRaw === '' ? null : parseInt(maxRaw, 10),
    expires_at: expRaw === '' ? null : new Date(expRaw).toISOString(),
    active: $('#promo-active').checked,
  };
  try {
    const id = $('#promo-id').value;
    if (id) await api('/admin/promo-codes/' + id, { method: 'PATCH', body: JSON.stringify(body) });
    else await api('/admin/promo-codes', { method: 'POST', body: JSON.stringify(body) });
    vAdmin();
  } catch (e) { msg.innerHTML = '<div class="error">' + esc(errText(e)) + '</div>'; }
};
window.deletePromo = async function (id) {
  if (!confirm(t('adm_promo_confirm_del'))) return;
  try { await api('/admin/promo-codes/' + id, { method: 'DELETE' }); vAdmin(); }
  catch (e) { alert(errText(e)); }
};

/* ---------- admin: dish moderation ---------- */
async function admDishes() {
  const vendors = await api('/admin/vendors');
  vendors.sort((a, b) => String(a.name).localeCompare(String(b.name)));
  const qv = S.admDishVendor || '';
  let url = '/admin/dishes';
  if (qv) url += '?vendor_id=' + encodeURIComponent(qv);
  const dishes = await api(url);
  const vById = {};
  vendors.forEach(v => { vById[v.id] = v.name; });
  let html = '<h3 class="section-title">' + esc(t('adm_tab_dishes')) + '</h3>' +
    '<div class="adm-toolbar"><label>' + esc(t('adm_filter_vendor')) + ' <select onchange="S.admDishVendor=this.value;vAdmin()">' +
    '<option value="">' + esc(t('adm_all')) + '</option>' +
    vendors.map(v => '<option value="' + v.id + '"' + (String(qv) === String(v.id) ? ' selected' : '') + '>' + esc(v.name) + '</option>').join('') +
    '</select></label></div>';
  html += dishes.length
    ? '<div class="table-wrap"><table class="menu-table"><thead><tr><th>' + esc(t('th_dish')) + '</th><th>' +
      esc(t('tbl_vendor')) + '</th><th>' + esc(t('th_price')) + '</th><th>' + esc(t('th_stock')) +
      '</th><th>' + esc(t('adm_dish_status')) + '</th><th></th></tr></thead><tbody>' +
      dishes.map(d => '<tr><td><strong>' + esc(dname(d)) + '</strong><br><small style="color:var(--muted)">' + esc(catLabel(d.category)) + '</small></td>' +
        '<td>' + esc(vById[d.vendor_id] || '') + '</td><td>' + money(d.price) + '</td>' +
        '<td>' + (d.stock_quantity == null ? '—' : esc(d.stock_quantity)) + '</td>' +
        '<td>' + (d.is_hidden ? '🙈 ' + esc(t('adm_dish_hidden')) : (d.available ? '✅ ' + esc(t('adm_dish_visible')) : '⏸️ ' + esc(t('adm_dish_unavailable')))) + '</td>' +
        '<td style="white-space:nowrap"><button class="btn small" onclick="admDishHide(' + d.id + ',' + (!!d.is_hidden) + ')">' +
        esc(d.is_hidden ? t('adm_dish_unhide') : t('adm_dish_hide')) + '</button> ' +
        '<button class="btn small danger" onclick="admDishDelete(' + d.id + ')">' + esc(t('delete')) + '</button></td></tr>').join('') +
      '</tbody></table></div>'
    : '<div class="empty">' + esc(t('adm_dish_none')) + '</div>';
  $('#adm-body').innerHTML = html;
}
window.admDishHide = async function (id, currentlyHidden) {
  try {
    await api('/admin/dishes/' + id, { method: 'PATCH', body: JSON.stringify({ is_hidden: !currentlyHidden }) });
    vAdmin();
  } catch (e) { alert(errText(e)); }
};
window.admDishDelete = async function (id) {
  if (!confirm(t('adm_dish_confirm_del'))) return;
  try { await api('/admin/dishes/' + id, { method: 'DELETE' }); vAdmin(); }
  catch (e) { alert(errText(e)); }
};

/* ---------- admin: review moderation ---------- */
async function admReviewsTab() {
  const reviews = await api('/admin/reviews?limit=100');
  let html = '<h3 class="section-title">' + esc(t('adm_tab_reviews')) + '</h3>';
  const statusBadge = s => {
    const cls = s === 'pending' ? 'vendor-tag' : (s === 'approved' ? 'status-paid' : 'status-cancelled');
    return '<span class="' + cls + '">' + esc(t('rev_status_' + s)) + '</span>';
  };
  html += reviews.length
    ? '<div class="table-wrap"><table class="menu-table"><thead><tr><th>' + esc(t('th_dish')) + '</th><th>' +
      esc(t('tbl_customer')) + '</th><th>' + esc(t('adm_review_rating')) + '</th><th>' + esc(t('adm_review_text')) +
      '</th><th>' + esc(t('adm_review_status')) + '</th><th>' + esc(t('tbl_date')) + '</th><th></th></tr></thead><tbody>' +
      reviews.map(r => '<tr><td>' + esc(r.dish_name || '') + '</td><td>' + esc(r.author_name || '') + '</td>' +
        '<td>' + '★'.repeat(Math.max(0, Math.min(5, r.rating || 0))) + '</td>' +
        '<td><small style="white-space:pre-wrap">' + esc(r.text || '') + '</small></td>' +
        '<td>' + statusBadge(r.status || 'pending') + '</td>' +
        '<td>' + esc(fmtDate(r.created_at)) + '</td>' +
        '<td style="white-space:nowrap">' +
          '<button class="btn small" onclick="admReviewStatus(' + r.id + ',\'approved\')">' + esc(t('rev_approve')) + '</button> ' +
          '<button class="btn small" onclick="admReviewStatus(' + r.id + ',\'hidden\')">' + esc(t('rev_hide')) + '</button> ' +
          '<button class="btn small danger" onclick="admReviewDelete(' + r.id + ')">' + esc(t('delete')) + '</button></td></tr>').join('') +
      '</tbody></table></div>'
    : '<div class="empty">' + esc(t('adm_review_none')) + '</div>';
  $('#adm-body').innerHTML = html;
}
window.admReviewStatus = async function (id, status) {
  try { await api('/admin/reviews/' + id, { method: 'PATCH', body: JSON.stringify({ status }) }); vAdmin(); }
  catch (e) { alert(errText(e)); }
};
window.admReviewDelete = async function (id) {
  if (!confirm(t('adm_review_confirm_del'))) return;
  try { await api('/admin/reviews/' + id, { method: 'DELETE' }); vAdmin(); }
  catch (e) { alert(errText(e)); }
};

/* ---------- admin: user management ---------- */
async function admUsers() {
  const q = S.admUserQ || '', role = S.admUserRole || '';
  let url = '/admin/users?limit=200';
  if (role) url += '&role=' + encodeURIComponent(role);
  if (q) url += '&q=' + encodeURIComponent(q);
  const users = await api(url);
  let html = '<h3 class="section-title">' + esc(t('adm_tab_users')) + '</h3>' +
    // === v40+: create staff (or other) accounts ===
    '<div class="form-card"><h3>' + esc(t('adm_user_create_h')) + '</h3><div id="ucreate-err"></div>' +
    '<div class="row2"><div><label class="field">' + esc(t('f_name')) + '</label>' +
    '<input type="text" id="uc-name" maxlength="120"></div>' +
    '<div><label class="field">' + esc(t('email_label')) + '</label>' +
    '<input type="email" id="uc-email" maxlength="255" dir="ltr"></div></div>' +
    '<div class="row2"><div><label class="field">' + esc(t('password_label')) + '</label>' +
    '<input type="password" id="uc-pass" minlength="8" maxlength="128" dir="ltr"></div>' +
    '<div><label class="field">' + esc(t('adm_user_role')) + '</label>' +
    '<select id="uc-role">' +
    ['staff', 'customer', 'vendor', 'admin'].map(r => '<option value="' + r + '">' + esc(t('role_' + r)) + '</option>').join('') +
    '</select></div></div>' +
    '<div class="mt"><button class="btn" onclick="admUserCreate()">' + esc(t('adm_user_create_btn')) + '</button></div></div>' +
    // === END v40+ ===
    '<div class="adm-toolbar"><input type="search" id="adm-user-q" placeholder="' + esc(t('adm_user_search_ph')) + '" value="' + esc(q) + '" oninput="S.admUserQ=this.value">' +
    '<button class="btn small" onclick="vAdmin()">' + esc(t('adm_user_search')) + '</button> ' +
    '<select onchange="S.admUserRole=this.value;vAdmin()"><option value="">' + esc(t('adm_all_roles')) + '</option>' +
    ['customer', 'vendor', 'admin', 'staff'].map(r => '<option value="' + r + '"' + (role === r ? ' selected' : '') + '>' + esc(t('role_' + r)) + '</option>').join('') +
    '</select></div>';
  html += users.length
    ? '<div class="table-wrap"><table class="menu-table"><thead><tr><th>' + esc(t('tbl_customer')) + '</th><th>' +
      esc(t('adm_user_role')) + '</th><th>' + esc(t('adm_user_status')) + '</th><th></th></tr></thead><tbody>' +
      users.map(u => '<tr><td><b>' + esc(u.name) + '</b><br><small>' + esc(u.email) + '</small></td>' +
        '<td><select onchange="admUserRole(' + u.id + ', this.value)">' +
        ['customer', 'vendor', 'admin', 'staff'].map(r => '<option value="' + r + '"' + (u.role === r ? ' selected' : '') + '>' + esc(t('role_' + r)) + '</option>').join('') +
        '</select></td>' +
        '<td>' + (u.is_active ? '✅ ' + esc(t('adm_user_active')) : '🚫 ' + esc(t('adm_user_deactivated'))) + '</td>' +
        '<td><button class="btn small' + (u.is_active ? ' danger' : '') + '" onclick="admUserToggleActive(' + u.id + ',' + (!!u.is_active) + ')">' +
        esc(u.is_active ? t('adm_user_deactivate') : t('adm_user_activate')) + '</button></td></tr>').join('') +
      '</tbody></table></div>'
    : '<div class="empty">' + esc(t('adm_user_none')) + '</div>';
  $('#adm-body').innerHTML = html;
}
window.admUserCreate = async function () {
  const errEl = $('#ucreate-err');
  errEl.innerHTML = '';
  const name = $('#uc-name').value.trim(), email = $('#uc-email').value.trim(),
    password = $('#uc-pass').value, role = $('#uc-role').value;
  if (!name || !email || password.length < 8) {
    errEl.innerHTML = '<div class="error">' + esc(t('adm_user_create_bad')) + '</div>';
    return;
  }
  try {
    await api('/admin/users', { method: 'POST', body: JSON.stringify({ name, email, password, role }) });
    vAdmin();
  } catch (e) { errEl.innerHTML = '<div class="error">' + esc(errText(e)) + '</div>'; }
};
window.admUserRole = async function (id, role) {
  try { await api('/admin/users/' + id, { method: 'PATCH', body: JSON.stringify({ role }) }); }
  catch (e) { alert(errText(e)); vAdmin(); }
};
window.admUserToggleActive = async function (id, currentlyActive) {
  if (currentlyActive && !confirm(t('adm_user_deactivate_q'))) return;
  try {
    await api('/admin/users/' + id, { method: 'PATCH', body: JSON.stringify({ is_active: !currentlyActive }) });
    vAdmin();
  } catch (e) { alert(errText(e)); }
};

/* ---------- admin: site settings ---------- */
async function admSettings() {
  const s = await api('/admin/settings');
  let html = '<h3 class="section-title">' + esc(t('adm_tab_settings')) + '</h3>' +
    '<div class="form-card"><div id="settings-msg"></div>' +
    '<label class="field">' + esc(t('adm_settings_tax')) + '</label>' +
    '<input type="number" id="set-tax" step="0.001" min="0" max="1" value="' + esc(s.tax_rate) + '">' +
    '<p class="hint">' + esc(t('adm_settings_tax_hint')) + '</p>' +
    '<label class="field">' + esc(t('adm_settings_commission')) + '</label>' +
    '<input type="number" id="set-comm" step="0.1" min="0" max="100" value="' + esc(s.commission_percent) + '">' +
    '<p class="hint">' + esc(t('adm_settings_commission_hint')) + '</p>' +
    '<label class="field">' + esc(t('adm_settings_site')) + '</label>' +
    '<input type="text" id="set-site" maxlength="200" value="' + esc(s.site_name) + '">' +
    '<div class="mt"><button class="btn" onclick="saveAdminSettings()">' + esc(t('save_changes')) + '</button></div></div>';
  // === v40+: admin alert toggles ===
  html += '<div class="form-card"><h3>' + esc(t('adm_alerts_h')) + '</h3><div id="alerts-msg"></div>' +
    '<label class="check"><input type="checkbox" id="set-alert-orders"' + (s.alert_orders ? ' checked' : '') + '> ' +
    esc(t('adm_alert_orders')) + '</label>' +
    '<label class="check"><input type="checkbox" id="set-alert-apps"' + (s.alert_applications ? ' checked' : '') + '> ' +
    esc(t('adm_alert_apps')) + '</label>' +
    '<label class="check"><input type="checkbox" id="set-alert-tickets"' + (s.alert_tickets ? ' checked' : '') + '> ' +
    esc(t('adm_alert_tickets')) + '</label>' +
    '<label class="field">' + esc(t('adm_alert_phone')) + '</label>' +
    '<input type="tel" id="set-alert-phone" maxlength="40" dir="ltr" placeholder="+1…" value="' + esc(s.alert_phone || '') + '">' +
    '<p class="hint">' + esc(t('adm_alert_phone_hint')) + '</p>' +
    '<div class="mt"><button class="btn" onclick="saveAlertSettings()">' + esc(t('save_changes')) + '</button></div></div>';
  // === v40+: one-click CSV exports ===
  html += '<div class="form-card"><h3>' + esc(t('adm_exports_h')) + '</h3>' +
    '<div class="row2"><div><label class="field">' + esc(t('adm_export_from')) + '</label>' +
    '<input type="date" id="exp-from"></div>' +
    '<div><label class="field">' + esc(t('adm_export_to')) + '</label>' +
    '<input type="date" id="exp-to"></div></div>' +
    '<div class="mt btn-row">' +
    '<button class="btn secondary" onclick="downloadExport(\'orders\')">' + esc(t('adm_export_orders')) + '</button> ' +
    '<button class="btn secondary" onclick="downloadExport(\'payouts\')">' + esc(t('adm_export_payouts')) + '</button> ' +
    '<button class="btn secondary" onclick="downloadExport(\'customers\')">' + esc(t('adm_export_customers')) + '</button>' +
    '</div></div>';
  // === v40+: one-tap backup ===
  html += '<div class="form-card"><h3>' + esc(t('adm_backup_h')) + '</h3>' +
    '<p class="hint">' + esc(t('adm_backup_hint')) + '</p>' +
    (s.last_backup_at
      ? '<p>' + esc(t('adm_backup_last', { when: fmtDate(s.last_backup_at) })) + '</p>'
      : '<p>' + esc(t('adm_backup_never')) + '</p>') +
    '<div class="mt"><button class="btn" onclick="downloadBackup()">' + esc(t('adm_backup_btn')) + '</button></div></div>';
  $('#adm-body').innerHTML = html;
}
// === v40+: renamed from saveSettings (the old name collided with the
// vendor shop-settings saver defined earlier in this file — the later
// assignment silently won and broke the vendor form). ===
window.saveAdminSettings = async function () {
  const msg = $('#settings-msg');
  msg.innerHTML = '';
  const tax = parseFloat($('#set-tax').value);
  const comm = parseFloat($('#set-comm').value);
  const site = $('#set-site').value.trim();
  if (isNaN(tax) || tax < 0 || tax > 1 || isNaN(comm) || comm < 0 || comm > 100 || !site) {
    msg.innerHTML = '<div class="error">' + esc(t('adm_settings_bad')) + '</div>';
    return;
  }
  try {
    await api('/admin/settings', {
      method: 'PUT',
      body: JSON.stringify({ tax_rate: tax, commission_percent: comm, site_name: site }),
    });
    msg.innerHTML = '<div class="success">' + esc(t('adm_settings_saved')) + '</div>';
  } catch (e) { msg.innerHTML = '<div class="error">' + esc(errText(e)) + '</div>'; }
};
window.saveAlertSettings = async function () {
  const msg = $('#alerts-msg');
  msg.innerHTML = '';
  try {
    await api('/admin/settings', {
      method: 'PUT',
      body: JSON.stringify({
        alert_orders: $('#set-alert-orders').checked,
        alert_applications: $('#set-alert-apps').checked,
        alert_tickets: $('#set-alert-tickets').checked,
        alert_phone: $('#set-alert-phone').value.trim(),
      }),
    });
    msg.innerHTML = '<div class="success">' + esc(t('adm_settings_saved')) + '</div>';
  } catch (e) { msg.innerHTML = '<div class="error">' + esc(errText(e)) + '</div>'; }
};
window.downloadExport = async function (kind) {
  const from = ($('#exp-from') || {}).value || '';
  const to = ($('#exp-to') || {}).value || '';
  let url = '/api/admin/export/' + kind;
  const q = [];
  if (from) q.push('from=' + encodeURIComponent(from));
  if (to) q.push('to=' + encodeURIComponent(to));
  try {
    // v40 security fix (P1-1): mint a 60-second download-scoped token first.
    // The long-lived session JWT must never appear in a URL (logs/history).
    const tok = await api('/admin/download-token', { method: 'POST' });
    q.push('token=' + encodeURIComponent(tok.token));
    window.open(url + '?' + q.join('&'), '_blank');
  } catch (e) { alert(errText(e)); }
};
window.downloadBackup = async function () {
  try {
    const tok = await api('/admin/download-token', { method: 'POST' });
    window.open('/api/admin/backup?token=' + encodeURIComponent(tok.token), '_blank');
    setTimeout(vAdmin, 2000); // refresh to show the new last-backup time
  } catch (e) { alert(errText(e)); }
};

/* ---------- admin: audit log ---------- */
async function admAuditLog() {
  const action = S.admAuditAction || '';
  const offset = S.admAuditOffset || 0;
  let url = '/admin/audit-log?limit=50&offset=' + offset;
  if (action) url += '&action=' + encodeURIComponent(action);
  const res = await api(url);
  const items = res.items || [];
  let html = '<h3 class="section-title">' + esc(t('adm_tab_audit_log')) + '</h3>' +
    '<div class="adm-toolbar"><label>' + esc(t('adm_audit_filter')) + ' <input type="text" id="adm-audit-action" placeholder="' + esc(t('adm_audit_action_ph')) + '" value="' + esc(action) + '"></label>' +
    '<button class="btn small" onclick="S.admAuditAction=$(\'#adm-audit-action\').value.trim();S.admAuditOffset=0;vAdmin()">' + esc(t('adm_user_search')) + '</button> ' +
    '<button class="btn small secondary" onclick="S.admAuditAction=\'\';S.admAuditOffset=0;vAdmin()">' + esc(t('adm_audit_clear')) + '</button></div>' +
    '<p class="hint">' + esc(t('adm_audit_total', { n: res.total || 0 })) + '</p>';
  html += items.length
    ? '<div class="table-wrap"><table class="menu-table"><thead><tr><th>' + esc(t('tbl_date')) + '</th><th>' +
      esc(t('adm_audit_admin')) + '</th><th>' + esc(t('adm_audit_action')) + '</th><th>' + esc(t('adm_audit_target')) +
      '</th><th>' + esc(t('adm_audit_details')) + '</th></tr></thead><tbody>' +
      items.map(r => '<tr><td>' + esc(fmtDate(r.created_at)) + '</td><td>' + esc(r.admin_name || ('#' + (r.admin_user_id || ''))) + '</td>' +
        '<td>' + esc(r.action) + '</td><td>' + esc((r.target_type || '') + (r.target_id != null ? ' #' + r.target_id : '')) + '</td>' +
        '<td><small>' + esc(JSON.stringify(r.details || {})) + '</small></td></tr>').join('') +
      '</tbody></table></div>'
    : '<div class="empty">' + esc(t('adm_audit_none')) + '</div>';
  if (items.length === 50) {
    html += '<div class="mt"><button class="btn secondary" onclick="S.admAuditOffset=' + (offset + 50) + ';vAdmin()">' + esc(t('adm_audit_more')) + '</button></div>';
  }
  $('#adm-body').innerHTML = html;
}
