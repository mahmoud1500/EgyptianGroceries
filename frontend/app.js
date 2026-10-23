/* Egyptian Home Food Marketplace — plain JS single-page app.
   Views: home, vendor storefront, cart, review, confirmation,
   login, signup, vendor portal, my orders. */
'use strict';

/* ================= constants ================= */
const PAYMENTS = [
  { id: 'zelle',       key: 'pay_zelle',  icon: '⚡' },
  { id: 'venmo',       key: 'pay_venmo',  icon: '💸' },
  { id: 'cash',        key: 'pay_cash',   icon: '💵' },
  { id: 'credit_card', key: 'pay_card',   icon: '💳' },
];
/* v41: is Stripe card payment actually configured? Fetched once per page
   load and cached; the checkout labels the credit-card option honestly
   from this (secure-checkout hint vs. coming-soon wording). */
async function stripeStatus() {
  if (S.stripeStatus === undefined) {
    try {
      const s = await api('/stripe/status');
      S.stripeStatus = !!(s && s.card_payments_enabled);
    } catch (e) { S.stripeStatus = false; } /* degraded: recorded-only flow */
  }
  return S.stripeStatus;
}
/* v41: "💳 Visa •••• 4242" for a card-paid order — brand + last4 from
   Stripe only. Raw card numbers, expiry dates, and CVCs are never stored
   or displayed anywhere in this app. */
function cardPaidHTML(order) {
  const b = String((order && order.card_brand) || '').trim();
  const l = String((order && order.card_last4) || '').trim();
  if (!b && !l) return '';
  const brand = b ? b.charAt(0).toUpperCase() + b.slice(1) : '';
  return ' · <span title="' + esc(t('paid_by_card')) + '">💳 ' +
    esc((brand + (l ? ' •••• ' + l : '')).trim()) + '</span>';
}
function payLabel(id) {
  const p = PAYMENTS.find(x => x.id === id);
  if (p) return t(p.key);
  // Retired methods: keep old orders readable.
  if (id === 'apple_pay') return 'Apple Pay';
  if (id === 'google_pay') return 'Google Pay';
  return id;
}
/* Vendor's payment handle for a manual method (set in the vendor portal
   settings). Returns '' when the vendor hasn't set one. */
function vendorHandle(v, method) {
  if (!v || (method !== 'zelle' && method !== 'venmo')) return '';
  const h = method === 'zelle' ? v.zelle_handle : v.venmo_handle;
  return String(h || '').trim();
}
/* Per-vendor payment hints under the payment options at checkout and on the
   review page: "Send to: @handle", or a hint that the vendor will share it. */
function payHintsHTML(groups, payment) {
  let rows = '';
  if (payment === 'zelle' || payment === 'venmo') {
    const method = payment === 'zelle' ? t('pay_zelle') : t('pay_venmo');
    rows = groups.map(gr => {
      const h = vendorHandle(gr.vendor, payment);
      const name = gr.vendor && gr.vendor.name ? gr.vendor.name : '';
      return '<div class="vendor-tag">⚡ ' + (h
        ? esc(t('pay_send_to', { name, method, handle: h }))
        : esc(t('pay_handle_hint', { name, method }))) + '</div>';
    }).join('');
  }
  // Always render the shell so renderPayHints can replace it in place.
  return '<div id="pay-handles" style="margin-top:.4rem">' + rows + '</div>';
}
function renderPayHints() {
  const el = $('#pay-handles');
  if (el) el.outerHTML = payHintsHTML(S.checkout._groups || [], S.checkout.payment);
}
window.setPayment = function (v) {
  S.checkout.payment = v;
  renderPayHints();
};
/* Cached vendor lookup for pages that only carry the vendor id (order views). */
async function vendorById(id) {
  if (S.vendorById[id]) return S.vendorById[id];
  const v = await api('/vendors/' + id);
  S.vendorById[id] = v;
  return v;
}
/* Pickup address block for a vendor — render ONLY on pickup orders and on the
   vendor storefront; never on delivery orders. Returns '' when the vendor
   hasn't filled in their structured address. */
function pickupAddrHTML(v) {
  const addr = composeAddress(v);
  if (!addr) return '';
  return '<div class="vendor-tag">📍 <strong>' + esc(t('pickup_location')) + '</strong> ' + esc(addr) + mapsLink(addr) + '</div>';
}
/* === FEATURE 9: pickup-point card ===
   The vendor's pickup logistics (address / map link / instructions) —
   shown at checkout (pickup orders), on the confirmation page, and in
   status-change emails/pushes. Returns '' when the vendor set nothing. */
function pickupCardHTML(v) {
  if (!v) return '';
  const addr = (v.pickup_address || '').trim();
  const instr = (v.pickup_instructions || '').trim();
  const mapUrl = (v.pickup_map_url || '').trim();
  if (!addr && !instr && !mapUrl) return '';
  let html = '<div class="pickup-card"><div class="pickup-card-title">📍 ' + esc(t('pickup_card_h')) + '</div>';
  if (addr) html += '<div>📍 ' + esc(addr) + '</div>';
  if (mapUrl) html += '<div>🗺️ <a href="' + esc(mapUrl) + '" target="_blank" rel="noopener">' + esc(t('maps_view')) + '</a></div>';
  if (instr) html += '<div>📝 ' + esc(instr) + '</div>';
  html += '</div>';
  return html;
}
/* === END FEATURE 9 === */
const NEXT_STATUS = { new: 'preparing', preparing: 'ready', ready: 'on_the_way', on_the_way: 'completed' };
function statusLabel(s) { return t('status_' + s); }
/* Sales tax rate on the order subtotal. TAX_RATE is the hardcoded fallback
   (0) — the checkout preview actually uses currentTaxRate(), which prefers
   the admin-set rate fetched from GET /api/settings/public. The backend
   (orders.py _current_tax_rate) is what actually charges. */
/* Effective tax rate for the checkout preview: the fetched admin-set rate
   when valid (0..1), else the TAX_RATE fallback. */
function currentTaxRate() {
  const r = S.publicSettings && Number(S.publicSettings.tax_rate);
  return (Number.isFinite(r) && r >= 0 && r <= 1) ? r : TAX_RATE;
}
const TAX_RATE = 0;
/* Itemized totals table: Subtotal / Delivery fees / Discount / Points / Tax /
   Grand total. Pass the backend-stored tax when you have it (order records);
   otherwise it is computed from currentTaxRate() (admin-set rate from
   GET /api/settings/public, TAX_RATE fallback). pointsDiscount is the dollar value
   redeemed from loyalty points (backend record) or the client estimate at
   checkout — shown as a "Points" line whenever > 0. */
function totalsBreakdown(sub, fee, storedTax, discount, pointsDiscount, feeWaived) {
  const tax = storedTax != null ? Number(storedTax) : Math.round(sub * currentTaxRate() * 100) / 100;
  const disc = discount && Number(discount.amount) > 0 ? Number(discount.amount) : 0;
  const pts = Number(pointsDiscount) > 0 ? Number(pointsDiscount) : 0;
  let h = '<table class="totals">' +
    '<tr><td>' + esc(t('subtotal')) + '</td><td style="text-align:right">' + money(sub) + '</td></tr>';
  if (fee > 0) h += '<tr><td>' + esc(t('delivery_fees_row')) + '</td><td style="text-align:right">' + money(fee) + '</td></tr>';
  // v46: a waived delivery fee still gets its row — shown as FREE.
  else if (feeWaived) h += '<tr><td>' + esc(t('delivery_fees_row')) + '</td><td style="text-align:right">' + esc(t('free_word')) + '</td></tr>';
  if (disc > 0) h += '<tr class="disc-row"><td>' + esc(t('discount_row', { code: (discount && discount.code) || '' })) +
    '</td><td style="text-align:right">−' + money(disc) + '</td></tr>';
  if (pts > 0) h += '<tr class="disc-row"><td>' + esc(t('points_row')) +
    '</td><td style="text-align:right">−' + money(pts) + '</td></tr>';
  h += '<tr><td>' + esc(t('tax_row')) + '</td><td style="text-align:right">' + money(tax) + '</td></tr>' +
    '<tr class="grand"><td>' + esc(t('grand_total')) + '</td><td style="text-align:right">' + money(sub + fee + tax - disc - pts) + '</td></tr></table>';
  return h;
}
/* Discount stored on a backend order record → totalsBreakdown row, or null. */
function discountOf(o) {
  return (o && Number(o.discount_amount) > 0) ? { code: o.promo_code, amount: Number(o.discount_amount) } : null;
}
/* Points discount stored on a backend order record → totalsBreakdown row, or 0. */
function pointsDiscountOf(o) {
  return (o && Number(o.points_discount) > 0) ? Number(o.points_discount) : 0;
}

/* ============ red-list shared helpers ============ */
function errText(e) {
  // Backend 422s come back as an array of {msg}; 400s as a plain string.
  const m = e && e.message;
  if (Array.isArray(m)) return m.map(x => (x && x.msg) || JSON.stringify(x)).join('; ');
  return String(m || 'Something went wrong.');
}
function paidBadgeHTML(paid) {
  return paid
    ? '<span class="paid-badge yes">' + esc(t('paid_badge_yes')) + '</span>'
    : '<span class="paid-badge no">' + esc(t('paid_badge_no')) + '</span>';
}

const MARKET_TIME_ZONE = 'America/Los_Angeles';
function marketDateTimeParts(date) {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: MARKET_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date || new Date());
  const values = {};
  parts.forEach(function (part) { values[part.type] = part.value; });
  return values;
}
function marketISODate(date) {
  const p = marketDateTimeParts(date);
  return p.year + '-' + p.month + '-' + p.day;
}
function marketWallTimeToDate(dateISO, hhmm) {
  const dateMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(dateISO || ''));
  const timeMatch = /^(\d{2}):(\d{2})$/.exec(String(hhmm || ''));
  if (!dateMatch || !timeMatch) return null;
  const target = Date.UTC(
    Number(dateMatch[1]), Number(dateMatch[2]) - 1, Number(dateMatch[3]),
    Number(timeMatch[1]), Number(timeMatch[2])
  );
  let guess = target;
  for (let i = 0; i < 4; i++) {
    const p = marketDateTimeParts(new Date(guess));
    const represented = Date.UTC(
      Number(p.year), Number(p.month) - 1, Number(p.day),
      Number(p.hour), Number(p.minute)
    );
    guess += target - represented;
  }
  const result = new Date(guess);
  const p = marketDateTimeParts(result);
  if (p.year !== dateMatch[1] || p.month !== dateMatch[2] || p.day !== dateMatch[3] ||
      p.hour !== timeMatch[1] || p.minute !== timeMatch[2]) return null;
  return result;
}
function pickupAtToUTC(pickupAt) {
  const match = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})$/.exec(String(pickupAt || ''));
  const instant = match && marketWallTimeToDate(match[1], match[2]);
  if (!instant) throw new Error(t('pickup_time_invalid'));
  return instant.toISOString();
}
/* ---- vendor open/closed computation (hours fields + is_paused) ----
   closed_weekdays: "5" or "5,6" or null — 0=Sunday … 6=Saturday.
   Shop hours are always interpreted in the marketplace timezone. */
function marketClockParts() {
  const values = marketDateTimeParts(new Date());
  const weekdays = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  return {
    weekday: weekdays.indexOf(values.weekday),
    minutes: Number(values.hour) * 60 + Number(values.minute),
  };
}
function vendorClosedReason(v) {
  if (!v) return null;
  if (v.is_paused) return { reason: 'paused' };
  const now = marketClockParts();
  const wd = String(now.weekday);
  const closed = String(v.closed_weekdays || '').split(',').map(s => s.trim()).filter(Boolean);
  if (closed.indexOf(wd) !== -1) return { reason: 'day' };
  const ot = v.open_time, ct = v.close_time;
  if (ot && ct) {
    const toMin = s => { const p = String(s).split(':'); return Number(p[0]) * 60 + Number(p[1] || 0); };
    const cur = now.minutes;
    const o = toMin(ot), c = toMin(ct);
    const isClosed = o <= c ? (cur < o || cur > c) : (cur < o && cur > c); // overnight ranges wrap
    if (isClosed) return { reason: 'hours', opensAt: ot, tomorrow: cur > c };
  }
  return null;
}
function fmtTimeHHMM(hhmm) {
  if (!hhmm) return '';
  const p = String(hhmm).split(':');
  let h = Number(p[0]);
  const m = p[1] || '00';
  const ap = h >= 12 ? 'PM' : 'AM';
  h = h % 12; if (h === 0) h = 12;
  if (lang() === 'ar') return h + ':' + m + ' ' + (ap === 'PM' ? 'م' : 'ص');
  return h + ':' + m + ' ' + ap;
}
/* Storefront open/closed banner. openStatus (from GET open-status) is used
   when the vendor has no hour fields of their own; paused gets its own banner. */
function openBannerHTML(v, openStatus) {
  if (v && v.is_paused) return '';
  if (openStatus && typeof openStatus.open === 'boolean') {
    return openStatus.open
      ? '<div class="open-banner open">' + esc(t('open_now')) + '</div>'
      : '<div class="open-banner closed">' + esc(openStatus.message || t('closed_reason_hours')) + '</div>';
  }
  const r = vendorClosedReason(v);
  if (!r) {
    const hasHours = v && (v.open_time || v.close_time || v.closed_weekdays);
    return hasHours ? '<div class="open-banner open">' + esc(t('open_now')) + '</div>' : '';
  }
  let msg;
  if (r.reason === 'day') {
    msg = v.open_time
      ? t('closed_opens_tomorrow', { time: fmtTimeHHMM(v.open_time) })
      : t('closed_reason_day');
  } else {
    msg = t(r.tomorrow ? 'closed_opens_tomorrow' : 'closed_opens_at', { time: fmtTimeHHMM(r.opensAt) });
  }
  return '<div class="open-banner closed">' + esc(msg) + '</div>';
}
/* Friendly checkout-block message when a vendor is closed/paused, or null. */
function closedBlockMsg(v) {
  const r = vendorClosedReason(v);
  if (!r) return null;
  const reason = r.reason === 'paused' ? t('closed_reason_paused')
    : r.reason === 'day' ? t('closed_reason_day') : t('closed_reason_hours');
  return t('vendor_closed_block', { name: (v && v.name) || t('unknown_vendor'), reason });
}

/* ---- advance ordering / weekly specials (America/Los_Angeles) ----
   Mirrors backend/app/order_windows.py in LA wall-clock terms. The server
   re-validates at checkout, so this is a UX pre-check only.
   available_days: weekday ints, 0=Monday..6=Sunday, null = every day.
   NOTE: the LA offset is sampled once at `now` and applied to the serving
   day (<= 7 days out); across the two yearly DST transitions the cutoff
   display can be off by an hour client-side — the server stays authoritative. */
var _LA_TZ = 'America/Los_Angeles';
var _MONDAY_UTC = Date.UTC(2026, 9, 12); // 2026-10-12 was a Monday
function laParts(d) {
  var p = {};
  new Intl.DateTimeFormat('en-US', { timeZone: _LA_TZ, weekday: 'short', year: 'numeric',
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
    .formatToParts(d).forEach(function (x) { p[x.type] = x.value; });
  var wdMap = { Mon: 0, Tue: 1, Wed: 2, Thu: 3, Fri: 4, Sat: 5, Sun: 6 };
  return { y: +p.year, mo: +p.month, d: +p.day, wd: wdMap[p.weekday], min: ((+p.hour) % 24) * 60 + (+p.minute) };
}
function laOffsetMinutes(d) {
  var p = {};
  new Intl.DateTimeFormat('en-US', { timeZone: _LA_TZ, hour12: false, year: 'numeric',
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
    .formatToParts(d).forEach(function (x) { p[x.type] = x.value; });
  var asUTC = Date.UTC(+p.year, +p.month - 1, +p.day, (+p.hour) % 24, +p.minute, +p.second);
  return Math.round((asUTC - d.getTime()) / 60000);
}
function wdName(wd, plural) {
  var loc = lang() === 'ar' ? 'ar' : 'en';
  var s = new Intl.DateTimeFormat(loc, { weekday: 'long', timeZone: 'UTC' })
    .format(new Date(_MONDAY_UTC + wd * 864e5));
  return (plural && loc === 'en') ? s + 's' : s;
}
/* null = every day (also when the stored list is empty or all 7). */
function dishDays(dish) {
  var r = dish && dish.available_days;
  if (!Array.isArray(r) || !r.length) return null;
  var days = [];
  r.forEach(function (x) { x = Number(x); if (x >= 0 && x <= 6 && days.indexOf(x) === -1) days.push(x); });
  if (!days.length || days.length >= 7) return null;
  return days.sort();
}
function dishRestricted(dish) {
  return dishDays(dish) !== null || (Number(dish && dish.order_cutoff_hours) || 0) > 0;
}
function dishWindow(dish, nowMs) {
  var days = dishDays(dish); // null = every day
  var H = Number(dish.order_cutoff_hours) || 0;
  var now = nowMs || Date.now();
  var off = laOffsetMinutes(new Date(now));
  var lp = laParts(new Date(now));
  var mid; // UTC ms of the LA midnight starting the serving day D
  var servingWd;
  if (days === null) {
    // Every-day dish: same-day deadline — order by (end of today − H).
    mid = Date.UTC(lp.y, lp.mo - 1, lp.d) - off * 60000;
    servingWd = lp.wd;
  } else {
    var k = 0;
    while (k <= 7 && days.indexOf((lp.wd + k) % 7) === -1) k++;
    if (k > 7) return { restricted: true, open: false, degenerate: true };
    var dd = new Date(Date.UTC(lp.y, lp.mo - 1, lp.d + k));
    mid = Date.UTC(dd.getUTCFullYear(), dd.getUTCMonth(), dd.getUTCDate()) - off * 60000;
    servingWd = (lp.wd + k) % 7;
  }
  var cutoff = days === null
    ? mid + 864e5 - H * 3600e3
    : (H > 0 ? mid - H * 3600e3 : mid + 864e5);
  var opensMs = mid + 864e5; // ordering reopens when the serving day ends
  return {
    restricted: true, open: now <= cutoff, days: days, hasCutoff: H > 0,
    servingWd: servingWd, cutoffMs: cutoff,
    opensWd: laParts(new Date(opensMs)).wd,
  };
}
function fmtCutoffLA(ms) {
  return new Intl.DateTimeFormat(lang() === 'ar' ? 'ar' : 'en-US',
    { timeZone: _LA_TZ, weekday: 'short', hour: 'numeric', minute: '2-digit' }).format(new Date(ms));
}
function availDaysStr(days) {
  if (!days) return t('avail_daily');
  var plural = lang() !== 'ar';
  return days.slice().sort().map(function (w) { return wdName(w, plural); }).join(lang() === 'ar' ? '، ' : ', ');
}
/* "📅 Available Fridays · order by Thu 8:00 PM" — only when restricted. */
function availBadge(dish) {
  if (!dishRestricted(dish)) return '';
  var w = dishWindow(dish);
  var txt = w.hasCutoff
    ? t('avail_badge_cutoff', { days: availDaysStr(w.days), cutoff: fmtCutoffLA(w.cutoffMs) })
    : t('avail_badge_days', { days: availDaysStr(w.days) });
  return '<span class="avail-badge">' + esc(txt) + '</span>';
}
/* Friendly localized block message for add-to-cart outside the window. */
function orderWindowBlockMsg(dish) {
  var w = dishWindow(dish);
  return t('order_window_closed', {
    name: dish.name, days: availDaysStr(w.days),
    cutoff: fmtCutoffLA(w.cutoffMs),
    serving: wdName(w.servingWd, false), opens: wdName(w.opensWd, false),
  });
}
/* Pickup datetime-local min: now + the vendor's prep time. */
function pickupMinISO(vendor) {
  const prep = Math.max(0, Number(vendor.prep_minutes) || 0);
  const d = new Date(Date.now() + prep * 60000);
  const p = marketDateTimeParts(d);
  return p.year + '-' + p.month + '-' + p.day + 'T' + p.hour + ':' + p.minute;
}

/* ---- Pickup date/time picker: mini calendar + rolling time wheel ----
   Replaces the day/time chips (Oct 2026): a month calendar for the date
   (30 days out, vendor closed weekdays disabled) and a scrollable wheel
   for the time (30-min slots inside vendor hours, honoring prep lead time).
   State stays in checkoutGroup(v).pickupAt ('YYYY-MM-DDTHH:MM'), so
   nextReview/placeOrder need no changes. */
function pickupISODate(d) {
  return d.getUTCFullYear() + '-' + String(d.getUTCMonth() + 1).padStart(2, '0') + '-' +
    String(d.getUTCDate()).padStart(2, '0');
}
function pickupDateFromISO(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || ''));
  return m ? new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]))) : null;
}
function pickupDayOpen(vendor, iso) {
  const closed = String(vendor.closed_weekdays || '').split(',').map(function (s) { return s.trim(); }).filter(Boolean);
  if (!closed.length) return true;
  const d = pickupDateFromISO(iso);
  return !!d && closed.indexOf(String(d.getUTCDay())) === -1;
}
/* Pickup lead time (v41 fix): the cart's real prep estimate for this
   vendor (the same "Estimated prep" number shown at checkout: per-dish
   minutes × qty), never below the vendor's own base prep. The old code used
   only vendor.prep_minutes, so a 50-min dish was offered 30-min slots.
   g._leadMins is set during the cart render (see vCart); callers outside the
   render (setPickupDay/setPickupTime) read the stored value. */
function pickupLead(vendor, g) {
  return Math.max(0, Number(vendor.prep_minutes) || 0, Number((g && g._leadMins) || 0));
}
function pickupTimeSlots(vendor, dateISO, g) {
  const parseHM = function (s, fb) {
    const m = /^(\d{1,2}):(\d{2})$/.exec(String(s || ''));
    return m ? Number(m[1]) * 60 + Number(m[2]) : fb;
  };
  let open = parseHM(vendor.open_time, 10 * 60), close = parseHM(vendor.close_time, 20 * 60);
  if (!(close > open)) { open = 0; close = 24 * 60; } // misconfigured hours → all day
  const prep = pickupLead(vendor, g);
  const minTs = Date.now() + prep * 60000;
  const loc = lang() === 'ar' ? 'ar-EG' : 'en-US';
  const slots = [];
  for (let m = open; m < close; m += 30) {
    const hh = String(Math.floor(m / 60)).padStart(2, '0'), mm = String(m % 60).padStart(2, '0');
    const dt = marketWallTimeToDate(dateISO, hh + ':' + mm);
    if (!dt) continue;
    if (dt.getTime() <= minTs) continue; // prep lead time
    slots.push({ value: hh + ':' + mm, label: dt.toLocaleTimeString(loc, {
      timeZone: MARKET_TIME_ZONE, hour: 'numeric', minute: '2-digit', hour12: true,
    }) });
  }
  return slots;
}
/* Current {date, time} selection; auto-selects the earliest valid slot when
   the group has none yet, so checkout is one tap faster. */
/* Current {date, time} selection; auto-selects the earliest valid slot when
   the group has none yet (up to 30 days out, skipping vendor closed days),
   so checkout stays one tap fast. */
function pickupSel(vendor, g) {
  let date = '', time = '';
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(String(g.pickupAt || ''));
  if (m) { date = m[1]; time = m[2]; }
  const today = pickupDateFromISO(marketISODate());
  const isos = [];
  for (let i = 0; i < 30; i++) {
    const d = new Date(today.getTime()); d.setUTCDate(d.getUTCDate() + i);
    isos.push(pickupISODate(d));
  }
  let needSearch = isos.indexOf(date) === -1 || !pickupDayOpen(vendor, date);
  if (!needSearch) {
    // Stored day is still bookable — keep it only if the stored time slot is
    // still valid (not expired); otherwise fall through to find the next one.
    const slots = pickupTimeSlots(vendor, date, g);
    if (slots.some(function (s) { return s.value === time; })) return { date: date, time: time };
    needSearch = true;
  }
  if (needSearch) {
    date = ''; time = '';
    for (const iso of isos) {
      if (!pickupDayOpen(vendor, iso)) continue;
      const slots = pickupTimeSlots(vendor, iso, g);
      if (slots.length) { date = iso; time = slots[0].value; break; }
    }
  }
  // Never leave a stale past datetime in state: clear it when nothing valid.
  g.pickupAt = (date && time) ? date + 'T' + time : '';
  return { date: date, time: time };
}
/* Mini month calendar for the pickup date. Viewed month persists per vendor
   across cart re-renders (S.pickCalView). */
function pickupCalHTML(vendor, g, sel) {
  const vid = vendor.id;
  S.pickCalView = S.pickCalView || {};
  const today = pickupDateFromISO(marketISODate());
  const maxD = new Date(today.getTime()); maxD.setUTCDate(maxD.getUTCDate() + 30);
  let vw = S.pickCalView[vid];
  if (!vw) { vw = { y: today.getUTCFullYear(), m: today.getUTCMonth() }; S.pickCalView[vid] = vw; }
  const curKey = today.getUTCFullYear() * 12 + today.getUTCMonth();
  const maxKey = maxD.getUTCFullYear() * 12 + maxD.getUTCMonth();
  let key = vw.y * 12 + vw.m;
  if (key < curKey) key = curKey;
  if (key > maxKey) key = maxKey;
  vw.y = Math.floor(key / 12); vw.m = key % 12;
  const loc = lang() === 'ar' ? 'ar-EG' : 'en-US';
  const weekStart = lang() === 'ar' ? 6 : 0; // Saturday in AR, Sunday in EN
  const title = new Date(Date.UTC(vw.y, vw.m, 1)).toLocaleDateString(loc, {
    month: 'long', year: 'numeric', timeZone: 'UTC',
  });
  let wdHead = '';
  for (let i = 0; i < 7; i++) {
    const wd = new Date(Date.UTC(2026, 9, 4 + ((weekStart + i) % 7))); // 2026-10-04 is a Sunday
    wdHead += '<div class="pick-cal-wd">' + esc(wd.toLocaleDateString(loc, {
      weekday: 'short', timeZone: 'UTC',
    })) + '</div>';
  }
  const first = new Date(Date.UTC(vw.y, vw.m, 1));
  const lead = (first.getUTCDay() - weekStart + 7) % 7;
  const dim = new Date(Date.UTC(vw.y, vw.m + 1, 0)).getUTCDate();
  let cells = '';
  for (let i = 0; i < lead; i++) cells += '<div class="pick-day empty"></div>';
  for (let d = 1; d <= dim; d++) {
    const dt = new Date(Date.UTC(vw.y, vw.m, d));
    const iso = pickupISODate(dt);
    const dis = dt < today || dt > maxD || !pickupDayOpen(vendor, iso);
    const isSel = iso === sel.date;
    cells += '<button type="button" class="pick-day' + (dis ? ' dis' : '') + (isSel ? ' sel' : '') + '"' +
      (dis ? ' disabled' : ' onclick="setPickupDay(' + vid + ',\'' + iso + '\')"') + '>' + d + '</button>';
  }
  const prevDis = key <= curKey, nextDis = key >= maxKey;
  return '<div class="pick-cal">' +
    '<div class="pick-cal-head">' +
    '<button type="button" class="pick-cal-nav"' + (prevDis ? ' disabled' : ' onclick="pickupCalNav(' + vid + ',-1)"') + '>&#8249;</button>' +
    '<div class="pick-cal-title">' + esc(title) + '</div>' +
    '<button type="button" class="pick-cal-nav"' + (nextDis ? ' disabled' : ' onclick="pickupCalNav(' + vid + ',1)"') + '>&#8250;</button>' +
    '</div>' +
    '<div class="pick-cal-grid">' + wdHead + cells + '</div></div>';
}
window.pickupCalNav = function (vid, delta) {
  S.pickCalView = S.pickCalView || {};
  const vw = S.pickCalView[vid] || {};
  const now = pickupDateFromISO(marketISODate());
  const key = ((vw.y || now.getUTCFullYear()) * 12 + (vw.m == null ? now.getUTCMonth() : vw.m)) + delta;
  S.pickCalView[vid] = { y: Math.floor(key / 12), m: ((key % 12) + 12) % 12 };
  vCart();
};
/* Rolling time wheel: vertical snap-scroll drum of the day's slots. */
function pickupWheelHTML(vendor, g, sel) {
  const slots = sel.date ? pickupTimeSlots(vendor, sel.date, g) : [];
  if (!slots.length) return '<div class="hint">' + esc(t('pick_no_slots')) + '</div>';
  return '<label class="field" for="pickup-time-' + vendor.id + '">' + esc(t('pickup_time_select')) + '</label>' +
    '<select class="pick-time-select" id="pickup-time-' + vendor.id + '" onchange="setPickupTime(' + Number(vendor.id) + ',this.value)">' +
    slots.map(function (s) {
      return '<option value="' + s.value + '"' + (s.value === sel.time ? ' selected' : '') + '>' +
        esc(s.label) + '</option>';
    }).join('') + '</select>';
}/* After the wheel stops scrolling, select the centered slot (quietly — no
   full cart re-render, so the wheel keeps its position). */
window.pickWheelScroll = function (el) {
  clearTimeout(el._wt);
  el._wt = setTimeout(function () {
    const items = el.querySelectorAll('.pick-wheel-item');
    if (!items.length) return;
    const mid = el.scrollTop + el.clientHeight / 2;
    let best = null, bestD = 1e9;
    items.forEach(function (it) {
      const c = it.offsetTop + it.offsetHeight / 2;
      const d = Math.abs(c - mid);
      if (d < bestD) { bestD = d; best = it; }
    });
    if (!best) return;
    el.scrollTo({ top: best.offsetTop - el.clientHeight / 2 + best.offsetHeight / 2, behavior: 'smooth' });
    if (!best.classList.contains('active')) setPickupTime(Number(el.dataset.vid), best.dataset.time, true);
  }, 130);
};
/* Center every wheel on its selected slot (runs after each cart render). */
function centerPickupWheels() {
  document.querySelectorAll('.pick-wheel').forEach(function (el) {
    const act = el.querySelector('.pick-wheel-item.active') || el.querySelector('.pick-wheel-item');
    if (act) el.scrollTop = act.offsetTop - el.clientHeight / 2 + act.offsetHeight / 2;
  });
}
function pickupPickerHTML(vendor, g) {
  const sel = pickupSel(vendor, g);
  let html = '<label class="field">' + esc(t('pickup_time_vendor', { name: vendor.name })) + '</label>';
  html += '<div class="pick-row">' + pickupCalHTML(vendor, g, sel) + pickupWheelHTML(vendor, g, sel) + '</div>';
  return html;
}
window.setPickupDay = function (vid, dateISO) {
  const v = S.vendorById[vid];
  if (!v) return;
  const g = checkoutGroup(v);
  const cur = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(String(g.pickupAt || ''));
  const slots = pickupTimeSlots(v, dateISO, g);
  const keep = cur && slots.some(function (s) { return s.value === cur[2]; });
  const time = keep ? cur[2] : (slots[0] && slots[0].value) || '';
  if (time) g.pickupAt = dateISO + 'T' + time;
  vCart();
};
window.setPickupTime = function (vid, hhmm, quiet) {
  const v = S.vendorById[vid];
  if (!v) return;
  const g = checkoutGroup(v);
  const cur = /^(\d{4}-\d{2}-\d{2})T/.exec(String(g.pickupAt || ''));
  const date = cur ? cur[1] : (pickupSel(v, g).date || '');
  if (!date) return;
  const slots = pickupTimeSlots(v, date, g);
  if (!slots.some(function (s) { return s.value === hhmm; })) return;
  g.pickupAt = date + 'T' + hhmm;
  // Keep the wheel's highlighted slot in sync (matters for the quiet path,
  // which skips the full re-render so the wheel holds its scroll position).
  document.querySelectorAll('.pick-wheel[data-vid="' + vid + '"] .pick-wheel-item').forEach(function (it) {
    it.classList.toggle('active', it.dataset.time === hhmm);
    it.setAttribute('aria-pressed', it.dataset.time === hhmm ? 'true' : 'false');
  });
  if (!quiet) vCart();
};

/* ---- dish customizations: multiple option groups + ingredients ----
   Dish.options: [{id, name, selection_type: 'single'|'multiple',
     min_select, max_select (int|null), choices: [{label, delta}]}].
   A cart entry carries {qty, cust} where cust =
     {modifiers: [{option_id, option_name, gi, choices: [{label, delta}]}],
      removed: [ingredient names], added: [{name, delta}]}.
   Legacy carts ({qty, modifier}) still render and check out. */
function dishOptionGroups(dish) {
  const gs = (dish && dish.options) || [];
  return gs.map(function (g) {
    const rawMax = (g && g.max_select !== undefined) ? g.max_select : null;
    return {
      id: (g && g.id !== undefined && g.id !== null) ? g.id : null,
      name: (g && g.name) || '',
      type: (g && g.selection_type === 'multiple') ? 'multiple' : 'single',
      min: Math.max(0, Number((g && g.min_select) || 0)),
      max: (rawMax === null || rawMax === undefined || rawMax === '')
        ? null : Math.max(0, Number(rawMax)),
      choices: ((g && g.choices) || []).map(function (c) {
        return { label: String(c.label), delta: Number(c.delta) || 0 };
      }),
    };
  });
}
function emptyCust() { return { modifiers: [], removed: [], added: [] }; }
function dishIngRows(dish) {
  // Structured ingredient rows, attached by the backend on the PUBLIC dish
  // endpoints — no vendor auth needed (the old code called a vendor-gated
  // endpoint here, so customers never saw the toggles).
  return (dish && Array.isArray(dish.ingredient_options)) ? dish.ingredient_options : [];
}
function dishIngredients(dish) {
  const rows = dishIngRows(dish);
  if (rows.length) return rows;
  // Fall back to the ingredients text (seeded): every listed ingredient
  // becomes a removable toggle, so "choose ingredients" works even when the
  // vendor never opened the portal's ingredient manager.
  const txt = dish && dish.ingredients;
  if (!txt) return [];
  return String(txt).split(',').map(function (s) { return s.trim(); }).filter(Boolean).slice(0, 30)
    .map(function (nm) { return { name: nm, included_by_default: true, removable: true, extra_price: 0 }; });
}
/* Is the dish-detail page for this dish currently rendered? Quick-add from
   dish cards has no customization UI — plain defaults apply there. */
function dishPageActive(dishId) {
  // Option groups and ingredient controls are rendered separately. A dish
  // with ingredients but no option groups has no #dish-custom wrapper, so
  // detect its ingredient list too or its ingredient selections are lost.
  const el = document.getElementById('dish-custom');
  if (el && Number(el.getAttribute('data-dish')) === Number(dishId)) return true;
  const ing = document.getElementById('ing-list');
  return !!(ing && Number(ing.getAttribute('data-dish')) === Number(dishId));
}
/* === Oct 2026 (the 4-fish bug): a dish is "customizable" when it has option
   groups (sides) or ingredient rows. Customizable dishes NEVER one-tap-add
   from cards — the customer must land on the dish page and see the choices. */
function dishCustomizable(dish) {
  if (!dish) return false;
  return dishOptionGroups(dish).length > 0 || dishIngredients(dish).length > 0;
}
/* Route to the dish page with the option groups highlighted + hint, so the
   customer chooses sides/ingredients before adding. */
window.goDishCustom = function (dishId) {
  S.highlightGroups = true;
  S.flash = t('quickadd_groups_hint');
  go('dish', dishId);
};
function optGroupKey(dishId, g, gi) {
  return dishId + '-' + (g.id !== null ? g.id : 'i' + gi);
}
/* Read the customer's current selections from the dish-page DOM. */
function chosenCustomizations(dish) {
  const cust = emptyCust();
  const groups = dishOptionGroups(dish);
  const onPage = dishPageActive(dish.id);
  groups.forEach(function (g, gi) {
    let picked = [];
    if (onPage) {
      const box = document.getElementById('optg-box-' + optGroupKey(dish.id, g, gi));
      if (box) {
        if (box.tagName === 'SELECT') {
          // Single-choice dropdown: the selected <option> carries data-ci.
          const opt = box.options[box.selectedIndex];
          const c = opt && g.choices[Number(opt.getAttribute('data-ci'))];
          if (c) picked.push({ label: c.label, delta: c.delta });
        } else {
          box.querySelectorAll('input[data-ci]:checked').forEach(function (inp) {
            const c = g.choices[Number(inp.getAttribute('data-ci'))];
            if (c) picked.push({ label: c.label, delta: c.delta });
          });
        }
      }
    } else if (g.type === 'single' && g.choices.length) {
      picked = [{ label: g.choices[0].label, delta: g.choices[0].delta }];
    }
    if (picked.length) cust.modifiers.push({ option_id: g.id, option_name: g.name, gi: gi, choices: picked });
  });
  if (onPage) {
    document.querySelectorAll('#ing-list input[data-ing]').forEach(function (inp) {
      const nm = inp.getAttribute('data-ing-name') || '';
      const kind = inp.getAttribute('data-ing');
      if (kind === 'rem' && !inp.checked && nm) cust.removed.push(nm);
      if (kind === 'add' && inp.checked && nm) {
        cust.added.push({ name: nm, delta: Number(inp.getAttribute('data-ing-price')) || 0 });
      }
    });
  }
  return cust;
}
/* Live per-unit total on the dish page (base price + choices + add-ons). */
window.updateDishPrice = function (dishId) {
  const d = S.dishById[dishId];
  if (!d) return;
  const cust = chosenCustomizations(d);
  const el = document.getElementById('dish-total');
  if (el) el.innerHTML = '💰 ' + money(custUnit(d, { cust: cust })) + ' ' + esc(t('each'));
  // Refresh the live counters on "pick many" groups.
  dishOptionGroups(d).forEach(function (g, gi) {
    if (g.type !== 'multiple') return;
    const cnt = document.getElementById('optg-count-' + optGroupKey(dishId, g, gi));
    const box = document.getElementById('optg-box-' + optGroupKey(dishId, g, gi));
    if (cnt && box) cnt.textContent = t('opt_picked_count', {
      n: box.querySelectorAll('input:checked').length, m: g.choices.length,
    });
  });
};
/* Checkbox/radio change on an option group: enforce the max client-side,
   then refresh the live total. */
window.onOptChange = function (dishId, gi, input) {
  const dish = S.dishById[dishId];
  const g = dish ? dishOptionGroups(dish)[gi] : null;
  let hitMax = false;
  if (g && g.type === 'multiple' && g.max !== null && input.checked) {
    const box = document.getElementById('optg-box-' + optGroupKey(dishId, g, gi));
    if (box && box.querySelectorAll('input:checked').length > g.max) {
      input.checked = false;
      hitMax = true;
    }
  }
  updateDishPrice(dishId);
  if (hitMax && g) {
    const cnt = document.getElementById('optg-count-' + optGroupKey(dishId, g, gi));
    if (cnt) cnt.innerHTML = '<span style="color:#b3261e;font-weight:700">' + esc(t('opt_max_hit', { n: g.max })) + '</span>';
  }
};
/* Ingredient toggle change: just refresh the live total. */
window.onIngChange = function (dishId) { updateDishPrice(dishId); };
/* 🌱 / 🌿 badges for dish cards and the dish page. */
function dietBadges(dish) {
  let h = '';
  if (dish && dish.is_vegetarian) h += ' <span class="diet-badge" title="' + esc(t('diet_veg')) + '">🌱</span>';
  if (dish && dish.is_vegan) h += ' <span class="diet-badge" title="' + esc(t('diet_vegan')) + '">🌿</span>';
  return h;
}
/* One customization line (legacy single-modifier cart entries, pre-v39 shape:
   {choice_label, delta}) in the same format as the modern added-extra line. */
function modLineHTML(mod) {
  if (!mod) return '';
  const nm = mod.choice_label || mod.label || '';
  const d = Number(mod.delta) || 0;
  return '<div class="vendor-tag mod-line">➕ ' + esc(d ? t('mod_line', { label: nm, delta: money(d) }) : nm) + '</div>';
}
/* Customization summary under a cart/checkout line (new shape + legacy). */
function custLinesHTML(entry) {
  const e = entry || {};
  let h = '';
  if (e.modifier) h += modLineHTML(e.modifier); // legacy single-modifier carts
  const cust = e.cust || emptyCust();
  (cust.modifiers || []).forEach(function (m) {
    const chs = (m.choices || []).filter(function (c) { return c; });
    if (!chs.length) return;
    const ch = chs.map(function (c) {
      return Number(c.delta) ? t('mod_line', { label: c.label, delta: money(c.delta) }) : String(c.label);
    }).join(', ');
    const line = m.option_name ? t('cust_group_line', { name: m.option_name, choices: ch }) : ch;
    h += '<div class="vendor-tag mod-line">🧩 ' + esc(line) + '</div>';
  });
  (cust.removed || []).forEach(function (n) {
    h += '<div style="color:#b3261e;font-weight:700">🚫 ' + esc(t('no_x', { name: n })) + '</div>';
  });
  (cust.added || []).forEach(function (a) {
    const nm = (a && a.name !== undefined) ? a.name : String(a);
    const d = Number(a && a.delta) || 0;
    h += '<div class="vendor-tag mod-line">➕ ' + esc(d ? t('mod_line', { label: nm, delta: money(d) }) : nm) + '</div>';
  });
  return h;
}
/* Order-item extras on confirmation / My Orders / tracking detail:
   multi-group modifier label + removed + added ingredients. */
function orderItemExtraHTML(i) {
  let h = '';
  if (i.modifier_label) h += ' <small>(' + esc(i.modifier_label) + ')</small>';
  (i.removed_ingredients || []).forEach(function (n) {
    h += '<div style="color:#b3261e;font-weight:700">🚫 ' + esc(t('no_x', { name: n })) + '</div>';
  });
  (i.added_ingredients || []).forEach(function (n) {
    h += '<div class="vendor-tag mod-line">➕ ' + esc(String(n)) + '</div>';
  });
  return h;
}
/* Line unit price: sale price + choice deltas + add-on extras (+ legacy). */
function custUnit(dish, entry) {
  let u = salePrice(dish);
  const e = entry || {};
  if (e.modifier) u += Number(e.modifier.delta) || 0; // legacy
  const cust = e.cust || emptyCust();
  (cust.modifiers || []).forEach(function (m) {
    (m.choices || []).forEach(function (c) { u += Number(c.delta) || 0; });
  });
  (cust.added || []).forEach(function (a) { u += Number(a.delta) || 0; });
  return u;
}

/* ---- promo codes ---- */
function promoDiscount(sub) {
  const p = S.checkout.promo;
  if (!p || !p.percent_off) return 0;
  return Math.round(sub * Number(p.percent_off)) / 100;
}
function cartDiscount(subSum) {
  const p = S.checkout.promo;
  return (p && p.percent_off) ? { code: p.code, amount: promoDiscount(subSum) } : null;
}
function promoBlockHTML() {
  const p = S.checkout.promo;
  let h = '<div class="promo-block"><label class="field">' + esc(t('promo_have')) + '</label>';
  if (p) {
    h += '<div class="promo-applied"><span class="promo-code">' + esc(t('promo_applied', { code: p.code, pct: p.percent_off })) + '</span> ' +
      '<button class="btn small secondary" onclick="removePromo()">' + esc(t('promo_remove')) + '</button></div>';
  } else {
    h += '<div class="promo-row"><input type="text" id="promo-code" placeholder="' + esc(t('promo_ph')) + '" maxlength="40" autocomplete="off">' +
      '<button class="btn small" onclick="applyPromo()">' + esc(t('promo_apply')) + '</button></div>' +
      '<div id="promo-msg"></div>';
  }
  return h + '</div>';
}
window.applyPromo = async function () {
  const inp = $('#promo-code'), msg = $('#promo-msg');
  const code = (inp && inp.value || '').trim();
  if (!code) return;
  if (msg) msg.innerHTML = '';
  try {
    const r = await api('/promos/validate', { method: 'POST', body: JSON.stringify({ code }) });
    if (r && r.valid) {
      S.checkout.promo = { code: code.toUpperCase(), percent_off: Number(r.percent_off) || 0 };
      if (S.route === 'cart') vCart(); else if (S.route === 'review') vReview();
    } else if (msg) {
      msg.innerHTML = '<div class="error">' + esc((r && r.reason) || t('promo_invalid')) + '</div>';
    }
  } catch (e) { if (msg) msg.innerHTML = '<div class="error">' + esc(t('promo_err')) + '</div>'; }
};
window.removePromo = function () {
  S.checkout.promo = null;
  if (S.route === 'cart') vCart(); else if (S.route === 'review') vReview();
};

/* ---- loyalty points ----
   Balance comes from GET /api/loyalty/balance (auth required). The public
   GET /api/loyalty/rates gives the redeem rate (points per $1) used only for
   the "X points = up to $Y off" display — the backend is authoritative on the
   actual discount. 50 points/$1 is the fallback when the rates endpoint is
   unreachable. */
const LOY_REDEEM_FALLBACK = 50;
async function loadLoyalty() {
  if (!S.user) return; // v44: any logged-in user (vendors/admins order too since v30)
  if (S.loyalty.balance !== null && S.loyalty.rate !== null && S.loyalty.earn_rate !== null) return;
  try {
    const [b, r] = await Promise.all([api('/loyalty/balance'), api('/loyalty/rates')]);
    S.loyalty.balance = Number(b && b.balance) || 0;
    const rate = r && Number(r.points_per_dollar_redeem);
    S.loyalty.rate = rate > 0 ? rate : LOY_REDEEM_FALLBACK;
    const earn = r && Number(r.points_per_dollar);
    S.loyalty.earn_rate = earn > 0 ? earn : 1;
  } catch (e) { /* loyalty is a bonus — never break the page */ }
}
/* Estimated dollar value of redeeming N points at the current redeem rate. */
function loyaltyEstOff(pts) {
  const rate = S.loyalty.rate || LOY_REDEEM_FALLBACK;
  return Math.floor((Number(pts) || 0) / rate * 100) / 100;
}
/* Estimated Points line for the cart/review totals: capped at the payable
   subtotal so the display never goes below zero. */
function checkoutPointsOff(subSum, feeSum) {
  if (!(S.checkout.redeem_points > 0)) return 0;
  return Math.min(loyaltyEstOff(S.checkout.redeem_points), Math.max(0, subSum + feeSum));
}
/* v44: "You'll earn ~N points on this order" preview shown right by the
   redeem block / totals. N = floor(cart subtotal × earn rate), mirroring
   the backend award — an estimate, the backend is authoritative. Shown
   only when logged in and N > 0; re-rendered with the totals (vCart and
   vReview call it next to the redeem block). */
function loyaltyEarnPreviewHTML(subSum) {
  if (!S.user) return '';
  const rate = S.loyalty.earn_rate || 1;
  const n = Math.floor(Number(subSum || 0) * rate);
  if (n <= 0) return '';
  return '<div class="hint loyalty-earn-hint">🪙 ' + esc(t('points_earn_preview', { n })) + '</div>';
}
function loyaltyBlockHTML() {
  if (!S.user) return ''; // v44: any logged-in user
  const bal = S.loyalty.balance;
  if (bal === null || bal <= 0) return '';
  const off = loyaltyEstOff(bal);
  const on = S.checkout.redeem_points > 0;
  return '<div class="loyalty-block"><label class="loyalty-check">' +
    '<input type="checkbox"' + (on ? ' checked' : '') + ' onchange="toggleLoyalty(this.checked)">' +
    '<span><strong>' + esc(t('points_use', { n: bal })) + '</strong><br>' +
    '<small>' + esc(t('points_up_to', { n: bal, off: money(off) })) + '</small></span></label></div>';
}
window.toggleLoyalty = function (on) {
  const bal = S.loyalty.balance || 0;
  S.checkout.redeem_points = on && bal > 0 ? bal : 0;
  if (S.route === 'cart') vCart(); else if (S.route === 'review') vReview();
};

/* ---- profile: loyalty points card (balance + ledger history) ---- */
async function renderLoyaltyCard() {
  const el = $('#loy-card');
  if (!el) return;
  try {
    const [b, ledger] = await Promise.all([api('/loyalty/balance'), api('/loyalty/ledger')]);
    const bal = Number(b && b.balance) || 0;
    let h = '<p><strong>🪙 ' + esc(t('points_balance', { n: bal })) + '</strong></p>';
    if (bal <= 0) h += '<p class="hint">' + esc(t('points_none')) + '</p>';
    h += '<h4>' + esc(t('points_history')) + '</h4>';
    h += (ledger && ledger.length)
      ? '<div class="ledger">' + ledger.map(l => {
          const d = Number(l.delta) || 0;
          return '<div class="ledger-row"><span class="delta ' + (d >= 0 ? 'plus' : 'minus') + '">' +
            (d >= 0 ? '+' : '') + d + '</span>' +
            '<span class="ledger-reason">' + esc(l.reason || '') +
            (l.order_id ? ' · #' + l.order_id : '') +
            (l.note ? '<br><small>' + esc(l.note) + '</small>' : '') +
            '</span><small>' + esc(fmtDate(l.created_at)) + '</small></div>';
        }).join('') + '</div>'
      : '<div class="empty">' + esc(t('points_ledger_empty')) + '</div>';
    el.innerHTML = h;
  } catch (e) {
    el.innerHTML = '<div class="error">' + esc(e.message) + '</div>';
  }
}

/* ---- order messages (customer ↔ vendor) ---- */
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
function stopMsgPoll() { if (S.msgTimer) { clearInterval(S.msgTimer); S.msgTimer = null; } }
function startMsgPoll(orderId, viewer) {
  stopMsgPoll();
  refreshMsgThread(orderId, viewer);
  S.msgTimer = setInterval(() => {
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

/* ---- guest checkout ---- */
window.setGuestMode = function (on) {
  S.checkout.guestMode = !!on;
  if (on && !S.checkout.guest) S.checkout.guest = { name: '', phone: '', email: '' };
  vCart();
};
window.setGuestField = function (k, v) {
  if (!S.checkout.guest) S.checkout.guest = {};
  S.checkout.guest[k] = v;
};
function guestBlockHTML() {
  if (S.user) return '';
  let h = '<div class="guest-block">';
  if (!S.checkout.guestMode) {
    h += '<button class="btn small secondary" style="width:100%" onclick="setGuestMode(true)">' + esc(t('guest_title')) + '</button>' +
      '<div class="hint">' + esc(t('guest_or_login')) + ' <a href="#" data-go="login">' + esc(t('nav_login')) + '</a></div>';
  } else {
    const g = S.checkout.guest || {};
    h += '<h4>' + esc(t('guest_title')) + '</h4>' +
      '<label class="field">' + esc(t('name_label')) + '</label><input type="text" id="guest-name" maxlength="120" autocomplete="name" value="' + esc(g.name || '') + '" oninput="setGuestField(\'name\',this.value)">' +
      '<label class="field">' + esc(t('phone_label')) + '</label><input type="tel" id="guest-phone" maxlength="40" autocomplete="tel" value="' + esc(g.phone || '') + '" oninput="setGuestField(\'phone\',this.value)">' +
      '<label class="field">' + esc(t('email_label')) + ' <span class="sub">' + esc(t('optional')) + '</span></label><input type="email" id="guest-email" maxlength="160" autocomplete="email" value="' + esc(g.email || '') + '" oninput="setGuestField(\'email\',this.value)">' +
      '<button class="btn small ghost" onclick="setGuestMode(false)">' + esc(t('cancel')) + '</button>';
  }
  return h + '</div>';
}

/* ---- vendor replies on reviews ---- */
function reviewCardHTML(r, vendorName) {
  const photos = Array.isArray(r.photo_urls) ? r.photo_urls.filter(Boolean).slice(0, 3) : [];
  return '<div class="review-card"><div class="review-head"><strong>' + esc(r.user_name || t('review_fallback_name')) +
    '</strong>' + stars(r.rating) + '</div>' +
    (photos.length
      ? '<div class="review-photos">' + photos.map(function (u) {
          return '<img src="' + esc(u) + '" alt="" loading="lazy" onerror="this.style.display=\'none\'">';
        }).join('') + '</div>'
      : '') +
    (r.text ? '<p>' + esc(r.text) + '</p>' : '') +
    (r.vendor_reply
      ? '<div class="vendor-reply">' + esc(t('review_reply_lbl', { name: vendorName || '' })) + ' ' + esc(r.vendor_reply) +
        (r.replied_at ? ' <small>· ' + esc(fmtDate(r.replied_at)) + '</small>' : '') + '</div>'
      : '') +
    '<div class="vendor-tag">' + esc(fmtDate(r.created_at)) + '</div></div>';
}

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
function catLabel(c) { return lang() === 'ar' ? (CAT_AR[c] || c) : c; }

/* US states for the structured address dropdown: [code, English, Arabic]. */
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
  const ar = lang() === 'ar';
  return '<option value="">' + esc(t('addr_state_ph')) + '</option>' +
    US_STATES.map(s => '<option value="' + s[0] + '"' + (s[0] === selected ? ' selected' : '') + '>' +
      esc(ar ? s[2] : s[1]) + '</option>').join('');
}
/* Compose a saved structured address into one line for delivery. */
function composeAddress(u) {
  if (!u || !u.street_address) return '';
  const parts = [u.street_address];
  if (u.apt) parts.push(u.apt);
  const cityState = [u.city, u.state].filter(Boolean).join(', ');
  parts.push(([cityState, u.zipcode].filter(Boolean).join(' ')));
  return parts.filter(Boolean).join(', ');
}
function zipOk(z) { return !z || /^\d{5}(-\d{4})?$/.test(z.trim()); }

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
  { k: ['shrimp'], img: 'grilled_shrimp.jpg', emoji: '🍤' },
  { k: ['calamari'], img: 'fried_calamari.jpg', emoji: '🦑' },
  { k: ['crab'], img: 'blue_crab.jpg', emoji: '🦀' },
  { k: ['seafood platter', 'platter'], img: 'seafood.jpg', emoji: '🦐' },
  { k: ['shrimp rice', 'fish rice', 'seafood rice'], img: 'cooked_rice.jpg', emoji: '🍚' },
  { k: ['seafood'], img: 'seafood.jpg', emoji: '🦐' },
  { k: ['tahini'], img: 'tahini.jpg', emoji: '🥣' },
  { k: ['hummus'], img: 'hummus.jpg', emoji: '🧆' },
  { k: ['baladi salad'], img: 'tomato_salad.jpg', emoji: '🥗' },
  { k: ['fattoush'], img: 'fattoush.jpg', emoji: '🥗' },
  { k: ['tabbouleh', 'tabouli'], img: 'tabbouleh.jpg', emoji: '🥗' },
  { k: ['greek salad'], img: 'greek_salad.jpg', emoji: '🥗' },
  { k: ['caesar'], img: 'caesar_salad.jpg', emoji: '🥗' },
  { k: ['coleslaw'], img: 'coleslaw.jpg', emoji: '🥗' },
  { k: ['pickle'], img: 'pickles.jpg', emoji: '🥒' },
  { k: ['koshary', 'koshari', 'kushari'], img: 'koshary.jpg', emoji: '🍚' },
  { k: ['kofta'], img: 'kofta.jpg', emoji: '🍢' },
  { k: ['kebab'], img: 'adana_kebab.jpg', emoji: '🍢' },
  { k: ['hawawshi'], img: 'feteer.jpg', emoji: '🫓' },
  { k: ['feteer'], img: 'feteer.jpg', emoji: '🫓' },
  { k: ['baladi bread'], img: 'feteer.jpg', emoji: '🫓' },
  { k: ['garlic bread'], img: 'feteer.jpg', emoji: '🍞' },
  { k: ['sausage'], img: 'adana_kebab.jpg', emoji: '🌭' },
  { k: ['liver'], img: 'adana_kebab.jpg', emoji: '🍢' },
  { k: ['grilled beef', 'grilled chicken'], img: 'adana_kebab.jpg', emoji: '🍖' },
  { k: ['chicken pane'], img: 'adana_kebab.jpg', emoji: '🍗' },
  { k: ['molokhia'], img: 'molokhia.jpg', emoji: '🍲' },
  { k: ['bamia', 'okra'], img: 'okra.jpg', emoji: '🍲' },
  { k: ['kahk', 'kaak'], img: 'kahk.jpg', emoji: '🍪' },
  { k: ['basbousa'], img: 'baklava.jpg', emoji: '🍰' },
  { k: ['om ali', 'omali', 'umm ali'], img: 'rice_pudding.jpg', emoji: '🍮' },
  { k: ['dolma', 'grape leaves'], img: 'dolma.jpg', emoji: '🫔' },
  { k: ['mahshi', 'mombar'], img: 'dolma.jpg', emoji: '🫔' },
  { k: ['stuffed cabbage', 'stuffed zucchini', 'stuffed eggplant', 'stuffed tomato', 'stuffed pepper'], img: 'dolma.jpg', emoji: '🫔' },
  { k: ['kaware', 'broth'], img: 'lentil_soup.jpg', emoji: '🍲' },
  { k: ['orzo', 'lisan asfour'], img: 'lentil_soup.jpg', emoji: '🍲' },
  { k: ['lentil soup'], img: 'lentil_soup.jpg', emoji: '🍲' },
  { k: ['soup'], img: 'lentil_soup.jpg', emoji: '🍲' },
  { k: ['fries'], img: 'french_fries.jpg', emoji: '🍟' },
  { k: ['fatta'], img: 'cooked_rice.jpg', emoji: '🍚' },
  { k: ['rice'], img: 'cooked_rice.jpg', emoji: '🍚' },
  { k: ['salad'], img: 'meze.jpg', emoji: '🥗' },
  { k: ['appetizer', 'meze'], img: 'meze.jpg', emoji: '🫒' },
];
const DEFAULT_PHOTO = { img: 'meze.jpg', emoji: '🍽️' };

/* ================= state ================= */
const S = {
  token: localStorage.getItem('ehf_token') || null,
  user: null,
  route: 'home',
  routeArg: null,
  vendors: [],
  vendorById: {},
  categories: [],
  filter: { q: '', category: '', veg: false, vegan: false, deliversMe: false },
  showAllHomeDishes: false,
  popularDishes: [],
  cart: loadCart(),
  dishById: {},
  dishIng: {}, // dish id -> ingredients list (per-dish ingredient customizations)
  pickCalView: {}, // vendor id -> {y, m} viewed month in the pickup calendar
  // Multi-vendor checkout (Oct 2026): per-vendor groups hold fulfillment +
  // pickup time + notes; payment + delivery address are shared.
  checkout: { payment: 'zelle', address: '', groups: {}, promo: null, guestMode: false, guest: null,
    redeem_points: 0 },
  // Loyalty points cache: balance + redeem rate, refreshed on demand.
  loyalty: { balance: null, rate: null, earn_rate: null },
  // Public site settings from GET /api/settings/public (auth-free):
  // admin-set tax_rate used by the checkout preview. Defaults to 0 until
  // the fetch resolves; a failed fetch keeps the TAX_RATE fallback.
  publicSettings: { tax_rate: 0, site_name: '' },
  flash: null,
  lastCheckout: null,
  favs: new Set(),
  // === Delivery ZIP (Oct 2026): localStorage 'ehf_zip'; drives delivery
  // badges, the "Delivers to me" filter and checkout gating. ===
  zipOpen: false, // header ZIP entry form open
  // === END Delivery ZIP ===
  // === FEATURE 2: referral share code from a #/vendor/<id>?ref=<code>
  // share link — sent at checkout; the server re-validates it. ===
  referral: localStorage.getItem('ehf_referral') || null,
  // === END FEATURE 2 ===
};

function normCartEntry(v, key) {
  // Cart lines: {dishId, qty, cust}. Older carts stored {qty, modifier} or a
  // bare number keyed by dishId — migrate.
  const keyId = (function () {
    const n = parseInt(String(key).split('|')[0], 10);
    return isNaN(n) ? null : n;
  })();
  if (v && typeof v === 'object') {
    const q = Math.floor(Number(v.qty) || 0);
    if (q <= 0) return null;
    let mod = null;
    if (v.modifier && v.modifier.choice_label) {
      mod = { choice_label: String(v.modifier.choice_label), delta: Number(v.modifier.delta) || 0 };
    }
    const c = (v.cust && typeof v.cust === 'object') ? v.cust : {};
    const cust = {
      modifiers: Array.isArray(c.modifiers) ? c.modifiers : [],
      removed: Array.isArray(c.removed) ? c.removed.map(String) : [],
      added: Array.isArray(c.added) ? c.added : [],
    };
    const dishId = v.dishId || keyId;
    if (!dishId) return null;
    return { dishId: dishId, qty: q, modifier: mod, cust: cust };
  }
  const q = Math.floor(Number(v) || 0);
  return q > 0 && keyId ? { dishId: keyId, qty: q, modifier: null, cust: emptyCust() } : null;
}
function loadCart() {
  try {
    const c = JSON.parse(localStorage.getItem('ehf_cart') || 'null');
    // Graceful migration: the old shape {vendorId, items} becomes {items};
    // pre-v16 carts keyed lines by bare dishId — rekey to "dishId|sig".
    // Never crash on junk — bad entries are dropped, good ones kept.
    if (c && typeof c === 'object') {
      const raw = (c.items && typeof c.items === 'object') ? c.items : {};
      const items = {};
      for (const k of Object.keys(raw)) {
        const e = normCartEntry(raw[k], k);
        if (e) {
          const nk = lineKey(e.dishId, e);
          if (items[nk]) items[nk].qty = Math.min(50, items[nk].qty + e.qty);
          else items[nk] = e;
        }
      }
      return { items };
    }
  } catch (e) { /* ignore */ }
  return { items: {} };
}
function saveCart() { localStorage.setItem('ehf_cart', JSON.stringify(S.cart)); }

/* Per-vendor checkout group state, with defaults derived from what the
   vendor actually offers (delivery-only vendors default to delivery). */
function checkoutGroup(vendor) {
  const id = String(vendor.id);
  if (!S.checkout.groups[id]) {
    const f = String(vendor.fulfillment || 'both').toLowerCase();
    S.checkout.groups[id] = {
      fulfillment: f === 'delivery' ? 'delivery' : 'pickup',
      pickupAt: '',
      notes: '',
      pickupSlotId: null,  // === F8: chosen weekly pickup slot ===
    };
  }
  return S.checkout.groups[id];
}
/* Coerce a group's fulfillment when the vendor doesn't offer it — including the
   delivery-ZIP gate: a delivery zone must serve the customer's ZIP. */
function coerceGroupFulfillment(vendor, g) {
  const f = String(vendor.fulfillment || 'both').toLowerCase();
  const allowPickup = f === 'pickup' || f === 'both';
  const allowDelivery = groupDeliveryAllowed(vendor);
  if (!allowPickup && g.fulfillment === 'pickup') g.fulfillment = 'delivery';
  if (!allowDelivery && g.fulfillment === 'delivery') g.fulfillment = 'pickup';
  return { allowPickup, allowDelivery };
}
/* Cart lines grouped by vendor: [{vendor, lines:[{dish, qty}], subtotal, fee, g, freeDelivery}] */
async function cartGroups() {
  const lines = await cartLines();
  const byVendor = new Map();
  for (const l of lines) {
    const vid = l.dish.vendor_id;
    if (!byVendor.has(vid)) byVendor.set(vid, []);
    byVendor.get(vid).push(l);
  }
  const groups = [];
  for (const [vid, vlines] of byVendor) {
    let vendor = S.vendorById[vid];
    if (!vendor) {
      try { vendor = await api('/vendors/' + vid).then(x => (S.vendorById[x.id] = x)); }
      catch (e) {
        vendor = { id: vid, name: t('unknown_vendor'), fulfillment: 'both', delivery_fee: 0 };
      }
    }
    const g = checkoutGroup(vendor);
    coerceGroupFulfillment(vendor, g);
    const subtotal = vlines.reduce((a, l) => a + l.unit * l.qty, 0);
    let fee = g.fulfillment === 'delivery' ? Number(vendor.delivery_fee) || 0 : 0;
    // === v46: free delivery over the vendor's threshold — mirrors the
    // backend rule (pre-discount items subtotal at/above the threshold). ===
    let freeDelivery = false;
    if (g.fulfillment === 'delivery') {
      const fdo = freeDeliveryOver(vendor);
      if (fdo !== null && subtotal >= fdo) { fee = 0; freeDelivery = true; }
    }
    // === END v46 ===
    groups.push({ vendor, lines: vlines, subtotal, fee, g, freeDelivery });
  }
  return groups;
}

/* ================= helpers ================= */
const $ = (sel) => document.querySelector(sel);

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}
function money(v) {
  const n = Number(v);
  return '$' + (isNaN(n) ? '0.00' : n.toFixed(2));
}
/* Effective price: the backend ships sale_price; fall back to computing it
   from discount_percent so older cached dish objects still work. */
function salePrice(dish) {
  if (dish.sale_price != null && dish.sale_price !== '') return Number(dish.sale_price);
  const d = Number(dish.discount_percent) || 0;
  return Math.round(Number(dish.price) * (1 - d / 100) * 100) / 100;
}
function hasDiscount(dish) { return effDiscPct(dish) > 0; }
/* === FEATURE 7: effective discount — flash-sale-aware. The backend ships
   sale_price (the price the customer actually pays); the badge percent is
   derived from it so flash sales (discount_percent=0, sale live) still
   show a strikethrough + badge. Falls back to discount_percent for old
   cached rows without sale_price. === */
function effDiscPct(dish) {
  const p = Number(dish.price) || 0;
  const sp = Number(dish.sale_price);
  if (p > 0 && isFinite(sp) && sp < p) return Math.round((1 - sp / p) * 100);
  return Number(dish.discount_percent) || 0;
}
/* === END FEATURE 7 === */
/* Prep time: dish-level minutes override the vendor's shop default (30). */
function prepMins(dish, vendor) {
  if (dish && dish.prep_minutes !== null && dish.prep_minutes !== undefined && dish.prep_minutes !== '') {
    const m = Number(dish.prep_minutes);
    if (isFinite(m) && m >= 0) return Math.round(m);
  }
  if (vendor && vendor.prep_minutes !== null && vendor.prep_minutes !== undefined) {
    const m = Number(vendor.prep_minutes);
    if (isFinite(m) && m >= 0) return Math.round(m);
  }
  return 30;
}
/* 25 -> "25 min"; 90 -> "1 hr 30 min". */
function fmtDur(mins) {
  const m = Math.max(0, Math.round(Number(mins) || 0));
  if (m < 60) return t('mins_short', { n: m });
  const h = Math.floor(m / 60), r = m % 60;
  return r ? t('hrs_mins_short', { h: h, n: r }) : t('hrs_short', { h: h });
}
/* Price HTML: strikethrough original + bold sale + -X% badge when discounted. */
function priceHTML(dish) {
  if (!hasDiscount(dish)) return '<span class="price">' + money(dish.price) + '</span>';
  return '<span class="price"><s class="was">' + money(dish.price) + '</s> ' +
    '<strong class="now">' + money(salePrice(dish)) + '</strong> ' +
    '<span class="disc-badge">-' + effDiscPct(dish) + '%' + (dish.sale_active ? ' ⚡' : '') + '</span></span>';
}
function mapsUrl(addr) {
  // Official Google Maps universal URL — no API key needed.
  return 'https://www.google.com/maps/search/?api=1&query=' + encodeURIComponent(addr || '');
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
  try {
    return d.toLocaleString(lang() === 'ar' ? 'ar-EG' : 'en-US', {
      timeZone: MARKET_TIME_ZONE,
    });
  } catch (e) { return d.toLocaleString(); }
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
function stars(n) {
  n = Math.max(0, Math.min(5, Math.round(Number(n) || 0)));
  return '<span class="stars">' + '★'.repeat(n) + '☆'.repeat(5 - n) + '</span>';
}

async function api(path, opts) {
  opts = opts || {};
  const headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
  if (S.token) headers['Authorization'] = 'Bearer ' + S.token;
  // === v50: request timeout. A sleeping free-tier server (wake-up can
  // take ~60s) must not leave a view sitting on its loading state
  // forever — abort the request so callers can retry or show an error.
  // opts.timeoutMs overrides; opts.signal (caller's own) wins as-is. ===
  let signal = opts.signal;
  let timer = null;
  if (!signal && typeof AbortController !== 'undefined') {
    const ctl = new AbortController();
    signal = ctl.signal;
    timer = setTimeout(() => ctl.abort(), opts.timeoutMs || 20000);
  }
  try {
    let res;
    try {
      res = await fetch('/api' + path, Object.assign({}, opts, { headers, signal }));
    } catch (e) {
      // Cross-realm AbortSignal: DOM test harnesses pair this realm's
      // AbortController with a foreign fetch that rejects the signal as
      // "not an instance of AbortSignal". Retry once without the signal
      // (that realm simply gets no abort-timeout). Real browsers share
      // one realm and never take this branch.
      if (timer && e && e.name === 'TypeError' && /signal/i.test(e.message || '')) {
        res = await fetch('/api' + path, Object.assign({}, opts, { headers, signal: undefined }));
      } else {
        throw e;
      }
    }
    if (res.status === 401) { logout(true); throw new Error(t('session_expired')); }
    if (!res.ok) {
      let msg = res.statusText;
      try { const j = await res.json(); if (j && j.detail) msg = j.detail; } catch (e) { /* ignore */ }
      const err = new Error(msg);
      err.status = res.status; // let callers distinguish 422 validation from 429 rate limit
      throw err;
    }
    if (res.status === 204) return null;
    return res.json();
  } finally {
    if (timer) clearTimeout(timer);
  }
}

function photoFor(dish) {
  const t = ((dish.name || '') + ' ' + (dish.description || '')).toLowerCase();
  for (const r of PHOTO_RULES) {
    for (const k of r.k) { if (t.indexOf(k) !== -1) return r; }
  }
  return DEFAULT_PHOTO;
}
function imgUrl(file) {
  return 'img/' + file;
}
function dishImg(dish, extraCls) {
  const cls = 'dish-img' + (extraCls ? ' ' + extraCls : '');
  if (dish.photo_url) {
    // vendor-supplied photo wins over the name-matched rules
    return '<img class="' + cls + '" src="' + esc(dish.photo_url) + '" alt="' + esc(dish.name) +
      '" loading="lazy" decoding="async" onerror="imgFallback(this)">';
  }
  const p = photoFor(dish);
  if (p.tile) {
    // emoji tile rendered directly — no photo to load
    return '<div class="' + cls + ' fallback">' + esc(p.emoji || '🍽️') + '</div>';
  }
  return '<img class="' + cls + '" src="' + imgUrl(p.img) + '" alt="' + esc(dish.name) +
    '" loading="lazy" decoding="async" data-emoji="' + p.emoji + '" onerror="imgFallback(this)">';
}
window.imgFallback = function (el) {
  const d = document.createElement('div');
  d.className = el.className + ' fallback';
  d.textContent = el.getAttribute('data-emoji') || '🍽️';
  el.replaceWith(d);
};

/* ================= v49: FULL MOTION PACKAGE =================
   Hero video, scroll reveals, dish marquee, stories carousel, badge pop.
   Vanilla only. Safety rules:
   - Content is VISIBLE BY DEFAULT. JS only *arms* hidden states when
     motion is allowed, and every armed element is force-revealed by a
     timer even if IntersectionObserver never fires — nothing can get
     stuck invisible.
   - prefers-reduced-motion: nothing is armed, the hero video never
     autoplays (poster only), the carousel never auto-advances. */
const MOTION_REDUCED = !!(window.matchMedia &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches);
function motionRTL() { return document.documentElement.dir === 'rtl'; }

/* ---------- scroll reveals ---------- */
const REVEAL_SELECTOR = '.dish-card, .vendor-card, .home-section, .testi-card, ' +
  '.home-video-card, .chef-card, .order-card, .section-title';
const revealArmed = new WeakSet();
let revealIO = null;
if (!MOTION_REDUCED && 'IntersectionObserver' in window) {
  revealIO = new IntersectionObserver(function (entries) {
    entries.forEach(function (en) {
      if (en.isIntersecting) { finishReveal(en.target); revealIO.unobserve(en.target); }
    });
  }, { threshold: 0.06, rootMargin: '0px 0px -3% 0px' });
}
function finishReveal(el) {
  if (!el.classList.contains('reveal-init') || el.classList.contains('revealed')) return;
  el.classList.add('revealed');
  setTimeout(function () {
    el.classList.remove('reveal-init');
    el.style.transitionDelay = '';
  }, 800);
}
function armReveal(el) {
  if (MOTION_REDUCED || revealArmed.has(el)) return;
  revealArmed.add(el);
  if (!revealIO) return; // no observer support → leave visible, never arm
  const idx = el.parentElement ? Array.prototype.indexOf.call(el.parentElement.children, el) : 0;
  el.style.transitionDelay = Math.min(Math.max(idx, 0), 6) * 55 + 'ms';
  el.classList.add('reveal-init');
  revealIO.observe(el);
  setTimeout(function () { finishReveal(el); }, 2800); // safety sweep
}

/* ---------- hero video: play/pause with visibility ---------- */
function wireHeroVideo(v) {
  if (!v || v.dataset.wired) return;
  v.dataset.wired = '1';
  if (MOTION_REDUCED) { try { v.pause(); } catch (e) { /* noop */ } return; }
  const tryPlay = function () { const p = v.play && v.play(); if (p && p.catch) p.catch(function () {}); };
  tryPlay();
  if ('IntersectionObserver' in window) {
    const io = new IntersectionObserver(function (es) {
      es.forEach(function (en) {
        if (!v.isConnected) { io.disconnect(); return; }
        if (en.isIntersecting) tryPlay(); else { try { v.pause(); } catch (e) { /* noop */ } }
      });
    }, { threshold: 0.05 });
    io.observe(v);
  }
}

/* ---------- stories carousel (testimonials) ---------- */
function mountCarousel(el) {
  if (!el || el.dataset.mounted) return;
  el.dataset.mounted = '1';
  const track = el.querySelector('.stories-track');
  const slides = el.querySelectorAll('.stories-slide');
  if (!track || slides.length < 2) return;
  const dotsWrap = el.querySelector('.stories-dots');
  let idx = 0, timer = null;
  const dots = [];
  slides.forEach(function (_, i) {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'stories-dot';
    b.setAttribute('aria-label', (i + 1) + ' / ' + slides.length);
    b.addEventListener('click', function () { goTo(i); restart(); });
    if (dotsWrap) dotsWrap.appendChild(b);
    dots.push(b);
  });
  function paint() {
    const sign = motionRTL() ? 1 : -1;
    track.style.transform = 'translateX(' + (sign * idx * 100) + '%)';
    dots.forEach(function (d, i) { d.classList.toggle('active', i === idx); });
    slides.forEach(function (s, i) { s.setAttribute('aria-hidden', i === idx ? 'false' : 'true'); });
  }
  function goTo(i) { idx = (i + slides.length) % slides.length; paint(); }
  function step(d) { goTo(idx + d); }
  const prev = el.querySelector('.stories-prev');
  const next = el.querySelector('.stories-next');
  if (prev) prev.addEventListener('click', function () { step(-1); restart(); });
  if (next) next.addEventListener('click', function () { step(1); restart(); });
  function start() {
    if (MOTION_REDUCED || timer) return;
    timer = setInterval(function () {
      if (!el.isConnected) { clearInterval(timer); timer = null; return; }
      if (document.hidden) return;
      step(1);
    }, 6000);
  }
  function stop() { if (timer) { clearInterval(timer); timer = null; } }
  function restart() { stop(); start(); }
  el.addEventListener('mouseenter', stop);
  el.addEventListener('mouseleave', start);
  el.addEventListener('focusin', stop);
  el.addEventListener('focusout', start);
  paint();
  start();
}

/* ---------- one scan wires every motion piece in a subtree ---------- */
function scanMotion(root) {
  const scope = root || document;
  if (!MOTION_REDUCED && revealIO) {
    scope.querySelectorAll(REVEAL_SELECTOR).forEach(armReveal);
  }
  scope.querySelectorAll('video.hero-video').forEach(wireHeroVideo);
  scope.querySelectorAll('.stories-carousel').forEach(mountCarousel);
}
/* Views render by swapping innerHTML (home, grids on filter, the async
   testimonial injection) — watch #app and wire whatever appears. */
(function () {
  const appEl = document.getElementById('app');
  if (!appEl || !('MutationObserver' in window)) { scanMotion(document); return; }
  let queued = false;
  const mo = new MutationObserver(function () {
    if (queued) return;
    queued = true;
    setTimeout(function () { queued = false; scanMotion(appEl); }, 30);
  });
  mo.observe(appEl, { childList: true, subtree: true });
  scanMotion(appEl);
})();
/* ================= END v49 motion package ================= */

function fulfillBadge(v) {
  const f = (v.fulfillment || 'pickup').toLowerCase();
  const label = f === 'pickup' ? t('fulfill_pickup') : f === 'delivery' ? t('fulfill_delivery') : t('fulfill_both');
  return '<span class="fulfill-badge ' + esc(f) + '">' + esc(label) + '</span>';
}

/* ================= delivery ZIP (Oct 2026) ================= */
/* The customer's delivery ZIP, persisted in localStorage ('ehf_zip').
   New backend contract: vendor.delivery_zips is a comma-separated string of
   5-digit ZIPs (or null); blank/null = pickup only. */
function getZip() {
  try { const z = (localStorage.getItem('ehf_zip') || '').trim(); return /^\d{5}$/.test(z) ? z : ''; }
  catch (e) { return ''; }
}
function saveZip(z) {
  try { localStorage.setItem('ehf_zip', z); } catch (e) { /* ignore */ }
}
/* "98052, 98201" -> ['98052','98201']; defensive — unparsable parts are dropped. */
function vendorDeliveryZips(v) {
  if (!v || v.delivery_zips === undefined || v.delivery_zips === null) return [];
  return String(v.delivery_zips).split(',').map(function (s) { return s.trim(); })
    .filter(function (s) { return /^\d{5}$/.test(s); });
}
/* Can this vendor deliver at all? Respects fulfillment AND the new zones:
   blank/null delivery_zips = pickup only. When the backend hasn't shipped the
   field yet (key absent), fall back to the legacy fulfillment-only behavior. */
function vendorOffersDelivery(v) {
  if (!v) return false;
  const f = String(v.fulfillment || 'both').toLowerCase();
  if (f === 'pickup') return false;
  if (v.delivery_zips !== undefined) return vendorDeliveryZips(v).length > 0;
  return true; // legacy: no zones to check against
}
/* Does this vendor deliver to the given ZIP? */
function vendorServesZip(v, zip) {
  if (!zip || !vendorOffersDelivery(v)) return false;
  if (v.delivery_zips === undefined) return true; // legacy: no zones to check against
  return vendorDeliveryZips(v).indexOf(zip) !== -1;
}
/* Should the checkout offer Delivery for this vendor's group right now? */
function groupDeliveryAllowed(v) {
  const f = String(v.fulfillment || 'both').toLowerCase();
  if (!(f === 'delivery' || f === 'both')) return false;
  if (!vendorOffersDelivery(v)) return false;
  if (v.delivery_zips !== undefined && !vendorServesZip(v, getZip())) return false;
  return true;
}
/* Badge for vendor cards + storefronts: delivers to YOUR zip, pickup only, or
   a prompt to enter a ZIP when none is set. */
function zipDeliveryBadge(v) {
  const zip = getZip();
  if (vendorServesZip(v, zip)) {
    return '<span class="zip-badge delivers">' + esc(t('delivers_to_zip')) + '</span>';
  }
  if (vendorOffersDelivery(v) && !zip) {
    return '<button type="button" class="zip-badge zip-prompt" onclick="event.stopPropagation();zipFormOpen()">' +
      esc(t('enter_zip_to_check')) + '</button>';
  }
  return '<span class="zip-badge pickup-only">' + esc(t('pickup_only')) + '</span>';
}
/* ================= v46: free delivery over a threshold ================= */
/* The vendor's free-delivery threshold in dollars, or null when the feature
   is off (field absent/null — older cached vendor objects included). */
function freeDeliveryOver(v) {
  if (!v || v.free_delivery_over === null || v.free_delivery_over === undefined || v.free_delivery_over === '') return null;
  const n = Number(v.free_delivery_over);
  return isFinite(n) && n >= 0 ? n : null;
}
/* Badge for vendor cards + storefronts: "Free delivery over $X". */
function freeDeliveryBadge(v) {
  const fdo = freeDeliveryOver(v);
  if (fdo === null) return '';
  return '<span class="zip-badge delivers">🛵 ' + esc(t('free_delivery_over', { amount: money(fdo) })) + '</span>';
}
/* ================= END v46 ================= */
/* Header ZIP widget: saved ZIP (or an "enter ZIP" prompt) with an inline
   editable form. Rendered by JS into #zip-wrap. */
function renderZipWidget() {
  const wrap = document.getElementById('zip-wrap');
  if (!wrap) return;
  const zip = getZip();
  if (S.zipOpen) {
    wrap.innerHTML = '<form class="zip-form" onsubmit="return zipSave(this)">' +
      '<input inputmode="numeric" maxlength="5" placeholder="' + esc(t('zip_ph')) + '" value="' + esc(zip) + '"' +
      ' aria-label="' + esc(t('zip_label')) + '" autocomplete="postal-code">' +
      '<button class="btn small" type="submit">' + esc(t('zip_save')) + '</button>' +
      '<button class="btn small secondary" type="button" onclick="zipFormClose()">' + esc(t('cancel')) + '</button>' +
      '<span class="zip-err" role="alert"></span></form>';
    const inp = wrap.querySelector('input');
    if (inp) inp.focus();
  } else {
    wrap.innerHTML = '<button type="button" class="zip-chip' + (zip ? ' set' : '') + '" onclick="zipFormOpen()" ' +
      'aria-label="' + esc(zip ? t('zip_change_label', { zip: zip }) : t('zip_enter')) + '">' +
      (zip ? '📍 ' + esc(zip) + ' <span class="zip-edit">' + esc(t('zip_change')) + '</span>'
           : '📍 ' + esc(t('zip_enter'))) + '</button>';
  }
}
window.zipFormOpen = function () { S.zipOpen = true; renderZipWidget(); };
window.zipFormClose = function () { S.zipOpen = false; renderZipWidget(); };
/* Save from the header widget OR the hero banner form (both are .zip-form). */
window.zipSave = function (form) {
  const inp = form.querySelector('input');
  const err = form.querySelector('.zip-err');
  const z = ((inp && inp.value) || '').trim();
  if (!/^\d{5}$/.test(z)) {
    if (err) err.textContent = t('zip_invalid');
    if (inp) inp.focus();
    return false;
  }
  saveZip(z);
  S.zipOpen = false;
  renderZipWidget();
  // Refresh any ZIP-dependent UI on the current view.
  if (S.route === 'home') vHome();
  else if (S.route === 'vendor') vVendor(S.routeArg);
  else if (S.route === 'cart') vCart();
  return false;
};
/* ================= END delivery ZIP ================= */

/* ================= chef's signature (Oct 2026) ================= */
function sigPill(dish) {
  return dish && dish.is_signature
    ? '<span class="sig-pill">⭐ ' + esc(t('chefs_signature')) + '</span>'
    : '';
}
/* ================= END chef's signature ================= */

/* ================= auth ================= */
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
  S.token = null; S.user = null; S.favs = new Set();
  localStorage.removeItem('ehf_token');
  updateAuthArea();
  if (!silent) go('home');
}
/* Public site settings (auth-free): the admin-set tax rate + site name.
   Raw fetch on purpose — never api(), which would log the user out on a
   401. Any failure (network, non-OK, bad payload) keeps the TAX_RATE
   fallback (0) so the checkout preview still renders. */
async function loadPublicSettings() {
  try {
    const res = await fetch('/api/settings/public');
    if (!res.ok) return;
    const j = await res.json();
    const rate = Number(j && j.tax_rate);
    if (Number.isFinite(rate) && rate >= 0 && rate <= 1) {
      S.publicSettings = { tax_rate: rate, site_name: (j && j.site_name) || '' };
    }
  } catch (e) { /* keep defaults */ }
}
let _lastCartN = null; // v49: badge pop only when the count grows
function updateAuthArea() {
  const area = $('#auth-area');
  const badge = $('#cart-badge');
  const n = cartCount();
  badge.textContent = n;
  badge.classList.toggle('hidden', n === 0);
  if (_lastCartN !== null && n > _lastCartN && !MOTION_REDUCED) {
    badge.classList.remove('badge-pop');
    void badge.offsetWidth; // restart the keyframe animation
    badge.classList.add('badge-pop');
  }
  _lastCartN = n;
  const cartLink = $('#nav-cart');
  if (cartLink) cartLink.setAttribute('aria-label', t('cart_live_count', { count: n }));
  const cartLive = $('#cart-live');
  if (cartLive) cartLive.textContent = t('cart_live_count', { count: n });
  $('#nav-orders').classList.toggle('hidden', !(S.user && (S.user.role === 'customer' || S.user.role === 'admin')));
  $('#nav-profile').classList.toggle('hidden', !(S.user && S.user.role === 'customer'));
  $('#nav-favorites').classList.toggle('hidden', !(S.user && S.user.role === 'customer'));
  document.querySelectorAll('#main-nav a').forEach(a => {
    a.classList.toggle('active', a.dataset.go === S.route);
  });
  if (S.user) {
    area.innerHTML = (S.user.role === 'admin'
      ? '<a class="btn small secondary" href="/admin/delivery" data-go="delivery-admin">🚚 Delivery Management</a>'
      : '') +
      '<span>👋 ' + esc(S.user.name) + '</span>' +
      '<button class="btn small secondary" onclick="logout()">' + esc(t('nav_logout')) + '</button>';
  } else {
    area.innerHTML = '<a href="#" data-go="login">' + esc(t('nav_login')) + '</a>' +
      '<a class="btn small" href="#" data-go="signup">' + esc(t('nav_signup')) + '</a>';
  }
  syncInternalLinks();
}
window.logout = logout;

/* ================= router ================= */
function routePath(route, arg) {
  if (route === 'dish') return '/dish/' + encodeURIComponent(arg);
  if (route === 'vendor') return '/cook/' + encodeURIComponent(arg);
  if (route === 'order') return '/orders/' + encodeURIComponent(arg);
  if (route === 'paid') {
    const id = arg && typeof arg === 'object' ? arg.id : arg;
    const sid = arg && typeof arg === 'object' && arg.sessionId ? '?session_id=' + encodeURIComponent(arg.sessionId) : '';
    return '/orders/' + encodeURIComponent(id) + '/paid' + sid;
  }
  if (route === 'verify-email' && arg) return '/verify-email?token=' + encodeURIComponent(arg);
  const paths = {
    home: '/', cart: '/cart', review: '/checkout/review', confirm: '/confirmation',
    login: '/login', signup: '/signup', orders: '/orders', bundles: '/bundles',
    profile: '/profile', groceries: '/groceries', dishes: '/dishes', favorites: '/favorites',
    forgot: '/forgot-password', reset: '/reset-password', 'verify-email': '/verify-email',
    about: '/about', faq: '/faq', terms: '/terms', privacy: '/privacy', help: '/help',
    apply: '/apply', catering: '/catering', 'paid-checkout': '/payment-complete',
    'delivery-admin': '/admin/delivery',
  };
  return paths[route] || '/';
}
function parsePathRoute() {
  const path = window.location.pathname.replace(/\/+$/, '') || '/';
  let match = path.match(/^\/dish\/(\d+)$/);
  if (match) return { route: 'dish', arg: Number(match[1]) };
  match = path.match(/^\/cook\/(\d+)$/);
  if (match) {
    const ref = new URLSearchParams(window.location.search).get('ref');
    if (ref) {
      S.referral = ref.trim() || null;
      if (S.referral) localStorage.setItem('ehf_referral', S.referral);
    }
    return { route: 'vendor', arg: Number(match[1]) };
  }
  match = path.match(/^\/orders\/(\d+)\/paid$/);
  if (match) return { route: 'paid', arg: { id: Number(match[1]), sessionId: new URLSearchParams(window.location.search).get('session_id') } };
  match = path.match(/^\/orders\/(\d+)$/);
  if (match) return { route: 'order', arg: Number(match[1]) };
  match = path.match(/^\/verify-email\/([^/]+)$/);
  if (match) return { route: 'verify-email', arg: decodeURIComponent(match[1]) };
  const pages = {
    '/': 'home', '/home': 'home', '/cart': 'cart', '/checkout': 'review', '/checkout/review': 'review',
    '/confirmation': 'confirm', '/login': 'login', '/signup': 'signup', '/orders': 'orders',
    '/bundles': 'bundles', '/profile': 'profile', '/groceries': 'groceries', '/dishes': 'dishes',
    '/favorites': 'favorites', '/forgot-password': 'forgot', '/forgot': 'forgot',
    '/reset-password': 'reset', '/reset': 'reset', '/verify-email': 'verify-email',
    '/about': 'about', '/faq': 'faq', '/terms': 'terms', '/privacy': 'privacy',
    '/help': 'help', '/apply': 'apply', '/catering': 'catering',
    '/payment-complete': 'paid-checkout', '/admin/delivery': 'delivery-admin',
  };
  const route = pages[path];
  if (!route) return null;
  if (route === 'verify-email') return { route, arg: new URLSearchParams(window.location.search).get('token') };
  return { route, arg: null };
}
function syncInternalLinks() {
  document.querySelectorAll('[data-go]').forEach(function (link) {
    link.setAttribute('href', routePath(link.dataset.go));
  });
}
function go(route, arg, navigation) {
  const path = routePath(route, arg);
  if (navigation && navigation.replace) history.replaceState({ route, arg }, '', path);
  else if (window.location.pathname + window.location.search !== path) history.pushState({ route, arg }, '', path);
  stopMsgPoll();
  // === F10: stop the retry-countdown ticker when leaving My Orders ===
  if (S.retryTimer) { clearInterval(S.retryTimer); S.retryTimer = null; }
  // === END F10 ===
  S.route = route;
  S.routeArg = (arg === undefined ? null : arg);
  let canonical = document.head.querySelector('link[rel="canonical"]');
  if (!canonical) {
    canonical = document.createElement('link');
    canonical.rel = 'canonical';
    document.head.appendChild(canonical);
  }
  canonical.href = new URL(path, window.location.origin).href;
  window.scrollTo(0, 0);
  render();
  syncInternalLinks();
  updateAuthArea();
}
window.go = go;

window.browseHome = function () {
  go('dishes');
};

document.addEventListener('click', (e) => {
  if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  const browseLink = e.target.closest('[data-browse]');
  if (browseLink) { e.preventDefault(); browseHome(); return; }
  const a = e.target.closest('[data-go]');
  if (a) { e.preventDefault(); go(a.dataset.go); }
});
window.addEventListener('popstate', function () {
  const legacy = window.location.pathname === '/' && window.location.hash ? parseReturnHash() : null;
  const current = legacy || parsePathRoute() || { route: 'home', arg: null };
  go(current.route, current.arg, { replace: true });
});

function render() {
  const app = $('#app');
  const flash = S.flash ? '<div class="notice">' + esc(S.flash) + '</div>' : '';
  S.flash = null;
  removeDishJsonLd(); // dish detail pages inject their own SEO tags
  let html = '';
  try {
    switch (S.route) {
      case 'vendor': html = '<div id="view"></div>'; break;
      case 'cart': html = '<div id="view"></div>'; break;
      case 'review': html = '<div id="view"></div>'; break;
      case 'confirm': html = '<div id="view"></div>'; break;
      case 'login': html = vLogin(); break;
      case 'signup': html = vSignup(); break;
      case 'orders': html = '<div id="view"></div>'; break;
      case 'order': html = '<div id="view"></div>'; break;
      // === F5: bundles discoverable listing ===
      case 'bundles': html = '<div id="view"></div>'; break;
      // === END F5 ===
      case 'paid': html = '<div id="view"></div>'; break;
      case 'paid-checkout': html = '<div id="view"></div>'; break;
      case 'profile': html = '<div id="view"></div>'; break;
      case 'groceries': html = '<div id="view"></div>'; break;
      case 'dishes': html = '<div id="view"></div>'; break;
      case 'favorites': html = '<div id="view"></div>'; break;
      case 'forgot': html = vForgot(); break;
      case 'reset': html = vReset(); break;
      case 'verify-email': html = '<div id="view"></div>'; break;
      case 'about': html = vAbout(); break;
      case 'faq': html = vFaq(); break;
      case 'terms': html = vTerms(); break;
      case 'privacy': html = vPrivacy(); break;
      case 'help': html = '<div id="view"></div>'; break;
      case 'apply': html = '<div id="view"></div>'; break;
      case 'catering': html = '<div id="view"></div>'; break;
      case 'delivery-admin': html = '<div id="view"></div>'; break;
      default: html = '<div id="view"></div>';
    }
  } catch (e) {
    html = '<div class="error">' + t('err_generic') + esc(e.message) + '</div>';
  }
  app.innerHTML = flash + html;
  syncInternalLinks();
  // async views fill #view
  if (S.route === 'home') vHome();
  else if (S.route === 'dish') vDishDetail(S.routeArg);
  else if (S.route === 'vendor') vVendor(S.routeArg);
  else if (S.route === 'cart') vCart();
  else if (S.route === 'review') vReview();
  else if (S.route === 'confirm') vConfirm();
  else if (S.route === 'orders') vOrders();
  else if (S.route === 'order') vCustomerOrder(S.routeArg);
  // === F5: bundles discoverable listing ===
  else if (S.route === 'bundles') vBundles();
  // === END F5 ===
  else if (S.route === 'paid') vPaid(S.routeArg);
  else if (S.route === 'paid-checkout') vPaidCheckout();
  else if (S.route === 'profile') vProfile();
  else if (S.route === 'groceries') vGroceries();
  else if (S.route === 'dishes') vDishes();
  else if (S.route === 'favorites') vFavorites();
  else if (S.route === 'help') vHelp();
  else if (S.route === 'verify-email') vVerifyEmail(S.routeArg);
  else if (S.route === 'apply') vApply();
  else if (S.route === 'catering') vCatering();
  else if (S.route === 'delivery-admin') vDeliveryAdmin();
}

/* ================= cart ================= */
function cartCount() {
  return Object.values(S.cart.items).reduce((a, e) => a + (e && e.qty || 0), 0);
}
/* Cart lines are keyed "dishId|sig" so the SAME dish with DIFFERENT sides /
   customizations lives on separate lines instead of overwriting each other. */
function lineSig(entry) {
  // Fish units carry unique identities so identical side selections never merge.
  const fishUnit = entry && entry.fishUnitId ? '#fish-unit:' + entry.fishUnitId : '';
  // === F5: bundle lines have no customizations — one line per bundle ===
  if (entry && entry.bundleId) return 'bundle';
  // === END F5 ===
  const c = (entry && entry.cust) || emptyCust();
  const mods = (c.modifiers || []).map(function (m) {
    return m.option_id + ':' + (m.choices || []).map(function (x) {
      return x.label + '~' + (Number(x.delta) || 0);
    }).sort().join(',');
  }).sort().join(';');
  const rem = (c.removed || []).slice().sort().join(',');
  const add = (c.added || []).map(function (a) {
    return (a && a.name !== undefined ? a.name : String(a)) + '~' + (Number(a && a.delta) || 0);
  }).sort().join(',');
  const leg = entry && entry.modifier && entry.modifier.choice_label
    ? entry.modifier.choice_label + '~' + (Number(entry.modifier.delta) || 0) : '';
  return mods + '#' + rem + '#' + add + '#' + leg + fishUnit;
}
function isWholeGrilledFish(dish) {
  return !!dish && String(dish.name || '').trim().toLowerCase() === 'whole grilled fish' && Number(dish.price) === 18;
}
function newFishUnitId() {
  S.fishUnitSeq = (Number(S.fishUnitSeq) || 0) + 1;
  return String(Date.now()) + '-' + S.fishUnitSeq;
}
function lineKey(dishId, entry) { return dishId + '|' + lineSig(entry); }
function entryDishId(key, entry) {
  if (entry && entry.dishId) return entry.dishId;
  const n = parseInt(String(key).split('|')[0], 10);
  return isNaN(n) ? null : n;
}
function dishLineKeys(dishId) {
  return Object.keys(S.cart.items).filter(function (k) {
    return entryDishId(k, S.cart.items[k]) === Number(dishId);
  });
}
function cartQty(dishId) {
  return dishLineKeys(dishId).reduce(function (a, k) {
    const e = S.cart.items[k]; return a + (e && e.qty || 0);
  }, 0);
}
/* The most recently touched line for a dish (insertion order = recency;
   touched lines are re-inserted last). */
function lastDishLineKey(dishId) {
  const ks = dishLineKeys(dishId);
  return ks.length ? ks[ks.length - 1] : null;
}
function touchLine(key) {
  const e = S.cart.items[key];
  if (!e) return;
  delete S.cart.items[key];
  S.cart.items[key] = e;
}

async function dishName(id) {
  if (S.dishById[id]) return S.dishById[id];
  try {
    const d = await api('/dishes/' + id);
    S.dishById[id] = d;
    return d;
  } catch (e) {
    // Dish deleted or hidden since it entered the cart — callers skip it.
    return null;
  }
}

window.addToCart = async function (dishId) {
  const dish = await dishName(dishId);
  if (!dish) { alert(t('dish_not_found')); return; }
  if (!dish.available) { alert(t('dish_unavailable')); return; }
  // Advance ordering / weekly specials: block outside the order window
  // (evaluated in America/Los_Angeles); the server re-checks at checkout.
  if (dishRestricted(dish) && !dishWindow(dish).open) {
    alert(orderWindowBlockMsg(dish));
    return;
  }
  // Multi-vendor cart: dishes from any vendor just get added. No conflict.
  // The dish page's option groups + ingredient toggles ride along.
  const cust = chosenCustomizations(dish);
  // Min-selection guard (dish page only — quick-add from cards uses defaults).
  if (dishPageActive(dish.id)) {
    const groups = dishOptionGroups(dish);
    for (let gi = 0; gi < groups.length; gi++) {
      const g = groups[gi];
      if (g.min > 0) {
        const m = cust.modifiers.find(function (x) { return x.gi === gi; });
        if (!m || m.choices.length < g.min) {
          alert(t('opt_min_hit', { n: g.min, name: g.name || t('mod_title') }));
          return;
        }
      }
    }
  }
  // Each Whole Grilled Fish is an independently customizable unit, even when
  // its sides match another fish in the cart. The checkout payload therefore
  // sends one order line per fish with that fish's own sides.
  const fishUnitId = isWholeGrilledFish(dish) ? newFishUnitId() : null;
  const entry = { dishId: dish.id, qty: 1, modifier: null, cust: cust };
  if (fishUnitId) entry.fishUnitId = fishUnitId;
  const key = lineKey(dish.id, entry);
  const cur = S.cart.items[key];
  S.cart.items[key] = cur && !fishUnitId
    ? { dishId: dish.id, qty: cur.qty + 1, modifier: null, cust: cust }
    : entry;
  touchLine(key);
  saveCart();
  refreshSteppers(dish.id);
  updateAuthArea();
};

/* Dish-card stepper: operates on the dish's most recently touched line so
   quick +/− keeps working when a dish has several customized lines. */
window.setQty = function (dishId, qty) {
  qty = Math.max(0, Math.min(50, qty | 0));
  const key = lastDishLineKey(dishId);
  if (!key) return;
  const dish = S.dishById[dishId];
  if (isWholeGrilledFish(dish)) {
    const current = cartQty(dishId);
    if (qty < current) {
      const e = S.cart.items[key];
      if (e.qty > 1) e.qty -= 1;
      else delete S.cart.items[key];
    } else if (qty > current) {
      const source = S.cart.items[key];
      const copy = { dishId: source.dishId, qty: 1, modifier: source.modifier || null,
        cust: JSON.parse(JSON.stringify(source.cust || emptyCust())), fishUnitId: newFishUnitId() };
      S.cart.items[lineKey(dishId, copy)] = copy;
    }
  } else if (qty === 0) delete S.cart.items[key];
  else {
    S.cart.items[key].qty = qty;
    touchLine(key);
  }
  saveCart();
  refreshSteppers(dishId);
  updateAuthArea();
  if (S.route === 'cart') vCart();
  if (S.route === 'review') vReview();
};

/* Cart-page line stepper: addresses one exact line (dish + customizations). */
window.setLineQty = function (key, qty) {
  qty = Math.max(0, Math.min(50, qty | 0));
  const e = S.cart.items[key];
  if (!e) return;
  const dishId = e.dishId;
  const dish = S.dishById[dishId];
  if (isWholeGrilledFish(dish) && qty > 1) {
    // A line quantity above one would force every fish to share its sides.
    // Convert the increment into a new, independently editable fish line.
    e.qty = 1;
    const copy = { dishId: e.dishId, qty: 1, modifier: e.modifier || null,
      cust: JSON.parse(JSON.stringify(e.cust || emptyCust())), fishUnitId: newFishUnitId() };
    S.cart.items[lineKey(dishId, copy)] = copy;
    touchLine(lineKey(dishId, copy));
  } else if (qty === 0) delete S.cart.items[key];
  else {
    e.qty = isWholeGrilledFish(dish) ? 1 : qty;
    touchLine(key);
  }
  saveCart();
  refreshSteppers(dishId);
  updateAuthArea();
  if (S.route === 'cart') vCart();
  if (S.route === 'review') vReview();
};

function lineStepperHTML(line) {
  const q = line.qty;
  const k = line.key.replace(/\\/g, '\\\\').replace(/'/g, "\\'");
  return '<span class="stepper">' +
    '<button onclick="setLineQty(\'' + k + '\',' + (q - 1) + ')" aria-label="' + esc(t('aria_remove')) + '">−</button>' +
    '<span class="qty">' + q + '</span>' +
    '<button onclick="setLineQty(\'' + k + '\',' + (q + 1) + ')" aria-label="' + esc(t('aria_add')) + '">+</button>' +
    '</span>';
}

function refreshSteppers(dishId) {
  document.querySelectorAll('[data-stepper="' + dishId + '"]').forEach(el => {
    const dish = S.dishById[dishId];
    if (dish) el.outerHTML = (el.getAttribute('data-sp') === 'page' ? dishPageStepperHTML(dish) : stepperHTML(dish));
  });
  // Keep the dish-page "your variations" strip in sync too.
  const dish = S.dishById[dishId];
  const vs = document.getElementById('dish-vars-' + dishId);
  if (dish && vs) vs.outerHTML = dishVarsHTML(dish);
}

/* Dish page: "your variations" strip — makes ordering the same dish with
   different options visible and easy. Each customized cart line shows its
   options + a qty stepper; changing the options above and tapping + adds
   a new variation line. */
function dishVarsHTML(dish) {
  if (!dish) return '';
  const groups = dishOptionGroups(dish);
  const ings = dishIngredients(dish);
  if (!groups.length && !ings.length) return '';
  const keys = dishLineKeys(dish.id);
  let inner = '';
  if (keys.length) {
    inner = '<div class="vars-title">🧾 ' + esc(t('vars_in_cart')) + '</div>' +
      keys.map(function (k) {
        const e = S.cart.items[k] || {};
        return '<div class="vars-line"><div class="vars-info">' +
          custLinesHTML({ cust: e.cust || emptyCust() }) + '</div>' +
          lineStepperHTML({ key: k, qty: e.qty || 0 }) + '</div>';
      }).join('');
  } else {
    inner = '<div class="hint">' + esc(t('vars_hint')) + '</div>';
  }
  return '<div class="vars-strip" id="dish-vars-' + dish.id + '">' + inner + '</div>';
}

/* ============ v39: inline sides/ingredients editor in the cart ============
   Every customizable cart line gets a "Sides & extras" expander. The editor
   renders the dish's option groups + ingredient toggles right under the line,
   pre-selected with the line's current customizations. Each change re-keys
   the line (dishId|sig) so different sides stay separate lines — the same
   rule as the dish page's variations. No dish page, no popup. */
function leSafe(key) {
  S.leMap = S.leMap || {};
  for (const id in S.leMap) if (S.leMap[id] === key) return id;
  const id = 'le' + (S.leSeq = (S.leSeq || 0) + 1);
  S.leMap[id] = key;
  return id;
}
function rerenderCartView() {
  if (S.route === 'cart') vCart();
  else if (S.route === 'review') vReview();
}
window.toggleLineEdit = function (id) {
  const key = S.leMap && S.leMap[id];
  if (!key || !S.cart.items[key]) return;
  S.lineEditOpen = S.lineEditOpen || {};
  if (S.lineEditOpen[key]) delete S.lineEditOpen[key];
  else S.lineEditOpen[key] = true;
  rerenderCartView();
};
function lineEditHTML(l) {
  const id = leSafe(l.key);
  const dish = l.dish;
  const groups = dishOptionGroups(dish);
  const ings = dishIngredients(dish);
  const cust = l.cust || emptyCust();
  let h = '<div class="line-edit" id="lebox-' + id + '">';
  groups.forEach(function (g, gi) {
    const cur = (cust.modifiers || []).filter(function (m) { return m.gi === gi; })[0];
    const curLabels = {};
    ((cur && cur.choices) || []).forEach(function (c) { curLabels[c.label] = true; });
    const multi = g.type === 'multiple';
    h += '<div class="mod-picker"><div class="mod-title">🧩 ' + esc(g.name || t('mod_title')) + '</div>';
    if (multi) {
      h += '<div class="mod-sub">' + esc(t('opt_pick_many')) +
        (g.max !== null ? ' ' + esc(t('opt_pick_up_to', { n: g.max })) : '') + '</div><div class="radio-list">';
      h += g.choices.map(function (c, ci) {
        const delta = Number(c.delta)
          ? '<span class="mod-delta">+' + money(c.delta) + '</span>'
          : '<span class="mod-delta">' + esc(t('mod_free')) + '</span>';
        return '<label class="radio-card"><input type="checkbox" data-leg="' + gi + '" data-ci="' + ci + '"' +
          (curLabels[c.label] ? ' checked' : '') + ' onchange="onLineOptChange(\'' + id + '\',' + gi + ',this)">' +
          '<span>' + esc(c.label) + '</span>' + delta + '</label>';
      }).join('') + '</div>';
    } else {
      h += '<div class="mod-sub">' + esc(t('opt_pick_one')) + '</div><div class="radio-list">' +
        g.choices.map(function (c, ci) {
          const delta = Number(c.delta)
            ? '<span class="mod-delta">+' + money(c.delta) + '</span>'
            : '<span class="mod-delta">' + esc(t('mod_free')) + '</span>';
          const checked = curLabels[c.label] || (!Object.keys(curLabels).length && ci === 0);
          return '<label class="radio-card side-choice"><input type="radio" name="le-' + id + '-' + gi + '" data-leg="' + gi + '" data-ci="' + ci + '"' +
            (checked ? ' checked' : '') + ' onchange="onLineOptChange(\'' + id + '\',' + gi + ',this)">' +
            '<span>' + esc(c.label) + '</span>' + delta + '</label>';
        }).join('') + '</div>';
    }
    h += '</div>';
  });
  if (ings.length) {
    h += '<div class="mod-picker"><div class="mod-title">' + esc(t('ing_title')) + '</div><div class="ing-list">';
    ings.forEach(function (ig) {
      const nm = ig.name || '';
      const isRemoved = (cust.removed || []).indexOf(nm) !== -1;
      const isAdded = (cust.added || []).some(function (a) {
        return (a && a.name !== undefined ? a.name : String(a)) === nm;
      });
      if (ig.included_by_default) {
        h += '<label class="ing-row ingredient-choice"><input class="ingredient-check" type="checkbox" data-leing="rem" data-ing-name="' + esc(nm) + '"' +
          (isRemoved ? '' : ' checked') + ' onchange="onLineIngChange(\'' + id + '\')">' +
          '<span class="ing-name">' + esc(nm) + '</span> <span class="ing-hint">' + esc(t('ing_tap_remove')) + '</span></label>';
      } else {
        const price = Number(ig.extra_price) || 0;
        h += '<label class="ing-row ingredient-choice"><input class="ingredient-check" type="checkbox" data-leing="add" data-ing-name="' + esc(nm) + '" data-ing-price="' + price + '"' +
          (isAdded ? ' checked' : '') + ' onchange="onLineIngChange(\'' + id + '\')">' +
          '<span class="ing-name">' + esc(t('ing_add')) + ' ' + esc(nm) + '</span>' +
          (price ? ' <span class="mod-delta">+' + money(price) + '</span>' : '') + '</label>';
      }
    });
    h += '</div></div>';
  }
  h += '<button class="btn small" onclick="toggleLineEdit(\'' + id + '\')">' + esc(t('le_done')) + '</button></div>';
  return h;
}
/* Read the inline editor's current selections back into a cust object. */
function readLineEdit(id) {
  const box = document.getElementById('lebox-' + id);
  const cust = emptyCust();
  if (!box) return cust;
  const key = S.leMap[id];
  const e = key && S.cart.items[key];
  const dish = e && S.dishById[e.dishId];
  const groups = dishOptionGroups(dish);
  groups.forEach(function (g, gi) {
    const picked = [];
    if (g.type === 'multiple') {
      box.querySelectorAll('input[data-leg="' + gi + '"]:checked').forEach(function (inp) {
        const c = g.choices[Number(inp.getAttribute('data-ci'))];
        if (c) picked.push({ label: c.label, delta: c.delta });
      });
    } else {
      const input = box.querySelector('input[data-leg="' + gi + '"]:checked');
      const c = input && g.choices[Number(input.getAttribute('data-ci'))];
      if (c) picked.push({ label: c.label, delta: c.delta });
    }
    if (picked.length) cust.modifiers.push({ option_id: g.id, option_name: g.name, gi: gi, choices: picked });
  });
  box.querySelectorAll('input[data-leing]').forEach(function (inp) {
    const nm = inp.getAttribute('data-ing-name') || '';
    const kind = inp.getAttribute('data-leing');
    if (kind === 'rem' && !inp.checked && nm) cust.removed.push(nm);
    if (kind === 'add' && inp.checked && nm) {
      cust.added.push({ name: nm, delta: Number(inp.getAttribute('data-ing-price')) || 0 });
    }
  });
  return cust;
}
/* Apply an inline edit: rebuild the cust, re-key the line (merging when the
   new signature already exists), keep the editor open, re-render. */
function applyLineEdit(id) {
  const key = S.leMap && S.leMap[id];
  const e = key && S.cart.items[key];
  if (!e) return;
  const cust = readLineEdit(id);
  const editedEntry = { cust: cust };
  if (e.fishUnitId) editedEntry.fishUnitId = e.fishUnitId;
  const newKey = lineKey(e.dishId, editedEntry);
  if (newKey === key) return; // max/min guard reverted the toggle — DOM already correct
  const target = S.cart.items[newKey];
  if (target && !e.fishUnitId) { target.qty += e.qty; touchLine(newKey); }
  else {
    const replacement = { dishId: e.dishId, qty: e.fishUnitId ? 1 : e.qty, modifier: e.modifier || null, cust: cust };
    if (e.fishUnitId) replacement.fishUnitId = e.fishUnitId;
    S.cart.items[newKey] = replacement;
    touchLine(newKey);
  }
  delete S.cart.items[key];
  if (S.lineEditOpen && S.lineEditOpen[key]) { delete S.lineEditOpen[key]; S.lineEditOpen[newKey] = true; }
  saveCart();
  updateAuthArea();
  rerenderCartView();
}
window.onLineOptChange = function (id, gi, el) {
  const key = S.leMap && S.leMap[id];
  const e = key && S.cart.items[key];
  if (!e) return;
  const dish = S.dishById[e.dishId];
  const g = dishOptionGroups(dish)[gi];
  if (g && g.type === 'multiple') {
    const box = document.getElementById('lebox-' + id);
    const checked = box ? box.querySelectorAll('input[data-leg="' + gi + '"]:checked').length : 0;
    if (g.max !== null && checked > g.max) { el.checked = false; return; } // over max — revert
    if (g.min > 0 && checked < g.min) { el.checked = true; return; } // under required min — revert
  }
  applyLineEdit(id);
};
window.onLineIngChange = function (id) { applyLineEdit(id); };

function stepperHTML(dish) {
  // === v39: only dishes with REQUIRED option groups route to the dish page
  // from cards — required choices can't be guessed. Everything else one-tap
  // adds; sides/ingredients are changed inline in the cart (v39 editor).
  const reqGroups = dishOptionGroups(dish).filter(function (g) { return g.min > 0; });
  if (reqGroups.length) {
    return '<span data-stepper="' + dish.id + '" data-sp="card" onclick="event.stopPropagation()">' +
      '<button class="btn small" onclick="goDishCustom(' + dish.id + ')">🧩 ' + esc(t('choose_options')) + '</button></span>';
  }
  const q = cartQty(dish.id);
  // stopPropagation: steppers sit inside clickable dish cards.
  if (q === 0) {
    return '<span data-stepper="' + dish.id + '" data-sp="card" onclick="event.stopPropagation()"><button class="btn small" onclick="addToCart(' + dish.id + ')">' + esc(t('add')) + '</button></span>';
  }
  return '<span data-stepper="' + dish.id + '" data-sp="card" onclick="event.stopPropagation()"><span class="stepper">' +
    '<button onclick="setQty(' + dish.id + ',' + (q - 1) + ')" aria-label="' + esc(t('aria_remove')) + '">−</button>' +
    '<span class="qty">' + q + '</span>' +
    '<button onclick="setQty(' + dish.id + ',' + (q + 1) + ')" aria-label="' + esc(t('aria_add')) + '">+</button>' +
    '</span></span>';
}

/* Dish-page stepper: unlike the card stepper, "+" here means "add one more
   with the options currently selected above" — it routes through addToCart
   so changing the side and tapping + spawns a NEW variation line instead of
   inflating the last line's quantity (the 4-fish bug, Oct 2026). "−" removes
   one from the line matching the current selection, else the last-touched. */
function dishPageStepperHTML(dish) {
  const q = cartQty(dish.id);
  if (q === 0) {
    return '<span data-stepper="' + dish.id + '" data-sp="page"><button class="btn small" onclick="addToCart(' + dish.id + ')">' + esc(t('add')) + '</button></span>';
  }
  return '<span data-stepper="' + dish.id + '" data-sp="page"><span class="stepper">' +
    '<button onclick="decDishLine(' + dish.id + ')" aria-label="' + esc(t('aria_remove')) + '">−</button>' +
    '<span class="qty">' + q + '</span>' +
    '<button onclick="addToCart(' + dish.id + ')" aria-label="' + esc(t('aria_add')) + '">+</button>' +
    '</span></span>';
}
window.decDishLine = function (dishId) {
  const dish = S.dishById[dishId];
  let target = null;
  if (dish) {
    const key = lineKey(dishId, { cust: chosenCustomizations(dish) });
    if (S.cart.items[key]) target = key;
  }
  if (!target) target = lastDishLineKey(dishId);
  if (!target) return;
  const e = S.cart.items[target];
  if (e.qty <= 1) delete S.cart.items[target];
  else { e.qty -= 1; touchLine(target); }
  saveCart();
  refreshSteppers(dishId);
  updateAuthArea();
  if (S.route === 'cart') vCart();
  if (S.route === 'review') vReview();
};

function dishCard(dish) {
  const v = S.vendorById[dish.vendor_id];
  const rating = dish.rating_count > 0
    ? '<span class="stars">★ ' + Number(dish.avg_rating).toFixed(1) + '</span> <span class="rating-count">(' + dish.rating_count + ')</span>'
    : '<span class="no-rating">' + esc(t('no_reviews_yet')) + '</span>';
  return '<div class="dish-card clickable" data-dishid="' + dish.id + '" onclick="go(\'dish\',' + dish.id + ')" ' +
    'onkeydown="if(event.key===\'Enter\')go(\'dish\',' + dish.id + ')" tabindex="0" role="link" aria-label="' + esc(dish.name) + '">' +
    favBtn(dish.id) + shareBtn(dish.id) + dishImg(dish) +
    '<div class="dish-body">' +
    '<span class="cat-pill">' + esc(catLabel(dish.category)) + '</span>' + dietBadges(dish) + availBadge(dish) + sigPill(dish) +
    '<span class="prep-pill">⏱ ~' + esc(fmtDur(prepMins(dish, v))) + '</span>' +
    '<h3 class="dish-name">' + esc(dish.name) + '</h3>' +
    '<div class="dish-rating">' + rating + '</div>' +
    (dish.description ? '<p class="dish-desc">' + esc(dish.description) + '</p>' : '') +
    (v ? '<span class="vendor-tag">' + esc(t('from_vendor')) + ' <a href="#" onclick="event.stopPropagation();go(\'vendor\',' + v.id + ');return false;">' + esc(v.name) + '</a></span>' : '') +
    '<div class="dish-row">' + priceHTML(dish) + stepperHTML(dish) + '</div>' +
    '</div></div>';
}

/* Share a dish: popup with WhatsApp + Facebook icons, deep link back to the dish. */
function shareBtn(dishId) {
  return '<button class="share-btn" onclick="shareDish(event,' + dishId + ')" ' +
    'aria-label="' + esc(t('share_dish')) + '" title="' + esc(t('share_dish')) + '">↗</button>';
}
/* Share a dish: popup with WhatsApp + Facebook icons, deep link back to the dish. */
window.shareDish = function (ev, dishId) {
  ev.preventDefault(); ev.stopPropagation();
  closeSharePop();
  const dish = S.dishById[dishId];
  if (!dish) return;
  const v = S.vendorById[dish.vendor_id];
  const url = window.location.origin + '/dish/' + dishId;
  const text = t('share_msg', { dish: dish.name, vendor: v ? v.name : '', url: url });
  const waSVG = '<svg viewBox="0 0 448 512" aria-hidden="true"><path fill="#fff" d="M380.9 97.1C339 55.1 283.2 32 223.9 32c-122.4 0-222 99.6-222 222 0 39.1 10.2 77.3 29.6 111L0 480l117.7-30.9c32.4 17.7 68.9 27 106.1 27h.1c122.3 0 224.1-99.6 224.1-222 0-59.3-25.2-115-67.1-157zm-157 341.6c-33.2 0-65.7-8.9-94-25.7l-6.7-4-69.8 18.3L72 359.2l-4.4-7c-18.5-29.4-28.2-63.3-28.2-98.2 0-101.7 82.8-184.5 184.6-184.5 49.3 0 95.6 19.2 130.4 54.1 34.8 34.9 56.2 81.2 56.1 130.5 0 101.8-84.9 184.6-186.6 184.6zm101.2-138.2c-5.5-2.8-32.8-16.2-37.9-18-5.1-1.9-8.8-2.8-12.5 2.8-3.7 5.6-14.3 18-17.6 21.8-3.2 3.7-6.5 4.2-12 1.4-32.6-16.3-54-29.1-75.5-66-5.7-9.8 5.7-9.1 16.3-32.4 3.4-7.4 1.7-13.9-1-19.8-2.1-4.5-12.5-30.2-17.1-41.4-4.5-10.8-9.1-9.3-12.5-9.5-3.2-.2-6.9-.2-10.6-.2-3.7 0-9.7 1.4-14.8 6.9-5.1 5.6-19.4 19-19.4 46.3 0 27.3 19.9 53.7 22.6 57.4 2.8 3.7 39.1 59.7 94.8 83.8 35.2 15.2 49 16.5 66.6 13.9 10.7-1.6 32.8-13.4 37.4-26.4 4.6-13 4.6-24.1 3.2-26.4-1.3-2.5-5-3.9-10.5-6.6z"/></svg>';
  const fbSVG = '<svg viewBox="0 0 320 512" aria-hidden="true"><path fill="#fff" d="M279.14 288l14.22-92.66h-88.91v-60.13c0-25.35 12.42-50.06 52.24-50.06h40.42V6.26S260.43 0 225.36 0c-73.22 0-121.08 44.38-121.08 124.72v70.62H22.89V288h81.39v224h100.17V288z"/></svg>';
  const pop = document.createElement('div');
  pop.className = 'share-pop'; pop.id = 'share-pop';
  pop.innerHTML =
    '<a class="share-opt wa" target="_blank" rel="noopener" aria-label="WhatsApp" title="WhatsApp" href="https://wa.me/?text=' + encodeURIComponent(text) + '">' + waSVG + '</a>' +
    '<a class="share-opt fb" target="_blank" rel="noopener" aria-label="Facebook" title="Facebook" href="https://www.facebook.com/sharer/sharer.php?u=' + encodeURIComponent(url) + '">' + fbSVG + '</a>';
  pop.addEventListener('click', function (e) { e.stopPropagation(); });
  document.body.appendChild(pop);
  const pad = 8, w = 112, h = 52;
  pop.style.left = Math.max(pad, Math.min(window.innerWidth - w - pad, ev.clientX - w / 2)) + 'px';
  pop.style.top = Math.max(pad, Math.min(window.innerHeight - h - pad, ev.clientY - h - 6)) + 'px';
  setTimeout(function () {
    document.addEventListener('click', closeSharePop);
    document.addEventListener('keydown', escCloseSharePop);
  }, 0);
};
function closeSharePop() {
  const p = document.getElementById('share-pop');
  if (p) p.remove();
  document.removeEventListener('click', closeSharePop);
  document.removeEventListener('keydown', escCloseSharePop);
}
function escCloseSharePop(e) { if (e.key === 'Escape') closeSharePop(); }

/* ================= F5: vendor combo meals (family bundles) ================= */
/* One-tap add: bundles always merge onto one line per bundle (no
   customizations — the fixed price is the whole story). */
window.addBundleToCart = async function (bundleId) {
  let b = S.bundleById && S.bundleById[bundleId];
  if (!b) {
    try { b = await api('/bundles/' + bundleId); }
    catch (e) { alert(t('bundle_unavailable')); return; }
  }
  if (!b.available) { alert(t('bundle_unavailable')); return; }
  S.bundleById = S.bundleById || {};
  S.bundleById[b.id] = b;
  const key = 'b' + b.id;
  const cur = S.cart.items[key];
  S.cart.items[key] = { bundleId: b.id, bundle: b, qty: (cur ? cur.qty : 0) + 1 };
  touchLine(key);
  saveCart();
  updateAuthArea();
  if (S.route === 'cart') vCart();
  if (S.route === 'review') vReview();
};
function bundleItemsText(b) {
  return (b.items || []).map(function (i) {
    return i.dish_name + ((i.quantity || 1) > 1 ? ' ×' + i.quantity : '');
  }).join(', ');
}
function bundleCard(b) {
  const v = S.vendorById[b.vendor_id];
  const name = (lang() === 'ar' && b.name_ar) ? b.name_ar : b.name;
  const desc = (lang() === 'ar' && b.description_ar) ? b.description_ar : b.description;
  return '<div class="dish-card">' +
    (b.photo_url ? '<img class="dish-img" src="' + esc(b.photo_url) + '" alt="" loading="lazy" onerror="this.style.display=\'none\'">' : '') +
    '<div class="dish-body">' +
    '<span class="cat-pill">🎁 ' + esc(t('bundles_title')) + '</span>' +
    '<h3 class="dish-name">' + esc(name) + '</h3>' +
    (desc ? '<p class="dish-desc">' + esc(desc) + '</p>' : '') +
    '<div class="vendor-tag">🍱 ' + esc(t('bundle_includes')) + ': ' + esc(bundleItemsText(b)) + '</div>' +
    (v ? '<span class="vendor-tag">' + esc(t('bundle_from', { vendor: v.name })) + '</span>' : '') +
    '<div class="dish-row"><span class="price">' + money(b.price) + '</span>' +
    '<button class="btn small" onclick="event.stopPropagation();addBundleToCart(' + b.id + ')">' + esc(t('bundle_add')) + '</button></div>' +
    '</div></div>';
}
/* ================= holiday feasts (Oct 2026) ================= */
/* Today's date in America/Los_Angeles as YYYY-MM-DD — anchors the feast countdown. */
function laTodayISO() {
  try { return new Date().toLocaleDateString('en-CA', { timeZone: 'America/Los_Angeles' }); }
  catch (e) { return new Date().toISOString().slice(0, 10); }
}
/* Days from today (LA) to an order_by 'YYYY-MM-DD'; null when unparsable. */
function feastDaysLeft(orderBy) {
  if (!orderBy || !/^\d{4}-\d{2}-\d{2}$/.test(String(orderBy).trim())) return null;
  const d = Math.round((Date.parse(orderBy) - Date.parse(laTodayISO())) / 86400000);
  return isNaN(d) ? null : d;
}
function feastCountdownText(days) {
  if (days <= 0) return t('last_call');
  if (days === 1) return t('one_day_left');
  return t('days_left', { n: days });
}
function feastCard(b) {
  const name = (lang() === 'ar' && b.name_ar) ? b.name_ar : b.name;
  const desc = (lang() === 'ar' && b.description_ar) ? b.description_ar : b.description;
  const days = feastDaysLeft(b.order_by);
  return '<div class="dish-card feast-card">' +
    '<div class="feast-holiday">🎉 ' + esc(b.holiday_name) + '</div>' +
    (b.photo_url ? '<img class="dish-img" src="' + esc(b.photo_url) + '" alt="" loading="lazy" onerror="this.style.display=\'none\'">' : '') +
    '<div class="dish-body">' +
    '<h3 class="dish-name">' + esc(name) + '</h3>' +
    (desc ? '<p class="dish-desc">' + esc(desc) + '</p>' : '') +
    (b.order_by ? '<div class="feast-countdown">⏳ ' + esc(t('order_by', { date: b.order_by })) +
      ' · <strong>' + esc(feastCountdownText(days)) + '</strong></div>' : '') +
    (b.max_orders ? '<div class="vendor-tag">' + esc(t('feast_max', { n: b.max_orders })) + '</div>' : '') +
    '<div class="dish-row"><span class="price">' + money(b.price) + '</span>' +
    '<button class="btn small" onclick="event.stopPropagation();addBundleToCart(' + b.id + ')">' + esc(t('bundle_add')) + '</button></div>' +
    '</div></div>';
}
/* ================= END holiday feasts ================= */
/* Discoverable listing: every vendor's available bundles, grouped by vendor. */
async function vBundles() {
  const view = $('#view');
  view.innerHTML = '<div class="empty"><span class="big">🎁</span>' + esc(t('bundles_title')) + '</div>';
  try {
    const [bundles, vendors] = await Promise.all([api('/bundles'), api('/vendors')]);
    vendors.forEach(function (v) { S.vendorById[v.id] = v; });
    bundles.forEach(function (b) { S.bundleById = S.bundleById || {}; S.bundleById[b.id] = b; });
    let html = '<h2 class="section-title">' + esc(t('bundles_title')) + '</h2>' +
      '<p class="hint">' + esc(t('bundles_sub')) + '</p>';
    if (!bundles.length) {
      html += '<div class="empty">' + esc(t('bundles_empty')) + '</div>';
    } else {
      const byVendor = {};
      bundles.forEach(function (b) { (byVendor[b.vendor_id] = byVendor[b.vendor_id] || []).push(b); });
      Object.keys(byVendor).forEach(function (vid) {
        const v = S.vendorById[vid];
        html += '<h3 class="section-title">🏪 ' + esc(v ? v.name : vid) + '</h3>' +
          '<div class="grid">' + byVendor[vid].map(bundleCard).join('') + '</div>';
      });
    }
    view.innerHTML = html;
  } catch (e) {
    view.innerHTML = '<div class="error">' + esc(e.message) + '</div>';
  }
}
/* Bundle components on cart / review lines (display-only). */
function bundleLinesHTML(l) {
  if (!l.bundle) return '';
  return '<div class="vendor-tag mod-line">🍱 ' + esc(t('bundle_includes')) + ': ' +
    esc(bundleItemsText(l.bundle)) + '</div>';
}
/* ================= END F5 ================= */

/* ================= favorites ================= */
function favBtn(dishId) {
  return '<button class="fav-btn" data-fav="' + dishId + '" onclick="toggleFav(event,' + dishId + ')" ' +
    'aria-label="' + esc(t('fav_aria')) + '">' + (S.favs.has(dishId) ? '❤️' : '🤍') + '</button>';
}
window.toggleFav = async function (ev, dishId) {
  ev.preventDefault(); ev.stopPropagation();
  if (!S.user) { S.flash = t('fav_login'); go('login'); return; }
  try {
    if (S.favs.has(dishId)) {
      await api('/favorites/' + dishId, { method: 'DELETE' });
      S.favs.delete(dishId);
    } else {
      await api('/favorites', { method: 'POST', body: JSON.stringify({ dish_id: dishId }) });
      S.favs.add(dishId);
    }
    document.querySelectorAll('[data-fav="' + dishId + '"]').forEach(b => {
      b.textContent = S.favs.has(dishId) ? '❤️' : '🤍';
    });
    if (S.route === 'favorites') vFavorites();
  } catch (e) { alert(t('fav_err') + e.message); }
};
async function loadFavs() {
  S.favs = new Set();
  if (!S.user) return;
  try {
    const favs = await api('/favorites');
    favs.forEach(d => S.favs.add(d.id));
  } catch (e) { /* favorites just won't show filled */ }
}
async function vFavorites() {
  const view = $('#view');
  if (!S.user) { go('login'); return; }
  view.innerHTML = '<div class="empty"><span class="big">❤️</span>' + esc(t('fav_loading')) + '</div>';
  try {
    const dishes = await api('/favorites');
    dishes.forEach(d => { S.dishById[d.id] = d; S.favs.add(d.id); });
    if (!dishes.length) {
      view.innerHTML = '<div class="empty"><span class="big">🤍</span>' + esc(t('fav_empty')) + '<br>' +
        esc(t('fav_empty_hint')) + '<br><br>' +
        '<button class="btn" onclick="go(\'home\')">' + esc(t('browse_dishes')) + '</button></div>';
      return;
    }
    view.innerHTML = '<h2 class="section-title">' + esc(t('fav_title')) + '</h2>' +
      '<div class="grid">' + dishes.map(quickAddCard).join('') + '</div>'; // === F3: one-tap quick-add on favorites ===
  } catch (e) {
    view.innerHTML = '<div class="error">' + esc(t('fav_err_load')) + esc(e.message) + '</div>';
  }
}

/* === F3 (Oct 2026): one-tap reorder ===
   quickAddCard wraps a dish card with an explicit ⚡ quick-add button; used
   by the Favorites view and the "Your usuals" rail. Tapping it adds the
   dish straight to the cart — UNLESS the dish has REQUIRED option groups
   (min_select > 0): we never guess the customer's customizations, so they
   go to the dish page with those groups highlighted instead. */
function quickAddCard(dish) {
  return '<div class="quickadd-card">' + dishCard(dish) +
    '<button class="btn small quickadd-btn" onclick="event.stopPropagation();quickAdd(' + dish.id + ')">' +
    esc(t('quick_add')) + '</button></div>';
}
window.quickAdd = async function (dishId) {
  const dish = await dishName(dishId);
  if (!dish.available) { alert(t('dish_unavailable')); return; }
  // Advance ordering / weekly specials: block outside the order window
  // (evaluated in America/Los_Angeles); the server re-checks at checkout.
  if (dishRestricted(dish) && !dishWindow(dish).open) {
    alert(orderWindowBlockMsg(dish));
    return;
  }
  // === v39: only REQUIRED groups route to the dish page — required choices
  // can't be guessed. Everything else one-tap adds; sides/ingredients are
  // changed inline in the cart.
  const required = dishOptionGroups(dish).filter(function (g) { return g.min > 0; });
  if (required.length) { goDishCustom(dishId); return; }
  await addToCart(dishId); // stepper on the card visibly ticks up
};
/* === END F3 === */

/* ================= home ================= */
/* Grocery categories live on the dedicated Groceries page. */
const GROCERY_CATS = ['Pantry', 'Spices & Herbs', 'Frozen', 'Dairy & Cheese', 'Sweets', 'Beverages'];

/* === v50: Egypt's proven best sellers (owner-curated) lead the home
   page: featured dishes in this name order come first in the popular
   grid and the photo marquee. Mirrors FEATURED_BEST_SELLERS in seed.py. === */
const BEST_SELLER_ORDER = [
  'stuffed grape leaves', 'mixed mahshi tray (half tray)', 'molokhia with chicken',
  'egyptian béchemel pasta (macarona bechamel)', 'koshary', 'fatta',
  'charcoal-grilled hawawshi (plate)', 'egyptian kofta (plate)',
  'okra with beef (bamia)', "egyptian baked rice with lamb (rice ma'amar)",
  'om ali', 'basbousa', 'konafa', 'qatayef', "ta'ameya (egyptian falafel)",
];
function bestSellerRank(d) {
  const i = BEST_SELLER_ORDER.indexOf((d.name || '').toLowerCase());
  return i === -1 ? BEST_SELLER_ORDER.length : i;
}
function byBestSeller(a, b) { return bestSellerRank(a) - bestSellerRank(b); }

async function vHome() {
  const view = $('#view');
  setPageSEO('Egyptian Home Food Marketplace | Homemade Egyptian Food',
    'Order homemade Egyptian food from local cooks. Browse dishes and groceries for pickup or delivery.', null, '/');
  view.innerHTML = '<div class="empty"><span class="big">🍲</span>' + esc(t('loading_market')) + '</div>';
  // === v50: retry the data batch up to 3 attempts with short backoff —
  // a waking free-tier server answers within ~60s, so one timed-out
  // attempt must not strand the page on the loading screen. The error
  // view (with a working Retry button) appears only after all attempts.
  let homeData = null;
  let homeErr = null;
  for (let attempt = 0; attempt < 3 && !homeData; attempt++) {
    try {
      homeData = await Promise.all([
        api('/vendors'),
        api('/dishes?featured=true'),
        api('/dishes?available_only=false'),
        api('/dishes/bestsellers?limit=10').catch(() => []),
        api('/bundles').catch(() => []), // === Holiday feasts (Oct 2026) ===
      ]);
    } catch (e) {
      homeErr = e;
      if (S.route !== 'home') return; // navigated away while loading
      if (attempt < 2) await new Promise(r => setTimeout(r, 1500 * (attempt + 1)));
    }
  }
  if (!homeData) {
    if (S.route !== 'home') return;
    view.innerHTML = '<div class="error">' + esc(t('err_market')) + esc(homeErr ? homeErr.message : '') +
      ' <button type="button" class="btn small" onclick="vHome()">' + esc(t('retry_load')) + '</button></div>';
    return;
  }
  try {
    const [vendors, featured, all, bestsellers, feastBundles] = homeData;
    S.vendors = vendors;
    S.vendorById = {};
    vendors.forEach(v => { S.vendorById[v.id] = v; });
    // Food and groceries have separate browse pages; the home page previews both.
    const foodOnly = all.filter(d => !GROCERY_CATS.includes(d.category));
    const groceryItems = all.filter(d => GROCERY_CATS.includes(d.category) && d.available);
    const featuredFood = featured.filter(d => !GROCERY_CATS.includes(d.category));
    const bestFood = bestsellers.filter(d => !GROCERY_CATS.includes(d.category));
    S.categories = [...new Set(foodOnly.map(d => d.category))].sort();
    featuredFood.forEach(d => { S.dishById[d.id] = d; });
    S.allDishes = all; // reused for the first grid paint — avoids re-fetching /dishes
    bestFood.forEach(d => { S.dishById[d.id] = d; });
    // Keep the homepage focused: one short popular list. v50: featured
    // dishes lead — ordered by the best-seller ranking — then the
    // order-data bestsellers, then other available dishes.
    const popularIds = new Set();
    S.popularDishes = [...[...featuredFood].sort(byBestSeller), ...bestFood, ...foodOnly.filter(d => d.available)]
      .filter(d => d.available && !popularIds.has(d.id) && popularIds.add(d.id))
      .slice(0, 6);
    S.popularDishes.forEach(d => { S.dishById[d.id] = d; });
    groceryItems.forEach(d => { S.dishById[d.id] = d; });

    // Trust strip: social proof computed from live data.
    const ratedVendors = vendors.filter(x => x.rating_count > 0);
    const trustRating = ratedVendors.length
      ? (ratedVendors.reduce((a, x) => a + x.avg_rating * x.rating_count, 0) /
         ratedVendors.reduce((a, x) => a + x.rating_count, 0)).toFixed(1)
      : null;

    // === v49: hero video (chef clip, web-optimized). Reduced motion or
    // small screens get the lighter file / poster-only treatment; the
    // headline, CTAs and ZIP form below are unchanged real content. ===
    const heroVideoHtml = (function () {
      const small = typeof window !== 'undefined' && window.innerWidth && window.innerWidth < 760;
      const sources = small
        ? '<source src="img/hero-sm.mp4" type="video/mp4">'
        : '<source src="img/hero.webm" type="video/webm"><source src="img/hero.mp4" type="video/mp4">';
      return '<video class="hero-video" ' + (MOTION_REDUCED ? '' : 'autoplay ') +
        'muted loop playsinline preload="' + (MOTION_REDUCED ? 'none' : 'metadata') + '"' +
        ' poster="img/hero-poster.jpg" aria-hidden="true" tabindex="-1">' + sources + '</video>';
    })();

    let html =
      '<section class="hero">' + heroVideoHtml + '<div class="hero-overlay">' +
      '<h1>' + esc(t('hero_title')) + '</h1>' +
      '<p>' + esc(t('hero_sub')) + '</p>' +
      '<a class="btn" href="/dishes" data-go="dishes"><span>' + esc(t('hero_browse')) + '</span></a> ' +
      '<a class="btn secondary" href="#" onclick="go(\'groceries\');return false;">' + esc(t('hero_groceries')) + '</a> ' +
      '<a class="btn secondary" href="#" onclick="document.getElementById(\'vendors\').scrollIntoView({behavior:\'smooth\'});return false;">' + esc(t('hero_cooks')) + '</a>' +
      '<div class="trust-strip">' + esc(t('hero_trust', {
        vendors: vendors.length,
        dishes: foodOnly.length,
        rating: trustRating || '–',
      })) + '</div>' +
      // === Delivery ZIP banner (Oct 2026): prominent, editable, persisted. ===
      '<div class="hero-zip">' + (function () {
        const myZip = getZip();
        if (myZip) {
          return '📍 ' + esc(t('zip_hero_set', { zip: myZip })) +
            ' <button type="button" class="linklike" onclick="zipFormOpen()">' + esc(t('zip_change')) + '</button>';
        }
        return '<form class="zip-form" onsubmit="return zipSave(this)">' +
          '<label class="zip-hero-label" for="hero-zip-input">📍 ' + esc(t('zip_enter')) + '</label>' +
          '<input id="hero-zip-input" inputmode="numeric" maxlength="5" placeholder="' + esc(t('zip_ph')) + '"' +
          ' aria-label="' + esc(t('zip_label')) + '" autocomplete="postal-code">' +
          '<button class="btn small" type="submit">' + esc(t('zip_save')) + '</button>' +
          '<span class="zip-err" role="alert"></span></form>';
      })() + '</div>' +
      // === END ZIP banner ===
      '</div></section>';

    // === v49: moving gallery — auto-scrolling ribbon of real dish
    // photos (available food dishes only; the second half is a visual
    // duplicate for the seamless loop, rendered non-interactive). ===
    (function () {
      const seenIds = new Set();
      // v50: 15 picks (was 14) so every ranked best seller — including
      // Ta'ameya at rank 15 — makes the ribbon.
      const picks = [...[...featuredFood].sort(byBestSeller), ...bestFood, ...foodOnly.filter(d => d.available)]
        .filter(d => d.available && !seenIds.has(d.id) && seenIds.add(d.id))
        .filter(d => d.photo_url || !photoFor(d).tile)
        .slice(0, 15);
      if (picks.length < 5) return;
      const itemHtml = function (d, dup) {
        const src = d.photo_url || imgUrl(photoFor(d).img);
        const inner = '<img class="mq-img" src="' + esc(src) + '" alt="' + (dup ? '' : esc(d.name)) + '" loading="lazy" decoding="async" onerror="imgFallback(this)">' +
          '<span>' + esc(d.name) + '</span>';
        return dup
          ? '<span class="marquee-item" aria-hidden="true">' + inner + '</span>'
          : '<a class="marquee-item" href="#" onclick="go(\'dish\',' + d.id + ');return false;">' + inner + '</a>';
      };
      html += '<section class="marquee-section"><h2 class="marquee-title">' + esc(t('home_marquee_title')) + '</h2>' +
        '<div class="marquee"><div class="marquee-track">' +
        '<div class="marquee-half">' + picks.map(d => itemHtml(d, false)).join('') + '</div>' +
        '<div class="marquee-half" aria-hidden="true">' + picks.map(d => itemHtml(d, true)).join('') + '</div>' +
        '</div></div></section>';
    })();

    html += '<section class="home-section" id="home-dishes"><div class="section-heading">' +
      '<div><h2 class="section-title">' + esc(t('popular_dishes')) + '</h2><p class="section-intro">' + esc(t('home_dishes_sub')) + '</p></div>' +
      '<a class="btn secondary" href="/dishes" data-go="dishes">' + esc(t('view_all_dishes')) + '</a></div>' +
      (S.popularDishes.length ? '<div class="grid">' + S.popularDishes.map(dishCard).join('') + '</div>' :
        '<div class="empty">' + esc(t('no_dishes')) + '</div>') + '</section>';

    html += '<section class="home-section" id="home-groceries"><div class="section-heading">' +
      '<div><h2 class="section-title">' + esc(t('home_groceries_title')) + '</h2><p class="section-intro">' + esc(t('home_groceries_sub')) + '</p></div>' +
      '<a class="btn secondary" href="/groceries" data-go="groceries">' + esc(t('home_shop_all')) + '</a></div>' +
      (groceryItems.length ? '<div class="grid">' + groceryItems.slice(0, 6).map(dishCard).join('') + '</div>' :
        '<div class="empty">' + esc(t('groc_none')) + '</div>') + '</section>';

    const cookingVideos = [
      ...vendors.filter(v => v.intro_video_url).map(v => ({
        video_url: v.intro_video_url, name: v.chef_name || v.name,
        photo_url: v.chef_photo_url, vendor_id: v.id, vendor: v,
      })),
      ...foodOnly.filter(d => d.video_url).map(d => ({ ...d, vendor: S.vendorById[d.vendor_id] })),
    ].slice(0, 3);
    html += '<section class="home-section home-video-section"><div class="section-heading"><div><h2 class="section-title">' +
      esc(t('home_video_title')) + '</h2><p class="section-intro">' + esc(t('home_video_sub')) + '</p></div>' +
      '<a class="btn small" href="/vendor/">' + esc(t('home_video_upload_cta')) + '</a></div>' +
      (cookingVideos.length
        ? '<div class="home-video-grid">' + cookingVideos.map(d =>
          '<article class="home-video-card"><video src="' + esc(d.video_url) + '" controls playsinline preload="metadata"' +
          (d.photo_url ? ' poster="' + esc(d.photo_url) + '"' : '') + ' aria-label="' + esc(d.name) + '"></video>' +
          '<h3>' + esc(d.name) + '</h3><button class="linklike" type="button" onclick="go(\'' +
          (d.id ? 'dish' : 'vendor') + '\',' + (d.id || d.vendor_id) + ')">' +
          esc(t('home_video_dish_link')) + '</button></article>').join('') + '</div>'
        : '<div class="home-video-placeholder"><span aria-hidden="true">▶</span><div><strong>' + esc(t('home_video_empty_title')) +
          '</strong><p>' + esc(t('home_video_empty_sub')) + '</p></div></div>') + '</section>';

    // === Holiday feasts (Oct 2026): bundles with a holiday_name + order-by
    // countdown in America/Los_Angeles. Backend already excludes ended feasts;
    // we never re-show one (ended flag + past order_by are both filtered). ===
    const feasts = (feastBundles || []).filter(function (b) {
      if (!b || !b.holiday_name || b.ended) return false;
      const days = feastDaysLeft(b.order_by);
      return days !== null && days >= 0;
    });
    if (feasts.length) {
      S.bundleById = S.bundleById || {};
      feasts.forEach(function (b) { S.bundleById[b.id] = b; });
      html += '<h2 class="section-title">' + esc(t('feasts_title')) + ' <span class="sub">' + esc(t('feasts_sub')) + '</span></h2>';
      html += '<div class="rail">' + feasts.map(feastCard).join('') + '</div>';
    }
    // === END holiday feasts ===

    html += '<h2 class="section-title" id="vendors">' + esc(t('vendors_h')) + ' <span class="sub">' + esc(t('vendors_sub')) + '</span></h2>';
    html += '<div class="grid">' + vendors.map(vendorCard).join('') + '</div>';

    html += '<div id="testi-slot"></div>';

    if (S.route !== 'home') return; // user (or a deep link like #/verify-email) navigated away while loading
    view.innerHTML = html;

    if (S.browseAfterHome) S.browseAfterHome = false;
    // Testimonials load after the page paints: real 5-star reviews with text.
    (async () => {
      try {
        const slot = document.getElementById('testi-slot');
        if (!slot) return;
        const withReviews = vendors.filter(v => (v.rating_count || 0) > 0).slice(0, 6);
        if (!withReviews.length) return;
        const revLists = await Promise.all(
          withReviews.map(v => api('/vendors/' + v.id + '/reviews').catch(() => ({ reviews: [] }))));
        const quotes = [];
        revLists.forEach((rl, i) => {
          (rl.reviews || []).forEach(r => {
            if (r.rating === 5 && r.text && r.text.trim() && quotes.length < 3)
              quotes.push({ r, v: withReviews[i] });
          });
        });
        if (quotes.length && document.getElementById('testi-slot')) {
          // === v49: stories carousel — same real 5-star reviews, one at
          // a time, auto-advancing with arrows + dots (mounted by
          // scanMotion). A single story renders as a plain card. ===
          const cardHtml = function (q) {
            return '<div class="testi-card"><div class="stars">★★★★★</div>' +
              '<p>“' + esc(q.r.text) + '”</p>' +
              '<div class="testi-who">— ' + esc(q.r.user_name || t('review_fallback_name')) +
              ' <span class="vendor-tag">' + esc(t('from_vendor')) + ' ' + esc(q.v.name) + '</span></div></div>';
          };
          if (quotes.length === 1) {
            slot.innerHTML = '<h2 class="section-title">' + esc(t('testi_h')) + ' <span class="sub">' + esc(t('testi_sub')) + '</span></h2>' +
              '<div class="testi-grid">' + cardHtml(quotes[0]) + '</div>';
          } else {
            slot.innerHTML = '<h2 class="section-title">' + esc(t('testi_h')) + ' <span class="sub">' + esc(t('testi_sub')) + '</span></h2>' +
              '<div class="stories-carousel" role="region" aria-roledescription="carousel" aria-label="' + esc(t('stories_label')) + '">' +
              '<div class="stories-viewport"><div class="stories-track">' +
              quotes.map(function (q, i) {
                return '<div class="stories-slide" role="group" aria-roledescription="slide" aria-label="' + (i + 1) + ' / ' + quotes.length + '">' + cardHtml(q) + '</div>';
              }).join('') +
              '</div></div>' +
              '<button type="button" class="stories-btn stories-prev" aria-label="' + esc(t('carousel_prev')) + '">‹</button>' +
              '<button type="button" class="stories-btn stories-next" aria-label="' + esc(t('carousel_next')) + '">›</button>' +
              '<div class="stories-dots"></div></div>';
          }
        }
      } catch (e) { /* testimonials are a bonus — never break the homepage */ }
    })();
  } catch (e) {
    if (S.route !== 'home') return; // navigated away while loading (deep link)
    view.innerHTML = '<div class="error">' + esc(t('err_market')) + esc(e.message) +
      ' <button type="button" class="btn small" onclick="vHome()">' + esc(t('retry_load')) + '</button></div>';
  }
}

async function vDishes() {
  const view = $('#view');
  setPageSEO('Browse Egyptian Dishes | Homemade Egyptian Food',
    'Search Egyptian dishes from local home cooks. Filter by category and dietary needs.', null, '/dishes');
  view.innerHTML = '<div class="empty"><span class="big">🍽️</span>' + esc(t('loading_dishes')) + '</div>';
  try {
    const [vendors, all] = await Promise.all([
      api('/vendors'),
      api('/dishes?available_only=false'),
    ]);
    if (S.route !== 'dishes') return;
    S.vendorById = {};
    vendors.forEach(v => { S.vendorById[v.id] = v; });
    S.vendors = vendors;
    S.allDishes = all;
    const foodOnly = all.filter(d => !GROCERY_CATS.includes(d.category));
    S.categories = [...new Set(foodOnly.map(d => d.category))].sort();
    all.forEach(d => { S.dishById[d.id] = d; });
    S.showAllHomeDishes = true;

    let html = '<h1 class="section-title" id="browse">' + esc(t('dishes_page_title')) + '</h1>' +
      '<p class="section-intro">' + esc(t('dishes_page_sub')) + '</p>' +
      '<div class="search-row"><input type="search" id="q" aria-label="' + esc(t('search_label')) + '" placeholder="' +
      esc(t('search_ph')) + '" value="' + esc(S.filter.q) + '"></div>' +
      '<div class="filters" id="chips"><button class="chip' + (S.filter.category === '' ? ' active' : '') +
      '" data-cat="">' + esc(t('chip_all')) + '</button>' + S.categories.map(c =>
        '<button class="chip' + (S.filter.category === c ? ' active' : '') + '" data-cat="' + esc(c) + '">' +
        esc(catLabel(c)) + '</button>').join('') + '</div>' +
      '<div class="filters" id="diet-chips"><button class="chip' + (S.filter.veg ? ' active' : '') +
      '" data-diet="veg">🌱 ' + esc(t('veg_filter')) + '</button><button class="chip' +
      (S.filter.vegan ? ' active' : '') + '" data-diet="vegan">🌿 ' + esc(t('vegan_filter')) + '</button></div>';
    if (getZip()) html += '<div class="filters" id="zipf-chips"><button class="chip' +
      (S.filter.deliversMe ? ' active' : '') + '" data-zf="me">🚚 ' + esc(t('delivers_to_me')) + '</button></div>';
    else S.filter.deliversMe = false;
    html += '<div id="dish-grid"><div class="empty">' + esc(t('loading_dishes')) + '</div></div>';
    view.innerHTML = html;
    bindDishBrowseControls();
    loadGrid();
  } catch (e) {
    if (S.route === 'dishes') view.innerHTML = '<div class="error">' + esc(t('err_dishes')) + esc(e.message) + '</div>';
  }
}

function bindDishBrowseControls() {
  const q = $('#q');
  const chips = $('#chips');
  const dietChips = $('#diet-chips');
  if (!q || !chips || !dietChips) return;
  q.addEventListener('input', debounce(() => { S.filter.q = q.value; loadGrid(); }, 300));
  chips.addEventListener('click', e => {
    const b = e.target.closest('[data-cat]');
    if (!b) return;
    S.filter.category = b.dataset.cat;
    chips.querySelectorAll('.chip').forEach(c => c.classList.toggle('active', c === b));
    loadGrid();
  });
  dietChips.addEventListener('click', e => {
    const b = e.target.closest('[data-diet]');
    if (!b) return;
    const key = b.dataset.diet;
    S.filter[key] = !S.filter[key];
    b.classList.toggle('active', S.filter[key]);
    loadGrid();
  });
  const zipChips = $('#zipf-chips');
  if (zipChips) zipChips.addEventListener('click', e => {
    if (!e.target.closest('[data-zf]')) return;
    S.filter.deliversMe = !S.filter.deliversMe;
    e.target.closest('[data-zf]').classList.toggle('active', S.filter.deliversMe);
    loadGrid();
  });
}

function renderGrid(dishes, emptyMsg) {
  const grid = $('#dish-grid');
  if (!grid) return;
  // === "Delivers to me" filter (Oct 2026): dishes whose vendor serves the ZIP. ===
  let list = dishes;
  const zip = getZip();
  if (S.filter.deliversMe && zip) {
    list = list.filter(function (d) { return vendorServesZip(S.vendorById[d.vendor_id], zip); });
  }
  // === END "Delivers to me" ===
  list.forEach(d => { S.dishById[d.id] = d; });
  grid.innerHTML = list.length
    ? '<div class="grid">' + list.map(dishCard).join('') + '</div>'
    : '<div class="empty"><span class="big">🍽️</span>' + esc(emptyMsg || t('no_dishes')) + '</div>';
  const toggle = $('#home-dishes-toggle');
  if (toggle) {
    const filtered = !!(S.filter.q || S.filter.category || S.filter.veg || S.filter.vegan || S.filter.deliversMe);
    const allCount = (S.allDishes || []).filter(d => d.available && !GROCERY_CATS.includes(d.category)).length;
    toggle.hidden = filtered || !S.popularDishes.length || allCount <= S.popularDishes.length;
    toggle.textContent = t(S.showAllHomeDishes ? 'show_fewer_dishes' : 'view_all_dishes');
  }
  const heading = $('#browse');
  if (heading) {
    const filtered = !!(S.filter.q || S.filter.category || S.filter.veg || S.filter.vegan || S.filter.deliversMe);
    heading.textContent = t(filtered || S.showAllHomeDishes ? 'browse_h' : 'popular_dishes');
  }
}

async function loadGrid() {
  const dietActive = S.filter.veg || S.filter.vegan;
  // First paint with no filters: vHome already fetched the full list — reuse it
  // instead of firing a second, nearly identical /dishes request.
  // Diet filters always hit the server (?vegetarian / ?vegan) so results are
  // authoritative even if the cached list lacks the flags.
  if (!S.filter.q && !S.filter.category && S.allDishes && !dietActive) {
    const available = S.allDishes.filter(d => d.available && !GROCERY_CATS.includes(d.category));
    renderGrid(S.showAllHomeDishes ? available : S.popularDishes);
    return;
  }
  const p = new URLSearchParams();
  if (S.filter.q) p.set('q', S.filter.q);
  if (S.filter.category) p.set('category', S.filter.category);
  if (S.filter.veg) p.set('vegetarian', 'true');
  if (S.filter.vegan) p.set('vegan', 'true');
  try {
    let dishes, emptyMsg;
    if (S.filter.q) {
      // === F4 (Oct 2026): smart bilingual search — typo-tolerant,
      // Arabic-normalized, transliteration-aware. Zero-result queries are
      // logged server-side for the vendors' "what customers searched for" panel.
      const res = await api('/search?' + p.toString());
      dishes = (res.hits || []).map(h => h.dish)
        .filter(d => !GROCERY_CATS.includes(d.category)); // groceries have their own page
      if (!dishes.length) emptyMsg = t('search_no_results', { q: S.filter.q });
      // === END F4 ===
    } else {
      dishes = (await api('/dishes?' + p.toString()))
        .filter(d => !GROCERY_CATS.includes(d.category)); // groceries have their own page
    }
    renderGrid(dishes, emptyMsg);
  } catch (e) {
    const grid = $('#dish-grid');
    if (grid) grid.innerHTML = '<div class="error">' + esc(t('err_dishes')) + esc(e.message) + '</div>';
  }
}

function vendorCard(v) {
  const rating = v.rating_count > 0
    ? '<span>⭐ ' + Number(v.avg_rating).toFixed(1) + ' (' + v.rating_count + ')</span>'
    : '<span class="no-rating">' + esc(t('no_reviews_yet')) + '</span>';
  return '<div class="vendor-card">' +
    '<h3>' + esc(v.name) + '</h3>' +
    '<p class="tagline">“' + esc(v.tagline) + '”</p>' +
    '<div class="vendor-meta"><span>📍 ' + esc(v.area) + '</span>' + rating +
    (v.dish_count > 0 ? '<span>🍲 ' + v.dish_count + '</span>' : '') +
    (v.phone ? '<span>📞 <a href="tel:' + esc(v.phone.replace(/[^+\d]/g, '')) + '">' + esc(v.phone) + '</a></span>' : '') +
    fulfillBadge(v) + zipDeliveryBadge(v) + freeDeliveryBadge(v) + '</div>' +
    '<div><button class="btn small" onclick="go(\'vendor\',' + v.id + ')">' + esc(t('view_menu')) + '</button></div>' +
    '</div>';
}

function debounce(fn, ms) {
  let t = null;
  return function () { clearTimeout(t); t = setTimeout(fn, ms); };
}

/* Dedicated groceries page — replaces the old "filter to Pantry" jump. */
window.goGroceries = function () { go('groceries'); };

async function vGroceries() {
  const view = $('#view');
  view.innerHTML = '<div class="empty"><span class="big">🛒</span>' + esc(t('groc_loading')) + '</div>';
  try {
    const [vendors, all] = await Promise.all([
      api('/vendors'),
      api('/dishes?available_only=false'),
    ]);
    S.vendorById = {};
    vendors.forEach(v => { S.vendorById[v.id] = v; });
    const groceries = all.filter(d => GROCERY_CATS.includes(d.category));
    groceries.forEach(d => { S.dishById[d.id] = d; });
    const cats = GROCERY_CATS.filter(c => groceries.some(d => d.category === c));

    let html = '<h2 class="section-title">' + esc(t('groc_title')) + ' <span class="sub">' + esc(t('groc_sub')) + '</span></h2>';
    html += '<div class="search-row"><input type="search" id="gq" aria-label="' + esc(t('groc_search_label')) + '" placeholder="' + esc(t('groc_search_ph')) + '"></div>';
    html += '<div class="filters" id="gchips"><button class="chip active" data-cat="">' + esc(t('chip_all')) + '</button>' +
      cats.map(c => '<button class="chip" data-cat="' + esc(c) + '">' + esc(catLabel(c)) + '</button>').join('') + '</div>';
    html += '<div id="grocery-grid"></div>';
    view.innerHTML = html;

    let gq = '', gcat = '';
    const renderGroceries = () => {
      const q = gq.trim().toLowerCase();
      const list = groceries.filter(d =>
        (!gcat || d.category === gcat) &&
        (!q || ((d.name || '') + ' ' + (d.description || '')).toLowerCase().includes(q)));
      const grid = $('#grocery-grid');
      if (!grid) return;
      grid.innerHTML = list.length
        ? '<div class="grid">' + list.map(dishCard).join('') + '</div>'
        : '<div class="empty"><span class="big">🛒</span>' + esc(t('groc_none')) + '</div>';
    };
    $('#gq').addEventListener('input', debounce(() => { gq = $('#gq').value; renderGroceries(); }, 300));
    $('#gchips').addEventListener('click', (e) => {
      const b = e.target.closest('[data-cat]');
      if (!b) return;
      gcat = b.dataset.cat;
      document.querySelectorAll('#gchips .chip').forEach(c => c.classList.toggle('active', c === b));
      renderGroceries();
    });
    renderGroceries();
  } catch (e) {
    view.innerHTML = '<div class="error">' + esc(t('groc_err')) + esc(e.message) + '</div>';
  }
}

/* ================= vendor storefront ================= */
async function vVendor(vendorId) {
  const view = $('#view');
  view.innerHTML = '<div class="empty"><span class="big">🍲</span>' + esc(t('vendor_loading')) + '</div>';
  try {
    const [v, dishes] = await Promise.all([
      api('/vendors/' + vendorId),
      api('/dishes?vendor_id=' + vendorId),
    ]);
    S.vendorById[v.id] = v;
    setPageSEO(v.name + ' | Homemade Egyptian Food',
      [v.tagline, v.area].filter(Boolean).join(' · ') || ('Order homemade Egyptian food from ' + v.name + '.'),
      v.chef_photo_url || null, '/cook/' + v.id);
    dishes.forEach(d => { S.dishById[d.id] = d; });
    // === F5: vendor's family bundles — own section above the menu ===
    let bundles = [];
    try {
      bundles = await api('/bundles?vendor_id=' + vendorId);
      S.bundleById = S.bundleById || {};
      bundles.forEach(b => { S.bundleById[b.id] = b; });
    } catch (e) { /* bundles are a bonus — never break the storefront */ }
    // === END F5 ===
    let rev = { reviews: [], avg_rating: null, count: 0 };
    try { rev = await api('/vendors/' + vendorId + '/reviews'); } catch (e) { /* no reviews yet */ }
    const groups = {};
    dishes.forEach(d => { (groups[d.category] = groups[d.category] || []).push(d); });

    let html = '<a class="crumb" href="#" onclick="go(\'home\');return false;">' + esc(t('back_to_cooks')) + '</a>' +
      (v.is_paused
        ? '<div class="paused-banner">' + esc(t('paused_banner')) + '</div>'
        : '<div id="open-banner">' + openBannerHTML(v) + '</div>') +
      '<div class="storefront-head">' +
      '<h1>' + esc(v.name) + '</h1>' +
      '<p class="tagline">“' + esc(v.tagline) + '”</p>' +
      '<div class="vendor-meta"><span>📍 ' + esc(v.area) + '</span>' +
      (v.phone ? '<span>📞 <a href="tel:' + esc(v.phone.replace(/[^+\d]/g, '')) + '">' + esc(v.phone) + '</a></span>' : '') +
      (rev.count ? '<span>⭐ ' + Number(rev.avg_rating).toFixed(1) + ' (' + esc(t('reviews_count', { count: rev.count })) + ')</span>' : '') +
      fulfillBadge(v) + zipDeliveryBadge(v) +
      (String(v.fulfillment).toLowerCase() === 'delivery' && Number(v.delivery_fee) > 0
        ? '<span>' + esc(t('delivery_fee', { fee: money(v.delivery_fee) })) + '</span>' : '') +
      freeDeliveryBadge(v) +
      '</div>';
    if (v.phone) {
      const digits = String(v.phone).replace(/\D/g, '');
      if (digits) {
        const waText = encodeURIComponent(t('whatsapp_msg', { name: v.name }));
        html += '<a class="btn small" style="margin-top:.7rem" href="https://wa.me/' + digits +
          '?text=' + waText + '" target="_blank" rel="noopener">' + esc(t('whatsapp_btn')) + '</a>';
      }
    }
    html += '</div>';
    const pickupBlock = pickupAddrHTML(v);
    if (pickupBlock) {
      html += '<div class="form-card" style="margin-top:1rem"><h3>' + esc(t('pickup_location_h')) + '</h3>' +
        pickupBlock + '</div>';
    }

    // === Chef card (Oct 2026): only when the vendor shared chef info. ===
    const chefBio = (lang() === 'ar' && v.chef_bio_ar) ? v.chef_bio_ar : v.chef_bio;
    if (v.chef_name || v.chef_photo_url || chefBio) {
      html += '<div class="chef-card"><div class="chef-row">' +
        (v.chef_photo_url
          ? '<img class="chef-photo" src="' + esc(v.chef_photo_url) + '" alt="' + esc(v.chef_name || v.name) +
            '" loading="lazy" onerror="this.style.display=\'none\'">'
          : '') +
        '<div class="chef-info"><div class="chef-kicker">' + esc(t('meet_chef')) + '</div>' +
        '<div class="chef-name">' + esc(v.chef_name || v.name) + '</div>' +
        (chefBio ? '<p class="chef-bio">' + esc(chefBio) + '</p>' : '') +
        '<span class="verified-badge">🏠✅ ' + esc(t('verified_kitchen')) + '</span></div></div></div>';
    }
    // === END chef card ===

    // === Signature dishes (Oct 2026): "Our specialties" row at the top, rank-ordered (nulls last). ===
    const sigDishes = dishes.filter(function (d) { return d.is_signature; }).sort(function (a, b) {
      const ra = (a.signature_rank === null || a.signature_rank === undefined) ? 1e9 : Number(a.signature_rank);
      const rb = (b.signature_rank === null || b.signature_rank === undefined) ? 1e9 : Number(b.signature_rank);
      return ra - rb;
    });
    if (sigDishes.length) {
      html += '<section class="cat-section"><h2>⭐ ' + esc(t('specialties')) + '</h2><div class="rail">' +
        sigDishes.map(dishCard).join('') + '</div></section>';
    }
    // === END signature ===

    // === Dish videos (Oct 2026): "Watch how it's made" strip. ===
    const vidDishes = dishes.filter(function (d) { return d.video_url; });
    if (vidDishes.length) {
      html += '<section class="cat-section"><h2>' + esc(t('watch_how')) + '</h2><div class="rail">' +
        vidDishes.map(function (d) {
          return '<div class="dish-card video-card">' +
            '<video src="' + esc(d.video_url) + '" controls playsinline preload="metadata"' +
            (d.photo_url ? ' poster="' + esc(d.photo_url) + '"' : '') +
            ' aria-label="' + esc(d.name) + '"></video>' +
            '<div class="dish-body"><h3 class="dish-name">' + esc(d.name) + '</h3></div></div>';
        }).join('') + '</div></section>';
    }
    // === END videos ===

    const cats = Object.keys(groups);
    // === F5: bundle cards — own section on the vendor storefront ===
    if (bundles.length) {
      html += '<section class="cat-section"><h2>' + esc(t('bundles_title')) + '</h2><div class="grid">' +
        bundles.map(bundleCard).join('') + '</div></section>';
    }
    // === END F5 ===
    if (!cats.length) html += '<div class="empty"><span class="big">🍽️</span>' + esc(t('vendor_no_dishes')) + '</div>';
    for (const c of cats) {
      html += '<section class="cat-section"><h2>' + esc(catLabel(c)) + '</h2><div class="grid">' +
        groups[c].map(dishCard).join('') + '</div></section>';
    }

    html += '<h2 class="section-title">' + esc(t('reviews_title')) +
      (rev.count ? ' <span class="sub">' + rev.count + '</span>' : '') + '</h2>';
    html += rev.reviews.length
      ? rev.reviews.map(r => reviewCardHTML(r, v.name)).join('')
      : '<div class="empty">' + esc(t('no_reviews')) + '</div>';
    view.innerHTML = html;
    // Vendors without their own hour fields: ask the backend for open status.
    if (!v.is_paused && !(v.open_time || v.close_time || v.closed_weekdays)) {
      api('/vendors/' + vendorId + '/open-status').then(st => {
        const el = document.getElementById('open-banner');
        if (el && S.route === 'vendor') el.innerHTML = openBannerHTML(v, st);
      }).catch(() => {});
    }
  } catch (e) {
    view.innerHTML = '<div class="error">' + esc(t('vendor_err')) + esc(e.message) + '</div>';
  }
}

/* ================= dish detail page ================= */
function removeDishJsonLd() {
  const old = document.getElementById('dish-jsonld');
  if (old) old.remove();
}
function setPageSEO(title, description, image, canonicalPath) {
  document.title = title;
  const ensureMeta = function (attr, key, value) {
    let meta = document.head.querySelector('meta[' + attr + '="' + key + '"]');
    if (!meta) {
      meta = document.createElement('meta');
      meta.setAttribute(attr, key);
      document.head.appendChild(meta);
    }
    meta.setAttribute('content', value || '');
  };
  const imageUrl = image ? new URL(image, window.location.origin).href : new URL('/img/logo.png', window.location.origin).href;
  ensureMeta('name', 'description', description);
  ensureMeta('property', 'og:title', title);
  ensureMeta('property', 'og:description', description);
  ensureMeta('property', 'og:url', new URL(canonicalPath, window.location.origin).href);
  ensureMeta('property', 'og:image', imageUrl);
  ensureMeta('name', 'twitter:title', title);
  ensureMeta('name', 'twitter:description', description);
  ensureMeta('name', 'twitter:image', imageUrl);
  let canonical = document.head.querySelector('link[rel="canonical"]');
  if (!canonical) {
    canonical = document.createElement('link');
    canonical.rel = 'canonical';
    document.head.appendChild(canonical);
  }
  canonical.href = new URL(canonicalPath, window.location.origin).href;
}
function injectDishJsonLd(dish, vendor) {
  removeDishJsonLd();
  const data = {
    '@context': 'https://schema.org',
    '@type': 'MenuItem',
    name: dish.name,
    offers: {
      '@type': 'Offer',
      price: String(salePrice(dish)),
      priceCurrency: 'USD',
      availability: dish.available ? 'https://schema.org/InStock' : 'https://schema.org/OutOfStock',
    },
  };
  if (dish.description) data.description = dish.description;
  if (dish.photo_url) data.image = dish.photo_url;
  if (vendor && vendor.name) data.provider = { '@type': 'FoodEstablishment', name: vendor.name };
  if (dish.rating_count > 0) {
    data.aggregateRating = {
      '@type': 'AggregateRating',
      ratingValue: Number(dish.avg_rating).toFixed(1),
      reviewCount: dish.rating_count,
    };
  }
  if (dish.calories != null) {
    data.nutrition = { '@type': 'NutritionInformation', calories: dish.calories + ' kcal' };
  }
  const s = document.createElement('script');
  s.type = 'application/ld+json';
  s.id = 'dish-jsonld';
  s.textContent = JSON.stringify(data);
  document.head.appendChild(s);
}

async function vDishDetail(dishId) {
  const view = $('#view');
  removeDishJsonLd();
  view.innerHTML = '<div class="empty"><span class="big">🍽️</span>' + esc(t('dish_loading')) + '</div>';
  try {
    const id = Number(dishId);
    if (!id) throw new Error('bad id');
    let dish = S.dishById[id];
    if (!dish || dish.id !== id) dish = await api('/dishes/' + id);
    S.dishById[dish.id] = dish;
    let v = S.vendorById[dish.vendor_id];
    if (!v) {
      try { v = await api('/vendors/' + dish.vendor_id); } catch (e) { v = null; }
    }
    if (v) S.vendorById[v.id] = v;
    setPageSEO(dish.name + ' | ' + (v ? v.name : 'Egyptian Home Food'),
      dish.description || ('Order ' + dish.name + ' from a local home cook for pickup or delivery.'),
      dish.photo_url || null, '/dish/' + dish.id);
    let rev = { reviews: [], avg_rating: 0, count: 0 };
    try { rev = await api('/dishes/' + dish.id + '/reviews'); } catch (e) { /* no reviews */ }
    // Per-dish ingredient customizations (toggles + add-ons). The rows ride on
    // the public dish object (dish.ingredient_options); the text fallback in
    // dishIngredients() covers dishes whose vendor never opened the portal's
    // ingredient manager.
    S.dishIng[dish.id] = dishIngRows(dish);
    let related = [];
    try {
      const menu = await api('/dishes?vendor_id=' + dish.vendor_id);
      menu.forEach(d => { S.dishById[d.id] = d; });
      related = menu.filter(d => d.id !== dish.id && d.available).slice(0, 4);
    } catch (e) { /* related is a bonus */ }

    const rating = dish.rating_count > 0
      ? '<span class="stars">★ ' + Number(dish.avg_rating).toFixed(1) + '</span> <span class="rating-count">(' + dish.rating_count + ' ' + esc(t('reviews_count', { count: dish.rating_count })) + ')</span>'
      : '<span class="no-rating">' + esc(t('no_reviews_yet')) + '</span>';

    // Details grid — only fields that actually have values.
    const details = [];
    if (dish.calories != null) details.push(['🔥', t('dd_calories'), t('dd_kcal', { n: dish.calories })]);
    if (dish.serving_size) details.push(['⚖️', t('dd_serving'), dish.serving_size]);
    if (dish.ingredients) details.push(['🧂', t('dd_ingredients'), dish.ingredients]);
    details.push(['⏱', t('dd_prep'), '~' + fmtDur(prepMins(dish, v))]);
    if (dish.allergens) details.push(['⚠️', t('dd_allergens'), dish.allergens]);

    let html = v
      ? '<a class="crumb" href="#" onclick="go(\'vendor\',' + v.id + ');return false;"><span class="crumb-arrow">←</span> ' + esc(v.name) + '</a>'
      : '<a class="crumb" href="#" onclick="go(\'home\');return false;">' + esc(t('back_to_cooks')) + '</a>';

    html += '<div class="dish-detail">' +
      '<div class="dd-photo">' + dishImg(dish) + '</div>' +
      '<div class="dd-info">' +
      '<span class="cat-pill">' + esc(catLabel(dish.category)) + '</span>' + dietBadges(dish) + availBadge(dish) + sigPill(dish) +
      '<h1>' + esc(dish.name) + '</h1>' +
      '<div class="dish-rating">' + rating + '</div>' +
      (dish.description ? '<p class="dd-desc">' + esc(dish.description) + '</p>' : '') +
      '<div class="dd-price-row">' + priceHTML(dish) + dishPageStepperHTML(dish) + shareBtn(dish.id) + '</div>' +
      (dish.available ? '' : '<div class="notice">' + esc(t('dish_unavailable')) + '</div>') +
      '</div></div>';

    // === Dish video (Oct 2026): HTML5 player, shown only when video_url is set. ===
    if (dish.video_url) {
      html += '<div class="dish-video"><video src="' + esc(dish.video_url) + '" controls playsinline preload="metadata"' +
        (dish.photo_url ? ' poster="' + esc(dish.photo_url) + '"' : '') +
        ' aria-label="' + esc(dish.name) + '"></video></div>';
    }
    // === END dish video ===

    if (v && v.is_paused) {
      html += '<div class="paused-banner">' + esc(t('paused_banner')) + '</div>';
    }
    // Low-stock urgency banner: null = unlimited.
    if (dish.stock_quantity != null) {
      const sq = Number(dish.stock_quantity);
      if (sq <= 0) html += '<div class="notice">' + esc(t('stock_out')) + '</div>';
      else if (sq <= 5) html += '<div class="stock-low">' + esc(t('stock_low', { n: sq })) + '</div>';
    }

    // Option groups: single → radio pills; multiple → checkboxes with a
    // live "pick up to N" counter. Max is enforced client-side; the server
    // 400/422 still surfaces via errText on checkout if it ever trips.
    const groups = dishOptionGroups(dish);
    // === F3: one-tap reorder landed here — highlight the required groups ===
    const hlGroups = !!S.highlightGroups;
    S.highlightGroups = false;
    if (hlGroups) {
      html += '<div class="notice quickadd-hint">👇 ' + esc(t('quickadd_groups_hint')) + '</div>';
    }
    if (groups.length) {
      html += '<div id="dish-custom" data-dish="' + dish.id + '">';
      groups.forEach(function (g, gi) {
        const key = optGroupKey(dish.id, g, gi);
        const multi = g.type === 'multiple';
        html += '<div class="mod-picker' + (hlGroups && g.min > 0 ? ' required-hl' : '') + '"><div class="mod-title">🧩 ' + esc(g.name || t('mod_title')) + '</div>';
        if (multi) {
          // "Pick many" groups keep the checkbox cards.
          html += '<div class="mod-sub">' + esc(t('opt_pick_many')) +
            (g.max !== null ? ' ' + esc(t('opt_pick_up_to', { n: g.max })) : '') + '</div>' +
            '<div class="radio-list" id="optg-box-' + key + '">' + g.choices.map(function (c, ci) {
              const delta = Number(c.delta)
                ? '<span class="mod-delta">+' + money(c.delta) + '</span>'
                : '<span class="mod-delta">' + esc(t('mod_free')) + '</span>';
              return '<label class="radio-card"><input type="checkbox" name="optg-' + key + '" value="' + ci + '" data-ci="' + ci +
                '" onchange="onOptChange(' + dish.id + ',' + gi + ',this)">' +
                '<span>' + esc(c.label) + '</span>' + delta + '</label>';
            }).join('') + '</div>' +
            '<div class="mod-count" id="optg-count-' + key + '">' +
            esc(t('opt_picked_count', { n: 0, m: g.choices.length })) + '</div>';
        } else {
          // "Pick one" groups: a simple dropdown — one tap to open, one tap to choose.
          html += '<div class="mod-sub">' + esc(t('opt_pick_one')) + '</div>' +
            '<div class="radio-list" id="optg-box-' + key + '" role="radiogroup" aria-label="' + esc(g.name || t('mod_title')) + '">' +
            g.choices.map(function (c, ci) {
              const delta = Number(c.delta)
                ? '<span class="mod-delta">+' + money(c.delta) + '</span>'
                : '<span class="mod-delta">' + esc(t('mod_free')) + '</span>';
              return '<label class="radio-card side-choice"><input type="radio" name="optg-' + key + '" value="' + ci + '" data-ci="' + ci + '"' +
                (ci === 0 ? ' checked' : '') + ' onchange="onOptChange(' + dish.id + ',' + gi + ',this)">' +
                '<span>' + esc(c.label) + '</span>' + delta + '</label>';
            }).join('') + '</div>';
        }
        html += '</div>';
      });
      html += '</div>';
    }

    // Live per-unit price preview (choices + add-ons), whenever customizable.
    // (dishIng comes from the public rows + ingredients-text fallback.)
    const dishIng = dishIngredients(dish);
    if (groups.length || dishIng.length) {
      html += '<div class="vendor-tag" id="dish-total"></div>';
    }

    // Ingredients: removable ones render as ON toggles (tap to remove),
    // fixed ones as plain info text, add-ons as "+ Add" switches with +$X.
    if (dishIng.length) {
      html += '<h2 class="section-title">' + esc(t('ing_title')) + '</h2><div class="ing-list" id="ing-list" data-dish="' + dish.id + '">';
      dishIng.forEach(function (ig) {
        const nm = ig.name || '';
        if (ig.included_by_default) {
          if (ig.removable) {
            html += '<label class="ing-row ingredient-choice"><input class="ingredient-check" type="checkbox" checked data-ing="rem" data-ing-name="' +
              esc(nm) + '" onchange="onIngChange(' + dish.id + ')">' +
              '<span class="ing-name">' + esc(nm) + '</span> <span class="ing-hint">' + esc(t('ing_tap_remove')) + '</span></label>';
          } else {
            html += '<div class="ing-row"><span class="ing-name">• ' + esc(nm) + '</span> <span class="ing-hint">' + esc(t('ing_fixed')) + '</span></div>';
          }
        } else {
          const price = Number(ig.extra_price) || 0;
          html += '<label class="ing-row ingredient-choice"><input class="ingredient-check" type="checkbox" data-ing="add" data-ing-name="' +
            esc(nm) + '" data-ing-price="' + price + '" onchange="onIngChange(' + dish.id + ')">' +
            '<span class="ing-name">' + esc(t('ing_add')) + ' ' + esc(nm) + '</span>' +
            (price ? ' <span class="mod-delta">+' + money(price) + '</span>' : '') + '</label>';
        }
      });
      html += '</div>';
    }

    // Your variations: existing customized cart lines for this dish, so
    // ordering the same dish with different options is visible and easy.
    html += dishVarsHTML(dish);

    if (v) {
      html += '<div class="madeby-card"><div class="who">' +
        '<div class="madeby-lbl">' + esc(t('dd_made_by')) + '</div>' +
        '<strong>' + esc(v.name) + '</strong>' +
        (v.area ? '<div class="vendor-tag">📍 ' + esc(v.area) + '</div>' : '') +
        '</div><button class="btn small" onclick="go(\'vendor\',' + v.id + ')">' + esc(t('dd_view_store')) + '</button></div>';
    }

    if (details.length) {
      html += '<h2 class="section-title">' + esc(t('dd_details')) + '</h2><div class="detail-grid">' +
        details.map(x => '<div class="detail-item"><div class="k">' + x[0] + ' ' + esc(x[1]) + '</div><div class="v">' + esc(x[2]) + '</div></div>').join('') +
        '</div>';
    }

    html += '<h2 class="section-title">' + esc(t('dd_reviews')) +
      (rev.count ? ' <span class="sub">' + rev.count + '</span>' : '') + '</h2>';
    html += rev.reviews.length
      ? rev.reviews.map(r => reviewCardHTML(r, v && v.name)).join('')
      : '<div class="empty">' + esc(t('no_reviews')) + '</div>';

    if (related.length) {
      html += '<h2 class="section-title">' + esc(t('dd_related')) + '</h2>' +
        '<div class="grid">' + related.map(dishCard).join('') + '</div>';
    }

    view.innerHTML = html;
    updateDishPrice(dish.id);
    injectDishJsonLd(dish, v);
    // === F3: scroll to the highlighted required groups after a quick-add landing ===
    if (hlGroups) {
      const cust = document.getElementById('dish-custom');
      if (cust) setTimeout(function () { cust.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 60);
    }
  } catch (e) {
    // Log the real cause (visible in the browser console) so a generic
    // "not found" never hides a JS error again.
    try { console.error('dish page failed for id ' + dishId + ':', e); } catch (e2) {}
    removeDishJsonLd();
    view.innerHTML = '<div class="empty"><span class="big">🔍</span>' + esc(t('dish_not_found')) + '<br><br>' +
      '<button class="btn" onclick="go(\'home\')">' + esc(t('back_home')) + '</button></div>';
  }
}

/* ================= cart & checkout ================= */
async function cartLines() {
  const keys = Object.keys(S.cart.items).filter(k => (S.cart.items[k] && S.cart.items[k].qty) > 0);
  const lines = [];
  for (const key of keys) {
    const e = S.cart.items[key];
    // === F5: bundle line — the bundle object rides on the entry; the
    // pseudo-dish keeps vendor grouping + price display working. ===
    if (e && e.bundleId && e.bundle) {
      const b = e.bundle;
      lines.push({
        key, bundle: b, qty: e.qty, modifier: null, cust: emptyCust(),
        dish: {
          id: null, name: b.name, vendor_id: b.vendor_id, price: b.price,
          photo_url: b.photo_url || '', discount_percent: 0, available: b.available,
        },
        unit: Number(b.price),
      });
      continue;
    }
    // === END F5 ===
    const id = entryDishId(key, e);
    if (!id) continue;
    const dish = await dishName(id);
    // Dish deleted/hidden since it was added: drop the stale line quietly.
    if (!dish) { delete S.cart.items[key]; saveCart(); continue; }
    lines.push({
      key, dish, qty: e.qty, modifier: (e && e.modifier) || null,
      cust: (e && e.cust) || emptyCust(), unit: custUnit(dish, e),
    });
  }
  return lines;
}

async function vCart() {
  const view = $('#view');
  S.leMap = {}; S.leSeq = 0; // v39: fresh inline-editor ids per render
  const groups = await cartGroups().catch(e => ({ error: e.message }));
  if (groups.error) { view.innerHTML = '<div class="error">' + esc(groups.error) + '</div>'; return; }
  if (!groups.length) {
    view.innerHTML = '<div class="empty"><span class="big">🛒</span>' + esc(t('cart_empty')) + '<br><br>' +
      '<button class="btn" onclick="go(\'home\')">' + esc(t('browse_dishes')) + '</button></div>';
    return;
  }
  S.checkout._groups = groups; // cached for the per-vendor payment hints
  const anyDelivery = groups.some(gr => gr.g.fulfillment === 'delivery');

  let html = '<h2 class="section-title">' + esc(t('cart_title')) + '</h2>';
  html += '<div class="steps"><span class="step current">① ' + esc(t('step_cart')) + '</span>' +
    '<span class="step-sep">→</span><span class="step">② ' + esc(t('step_details')) + '</span>' +
    '<span class="step-sep">→</span><span class="step">③ ' + esc(t('step_done')) + '</span></div>';
  html += '<div class="cart-layout"><div>';
  for (const gr of groups) {
    const v = gr.vendor, g = gr.g;
    const vendorRating = Number(v.rating_count) > 0
      ? '<span class="vendor-tag" aria-label="' + esc(t('reviews_count', { count: v.rating_count })) + '">★ ' + Number(v.avg_rating).toFixed(1) + ' (' + esc(t('reviews_count', { count: v.rating_count })) + ')</span>'
      : '';
    const f = String(v.fulfillment || 'both').toLowerCase();
    const allowPickup = f === 'pickup' || f === 'both';
    // === Delivery ZIP gating (Oct 2026): Delivery is offered only when the
    // vendor's zones serve the customer's ZIP. The server 422s unserved ZIPs —
    // this gate is the friendly front door, not the lock. ===
    const myZip = getZip();
    const allowDelivery = groupDeliveryAllowed(v);
    // === END ZIP gating ===
    html += '<div class="order-card" id="vendor-checkout-' + v.id + '" tabindex="-1"><div class="order-head"><strong>' + esc(v.name) + '</strong>' + vendorRating + fulfillBadge(v) + '</div>';
    const closedMsg = closedBlockMsg(v);
    if (closedMsg) html += '<div class="error">' + esc(closedMsg) + '</div>';
    for (const l of gr.lines) {
      // Cart items open their dish page on click (bundles have no dish page — not clickable).
      const openDish = l.bundle ? '' : ' onclick="go(\'dish\',' + l.dish.id + ')" style="cursor:pointer"';
      // === v39: inline sides/ingredients editor — the expander + the editor
      // itself render inside the line's info block.
      const leOpen = !!(S.lineEditOpen && S.lineEditOpen[l.key]);
      const leBtn = (!l.bundle && l.dish && l.dish.id && dishCustomizable(l.dish))
        ? '<button class="btn small ghost" onclick="event.stopPropagation();toggleLineEdit(\'' + leSafe(l.key) + '\')">🧩 ' + esc(t('sides_extras')) + '</button>'
        : '';
      html += '<div class="cart-line"><span' + openDish + '>' + dishImg(l.dish) + '</span>' +
        '<div class="info"><div class="dish-name"' + openDish + '>' + esc(l.dish.name) + '</div>' +
        custLinesHTML(l) + bundleLinesHTML(l) + // === F5: bundle components ===
        '<div class="vendor-tag">' + priceHTML(l.dish) + ' ' + esc(t('each')) + '</div>' +
        leBtn + (leOpen ? lineEditHTML(l) : '') + '</div>' +
        lineStepperHTML(l) +
        '<div class="price">' + money(l.unit * l.qty) + '</div></div>';
    }
    html += '<label class="field">' + esc(t('fulfillment')) + '</label><div class="radio-list">';
    if (allowPickup) html += '<label class="radio-card"><input type="radio" name="ful-' + v.id + '" value="pickup" ' +
      (g.fulfillment === 'pickup' ? 'checked' : '') + ' onchange="setGroupFulfillment(' + v.id + ',\'pickup\')"><span class="r-ico">🛍️</span>' + esc(t('pickup')) + '</label>';
    if (allowDelivery) html += '<label class="radio-card"><input type="radio" name="ful-' + v.id + '" value="delivery" ' +
      (g.fulfillment === 'delivery' ? 'checked' : '') + ' onchange="setGroupFulfillment(' + v.id + ',\'delivery\')"><span class="r-ico">🛵</span>' + esc(t('delivery')) +
      (gr.freeDelivery ? ' (' + esc(t('free_word')) + ')' // === v46: waived at this subtotal ===
        : Number(v.delivery_fee) > 0 ? esc(t('delivery_fee_suffix', { fee: money(v.delivery_fee) })) : '') + '</label>';
    // === Community drops (Oct 2026): a third fulfillment option when the
    // vendor has active drops serving the customer's ZIP. Drops are free
    // like pickup (no delivery fee). ===
    const drops = myZip ? await vendorDrops(v.id, myZip) : [];
    // The chosen drop may have vanished (deactivated / ZIP changed /
    // became full) since the group was cached — fall back to pickup.
    if (g.fulfillment === 'drop' && !drops.some(function (d) { return String(d.id) === String(g.dropId); })) {
      g.fulfillment = allowPickup ? 'pickup' : (allowDelivery ? 'delivery' : 'pickup');
      g.dropId = null;
    }
    for (const d of drops) {
      const checked = g.fulfillment === 'drop' && String(g.dropId) === String(d.id);
      html += '<label class="radio-card"><input type="radio" name="ful-' + v.id + '" value="drop-' + d.id + '" ' +
        (checked ? 'checked' : '') + ' onchange="setGroupDrop(' + v.id + ',' + d.id + ')">' +
        '<span class="r-ico">📦</span>' + esc(t('drop_join')) +
        '<div class="sub">' + esc(t('drop_option_sub', {
          label: d.label, date: fmtDay(d.drop_date), start: d.time_start, end: d.time_end,
        })) + '</div></label>';
    }
    // === END community drops ===
    html += '</div>';
    // === Delivery ZIP prompts (Oct 2026) ===
    if ((f === 'delivery' || f === 'both') && vendorOffersDelivery(v)) {
      if (!myZip) {
        // Vendor delivers somewhere but we don't know where the customer is yet.
        html += '<div class="hint">📍 ' + esc(t('zip_prompt_delivery')) +
          ' <button type="button" class="linklike" onclick="zipFormOpen()">' + esc(t('zip_enter')) + '</button></div>';
      } else if (!allowDelivery) {
        html += '<div class="notice">' + esc(t('zip_not_served_cart', { name: v.name, zip: myZip })) + '</div>';
      }
    }
    // === END ZIP prompts ===
    if (g.fulfillment === 'pickup') {
      // === F8: vendor weekly pickup slots — shown only when the vendor
      // configured active slots; then choosing one is required (the datetime
      // auto-fills from the slot, so no separate picker is shown). ===
      const slots = await vendorPickupSlots(v.id);
      if (slots.length) {
        html += '<label class="field">' + esc(t('pickup_time_vendor', { name: v.name })) + '</label>' +
          '<label class="field">' + esc(t('slot_pick')) + '</label>' +
          '<select id="pickup-slot-' + v.id + '" onchange="setGroupPickupSlot(' + v.id + ',this.value)">' +
          '<option value="">' + esc(t('slot_pick_ph')) + '</option>' +
          slots.map(s => '<option value="' + s.id + '"' +
            (String(g.pickupSlotId) === String(s.id) ? ' selected' : '') + '>' +
            esc(s.label) + '</option>').join('') + '</select>' +
          '<div class="hint">' + esc(t('slot_time_hint')) + '</div>';
      } else {
        // Calendar + rolling time wheel (Oct 2026).
        // v41: stash the cart's prep estimate on the group FIRST so the
        // wheel's lead time honors the dishes actually in the cart.
        g._leadMins = gr.lines.reduce(function (a, l) {
          return a + prepMins(l.dish, v) * (Number(l.qty) || 0);
        }, 0);
        html += pickupPickerHTML(v, g);
      }
      // === END F8 ===
    }
      html += pickupCardHTML(v); // === FEATURE 9: pickup-point card ===
    html += '<label class="field">' + esc(t('notes_vendor', { name: v.name })) + ' <span class="sub">' + esc(t('optional')) + '</span></label>' +
      '<textarea id="notes-' + v.id + '" rows="2" maxlength="1000" placeholder="' + esc(t('notes_ph')) + '" ' +
      'oninput="setGroupNotes(' + v.id + ',this.value)">' + esc(g.notes) + '</textarea>';
    html += '<table class="totals"><tr><td>' + esc(t('subtotal')) + '</td><td style="text-align:right">' + money(gr.subtotal) + '</td></tr>' +
      (gr.fee ? '<tr><td>' + esc(t('fee_row')) + '</td><td style="text-align:right">' + money(gr.fee) + '</td></tr>'
        : gr.freeDelivery ? '<tr><td>' + esc(t('fee_row')) + '</td><td style="text-align:right">' + esc(t('free_word')) + '</td></tr>' : '') + '</table>';
    // === v46: free-delivery progress messaging for delivery groups ===
    if (g.fulfillment === 'delivery') {
      const fdo = freeDeliveryOver(v);
      if (fdo !== null) {
        if (gr.freeDelivery) {
          html += '<div class="notice">🎉 ' + esc(t('free_delivery_applied')) + '</div>';
        } else {
          html += '<div class="hint">🛵 ' + esc(t('free_delivery_more', { amount: money(fdo - gr.subtotal), name: v.name })) + '</div>';
        }
      }
    }
    // === END v46 ===
    // Estimated prep time for this vendor's items: per-dish minutes × qty.
    const prepTotal = gr.lines.reduce(function (a, l) {
      return a + prepMins(l.dish, v) * (Number(l.qty) || 0);
    }, 0);
    html += '<div class="prep-est">⏱ ' + esc(t('est_prep')) + ': ~' + esc(fmtDur(prepTotal)) + '</div>';
    html += '</div>';
  }
  html += '<button class="btn small secondary" onclick="clearCart()">' + esc(t('clear_cart')) + '</button></div>';

  html += '<div class="summary" aria-label="' + esc(t('checkout_title')) + '"><h3>' + esc(t('checkout_title')) + '</h3>';
  if (anyDelivery) {
    // One shared delivery address for every delivery sub-order.
    // Pre-fill from the customer's saved structured address (still editable).
    if (!S.checkout.address && S.user) {
      const composed = composeAddress(S.user);
      if (composed) S.checkout.address = composed;
    }
    html += '<div class="hint" style="margin-bottom:.4rem;">' + esc(t('delivery_shared')) + '</div>';
    html += '<label class="field">' + esc(t('delivery_address')) + '</label>' +
      '<textarea id="delivery-address" rows="2" aria-label="' + esc(t('delivery_address')) + '" placeholder="' + esc(t('address_ph')) + '" ' +
      'oninput="S.checkout.address=this.value;updateMapsLink()">' + esc(S.checkout.address) + '</textarea>' +
      '<div id="maps-link" class="maps-link">' + mapsLink(S.checkout.address, t('maps_verify')) + '</div>';
  }

  const cardOn = await stripeStatus(); // v41: label the card option honestly
  // === v48: direct-pay pause — when ANY shop in the cart has direct
  // payments paused (unpaid commission), cash/Zelle/Venmo are hidden
  // entirely (the backend rejects them too) and the selection falls
  // back to card. ===
  const DIRECT_PAY_IDS = ['zelle', 'venmo', 'cash'];
  const anyDirectPaused = groups.some(gr => gr.vendor && gr.vendor.direct_pay_paused);
  if (anyDirectPaused && DIRECT_PAY_IDS.includes(S.checkout.payment)) S.checkout.payment = 'credit_card';
  const visiblePayments = anyDirectPaused ? PAYMENTS.filter(p => !DIRECT_PAY_IDS.includes(p.id)) : PAYMENTS;
  html += '<label class="field">' + esc(t('payment_method')) + '</label><div class="radio-list">' +
    visiblePayments.map(p => {
      const unavailable = p.id === 'credit_card' && !cardOn;
      return '<label class="radio-card' + (unavailable ? ' is-disabled' : '') + '"><input type="radio" name="pay" value="' + p.id + '" ' +
        (S.checkout.payment === p.id ? 'checked' : '') + (unavailable ? ' disabled' : '') + ' onchange="setPayment(this.value)">' +
        '<span class="r-ico">' + p.icon + '</span>' + esc(t(p.key)) +
        (p.id === 'credit_card'
          ? ' <small style="opacity:.75">' + esc(t(cardOn ? 'card_secure_hint' : 'card_coming_soon')) + '</small>'
          : '') + '</label>';
    }).join('') + '</div>' +
    (anyDirectPaused ? '<div class="notice">⏸ ' + esc(t('direct_pay_paused_notice')) + '</div>' : '') +
    payHintsHTML(groups, S.checkout.payment) +
    '<div class="hint" style="margin:.6rem 0;">' + esc(t('demo_hint')) + '</div>';

  html += promoBlockHTML();
  await loadLoyalty();
  html += loyaltyBlockHTML();
  html += guestBlockHTML();

  const subSum = groups.reduce((a, gr) => a + gr.subtotal, 0);
  const feeSum = groups.reduce((a, gr) => a + gr.fee, 0);
  html += loyaltyEarnPreviewHTML(subSum);
  html += totalsBreakdown(subSum, feeSum, null, cartDiscount(subSum), checkoutPointsOff(subSum, feeSum), groups.some(gr => gr.freeDelivery));
  html += '<button class="btn" style="width:100%" onclick="nextReview()">' + esc(t('next_review')) + '</button>';
  html += '</div></div>';
  view.innerHTML = html;
  const checkoutSteps = view.querySelector('.steps');
  if (checkoutSteps) {
    checkoutSteps.setAttribute('role', 'list');
    checkoutSteps.setAttribute('aria-label', t('checkout_title'));
    const currentStep = checkoutSteps.querySelector('.step.current');
    if (currentStep) {
      currentStep.setAttribute('role', 'listitem');
      currentStep.setAttribute('aria-current', 'step');
    }
  }
  centerPickupWheels(); // center each time wheel on its selected slot
}
window.clearCart = function () {
  S.cart = { items: {} };
  S.checkout.groups = {};
  saveCart(); updateAuthArea(); vCart();
};
window.setGroupFulfillment = function (vid, f) {
  const v = S.vendorById[vid];
  if (v) { const g = checkoutGroup(v); g.fulfillment = f; g.dropId = null; }
  vCart();
};
/* === Community drops (Oct 2026): active drops for this vendor + ZIP,
   cached per vendor|zip. Public endpoint — no auth needed. === */
async function vendorDrops(vendorId, zip) {
  S.vendorDrops = S.vendorDrops || {};
  const key = vendorId + '|' + zip;
  if (!S.vendorDrops[key]) {
    try {
      const d = await api('/vendors/' + vendorId + '/drops?zip=' + encodeURIComponent(zip));
      S.vendorDrops[key] = Array.isArray(d) ? d : [];
    } catch (e) { S.vendorDrops[key] = []; }
  }
  return S.vendorDrops[key];
}
window.setGroupDrop = function (vid, dropId) {
  const v = S.vendorById[vid];
  if (v) { const g = checkoutGroup(v); g.fulfillment = 'drop'; g.dropId = dropId; }
  vCart();
};
/* Human-readable drop line from the cached drops (for the review page). */
function dropLabelFor(vendorId, dropId) {
  const cache = S.vendorDrops || {};
  for (const k in cache) {
    const list = cache[k] || [];
    for (const d of list) {
      if (String(d.id) === String(dropId) && String(d.vendor_id) === String(vendorId)) {
        return d.label + ' · ' + fmtDay(d.drop_date) + ', ' + d.time_start + '–' + d.time_end;
      }
    }
  }
  return '';
}
/* === END community drops === */
window.setGroupPickup = function (vid, val) {
  const v = S.vendorById[vid];
  if (v) checkoutGroup(v).pickupAt = val;
};
/* === F8: vendor weekly pickup slots — cached per vendor; the checkout
   picker lists only ACTIVE slots. === */
async function vendorPickupSlots(vendorId, refresh) {
  S.vendorSlots = S.vendorSlots || {};
  if (refresh || !S.vendorSlots[vendorId]) {
    try {
      const slots = await api('/pickup-slots/vendor/' + vendorId);
      S.vendorSlots[vendorId] = Array.isArray(slots) ? slots : [];
    } catch (e) {
      if (refresh) throw e;
      S.vendorSlots[vendorId] = [];
    }
  }
  return S.vendorSlots[vendorId];
}
window.setGroupPickupSlot = function (vid, val) {
  const v = S.vendorById[vid];
  if (v) checkoutGroup(v).pickupSlotId = val ? Number(val) : null;
  /* === designer pass (launch day): when the customer picks a slot, auto-fill
     the pickup datetime from the slot's next occurrence — typing a separate
     time can only conflict with the chosen slot. Backend still receives a
     valid pickup_at, so no contract change. === */
  if (val && v) {
    const slots = (S.vendorSlots && S.vendorSlots[vid]) || [];
    const s = slots.find(function (x) { return String(x.id) === String(val); });
    if (s && s.next_date && s.start_time) {
      const dt = s.next_date + 'T' + String(s.start_time).slice(0, 5);
      checkoutGroup(v).pickupAt = dt;
      const el = document.getElementById('pickup-at-' + vid);
      if (el) el.value = dt;
    }
  }
};
/* === END F8 === */
window.setGroupNotes = function (vid, val) {
  const v = S.vendorById[vid];
  if (v) checkoutGroup(v).notes = val;
};
window.updateMapsLink = function () {
  const el = $('#maps-link');
  if (el) el.innerHTML = mapsLink(S.checkout.address, t('maps_verify'));
};

function showCheckoutError(message, target) {
  document.querySelectorAll('.checkout-inline-error').forEach(function (el) { el.remove(); });
  document.querySelectorAll('[aria-describedby="checkout-inline-error"]').forEach(function (el) {
    el.removeAttribute('aria-describedby');
  });
  const error = document.createElement('div');
  error.className = 'checkout-inline-error';
  error.id = 'checkout-inline-error';
  error.setAttribute('role', 'alert');
  error.textContent = message;
  if (target && target.parentNode) {
    target.insertAdjacentElement('beforebegin', error);
    target.setAttribute('aria-describedby', 'checkout-inline-error');
    target.focus({ preventScroll: true });
  } else {
    const summary = document.querySelector('.summary');
    if (summary) summary.insertBefore(error, summary.firstChild);
    error.setAttribute('tabindex', '-1');
    error.focus({ preventScroll: true });
  }
  error.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

window.nextReview = async function () {
  // Logged-out customers may check out as guests (name + phone required).
  if (!S.user && !S.checkout.guestMode) { S.flash = t('login_required'); go('login'); return; }
  if (!S.user) {
    const g = S.checkout.guest || {};
    if (!(g.name || '').trim() || !(g.phone || '').trim()) {
      showCheckoutError(t('guest_need_info'), $('#guest-name') && !String(g.name || '').trim() ? $('#guest-name') : $('#guest-phone'));
      return;
    }
  }
  // Vendors and admins may also place orders (Oct 2026) — they check out
  // exactly like customers. Guests are handled above.
  const groups = await cartGroups().catch(() => []);
  if (!groups.length) { go('cart'); return; }
  // Block closed/paused vendors — friendly message, no submit.
  for (const gr of groups) {
    const msg = closedBlockMsg(gr.vendor);
    if (msg) { showCheckoutError(msg, $('#vendor-checkout-' + gr.vendor.id)); return; }
  }
  for (const gr of groups) {
    const g = gr.g;
    // No valid fulfillment at all (delivery-only vendor whose zones don't serve
    // this ZIP): stop with the friendly message instead of a broken form.
    // Community drops are exempt — the drop itself carries the coverage
    // validation (server-enforced).
    const f0 = String(gr.vendor.fulfillment || 'both').toLowerCase();
    if (g.fulfillment !== 'drop' && !(f0 === 'pickup' || f0 === 'both') && !groupDeliveryAllowed(gr.vendor)) {
      if (!getZip()) {
        zipFormOpen();
        showCheckoutError(t('need_zip'), document.querySelector('#zip-wrap input'));
      } else {
        showCheckoutError(t('zip_not_served_cart', { name: gr.vendor.name, zip: getZip() }), $('#zip-wrap button'));
      }
      return;
    }
    if (g.fulfillment === 'pickup') {
      // Checkout now uses the calendar + time wheel (there is no pickup-at
      // input). Recompute the cart prep lead here and validate the state that
      // the picker actually stores; this also replaces a slot that expired
      // while the customer was on the checkout page.
      g._leadMins = gr.lines.reduce(function (a, l) {
        return a + prepMins(l.dish, gr.vendor) * (Number(l.qty) || 0);
      }, 0);
      // === F8: when the vendor configured active slots, one must be chosen ===
      let slots;
      try { slots = await vendorPickupSlots(gr.vendor.id, true); }
      catch (e) { showCheckoutError(e.message || t('pickup_time_invalid'), $('#pickup-slot-' + gr.vendor.id)); return; }
      if (slots.length) {
        const sel = $('#pickup-slot-' + gr.vendor.id);
        const sv = sel ? sel.value : g.pickupSlotId;
        if (!sv) { showCheckoutError(t('need_pickup_slot', { name: gr.vendor.name }), sel); return; }
        g.pickupSlotId = Number(sv);
        const selectedSlot = slots.find(function (s) { return String(s.id) === String(sv); });
        if (selectedSlot && selectedSlot.next_date && selectedSlot.start_time) {
          g.pickupAt = selectedSlot.next_date + 'T' + String(selectedSlot.start_time).slice(0, 5);
        }
      } else {
        g.pickupSlotId = null;
        const selected = pickupSel(gr.vendor, g);
        if (!selected.date || !selected.time) {
          showCheckoutError(t('need_pickup_time_vendor', { name: gr.vendor.name }), $('#pickup-time-' + gr.vendor.id)); return;
        }
        g.pickupAt = selected.date + 'T' + selected.time;
      }
      try { pickupAtToUTC(g.pickupAt); }
      catch (e) { showCheckoutError(t('pickup_time_invalid'), $('#pickup-time-' + gr.vendor.id) || $('#pickup-slot-' + gr.vendor.id)); return; }
      // === END F8 ===
    }
    // === Delivery ZIP (Oct 2026): per-vendor-group delivery_zip for checkout. ===
    if (g.fulfillment === 'delivery') {
      const z = getZip();
      if (gr.vendor.delivery_zips !== undefined && !vendorServesZip(gr.vendor, z)) {
        if (!z) {
          zipFormOpen();
          showCheckoutError(t('need_zip'), document.querySelector('#zip-wrap input'));
          return;
        }
        showCheckoutError(t('zip_not_served_cart', { name: gr.vendor.name, zip: z }), $('#zip-wrap button'));
        return;
      }
      g.deliveryZip = z || null;
    }
    // === END delivery ZIP ===
    // === Community drops (Oct 2026): the customer ZIP rides along as
    // delivery_zip so the server can validate drop coverage. ===
    if (g.fulfillment === 'drop') {
      const z = getZip();
      if (!z) {
        zipFormOpen();
        showCheckoutError(t('need_zip'), document.querySelector('#zip-wrap input'));
        return;
      }
      g.deliveryZip = z;
    }
    // === END community drops ===
    const notesEl = $('#notes-' + gr.vendor.id);
    if (notesEl) g.notes = notesEl.value;
  }
  if (groups.some(gr => gr.g.fulfillment === 'delivery')) {
    const el = $('#delivery-address');
    const val = (el ? el.value : S.checkout.address).trim();
    if (!val) { showCheckoutError(t('need_address'), el); return; }
    S.checkout.address = val;
  }
  go('review');
};

async function vReview() {
  const view = $('#view');
  S.leMap = {}; S.leSeq = 0; // v39: fresh inline-editor ids per render
  const groups = await cartGroups().catch(e => ({ error: e.message }));
  if (groups.error) { view.innerHTML = '<div class="error">' + esc(groups.error) + '</div>'; return; }
  if (!groups.length) { go('cart'); return; }
  const pay = PAYMENTS.find(p => p.id === S.checkout.payment);

  let html = '<h2 class="section-title">' + esc(t('review_title')) + '</h2><div class="cart-layout"><div>';
  for (const gr of groups) {
    const v = gr.vendor, g = gr.g;
    html += '<div class="order-card"><div class="order-head"><strong>' + esc(v.name) + '</strong>' + fulfillBadge(v) + '</div>';
    html += '<ul class="order-items review-lines">' + gr.lines.map(l => {
      const picks = custLinesHTML(l) + bundleLinesHTML(l); // === F5: bundle components ===
      // === v39: inline editor on review lines too — same component as cart.
      const rleOpen = !!(S.lineEditOpen && S.lineEditOpen[l.key]);
      const rleBtn = (!l.bundle && l.dish && l.dish.id && dishCustomizable(l.dish))
        ? ' <button class="btn small ghost" onclick="toggleLineEdit(\'' + leSafe(l.key) + '\')">🧩 ' + esc(t('sides_extras')) + '</button>'
        : '';
      return '<li class="review-line"><div class="review-line-head"><strong>' + l.qty + ' × ' + esc(l.dish.name) + '</strong>' + rleBtn +
        '<span class="price">' + money(l.unit * l.qty) + '</span></div>' +
        (picks ? '<div class="pick-highlight">' + picks + '</div>' : '') +
        (rleOpen ? lineEditHTML(l) : '') + '</li>';
    }).join('') + '</ul>';
    html += '<div class="vendor-tag">' +
      (g.fulfillment === 'drop'
        ? '📦 ' + esc(t('drop_join')) + ' · <strong>' + esc(dropLabelFor(v.id, g.dropId)) + '</strong>'
        : g.fulfillment === 'pickup'
        ? '🛍️ ' + esc(t('pickup')) + ' · <strong>' + esc(t('pickup_time_is')) + '</strong> ' + esc(fmtPickupDate(pickupAtToUTC(g.pickupAt)))
        : '🛵 ' + esc(t('delivery')) + ' · <strong>' + esc(t('deliver_to')) + '</strong> ' + esc(S.checkout.address) + mapsLink(S.checkout.address)) +
      (gr.fee ? ' · ' + esc(t('fee_row')) + ' ' + money(gr.fee)
        : gr.freeDelivery ? ' · ' + esc(t('fee_row')) + ' ' + esc(t('free_word')) : '') +
      ' · <strong>' + money(gr.subtotal + gr.fee) + '</strong></div>';
    if ((g.notes || '').trim()) {
      html += '<div class="vendor-tag">📝 ' + esc(g.notes.trim()) + '</div>';
    }
    html += '</div>';
  }
  html += '<div class="order-card"><strong>' + esc(t('payment_is')) + '</strong> ' + (pay ? pay.icon + ' ' + esc(t(pay.key)) : esc(S.checkout.payment)) +
    payHintsHTML(groups, S.checkout.payment) + '</div>';
  html += '<button class="btn secondary" onclick="go(\'cart\')">' + esc(t('back_to_cart')) + '</button></div>';
  const grand = groups.reduce((a, gr) => a + gr.subtotal + gr.fee, 0);
  const feeSum = groups.reduce((a, gr) => a + gr.fee, 0);
  const subSum = groups.reduce((a, gr) => a + gr.subtotal, 0);
  await loadLoyalty();
  html += '<div class="summary"><h3>' + esc(t('order_total')) + '</h3>' + promoBlockHTML() + loyaltyBlockHTML() +
    loyaltyEarnPreviewHTML(subSum) +
    totalsBreakdown(subSum, feeSum, null, cartDiscount(subSum), checkoutPointsOff(subSum, feeSum), groups.some(gr => gr.freeDelivery)) +
    '<div class="hint" style="margin:.6rem 0;">' + esc(t('multi_split_hint')) + '</div>' +
    '<div id="review-error" class="checkout-inline-error" role="alert" tabindex="-1" hidden></div>' +
    '<button class="btn" style="width:100%" onclick="placeOrder(this)">' + esc(t('place_order')) + '</button></div></div>';
  view.innerHTML = html;
  const reviewSteps = document.createElement('div');
  reviewSteps.className = 'steps';
  reviewSteps.setAttribute('role', 'list');
  reviewSteps.setAttribute('aria-label', t('checkout_title'));
  reviewSteps.innerHTML = '<span class="step" role="listitem">1. ' + esc(t('step_cart')) + '</span>' +
    '<span class="step-sep" aria-hidden="true">›</span><span class="step current" role="listitem" aria-current="step">2. ' + esc(t('step_details')) + '</span>' +
    '<span class="step-sep" aria-hidden="true">›</span><span class="step" role="listitem">3. ' + esc(t('step_done')) + '</span>';
  view.insertBefore(reviewSteps, view.firstChild);
}

window.placeOrder = async function (btn) {
  btn = btn || document.querySelector('.summary button[onclick^="placeOrder"]');
  if (!btn) return;
  btn.disabled = true; btn.textContent = t('placing');
  try {
    if (S.checkout.payment === 'credit_card' && !(await stripeStatus())) {
      throw new Error(t('card_not_enabled'));
    }
    const groups = await cartGroups();
    // Closed/paused vendors block the submit with the friendly message.
    for (const gr of groups) {
      const msg = closedBlockMsg(gr.vendor);
      if (msg) throw new Error(msg);
    }
    const isGuest = !S.user;
    if (isGuest) {
      const g = S.checkout.guest || {};
      if (!(g.name || '').trim() || !(g.phone || '').trim()) throw new Error(t('guest_need_info'));
    }
    const payload = {
      groups: groups.map(gr => ({
        vendor_id: gr.vendor.id,
        items: gr.lines.map(l => {
          // === F5: bundle lines are identified by bundle_id ===
          if (l.bundle) return { bundle_id: l.bundle.id, quantity: l.qty };
          // === END F5 ===
          const cust = l.cust || emptyCust();
          const item = { dish_id: l.dish.id, quantity: l.qty };
          // New multi-group shape: [{option_id, choice_labels}]. Groups
          // without an id can't be validated server-side — skipped.
          const mods = (cust.modifiers || [])
            .filter(m => m.option_id !== null && m.option_id !== undefined &&
              m.choices && m.choices.length)
            .map(m => ({ option_id: m.option_id, choice_labels: m.choices.map(c => c.label) }));
          if (mods.length) item.modifiers = mods;
          item.removed_ingredients = (cust.removed || []).slice();
          item.added_ingredients = (cust.added || [])
            .map(a => (a && a.name !== undefined) ? a.name : String(a));
          if (l.modifier) { // legacy single-modifier carts — backend still accepts
            item.modifier = { choice_label: l.modifier.choice_label, delta: l.modifier.delta };
          }
          return item;
        }),
        fulfillment: gr.g.fulfillment,
        pickup_at: gr.g.fulfillment === 'pickup' ? pickupAtToUTC(gr.g.pickupAt) : null,
        // === F8: chosen weekly pickup slot (null when the vendor has none) ===
        pickup_slot_id: gr.g.fulfillment === 'pickup' ? (gr.g.pickupSlotId || null) : null,
        // === END F8 ===
        delivery_address: gr.g.fulfillment === 'delivery' ? S.checkout.address.trim() : null,
        // === Delivery ZIP (Oct 2026): per-vendor-group; the server 422s unserved ZIPs ===
        delivery_zip: (gr.g.fulfillment === 'delivery' || gr.g.fulfillment === 'drop') ? (gr.g.deliveryZip || getZip() || null) : null,
        // === END delivery ZIP ===
        // === Community drops (Oct 2026): drop batch id for drop orders ===
        drop_id: gr.g.fulfillment === 'drop' ? (gr.g.dropId || null) : null,
        // === END community drops ===
        notes: (gr.g.notes || '').trim() || null,
      })),
      payment_method: S.checkout.payment,
      promo_code: S.checkout.promo ? S.checkout.promo.code : null,
      // === FEATURE 2: referral share code — the server re-validates it ===
      referral_code: S.referral || null,
      // === END FEATURE 2 ===
      // Loyalty points: guests never have a balance; the backend validates and
      // is authoritative on the actual dollar discount.
      ...(S.checkout.redeem_points > 0 && !isGuest ? { redeem_points: S.checkout.redeem_points } : {}),
    };
    let res;
    if (isGuest) {
      const g = S.checkout.guest;
      res = await api('/orders/checkout-guest', {
        method: 'POST',
        body: JSON.stringify({
          guest: { name: g.name.trim(), phone: g.phone.trim(), email: (g.email || '').trim() || null },
          groups: payload.groups,
          payment_method: payload.payment_method,
          promo_code: payload.promo_code,
          referral_code: S.referral || null, // === FEATURE 2: server re-validates ===
        }),
      });
    } else {
      res = await api('/orders/checkout-multi', { method: 'POST', body: JSON.stringify(payload) });
    }
    S.cart = { items: {} };
    S.checkout.groups = {};
    S.checkout.promo = null;
    S.checkout.redeem_points = 0;
    S.loyalty.balance = null; // points changed — refetch next time
    saveCart(); updateAuthArea();
    if (S.checkout.payment === 'credit_card') {
      // ONE Stripe session for the whole multi-vendor checkout; when card
      // payments aren't configured (501) fall back to the recorded-only flow.
      try {
        const s = await api('/stripe/checkout-group-session',
          { method: 'POST', body: JSON.stringify({ checkout_group: res.checkout_group }) });
        if (s && s.checkout_url) { window.location.href = s.checkout_url; return; }
        throw new Error('no checkout url');
      } catch (e) {
        S.flash = t('card_start_failed');
      }
    }
    S.lastCheckout = res;
    go('confirm');
  } catch (e) {
    btn.disabled = false; btn.textContent = t('place_order');
    // errText surfaces backend 422s (e.g. stock exceeded) readably.
    const error = $('#review-error');
    if (error) {
      error.textContent = t('order_failed') + errText(e);
      error.hidden = false;
      error.focus();
      error.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
  }
};

async function vConfirm() {
  const view = $('#view');
  const c = S.lastCheckout;
  if (!c || !c.orders || !c.orders.length) {
    view.innerHTML = '<div class="empty"><span class="big">🧾</span>' + esc(t('no_recent')) + '</div>';
    return;
  }
  const orders = c.orders;
  const guest = (S.checkout.guest && S.checkout.guest.name && S.checkout.guest.name.trim()) || t('guest_name');
  let html = '<div class="form-card" style="max-width:640px;"><div class="center">' +
    '<div style="font-size:3rem;">🎉</div><h2>' + esc(t('orders_placed')) + '</h2>' +
    '<p>' + t('confirm_multi_head', { n: orders.length, total: money(c.grand_total) }) + '</p></div>';
  for (const o of orders) {
    const pay = PAYMENTS.find(p => p.id === o.payment_method);
    html += '<div class="order-card"><div class="order-head"><strong>' + esc(t('order_num')) + o.id + '</strong>' +
      '<span>' + esc(o.vendor_name) + '</span></div>';
    html += '<ul class="order-items">' + o.items.map(i =>
      '<li>' + i.quantity + ' × ' + esc(i.dish_name) + orderItemExtraHTML(i) +
      ' — ' + money(Number(i.unit_price) * i.quantity) + '</li>').join('') + '</ul>';
    if (o.fulfillment === 'pickup' && o.pickup_at) html += '<p><strong>' + esc(t('pickup_time_is')) + '</strong> ' + esc(fmtPickupDate(o.pickup_at)) + '</p>';
    if (o.fulfillment === 'pickup') {
      // Pickup address comes from the vendor's structured address — shown here
      // only for pickup orders, never for delivery.
      try {
        const vv = await vendorById(o.vendor_id);
        html += pickupAddrHTML(vv);
        html += pickupCardHTML(vv); // === FEATURE 9: pickup-point card ===
      } catch (e) { /* vendor gone — skip */ }
    }
    if (o.fulfillment === 'delivery' && o.delivery_address) {
      html += '<p><strong>' + esc(t('deliver_to')) + '</strong> ' + esc(o.delivery_address) + mapsLink(o.delivery_address) + '</p>';
    }
    html += '<p><strong>' + esc(t('payment_is')) + '</strong> ' + (pay ? pay.icon + ' ' + esc(t(pay.key)) : esc(o.payment_method)) +
      (o.payment_method && o.payment_method !== 'credit_card' ? ' <small>' + esc(t('recorded_only')) + '</small>' : '') + '</p>' +
      totalsBreakdown(Number(o.subtotal), Number(o.delivery_fee || 0), o.tax, discountOf(o), pointsDiscountOf(o),
        o.fulfillment === 'delivery' && !(Number(o.delivery_fee) > 0)) +
      '<div class="notice">' + t('vendor_notified', { name: esc(o.vendor_name) }) + '</div>' +
      '<div class="order-actions"><button class="btn small secondary" onclick="reorder(' + o.id + ')">' +
      esc(t('order_again')) + '</button></div></div>';
  }
  // One combined email preview (the customer gets one confirmation email per
  // sub-order; the preview shows the first).
  const o0 = orders[0];
  html += '<div class="email-preview"><div class="e-head">📧 <strong>' + esc(t('email_head')) + '</strong> ' + esc(t('email_sim')) + '</div>' +
    '<div class="e-body"><h4>' + t('email_thanks', { name: esc(S.user ? S.user.name : guest) }) + '</h4>' +
    '<p>' + t('email_hi', { name: esc(S.user ? S.user.name : guest) }) + '<br>' +
    t('email_received', { id: o0.id, vendor: esc(o0.vendor_name), total: money(o0.total) }) +
    (o0.fulfillment === 'pickup'
      ? t('email_pickup', { time: esc(fmtPickupDate(o0.pickup_at)) })
      : t('email_delivery')) + '<br><br>' + esc(t('email_bye')) + '</p></div></div>';
  // Guests can't track orders — nudge them to create an account.
  if (!S.user) {
    html += '<div class="notice">💡 ' + esc(t('guest_upsell')) + ' ' +
      '<a href="#" data-go="signup"><strong>' + esc(t('nav_signup')) + '</strong></a></div>';
  }
  html += '<div class="center mt"><button class="btn" onclick="go(\'orders\')">' + esc(t('view_orders')) + '</button> ' +
    '<button class="btn secondary" onclick="go(\'home\')">' + esc(t('back_home')) + '</button></div></div>';
  view.innerHTML = html;
}

/* ============ Stripe return: /orders/<id>/paid ============ */
window.payByCard = async function (orderId) {
  try {
    const s = await api('/stripe/checkout-session',
      { method: 'POST', body: JSON.stringify({ order_id: orderId }) });
    if (s && s.checkout_url) { window.location.href = s.checkout_url; return; }
    throw new Error('no checkout url');
  } catch (e) {
    alert(t('card_pay_failed'));
  }
};

async function vPaid(arg) {
  const view = $('#view');
  const orderId = arg && arg.id;
  if (!S.user) { go('login'); return; }
  if (!orderId) { view.innerHTML = '<div class="error">' + esc(t('missing_order')) + '</div>'; return; }
  view.innerHTML = '<div class="empty"><span class="big">💳</span>' + esc(t('confirming_pay')) + '</div>';
  let order = null;
  // The Stripe webhook usually lands within seconds; poll a few times, then stop.
  for (let i = 0; i < 4 && !(order && order.paid); i++) {
    try { order = await api('/orders/' + orderId); }
    catch (e) { break; }
    if (order && !order.paid && i < 3) await new Promise(r => setTimeout(r, 2000));
  }
  if (!order) { view.innerHTML = '<div class="error">' + esc(t('order_load_err')) + esc(orderId) + '.</div>'; return; }
  let html = '<div class="form-card" style="max-width:640px;"><div class="center">';
  if (order.paid) {
    html += '<div style="font-size:3rem;">✅</div><h2>' + esc(t('pay_success')) + '</h2>' +
      '<p>' + esc(t('order_num')) + '<strong>' + order.id + '</strong> · ' + money(order.total) +
      esc(t('pay_success_sub')) + '</p>';
  } else {
    html += '<div style="font-size:3rem;">⏳</div><h2>' + esc(t('pay_pending')) + '</h2>' +
      '<p>' + t('pay_pending_sub', { id: order.id }) + '</p>';
  }
  html += '<div class="center mt"><button class="btn" onclick="go(\'order\',' + order.id + ')">' + esc(t('track_order')) + '</button> ' +
    '<button class="btn secondary" onclick="go(\'home\')">' + esc(t('back_home')) + '</button></div></div></div>';
  view.innerHTML = html;
}

function vPaidCheckout() {
  const view = $('#view');
  view.innerHTML = '<div class="form-card center"><div style="font-size:3rem">✅</div>' +
    '<h2>' + esc(t('card_group_paid_title')) + '</h2><p>' + esc(t('card_group_paid_desc')) + '</p>' +
    '<button class="btn" onclick="go(\'home\')">' + esc(t('browse_dishes')) + '</button></div>';
}

/* Legacy hash links (including Stripe returns) are translated to path routes
   during boot so bookmarks from older versions continue to work. */
function parseReturnHash() {
  const h = window.location.hash || '';
  let m = h.match(/^#\/paid-checkout(?:[?#]|$)/);
  if (m) {
    try { history.replaceState(null, '', window.location.pathname + window.location.search); } catch (e) {}
    return { route: 'paid-checkout', arg: null };
  }
  m = h.match(/^#\/orders(?:[?#]|$)/);
  if (m) {
    try { history.replaceState(null, '', window.location.pathname + window.location.search); } catch (e) {}
    return { route: 'orders', arg: null };
  }
  m = h.match(/^#\/order\/(\d+)\/paid/);
  if (m) {
    const sid = (h.match(/[?&]session_id=([^&]+)/) || [])[1] || null;
    try { history.replaceState(null, '', window.location.pathname + window.location.search); } catch (e) {}
    return { route: 'paid', arg: { id: Number(m[1]), sessionId: sid } };
  }
  m = h.match(/^#\/order\/(\d+)(?:[?#]|$)/);
  if (m) {
    try { history.replaceState(null, '', window.location.pathname + window.location.search); } catch (e) {}
    return { route: 'order', arg: Number(m[1]) };
  }
  // Shared dish link (#/dish/42): open the dish detail page.
  m = h.match(/^#\/dish\/(\d+)(?:[?#]|$)/);
  if (m) {
    return { route: 'dish', arg: Number(m[1]) };
  }
  // === FEATURE 2: shared vendor menu link (#/vendor/12 or
  // #/vendor/12?ref=AB12CD34). A ?ref= code is remembered (localStorage)
  // and sent at checkout for server-side referral attribution. ===
  m = h.match(/^#\/vendor\/(\d+)(?:[?#]|$)/);
  if (m) {
    const ref = (h.match(/[?&]ref=([^&#]+)/) || [])[1] || null;
    if (ref) {
      try {
        S.referral = decodeURIComponent(ref).trim() || null;
        if (S.referral) localStorage.setItem('ehf_referral', S.referral);
      } catch (e) { /* bad encoding — ignore */ }
    }
    try { history.replaceState(null, '', window.location.pathname + window.location.search); } catch (e) {}
    return { route: 'vendor', arg: Number(m[1]) };
  }
  // === END FEATURE 2 ===
  // Email verification link (#/verify-email?token=...).
  m = h.match(/^#\/verify-email\/?(?:[?#]|$)/);
  if (m) {
    const tok = (h.match(/[?&]token=([^&#]+)/) || [])[1] || null;
    try { history.replaceState(null, '', window.location.pathname + window.location.search); } catch (e) {}
    return { route: 'verify-email', arg: tok ? decodeURIComponent(tok) : null };
  }
  // Vendor application form (#/apply).
  m = h.match(/^#\/apply(?:[?#]|$)/);
  if (m) {
    try { history.replaceState(null, '', window.location.pathname + window.location.search); } catch (e) {}
    return { route: 'apply', arg: null };
  }
  // Event catering request form (#/catering).
  m = h.match(/^#\/catering(?:[?#]|$)/);
  if (m) {
    try { history.replaceState(null, '', window.location.pathname + window.location.search); } catch (e) {}
    return { route: 'catering', arg: null };
  }
  return null;
}

/* ================= auth views ================= */
function vLogin() {
  return '<div class="form-card"><h2>' + esc(t('login_title')) + '</h2>' +
    '<div class="hint">' + esc(t('login_demo')) + ' <code>customer@demo.com</code> / <code>demo1234</code><br>' +
    esc(t('login_demo_vendor')) + ' <code>vendor@demo.com</code> / <code>demo1234</code></div>' +
    '<div id="login-err"></div>' +
    '<label class="field">' + esc(t('email_label')) + '</label><input type="email" id="li-email" autocomplete="email">' +
    '<label class="field">' + esc(t('password_label')) + '</label><input type="password" id="li-pass" autocomplete="current-password">' +
    '<div class="mt"><button class="btn" id="li-btn" style="width:100%" onclick="doLogin()">' + esc(t('login_title')) + '</button></div>' +
    '<p class="center"><a href="#" data-go="forgot">' + esc(t('forgot_q')) + '</a></p>' +
    '<p class="center">' + esc(t('no_account')) + ' <a href="#" data-go="signup">' + esc(t('nav_signup')) + '</a></p></div>';
}
window.doLogin = async function () {
  const err = $('#login-err');
  const btn = $('#li-btn');
  err.innerHTML = '';
  if (btn) btn.disabled = true;
  try {
    const r = await api('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email: $('#li-email').value.trim(), password: $('#li-pass').value }),
    });
    S.token = r.access_token;
    localStorage.setItem('ehf_token', S.token);
    await loadMe();
    await loadFavs();
    updateAuthArea();
    if (S.user.role === 'vendor') { window.location.href = '/vendor/'; return; }
    go('home');
  } catch (e) { err.innerHTML = '<div class="error">' + esc(e.message) + '</div>'; }
  finally { if (btn) btn.disabled = false; }
};

function vSignup() {
  return '<div class="form-card"><h2>' + esc(t('signup_title')) + '</h2>' +
    '<div id="su-err"></div>' +
    '<label class="field">' + esc(t('name_label')) + '</label><input type="text" id="su-name" autocomplete="name">' +
    '<label class="field">' + esc(t('email_label')) + '</label><input type="email" id="su-email" autocomplete="email">' +
    '<label class="field">' + esc(t('password_label')) + '</label><input type="password" id="su-pass" autocomplete="new-password">' +
    '<label class="field">' + esc(t('phone_label')) + ' <span class="sub">' + esc(t('optional')) + '</span></label><input type="tel" id="su-phone" autocomplete="tel" maxlength="40">' +
    '<div class="form-sub">' + esc(t('address_h')) + ' <span class="sub">' + esc(t('optional')) + '</span></div>' +
    '<label class="field">' + esc(t('addr_street')) + '</label><input type="text" id="su-street" maxlength="120" autocomplete="street-address">' +
    '<label class="field">' + esc(t('addr_apt')) + ' <span class="sub">' + esc(t('optional')) + '</span></label><input type="text" id="su-apt" maxlength="40">' +
    '<div class="row2"><div><label class="field">' + esc(t('addr_city')) + '</label><input type="text" id="su-city" maxlength="80" autocomplete="address-level2"></div>' +
    '<div><label class="field">' + esc(t('addr_state')) + '</label><select id="su-state" autocomplete="address-level1">' + stateOptions('') + '</select></div></div>' +
    '<label class="field">' + esc(t('addr_zip')) + '</label><input type="text" id="su-zip" maxlength="10" inputmode="numeric" placeholder="' + esc(t('addr_zip_ph')) + '" autocomplete="postal-code">' +
    '<div class="mt"><button class="btn" id="su-btn" style="width:100%" onclick="doSignup()">' + esc(t('nav_signup')) + '</button></div>' +
    '<p class="center">' + esc(t('have_account')) + ' <a href="#" data-go="login">' + esc(t('nav_login')) + '</a></p></div>';
}
window.doSignup = async function () {
  const err = $('#su-err');
  const btn = $('#su-btn');
  err.innerHTML = '';
  const zip = $('#su-zip').value.trim();
  if (!zipOk(zip)) { err.innerHTML = '<div class="error">' + esc(t('zip_invalid')) + '</div>'; return; }
  if (btn) btn.disabled = true;
  try {
    const r = await api('/auth/register', {
      method: 'POST',
      body: JSON.stringify({
        name: $('#su-name').value.trim(),
        email: $('#su-email').value.trim(),
        password: $('#su-pass').value,
        phone: $('#su-phone').value.trim() || null,
        street_address: $('#su-street').value.trim() || null,
        apt: $('#su-apt').value.trim() || null,
        city: $('#su-city').value.trim() || null,
        state: $('#su-state').value || null,
        zipcode: zip || null,
      }),
    });
    if (!r.access_token) {
      // Email already registered: the backend sends the owner a sign-in link
      // instead of revealing anything. Point the user at the login page.
      err.innerHTML = '<div class="notice">' + esc(t('signup_exists')) + '</div>';
      setTimeout(function () { go('login'); }, 2500);
      return;
    }
    S.token = r.access_token;
    localStorage.setItem('ehf_token', S.token);
    await loadMe();
    await loadFavs();
    updateAuthArea();
    go('home');
  } catch (e) { err.innerHTML = '<div class="error">' + esc(e.message) + '</div>'; }
  finally { if (btn) btn.disabled = false; }
};

/* ================= forgot / reset password ================= */
function vForgot() {
  return '<div class="form-card"><h2>' + esc(t('forgot_q')) + '</h2>' +
    '<p class="hint">' + esc(t('forgot_hint')) + '</p>' +
    '<div id="fg-msg"></div>' +
    '<label class="field">' + esc(t('email_label')) + '</label><input type="email" id="fg-email" autocomplete="email">' +
    '<div class="mt"><button class="btn" style="width:100%" onclick="doForgot()">' + esc(t('send_code')) + '</button></div>' +
    '<p class="center">' + esc(t('have_code')) + ' <a href="#" data-go="reset">' + esc(t('enter_here')) + '</a></p>' +
    '<p class="center"><a href="#" data-go="login">' + esc(t('back_login')) + '</a></p></div>';
}
window.doForgot = async function () {
  const msg = $('#fg-msg');
  msg.innerHTML = '';
  const email = $('#fg-email').value.trim();
  if (!email) { msg.innerHTML = '<div class="error">' + esc(t('need_email')) + '</div>'; return; }
  try {
    await api('/auth/forgot', { method: 'POST', body: JSON.stringify({ email }) });
    msg.innerHTML = '<div class="notice">' + esc(t('code_sent')) +
      '<a href="#" data-go="reset">' + esc(t('enter_code')) + '</a></div>';
  } catch (e) { msg.innerHTML = '<div class="error">' + esc(e.message) + '</div>'; }
};
function vReset() {
  return '<div class="form-card"><h2>' + esc(t('reset_title')) + '</h2>' +
    '<p class="hint">' + esc(t('reset_hint')) + '</p>' +
    '<div id="rs-msg"></div>' +
    '<label class="field">' + esc(t('reset_code_label')) + '</label><input type="text" id="rs-token" autocomplete="off" placeholder="' + esc(t('reset_code_ph')) + '">' +
    '<label class="field">' + esc(t('new_password')) + '</label><input type="password" id="rs-new" autocomplete="new-password">' +
    '<label class="field">' + esc(t('confirm_password')) + '</label><input type="password" id="rs-confirm" autocomplete="new-password">' +
    '<div class="mt"><button class="btn" style="width:100%" onclick="doReset()">' + esc(t('do_reset')) + '</button></div>' +
    '<p class="center"><a href="#" data-go="login">' + esc(t('back_login')) + '</a></p></div>';
}
window.doReset = async function () {
  const msg = $('#rs-msg');
  msg.innerHTML = '';
  const token = $('#rs-token').value.trim();
  const nw = $('#rs-new').value, cf = $('#rs-confirm').value;
  if (!token || !nw) { msg.innerHTML = '<div class="error">' + esc(t('fill_all')) + '</div>'; return; }
  if (nw !== cf) { msg.innerHTML = '<div class="error">' + esc(t('pw_mismatch')) + '</div>'; return; }
  if (nw.length < 8) { msg.innerHTML = '<div class="error">' + esc(t('pw_short')) + '</div>'; return; }
  try {
    await api('/auth/reset', { method: 'POST', body: JSON.stringify({ token, new_password: nw }) });
    S.flash = t('pw_reset_done');
    go('login');
  } catch (e) { msg.innerHTML = '<div class="error">' + esc(e.message) + '</div>'; }
};

/* ================= email verification (#/verify-email?token=...) ============ */
/* Verifies the token via the backend and shows a success or invalid-link
   message. Nothing is blocked when unverified — the profile page just nudges. */
async function vVerifyEmail(token) {
  const view = $('#view');
  if (!token) {
    view.innerHTML = '<div class="form-card"><h2>' + esc(t('verify_title')) + '</h2>' +
      '<div class="error">' + esc(t('verify_missing')) + '</div></div>';
    return;
  }
  view.innerHTML = '<div class="empty"><span class="big">✉️</span>' + esc(t('verify_loading')) + '</div>';
  try {
    await api('/auth/verify-email?token=' + encodeURIComponent(token));
    // Refresh the session so the profile nudge clears right away.
    try { await loadMe(); updateAuthArea(); } catch (e) { /* keep going */ }
    view.innerHTML = '<div class="form-card center"><div style="font-size:3rem;">✅</div>' +
      '<h2>' + esc(t('verify_success')) + '</h2><br>' +
      '<button class="btn" onclick="go(\'home\')">' + esc(t('back_home')) + '</button></div>';
  } catch (e) {
    view.innerHTML = '<div class="form-card"><h2>' + esc(t('verify_title')) + '</h2>' +
      '<div class="error">' + esc(t('verify_invalid')) + '</div><br>' +
      '<button class="btn" onclick="go(\'home\')">' + esc(t('back_home')) + '</button></div>';
  }
}

/* ================= customer orders ================= */
async function vOrders() {
  const view = $('#view');
  if (!S.user) { go('login'); return; }
  view.innerHTML = '<div class="empty"><span class="big">🧾</span>' + esc(t('orders_loading')) + '</div>';
  try {
    const orders = await api('/orders');
    if (!orders.length) {
      view.innerHTML = '<div class="empty"><span class="big">🧾</span>' + esc(t('orders_empty')) + '<br><br>' +
        '<button class="btn" onclick="go(\'home\')">' + esc(t('browse_dishes')) + '</button></div>';
      return;
    }
    view.innerHTML = '<h2 class="section-title">' + esc(t('orders_title')) + '</h2>' + groupOrdersHTML(orders);
    // === F10: tick the retry countdowns every 30s ===
    if (S.retryTimer) clearInterval(S.retryTimer);
    tickRetryCountdowns();
    S.retryTimer = setInterval(tickRetryCountdowns, 30000);
    // === END F10 ===
  } catch (e) {
    view.innerHTML = '<div class="error">' + esc(t('orders_err')) + esc(e.message) + '</div>';
  }
}

/* Group sub-orders from one multi-vendor checkout under a shared header so
   the customer sees them as one shopping trip. Orders are already sorted
   newest-first; sub-orders of one checkout sit next to each other. */
function groupOrdersHTML(orders) {
  let html = '';
  let i = 0;
  while (i < orders.length) {
    const o = orders[i];
    if (o.checkout_group) {
      const grp = [o];
      let j = i + 1;
      while (j < orders.length && orders[j].checkout_group === o.checkout_group) {
        grp.push(orders[j]);
        j++;
      }
      if (grp.length > 1) {
        const grand = grp.reduce((a, x) => a + Number(x.total), 0);
        html += '<div class="checkout-group"><div class="checkout-group-head">🛍️ ' +
          esc(t('checkout_group_title', { date: fmtDate(o.created_at), n: grp.length })) +
          ' · <strong>' + money(grand) + '</strong></div>' +
          grp.map(orderCard).join('') + '</div>';
        i = j;
        continue;
      }
    }
    html += orderCard(o);
    i++;
  }
  return html;
}

function orderCard(o) {
  return '<div class="order-card clickable" onclick="go(\'order\',' + o.id + ')"><div class="order-head">' +
    '<div><strong>' + esc(t('order_num')) + o.id + '</strong> · ' + esc(o.vendor_name) + '</div>' +
    '<span class="status-pill status-' + esc(o.status) + '">' + esc(statusLabel(o.status)) + '</span></div>' +
    '<ul class="order-items">' + o.items.map(i =>
      '<li>' + i.quantity + ' × ' + esc(i.dish_name) + orderItemExtraHTML(i) +
      ' — ' + money(Number(i.unit_price) * i.quantity) + probLineBtn(o.id, i.id) + '</li>').join('') + '</ul>' +
    '<div id="prob-form-' + o.id + '"></div>' + // === F6: report-a-problem inline form lands here ===
    '<div class="vendor-tag">' +
    // === Community drops (Oct 2026): drop orders show the drop label ===
    (o.fulfillment === 'drop'
      ? '📦 ' + esc(o.drop_label || t('drop_join'))
      : (o.fulfillment === 'pickup' ? '🛍️ ' + esc(t('pickup')) + (o.pickup_at ? ' · ' + esc(fmtPickupDate(o.pickup_at)) : '') : '🛵 ' + esc(t('delivery')))) +
    // === END community drops ===
    ' · ' + money(o.total) + ' · <small>' + esc(fmtDate(o.created_at)) + '</small></div>' +
    // === F8: chosen weekly pickup slot snapshot ===
    (o.pickup_slot_label ? '<div class="vendor-tag">' + esc(t('slot_label')) + ': <strong>' + esc(o.pickup_slot_label) + '</strong></div>' : '') +
    // === END F8 ===
    (o.fulfillment === 'delivery' && o.delivery_address
      ? '<div class="vendor-tag">📍 ' + esc(o.delivery_address) + mapsLink(o.delivery_address) + '</div>' : '') +
    (o.notes ? '<div class="vendor-tag">📝 ' + esc(o.notes) + '</div>' : '') +
    // === F10: failed card payment badge ===
    (o.payment_status === 'failed' && o.payment_failed_at
      ? '<div class="vendor-tag" style="color:#b3261e;font-weight:700">⚠️ ' + esc(t('payment_failed_badge')) + '</div>'
      : '') +
    // === END F10 ===
    '<div class="order-actions"><button class="btn small secondary" onclick="event.stopPropagation();reorder(' + o.id + ')">' +
    esc(t('order_again')) + '</button>' +
    (o.status === 'completed'
      ? '<button class="btn small secondary" onclick="event.stopPropagation();openReviewForm(' + o.id + ',' + o.vendor_id + ')">' + esc(t('write_review')) + '</button>'
      : '') +
    retryPaymentHTML(o) + // === F10: retry button + countdown ===
    '</div>' +
    '<div id="review-form-' + o.id + '"></div>' +
    '<div class="open-hint">' + esc(t('track_hint')) + '</div></div>';
}

/* === F10: payment retry / resume checkout ===
   Failed card orders (payment_status='failed') show a retry button with a
   live countdown of the 30-minute window. Clicking mints a FRESH
   PaymentIntent for the stored total, then continues through the normal
   Stripe checkout-session redirect. */
function retryMsLeft(o) {
  if (!o.payment_failed_at) return 0;
  const failedAt = new Date(o.payment_failed_at).getTime();
  return 30 * 60 * 1000 - (Date.now() - failedAt);
}
function retryPaymentHTML(o) {
  if (o.payment_status !== 'failed' || !o.payment_failed_at) return '';
  if (o.status !== 'new' || o.paid) return '';
  const left = retryMsLeft(o);
  if (left <= 0) {
    return '<span class="vendor-tag" style="color:var(--muted)">' + esc(t('retry_expired')) + '</span>';
  }
  const mins = Math.max(1, Math.ceil(left / 60000));
  return '<button class="btn small" onclick="event.stopPropagation();retryPayment(' + o.id + ')">' +
    esc(t('retry_pay')) + ' <span data-retry-countdown="' + esc(o.payment_failed_at) + '">(' +
    esc(t('retry_left', { n: mins })) + ')</span></button>';
}
function tickRetryCountdowns() {
  document.querySelectorAll('[data-retry-countdown]').forEach(function (el) {
    const failedAt = new Date(el.getAttribute('data-retry-countdown')).getTime();
    const left = 30 * 60 * 1000 - (Date.now() - failedAt);
    if (left <= 0) { el.textContent = '(' + t('retry_expired') + ')'; return; }
    el.textContent = '(' + t('retry_left', { n: Math.max(1, Math.ceil(left / 60000)) }) + ')';
  });
}
window.retryPayment = async function (orderId) {
  try {
    // Fresh PaymentIntent for the stored total (re-arms the order). Then
    // continue through the normal card flow (Stripe checkout redirect).
    await api('/orders/' + orderId + '/retry-payment', { method: 'POST' });
    const s = await api('/stripe/checkout-session',
      { method: 'POST', body: JSON.stringify({ order_id: orderId }) });
    if (s && s.checkout_url) { window.location.href = s.checkout_url; return; }
    throw new Error('no checkout url');
  } catch (e) {
    const msg = (e && e.message) || '';
    if (/501/.test(msg) || /not configured/i.test(msg)) alert(t('card_not_configured'));
    else alert(t('retry_failed') + errText(e));
  }
  if (S.route === 'orders') vOrders();
  else if (S.route === 'order') vCustomerOrder(orderId);
};
/* === END F10 === */

/* Inline review form on a completed order. */
let reviewRating = 0;
window.openReviewForm = function (orderId, vendorId) {
  const box = $('#review-form-' + orderId);
  if (!box) return;
  reviewRating = 0;
  box.innerHTML = '<div class="review-form" onclick="event.stopPropagation()"><h4>' + esc(t('review_form_title')) + '</h4>' +
    '<div class="star-picker" id="star-picker">' +
    [1, 2, 3, 4, 5].map(n => '<button type="button" data-star="' + n + '" onclick="setReviewRating(' + n + ')">☆</button>').join('') +
    '</div>' +
    '<textarea id="review-text-' + orderId + '" rows="3" maxlength="1000" placeholder="' + esc(t('review_ph')) + '"></textarea>' +
    '<label class="field upload-label">' + esc(t('review_photos_lbl')) +
    ' <input type="file" id="review-photos-' + orderId + '" accept="image/jpeg,image/png,image/webp,image/gif" multiple onchange="reviewPhotosPicked(' + orderId + ')"></label>' +
    '<div class="hint">' + esc(t('review_photos_hint')) + '</div>' +
    '<div id="review-thumbs-' + orderId + '" class="review-thumbs"></div>' +
    '<div class="order-actions"><button class="btn small" onclick="event.stopPropagation();submitReview(' + orderId + ',' + vendorId + ')">' + esc(t('post_review')) + '</button> ' +
    '<button class="btn small secondary" onclick="event.stopPropagation();document.getElementById(\'review-form-' + orderId + '\').innerHTML=\'\'">' + esc(t('cancel')) + '</button></div>' +
    '<div id="review-msg-' + orderId + '"></div></div>';
};
/* Photo picker for reviews: preview thumbnails before submit (max 3). */
window.reviewPhotosPicked = function (orderId) {
  const inp = $('#review-photos-' + orderId), thumbs = $('#review-thumbs-' + orderId);
  if (!inp || !thumbs) return;
  const files = Array.prototype.slice.call(inp.files || []).slice(0, 3);
  thumbs.innerHTML = '';
  files.forEach(function (f) {
    const img = document.createElement('img');
    img.src = URL.createObjectURL(f);
    img.className = 'review-thumb';
    img.alt = '';
    thumbs.appendChild(img);
  });
  if (inp.files && inp.files.length > 3) {
    const msg = $('#review-msg-' + orderId);
    if (msg) msg.innerHTML = '<div class="notice">' + esc(t('review_photo_max')) + '</div>';
  }
};
/* Raw fetch: api() forces a JSON content-type, which breaks multipart uploads. */
async function uploadReviewPhoto(reviewId, file) {
  const fd = new FormData();
  fd.append('file', file);
  const headers = {};
  if (S.token) headers['Authorization'] = 'Bearer ' + S.token;
  const res = await fetch('/api/reviews/' + reviewId + '/photos', { method: 'POST', headers, body: fd });
  if (!res.ok) {
    let msg = res.statusText;
    try { const j = await res.json(); if (j && j.detail) msg = j.detail; } catch (e) { /* ignore */ }
    throw new Error(t('review_photo_failed') + msg);
  }
  return res.json();
}
window.setReviewRating = function (n) {
  reviewRating = n;
  document.querySelectorAll('#star-picker button').forEach(b => {
    b.textContent = Number(b.dataset.star) <= n ? '★' : '☆';
  });
};
window.submitReview = async function (orderId, vendorId) {
  const msg = $('#review-msg-' + orderId);
  msg.innerHTML = '';
  if (!reviewRating) { msg.innerHTML = '<div class="error">' + esc(t('pick_stars')) + '</div>'; return; }
  const text = ($('#review-text-' + orderId).value || '').trim() || null;
  const fileInp = $('#review-photos-' + orderId);
  const files = fileInp && fileInp.files
    ? Array.prototype.slice.call(fileInp.files).slice(0, 3)
    : [];
  try {
    const r = await api('/reviews', {
      method: 'POST',
      body: JSON.stringify({ vendor_id: vendorId, rating: reviewRating, text }),
    });
    // Attach the picked photos to the new review (author-only endpoint).
    for (const f of files) {
      await uploadReviewPhoto(r.id, f);
    }
    $('#review-form-' + orderId).innerHTML =
      '<div class="notice">' + esc(t('review_thanks')) + stars(r.rating) + '</div>';
  } catch (e) { msg.innerHTML = '<div class="error">' + esc(e.message) + '</div>'; }
};

/* Customer order tracking detail. */
const CUST_EVENT_ICON = { placed: '🧾', status: '🔄', email: '📧', note: '📝' };

async function vCustomerOrder(orderId) {
  const view = $('#view');
  if (!S.user) { go('login'); return; }
  view.innerHTML = '<div class="empty"><span class="big">🧾</span>' + esc(t('order_loading')) + '</div>';
  try {
    const [order, events] = await Promise.all([
      api('/orders/' + orderId),
      api('/orders/' + orderId + '/events'),
    ]);
    // Pickup address from the vendor's structured address — pickup only.
    let pickupHTML = '';
    if (order.fulfillment === 'pickup') {
      try { pickupHTML = pickupAddrHTML(await vendorById(order.vendor_id)); } catch (e) { /* vendor gone — skip */ }
    }
    const flow = order.fulfillment === 'delivery'
      ? ['new', 'preparing', 'ready', 'on_the_way', 'completed']
      : ['new', 'preparing', 'ready', 'completed'];
    const idx = flow.indexOf(order.status);
    let steps = '';
    if (order.status === 'cancelled') {
      steps = '<div class="status-options"><span class="status-pill status-cancelled">' + esc(statusLabel('cancelled')) + '</span></div>';
    } else {
      steps = '<div class="status-options">' + flow.map(s => {
        const si = flow.indexOf(s);
        const cls = si < idx ? 'done' : si === idx ? ' current' : '';
        return '<span class="status-pill status-' + s + cls + '">' + (si <= idx ? '✓ ' : '') +
          esc(statusLabel(s)) + '</span>';
      }).join('') + '</div>';
    }

    let html = '<button class="btn small ghost" onclick="go(\'orders\')">' + esc(t('back_orders')) + '</button>';
    html += '<h2 class="section-title">' + esc(t('order_title')) + order.id +
      ' <span class="status-pill status-' + esc(order.status) + '">' + esc(statusLabel(order.status)) + '</span></h2>';
    html += steps;
    html += '<div class="order-card"><div class="order-head"><strong>' + esc(order.vendor_name) + '</strong></div>' +
      '<ul class="order-items">' + order.items.map(i =>
        '<li>' + i.quantity + ' × ' + esc(i.dish_name) + orderItemExtraHTML(i) +
        ' — ' + money(Number(i.unit_price) * i.quantity) + probLineBtn(order.id, i.id) + '</li>').join('') + '</ul>' +
      '<div id="prob-form-' + order.id + '"></div>' + // === F6: report-a-problem inline form lands here ===
      '<div class="vendor-tag">' +
      // === Community drops (Oct 2026): drop orders show the drop label ===
      (order.fulfillment === 'drop'
        ? '📦 ' + esc(order.drop_label || t('drop_join'))
        : (order.fulfillment === 'pickup'
        ? '🛍️ ' + esc(t('pickup')) + (order.pickup_at ? ' · ' + esc(fmtPickupDate(order.pickup_at)) : '')
        : '🛵 ' + esc(t('delivery')))) +
      // === END community drops ===
      ' · 💳 ' + esc(order.payment_method ? payLabel(order.payment_method) : '—') +
      (order.paid ? ' · <strong>' + esc(t('paid_yes')) + '</strong>' + cardPaidHTML(order)
        : order.payment_method === 'credit_card' ? ' · ' + esc(t('pay_pending'))
        : ' ' + esc(t('recorded_only'))) +
      '</div>' +
      totalsBreakdown(Number(order.subtotal), Number(order.delivery_fee || 0), order.tax, discountOf(order), pointsDiscountOf(order),
        order.fulfillment === 'delivery' && !(Number(order.delivery_fee) > 0)) +
      pickupHTML +
      // === F8: chosen weekly pickup slot snapshot ===
      (order.pickup_slot_label ? '<div class="vendor-tag">' + esc(t('slot_label')) + ': <strong>' + esc(order.pickup_slot_label) + '</strong></div>' : '') +
      // === END F8 ===
      (order.fulfillment === 'delivery' && order.delivery_address
        ? '<div class="delivery-addr">📍 <strong>' + esc(t('deliver_to')) + '</strong> ' + esc(order.delivery_address) +
          '<br><a class="btn small" style="margin-top:.4rem" href="' + mapsUrl(order.delivery_address) +
          '" target="_blank" rel="noopener">' + esc(t('maps_open')) + '</a></div>' : '') +
      // === v46: delivery photo proof — the cook's handoff photo ===
      (order.delivery_photo_url
        ? '<div class="delivery-photo"><div class="vendor-tag">📸 <strong>' + esc(t('delivery_photo_title')) + '</strong></div>' +
          '<a href="' + esc(order.delivery_photo_url) + '" target="_blank" rel="noopener">' +
          '<img src="' + esc(order.delivery_photo_url) + '" alt="' + esc(t('delivery_photo_title')) +
          '" loading="lazy" style="max-height:260px;max-width:100%;border-radius:10px"></a></div>'
        : '') +
      // === END v46 ===
      (order.notes ? '<div class="vendor-tag">📝 <strong>' + esc(t('your_notes')) + '</strong> ' + esc(order.notes) + '</div>' : '') +
      // === F10: failed card payment badge + retry ===
      (order.payment_status === 'failed' && order.payment_failed_at
        ? '<div class="vendor-tag" style="color:#b3261e;font-weight:700">⚠️ ' + esc(t('payment_failed_badge')) + '</div>' +
          '<div class="order-actions">' + retryPaymentHTML(order) + '</div>'
        : '') +
      // === END F10 ===
      '</div>';
    html += '<div class="order-actions">';
    if (order.status === 'new') {
      html += '<button class="btn danger" onclick="cancelOrder(' + order.id + ')">' + esc(t('cancel_order')) + '</button>';
    }
    if (order.status === 'new' && order.payment_method === 'credit_card' && !order.paid) {
      html += '<button class="btn" onclick="payByCard(' + order.id + ')">' + esc(t('card_pay_now')) + '</button>';
    }
    html += '<button class="btn secondary" onclick="reorder(' + order.id + ')">' + esc(t('reorder_btn')) + '</button></div>';

    const timeline = events.filter(e => e.event_type !== 'email');
    html += '<h3 class="section-title">' + esc(t('timeline')) + '</h3>';
    html += timeline.length
      ? '<div class="timeline">' + timeline.map(e => {
          // The on_the_way status change gets the 🚚 marker + timestamp.
          const otw = e.event_type === 'status' && /on_the_way/.test(e.message || '');
          return '<div class="tl-event"><div class="tl-dot">' + (otw ? '🚚' : (CUST_EVENT_ICON[e.event_type] || '•')) + '</div>' +
            '<div class="tl-body"><div class="tl-msg">' + esc(e.message) + '</div>' +
            '<div class="tl-time">' + esc(fmtDate(e.created_at)) + '</div></div></div>';
        }).join('') + '</div>'
      : '<div class="empty">' + esc(t('no_updates')) + '</div>';

    // Customer ↔ vendor messages: plain text, oldest first, polled every 15s.
    html += '<h3 class="section-title">' + esc(t('msg_title')) + '</h3>' +
      '<div id="msg-thread"><div class="empty">' + esc(t('msg_empty')) + '</div></div>' +
      '<div class="msg-input-row"><input type="text" id="msg-input" maxlength="2000" placeholder="' + esc(t('msg_ph')) + '">' +
      '<button class="btn small" onclick="sendOrderMessage(' + order.id + ',\'customer\')">' + esc(t('msg_send')) + '</button></div>';
    view.innerHTML = html;
    startMsgPoll(order.id, 'customer');
  } catch (e) {
    view.innerHTML = '<div class="error">' + esc(t('order_err')) + esc(e.message) + '</div>';
  }
}

/* Customer cancels their own order (only while it is still 'new'). */
window.cancelOrder = async function (orderId) {
  if (!confirm(t('cancel_confirm'))) return;
  try {
    await api('/orders/' + orderId + '/status', {
      method: 'PATCH',
      body: JSON.stringify({ status: 'cancelled' }),
    });
    S.flash = t('cancelled_flash', { id: orderId });
    vCustomerOrder(orderId);
  } catch (e) { alert(t('cancel_failed') + e.message); }
};

/* One-tap reorder: copy a past order's dishes (same quantities, current
   prices — dishes are re-resolved by id) into the cart, then go to cart.
   Dishes that are gone or unavailable are skipped and named in a note.
   A past modifier is re-applied when the dish still offers that choice. */
window.reorder = async function (orderId) {
  try {
    const order = await api('/orders/' + orderId);
    if (!order.items.length) { alert(t('reorder_empty')); return; }
    let added = 0;
    const skipped = [];
    for (const i of order.items) {
      // === F5: bundle lines re-add the bundle (fixed price, no customization) ===
      if (i.bundle_id) {
        let b = null;
        try { b = await api('/bundles/' + i.bundle_id); } catch (e) { b = null; }
        if (!b || !b.available) { skipped.push(i.dish_name); continue; }
        S.bundleById = S.bundleById || {};
        S.bundleById[b.id] = b;
        const bkey = 'b' + b.id;
        const cur = S.cart.items[bkey];
        S.cart.items[bkey] = {
          bundleId: b.id, bundle: b,
          qty: Math.min(50, (cur ? cur.qty : 0) + i.quantity),
        };
        added++;
        continue;
      }
      // === END F5 ===
      let d = null;
      try { d = await api('/dishes/' + i.dish_id); } catch (e) { d = null; }
      if (!d || !d.available) { skipped.push(i.dish_name); continue; }
      // Advance ordering: skip dishes whose order window is currently closed
      // (checkout would 400 on them anyway).
      if (dishRestricted(d) && !dishWindow(d).open) { skipped.push(i.dish_name); continue; }
      const cust = emptyCust();
      const pastLabel = i.modifier_label || (i.modifier && i.modifier.choice_label);
      if (pastLabel) {
        // Re-apply past choices per group: a stored choice is re-selected
        // when the dish still offers that exact label (max still respected).
        dishOptionGroups(d).forEach(function (g, gi) {
          const picks = [];
          g.choices.forEach(function (c) {
            if (String(pastLabel).indexOf(String(c.label)) !== -1 &&
              (g.max === null || picks.length < g.max)) {
              picks.push({ label: String(c.label), delta: Number(c.delta) || 0 });
            }
          });
          if (picks.length) cust.modifiers.push({ option_id: g.id, option_name: g.name, gi: gi, choices: picks });
        });
      }
      // Re-apply removed / added ingredients when the dish still has them.
      // (Public rows + text fallback — the old vendor-gated endpoint 403s
      // for customers, so reorder silently dropped their customizations.)
      const ings = dishIngredients(d);
      if (Array.isArray(ings)) {
        (i.removed_ingredients || []).forEach(function (n) {
          if (ings.some(x => x.name === n && x.included_by_default && x.removable)) cust.removed.push(n);
        });
        (i.added_ingredients || []).forEach(function (n) {
          const f = ings.find(x => x.name === n && !x.included_by_default);
          if (f) cust.added.push({ name: f.name, delta: Number(f.extra_price) || 0 });
        });
      }
      const rk = lineKey(d.id, { cust: cust });
      const existing = S.cart.items[rk];
      if (existing) existing.qty = Math.min(50, existing.qty + i.quantity);
      else S.cart.items[rk] = { dishId: d.id, qty: i.quantity, modifier: null, cust: cust };
      added++;
    }
    saveCart(); updateAuthArea();
    if (skipped.length) alert(t('reorder_skipped', { names: skipped.join(', ') }));
    if (!added) { if (!skipped.length) alert(t('reorder_none')); return; }
    S.flash = t('reorder_added', { n: added });
    go('cart');
  } catch (e) { alert(t('reorder_failed') + errText(e)); }
};

/* === F6 (Oct 2026): report-a-problem per order ===
   PRIVATE: reports are visible to the order's vendor + the site admin
   only — never public. One button per order line; the inline form collects
   category, description, desired outcome, and an optional photo (same
   multipart upload pattern as review photos). */
function probLineBtn(orderId, itemId) {
  return ' <button class="prob-btn" onclick="event.stopPropagation();openProblemForm(' + orderId + ',' + itemId + ')"' +
    ' title="' + esc(t('prob_btn')) + '" aria-label="' + esc(t('prob_btn')) + '">⚠️</button>';
}
window.openProblemForm = function (orderId, itemId) {
  const box = $('#prob-form-' + orderId);
  if (!box) return;
  box.innerHTML = '<div class="review-form" onclick="event.stopPropagation()"><h4>' + esc(t('prob_title')) + '</h4>' +
    '<div class="hint">' + esc(t('prob_private_note')) + '</div>' +
    '<label class="field">' + esc(t('prob_cat')) + '</label>' +
    '<select id="prob-cat-' + orderId + '">' +
    ['missing', 'wrong_item', 'quality', 'late'].map(function (c) {
      return '<option value="' + c + '">' + esc(t('prob_cat_' + c)) + '</option>';
    }).join('') + '</select>' +
    '<textarea id="prob-desc-' + orderId + '" rows="3" maxlength="2000" placeholder="' + esc(t('prob_desc_ph')) + '"></textarea>' +
    '<input type="text" id="prob-outcome-' + orderId + '" maxlength="1000" placeholder="' + esc(t('prob_outcome_ph')) + '">' +
    '<label class="field upload-label">' + esc(t('prob_photo_lbl')) +
    ' <input type="file" id="prob-photo-' + orderId + '" accept="image/jpeg,image/png,image/webp,image/gif"></label>' +
    '<div class="order-actions"><button class="btn small" onclick="event.stopPropagation();submitProblem(' + orderId + ',' + itemId + ')">' + esc(t('prob_send')) + '</button> ' +
    '<button class="btn small secondary" onclick="event.stopPropagation();document.getElementById(\'prob-form-' + orderId + '\').innerHTML=\'\'">' + esc(t('cancel')) + '</button></div>' +
    '<div id="prob-msg-' + orderId + '"></div></div>';
  box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
};
window.submitProblem = async function (orderId, itemId) {
  const msg = $('#prob-msg-' + orderId);
  const cat = $('#prob-cat-' + orderId).value;
  const desc = $('#prob-desc-' + orderId).value.trim();
  const outcome = $('#prob-outcome-' + orderId).value.trim();
  if (!desc) {
    if (msg) msg.innerHTML = '<div class="notice">' + esc(t('prob_need_both')) + '</div>';
    return;
  }
  try {
    const p = await api('/problems', {
      method: 'POST',
      body: JSON.stringify({
        order_id: orderId,
        order_item_id: itemId,
        category: cat,
        description: desc,
        desired_outcome: outcome || null,
      }),
    });
    // Optional photo — raw fetch: api() forces a JSON content-type, which
    // breaks multipart uploads (same pattern as review photos).
    const fileInput = $('#prob-photo-' + orderId);
    if (fileInput && fileInput.files && fileInput.files[0]) {
      const fd = new FormData();
      fd.append('file', fileInput.files[0]);
      const r = await fetch('/api/problems/' + p.id + '/photo', {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + S.token },
        body: fd,
      });
      if (!r.ok) throw new Error(t('prob_err') + r.status);
    }
    if (msg) msg.innerHTML = '<div class="notice">' + esc(t('prob_sent')) + '</div>';
    setTimeout(function () { const b = $('#prob-form-' + orderId); if (b) b.innerHTML = ''; }, 5000);
  } catch (e) {
    if (msg) msg.innerHTML = '<div class="error">' + esc(t('prob_err')) + esc(errText(e)) + '</div>';
  }
};
/* === END F6 === */

/* ================= customer profile ================= */
/* ================= reorder nudges (Oct 2026) ================= */
/* "Time to reorder? 🍲" — dishes the customer hasn't ordered in a while, with
   one-tap reorder via quickAdd (fetches the full dish, honors option groups). */
function nudgeCard(n) {
  return '<div class="dish-card nudge-card">' +
    (n.photo_url
      ? '<img class="dish-img" src="' + esc(n.photo_url) + '" alt="' + esc(n.dish_name) + '" loading="lazy" onerror="this.style.display=\'none\'">'
      : '<div class="dish-img fallback">🍲</div>') +
    '<div class="dish-body">' +
    '<h3 class="dish-name">' + esc(n.dish_name) + '</h3>' +
    '<div class="vendor-tag">' + esc(n.vendor_name) + '</div>' +
    '<div class="vendor-tag">💰 ' + money(Number(n.last_price) || 0) + ' · ' + esc(t('days_ago', { n: n.days_since_last })) + '</div>' +
    '<button class="btn small" onclick="quickAdd(' + Number(n.dish_id) + ')">' + esc(t('nudge_reorder_btn')) + '</button>' +
    '</div></div>';
}
/* ================= END reorder nudges ================= */

/* ================= new-dish announcements (Oct 2026) ================= */
/* Date-only formatter (YYYY-MM-DD): new Date('2026-10-25') parses as UTC
   midnight, which shows the previous day in US timezones — build the date
   from parts in local time instead. */
function fmtDay(isoDay) {
  if (!isoDay) return '—';
  const parts = String(isoDay).slice(0, 10).split('-');
  if (parts.length !== 3) return String(isoDay);
  try {
    const d = new Date(Number(parts[0]), Number(parts[1]) - 1, Number(parts[2]));
    return d.toLocaleDateString(lang() === 'ar' ? 'ar-EG' : 'en-US');
  } catch (e) { return String(isoDay); }
}
function annCard(a) {
  // === v40: admin broadcasts render as announcement cards too ===
  if (a.kind === 'broadcast') {
    const ar = lang() === 'ar';
    const title = ar ? (a.title_ar || a.title_en) : (a.title_en || a.title_ar);
    const body = ar ? (a.body_ar || a.body_en) : (a.body_en || a.body_ar);
    return '<div class="dish-card nudge-card">' +
      '<div class="dish-img fallback">📣</div>' +
      '<div class="dish-body">' +
      '<h3 class="dish-name">' + esc(title) + (a.unseen ? ' <span class="sig-pill">●</span>' : '') + '</h3>' +
      '<div class="vendor-tag">' + esc(fmtDay((a.created_at || '').slice(0, 10))) + '</div>' +
      '<p>' + esc(body) + '</p>' +
      '</div></div>';
  }
  // === END v40 ===
  return '<div class="dish-card nudge-card">' +
    '<div class="dish-img fallback">🎉</div>' +
    '<div class="dish-body">' +
    '<h3 class="dish-name" onclick="go(\'dish\',' + Number(a.dish_id) + ')" style="cursor:pointer">' +
    esc(a.dish_name) + (a.unseen ? ' <span class="sig-pill">●</span>' : '') + '</h3>' +
    '<div class="vendor-tag">' + esc(a.vendor_name) + ' · ' + esc(fmtDay((a.created_at || '').slice(0, 10))) + '</div>' +
    '<button class="btn small" onclick="go(\'dish\',' + Number(a.dish_id) + ')">' + esc(t('ann_view_dish')) + '</button>' +
    '</div></div>';
}
/* ================= END announcements ================= */

async function vProfile() {
  const view = $('#view');
  if (!S.user || S.user.role !== 'customer') { go('login'); return; }
  const u = S.user;
  // Email verification nudge: visible but dismissible, never blocking.
  const nudge = (u.email_verified === false && !S.verifyDismissed)
    ? '<div class="notice" id="verify-nudge">✉️ ' + esc(t('verify_nudge')) + ' ' +
      '<button class="btn small secondary" onclick="S.verifyDismissed=true;vProfile()">' + esc(t('verify_nudge_close')) + '</button></div>'
    : '';
  view.innerHTML =
    '<h2 class="section-title">' + esc(t('profile_title')) + '</h2>' + nudge +
    '<div class="form-card"><h3>' + esc(t('points_title')) + '</h3><div id="loy-card">' + esc(t('points_loading')) + '</div></div>' +
    '<div class="form-card"><h3>' + esc(t('reorder_title')) + '</h3>' +
    '<p class="hint">' + esc(t('reorder_sub')) + '</p>' +
    '<div id="reorder-nudges"><div class="empty">' + esc(t('reorder_loading')) + '</div></div></div>' +
    // === New-dish announcements (Oct 2026): "New from your cooks" ===
    '<div class="form-card"><h3>📣 ' + esc(t('ann_section')) + '</h3>' +
    '<div id="ann-list"><div class="empty">' + esc(t('reorder_loading')) + '</div></div></div>' +
    // === END announcements ===
    '<div class="form-card"><h3>' + esc(t('contact_details')) + '</h3><div id="pf-msg"></div>' +
    '<label class="field">' + esc(t('name_label')) + '</label><input type="text" id="pf-name" value="' + esc(u.name || '') + '" maxlength="120">' +
    '<label class="field">' + esc(t('email_label')) + '</label><input type="email" value="' + esc(u.email || '') + '" disabled>' +
    '<label class="field">' + esc(t('phone_label')) + '</label><input type="tel" id="pf-phone" value="' + esc(u.phone || '') + '" maxlength="40" autocomplete="tel">' +
    '<div class="form-sub">' + esc(t('address_h')) + '</div>' +
    '<label class="field">' + esc(t('addr_street')) + '</label><input type="text" id="pf-street" value="' + esc(u.street_address || '') + '" maxlength="120" autocomplete="street-address">' +
    '<label class="field">' + esc(t('addr_apt')) + ' <span class="sub">' + esc(t('optional')) + '</span></label><input type="text" id="pf-apt" value="' + esc(u.apt || '') + '" maxlength="40">' +
    '<div class="row2"><div><label class="field">' + esc(t('addr_city')) + '</label><input type="text" id="pf-city" value="' + esc(u.city || '') + '" maxlength="80" autocomplete="address-level2"></div>' +
    '<div><label class="field">' + esc(t('addr_state')) + '</label><select id="pf-state" autocomplete="address-level1">' + stateOptions(u.state || '') + '</select></div></div>' +
    '<label class="field">' + esc(t('addr_zip')) + '</label><input type="text" id="pf-zip" value="' + esc(u.zipcode || '') + '" maxlength="10" inputmode="numeric" placeholder="' + esc(t('addr_zip_ph')) + '" autocomplete="postal-code">' +
    '<div class="mt"><button class="btn" onclick="saveProfile()">' + esc(t('save_changes')) + '</button></div></div>' +
    '<div class="form-card"><h3>' + esc(t('change_pw')) + '</h3><div id="pw-msg"></div>' +
    '<label class="field">' + esc(t('current_pw')) + '</label><input type="password" id="pw-cur" autocomplete="current-password">' +
    '<label class="field">' + esc(t('new_password')) + '</label><input type="password" id="pw-new" autocomplete="new-password">' +
    '<div class="mt"><button class="btn" onclick="changePassword()">' + esc(t('change_pw')) + '</button></div></div>';
  renderLoyaltyCard(); // fills the points card above — non-blocking
  // === Reorder nudges (Oct 2026): "Time to reorder?" — auth-only endpoint. ===
  (function () {
    const el = document.getElementById('reorder-nudges');
    if (!el) return;
    api('/nudges').then(function (nudges) {
      if (S.route !== 'profile' || !document.getElementById('reorder-nudges')) return;
      const list = Array.isArray(nudges) ? nudges : [];
      el.innerHTML = list.length
        ? '<div class="rail">' + list.map(nudgeCard).join('') + '</div>'
        : '<div class="empty">' + esc(t('nudge_empty')) + '</div>';
    }).catch(function () {
      if (S.route === 'profile' && document.getElementById('reorder-nudges'))
        el.innerHTML = '<div class="hint">' + esc(t('reorder_unavailable')) + '</div>';
    });
  })();
  // === END nudges ===
  // === New-dish announcements (Oct 2026): fetch on profile render; mark
  // seen once the section has been viewed. ===
  (function () {
    const el = document.getElementById('ann-list');
    if (!el) return;
    api('/announcements').then(function (anns) {
      if (S.route !== 'profile' || !document.getElementById('ann-list')) return;
      const list = Array.isArray(anns) ? anns : [];
      el.innerHTML = list.length
        ? '<div class="rail">' + list.map(annCard).join('') + '</div>'
        : '<div class="empty">' + esc(t('ann_none')) + '</div>';
      api('/announcements/seen', { method: 'POST' }).catch(function () { /* ignore */ });
    }).catch(function () {
      if (S.route === 'profile' && document.getElementById('ann-list'))
        el.innerHTML = '<div class="hint">' + esc(t('reorder_unavailable')) + '</div>';
    });
  })();
  // === END announcements ===
}
window.saveProfile = async function () {
  const msg = $('#pf-msg');
  msg.innerHTML = '';
  const zip = $('#pf-zip').value.trim();
  if (!zipOk(zip)) { msg.innerHTML = '<div class="error">' + esc(t('zip_invalid')) + '</div>'; return; }
  try {
    const u = await api('/auth/me', {
      method: 'PATCH',
      body: JSON.stringify({
        name: $('#pf-name').value.trim(),
        phone: $('#pf-phone').value.trim(),
        street_address: $('#pf-street').value.trim(),
        apt: $('#pf-apt').value.trim(),
        city: $('#pf-city').value.trim(),
        state: $('#pf-state').value,
        zipcode: zip,
      }),
    });
    S.user = u;
    updateAuthArea();
    msg.innerHTML = '<div class="hint" style="color:var(--brand);font-weight:700;">' + esc(t('profile_saved')) + '</div>';
  } catch (e) { msg.innerHTML = '<div class="error">' + esc(e.message) + '</div>'; }
};
window.changePassword = async function () {
  const msg = $('#pw-msg');
  msg.innerHTML = '';
  const cur = $('#pw-cur').value, nw = $('#pw-new').value;
  if (!cur || !nw) { msg.innerHTML = '<div class="error">' + esc(t('fill_both_pw')) + '</div>'; return; }
  if (nw.length < 8) { msg.innerHTML = '<div class="error">' + esc(t('new_pw_short')) + '</div>'; return; }
  try {
    const r = await api('/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ current_password: cur, new_password: nw }),
    });
    // The backend invalidates all old tokens on password change and returns a
    // fresh one — store it so this session survives.
    if (r && r.access_token) { S.token = r.access_token; localStorage.setItem('ehf_token', S.token); }
    $('#pw-cur').value = ''; $('#pw-new').value = '';
    msg.innerHTML = '<div class="hint" style="color:var(--brand);font-weight:700;">' + esc(t('pw_changed')) + '</div>';
  } catch (e) { msg.innerHTML = '<div class="error">' + esc(e.message) + '</div>'; }
};

/* ================= static pages ================= */
function vAbout() { return t('page_about'); }
function vFaq() { return t('page_faq'); }
function vTerms() { return t('page_terms'); }
function vPrivacy() { return t('page_privacy'); }

/* ================= help / support tickets ================= */
const HELP_CATS = ['order', 'vendor', 'payment', 'account', 'technical', 'other'];
function helpCatLabel(c) { return t('sup_cat_' + c); }

async function vHelp() {
  const view = document.getElementById('view');
  if (!S.user) {
    view.innerHTML = '<div class="empty"><span class="big">🎧</span>' + esc(t('help_need_login')) +
      '<br><br><a class="btn" href="#" data-go="login">' + esc(t('nav_login')) + '</a></div>';
    return;
  }
  view.innerHTML = '<h2 class="section-title">' + esc(t('help_title')) + '</h2><div id="help-msg"></div>' +
    '<div class="form-card"><h3>' + esc(t('help_new')) + '</h3><div id="help-err"></div>' +
    '<label class="field">' + esc(t('help_cat')) + '</label><select id="help-cat">' +
    HELP_CATS.map(c => '<option value="' + c + '">' + esc(helpCatLabel(c)) + '</option>').join('') + '</select>' +
    '<label class="field">' + esc(t('help_order')) + '</label><select id="help-order"><option value="">' + esc(t('help_order_none')) + '</option></select>' +
    '<label class="field">' + esc(t('help_subject')) + '</label><input type="text" id="help-subject" maxlength="160">' +
    '<label class="field">' + esc(t('help_message')) + '</label><textarea id="help-message" rows="4" maxlength="5000"></textarea>' +
    '<div class="mt"><button class="btn" onclick="submitHelpTicket()">' + esc(t('help_send')) + '</button></div></div>' +
    '<h3 class="section-title">' + esc(t('help_mine')) + '</h3><div id="help-list"><div class="empty">' + esc(t('orders_loading')) + '</div></div>';
  try {
    const [orders, tickets] = await Promise.all([
      api('/orders').catch(() => []),
      api('/complaints/mine').catch(() => []),
    ]);
    const sel = document.getElementById('help-order');
    orders.forEach(o => {
      const op = document.createElement('option');
      op.value = o.id;
      op.textContent = '#' + o.id + ' — ' + money(Number(o.total) || 0) + ' — ' + o.status;
      sel.appendChild(op);
    });
    document.getElementById('help-list').innerHTML = tickets.length
      ? tickets.map(helpTicketCard).join('')
      : '<div class="empty">' + esc(t('help_none')) + '</div>';
  } catch (e) {
    document.getElementById('help-list').innerHTML = '<div class="error">' + esc(t('err_generic')) + esc(e.message) + '</div>';
  }
}

function helpTicketCard(c) {
  return '<div class="order-card"><div class="order-head"><strong>#' + c.id + ' — ' + esc(c.subject) + '</strong> ' +
    '<span class="status-pill status-' + esc(c.status) + '">' + esc(t('sup_st_' + c.status)) + '</span></div>' +
    '<div class="vendor-tag">' + esc(helpCatLabel(c.category)) + ' · <small>' + esc(fmtDate(c.created_at)) + '</small>' +
    (c.order_id ? ' · ' + esc(t('sup_order')) + ' #' + c.order_id : '') + '</div>' +
    '<p style="white-space:pre-wrap">' + esc(c.message) + '</p>' +
    (c.admin_reply ? '<div class="notice"><strong>' + esc(t('help_reply')) + ':</strong><br>' + esc(c.admin_reply) + '</div>' : '') +
    '</div>';
}

window.submitHelpTicket = async function () {
  const errEl = document.getElementById('help-err'), msgEl = document.getElementById('help-msg');
  errEl.innerHTML = ''; msgEl.innerHTML = '';
  const subject = document.getElementById('help-subject').value.trim();
  const message = document.getElementById('help-message').value.trim();
  if (!subject || !message) { errEl.innerHTML = '<div class="error">' + esc(t('help_need_both')) + '</div>'; return; }
  try {
    const orderId = document.getElementById('help-order').value;
    await api('/complaints', {
      method: 'POST',
      body: JSON.stringify({
        category: document.getElementById('help-cat').value, subject, message,
        order_id: orderId ? Number(orderId) : null,
      }),
    });
    msgEl.innerHTML = '<div class="success">' + esc(t('help_sent')) + '</div>';
    window.scrollTo(0, 0);
    vHelp();
  } catch (e) { errEl.innerHTML = '<div class="error">' + esc(e.message) + '</div>'; }
};



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
async function vDeliveryAdmin() {
  const view = $('#view');
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

/* ================= vendor applications (#/apply) ================= */
async function vApply() {
  const view = $('#view');
  view.innerHTML = '<div class="form-card" style="max-width:640px"><h2>' + esc(t('apply_title')) + '</h2>' +
    '<p class="hint">' + esc(t('apply_sub')) + '</p><div id="apply-msg"></div>' +
    '<label class="field">' + esc(t('apply_name')) + '</label><input type="text" id="ap-name" maxlength="120" autocomplete="name">' +
    '<label class="field">' + esc(t('apply_phone')) + '</label><input type="tel" id="ap-phone" maxlength="40" autocomplete="tel">' +
    '<label class="field">' + esc(t('apply_email')) + '</label><input type="email" id="ap-email" maxlength="160" autocomplete="email">' +
    '<label class="field">' + esc(t('apply_city')) + '</label><input type="text" id="ap-city" maxlength="80" autocomplete="address-level2">' +
    '<label class="field">' + esc(t('apply_cooking')) + '</label><input type="text" id="ap-cooking" maxlength="255" placeholder="' + esc(t('apply_cooking_ph')) + '">' +
    '<label class="field">' + esc(t('apply_message')) + '</label><textarea id="ap-message" rows="4" maxlength="5000" placeholder="' + esc(t('apply_message_ph')) + '"></textarea>' +
    // WA permits gate — required. Client-side checks mirror the backend 400s.
    '<h3 style="margin-top:1.2em">' + esc(t('apply_permits_h')) + '</h3>' +
    '<p class="hint">' + esc(t('apply_permits_sub')) + '</p>' +
    '<label class="field"><input type="checkbox" id="ap-permit-fwc"> ' + esc(t('apply_permit_fwc')) + '</label>' +
    '<div class="row2"><div><input type="text" id="ap-permit-fwc-num" maxlength="80" placeholder="' + esc(t('apply_permit_fwc_num')) + '"></div>' +
    '<div><input type="date" id="ap-permit-fwc-exp" title="' + esc(t('apply_permit_expiry')) + '"></div></div>' +
    '<label class="field"><input type="checkbox" id="ap-permit-est"> ' + esc(t('apply_permit_est')) + '</label>' +
    '<div class="row2"><div><input type="text" id="ap-permit-est-num" maxlength="80" placeholder="' + esc(t('apply_permit_est_num')) + '"></div>' +
    '<div><input type="date" id="ap-permit-est-exp" title="' + esc(t('apply_permit_expiry')) + '"></div></div>' +
    '<label class="field"><input type="checkbox" id="ap-permit-cottage"> ' + esc(t('apply_permit_cottage')) + '</label>' +
    '<p class="hint">' + esc(t('apply_permit_cottage_note')) + '</p>' +
    '<div class="row2"><div><input type="text" id="ap-permit-cottage-num" maxlength="80" placeholder="' + esc(t('apply_permit_cottage_num')) + '"></div>' +
    '<div><input type="date" id="ap-permit-cottage-exp" title="' + esc(t('apply_permit_expiry')) + '"></div></div>' +
    '<label class="field"><input type="checkbox" id="ap-permit-biz"> ' + esc(t('apply_permit_biz')) + '</label>' +
    '<input type="text" id="ap-permit-biz-ubi" maxlength="80" placeholder="' + esc(t('apply_permit_biz_ubi')) + '">' +
    '<label class="field"><input type="checkbox" id="ap-permit-attest"> ' + esc(t('apply_permit_attest')) + '</label>' +
    '<div class="mt"><button class="btn" style="width:100%" onclick="submitApplication()">' + esc(t('apply_send')) + '</button></div></div>';
}
window.submitApplication = async function () {
  const msg = $('#apply-msg');
  msg.innerHTML = '';
  const chk = id => { const el = document.getElementById(id); return !!(el && el.checked); };
  const val = id => { const el = document.getElementById(id); return el ? el.value.trim() : ''; };
  const body = {
    name: $('#ap-name').value.trim(),
    phone: $('#ap-phone').value.trim(),
    email: $('#ap-email').value.trim(),
    city: $('#ap-city').value.trim() || null,
    cooking: $('#ap-cooking').value.trim() || null,
    message: $('#ap-message').value.trim() || null,
    permits_food_worker_card: chk('ap-permit-fwc'),
    permits_food_worker_card_number: val('ap-permit-fwc-num') || null,
    permits_food_worker_card_expiry: val('ap-permit-fwc-exp') || null,
    permits_establishment: chk('ap-permit-est'),
    permits_establishment_number: val('ap-permit-est-num') || null,
    permits_establishment_expiry: val('ap-permit-est-exp') || null,
    permits_cottage: chk('ap-permit-cottage'),
    permits_cottage_number: val('ap-permit-cottage-num') || null,
    permits_cottage_expiry: val('ap-permit-cottage-exp') || null,
    permits_business_license: chk('ap-permit-biz'),
    permits_business_license_ubi: val('ap-permit-biz-ubi') || null,
    permits_attested: chk('ap-permit-attest'),
  };
  if (!body.name || !body.phone || !body.email) {
    msg.innerHTML = '<div class="error">' + esc(t('apply_need')) + '</div>';
    return;
  }
  // WA permit gate — mirrors the backend 400s.
  if (!body.permits_attested) {
    msg.innerHTML = '<div class="error">' + esc(t('apply_permit_need_attest')) + '</div>';
    return;
  }
  if (!body.permits_food_worker_card) {
    msg.innerHTML = '<div class="error">' + esc(t('apply_permit_need_fwc')) + '</div>';
    return;
  }
  if (!body.permits_establishment && !body.permits_cottage) {
    msg.innerHTML = '<div class="error">' + esc(t('apply_permit_need_operating')) + '</div>';
    return;
  }
  // Permit numbers are required for every claimed permit; provided expiries
  // must be current and within 10 years — mirrors the backend 400s.
  const numOk = (claimed, num) => !claimed || !!num;
  if (!numOk(body.permits_food_worker_card, body.permits_food_worker_card_number) ||
      !numOk(body.permits_establishment, body.permits_establishment_number) ||
      !numOk(body.permits_cottage, body.permits_cottage_number) ||
      (body.permits_business_license && !body.permits_business_license_ubi)) {
    msg.innerHTML = '<div class="error">' + esc(t('apply_permit_need_number')) + '</div>';
    return;
  }
  const dstr = d => d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  const todayS = dstr(new Date());
  const maxD = new Date(); maxD.setFullYear(maxD.getFullYear() + 10);
  const maxS = dstr(maxD);
  const expiries = [body.permits_food_worker_card_expiry, body.permits_establishment_expiry, body.permits_cottage_expiry];
  if (expiries.some(e => !!e && e < todayS)) {
    msg.innerHTML = '<div class="error">' + esc(t('apply_permit_expired')) + '</div>';
    return;
  }
  if (expiries.some(e => !!e && e > maxS)) {
    msg.innerHTML = '<div class="error">' + esc(t('apply_permit_expiry_far')) + '</div>';
    return;
  }
  try {
    await api('/applications', { method: 'POST', body: JSON.stringify(body) });
    msg.innerHTML = '<div class="success">' + esc(t('apply_sent')) + '</div>';
    ['ap-name', 'ap-phone', 'ap-email', 'ap-city', 'ap-cooking', 'ap-message',
     'ap-permit-fwc-num', 'ap-permit-fwc-exp', 'ap-permit-est-num', 'ap-permit-est-exp',
     'ap-permit-cottage-num', 'ap-permit-cottage-exp', 'ap-permit-biz-ubi']
      .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    ['ap-permit-fwc', 'ap-permit-est', 'ap-permit-cottage', 'ap-permit-biz', 'ap-permit-attest']
      .forEach(id => { const el = document.getElementById(id); if (el) el.checked = false; });
    window.scrollTo(0, 0);
  } catch (e) { msg.innerHTML = '<div class="error">' + esc(errText(e)) + '</div>'; }
};

/* ================= event catering (#/catering) ================= */
const CATERING_TYPES = ['birthday', 'wedding', 'corporate', 'other'];
/* Today's date as YYYY-MM-DD in the browser's local timezone. */
function todayLocalISO() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 10);
}

async function vCatering() {
  const view = $('#view');
  const min = todayLocalISO();
  view.innerHTML = '<div class="form-card" style="max-width:640px"><h2>' + esc(t('catering_title')) + '</h2>' +
    '<p class="hint">' + esc(t('catering_sub')) + '</p><div id="cat-msg"></div>' +
    '<label class="field">' + esc(t('catering_event_type')) + '</label><select id="cat-type">' +
    CATERING_TYPES.map(x => '<option value="' + x + '">' + esc(t('catering_type_' + x)) + '</option>').join('') + '</select>' +
    '<label class="field">' + esc(t('catering_event_date')) + '</label><input type="date" id="cat-date" min="' + min + '" value="">' +
    '<label class="field">' + esc(t('catering_location')) + '</label><input type="text" id="cat-location" maxlength="200" placeholder="' + esc(t('catering_location_ph')) + '">' +
    '<div class="row2"><div><label class="field">' + esc(t('catering_name')) + '</label><input type="text" id="cat-name" maxlength="120" autocomplete="name"></div>' +
    '<div><label class="field">' + esc(t('catering_phone')) + '</label><input type="tel" id="cat-phone" maxlength="40" autocomplete="tel"></div></div>' +
    '<label class="field">' + esc(t('catering_email')) + ' <span class="sub">' + esc(t('optional')) + '</span></label><input type="email" id="cat-email" maxlength="160" autocomplete="email">' +
    '<label class="field">' + esc(t('catering_food_type')) + '</label><textarea id="cat-food" rows="3" maxlength="2000" placeholder="' + esc(t('catering_food_ph')) + '"></textarea>' +
    '<label class="field">' + esc(t('catering_guests')) + ' <span class="sub">' + esc(t('optional')) + '</span></label><input type="number" id="cat-guests" min="1" max="100000" inputmode="numeric">' +
    '<label class="field">' + esc(t('catering_notes')) + ' <span class="sub">' + esc(t('optional')) + '</span></label><textarea id="cat-notes" rows="2" maxlength="2000"></textarea>' +
    '<div class="mt"><button class="btn" style="width:100%" id="cat-btn" onclick="submitCatering()">' + esc(t('catering_send')) + '</button></div></div>';
}
window.submitCatering = async function () {
  const msg = $('#cat-msg');
  const btn = $('#cat-btn');
  msg.innerHTML = '';
  const val = id => { const el = document.getElementById(id); return el ? el.value.trim() : ''; };
  const body = {
    event_type: val('cat-type'),
    event_date: val('cat-date'),
    location: val('cat-location'),
    contact_name: val('cat-name'),
    phone: val('cat-phone'),
    email: val('cat-email') || null,
    food_type: val('cat-food'),
    guest_count: val('cat-guests') ? Number(val('cat-guests')) : null,
    notes: val('cat-notes') || null,
  };
  // Client-side validation mirroring the backend (422).
  if (!CATERING_TYPES.includes(body.event_type) || !body.event_date || !body.location ||
      !body.contact_name || !body.phone || !body.food_type) {
    msg.innerHTML = '<div class="error">' + esc(t('catering_need')) + '</div>';
    window.scrollTo(0, 0);
    return;
  }
  if (body.event_date < todayLocalISO()) {
    msg.innerHTML = '<div class="error">' + esc(t('catering_bad_date')) + '</div>';
    window.scrollTo(0, 0);
    return;
  }
  if (body.phone.replace(/\D/g, '').length < 7) {
    msg.innerHTML = '<div class="error">' + esc(t('catering_bad_phone')) + '</div>';
    window.scrollTo(0, 0);
    return;
  }
  if (body.email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(body.email)) {
    msg.innerHTML = '<div class="error">' + esc(t('catering_bad_email')) + '</div>';
    window.scrollTo(0, 0);
    return;
  }
  if (body.guest_count !== null && !(Number.isInteger(body.guest_count) && body.guest_count > 0)) {
    msg.innerHTML = '<div class="error">' + esc(t('catering_bad_guests')) + '</div>';
    window.scrollTo(0, 0);
    return;
  }
  if (btn) btn.disabled = true;
  try {
    await api('/catering', { method: 'POST', body: JSON.stringify(body) });
    msg.innerHTML = '<div class="notice">' + esc(t('catering_sent')) + '</div>';
    ['cat-date', 'cat-location', 'cat-name', 'cat-phone', 'cat-email', 'cat-food', 'cat-guests', 'cat-notes']
      .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
    window.scrollTo(0, 0);
  } catch (e) {
    // 429 = rate limited — friendly message; 422s surface backend field errors.
    msg.innerHTML = '<div class="error">' + esc(e && e.status === 429 ? t('catering_too_many') : errText(e)) + '</div>';
    window.scrollTo(0, 0);
  } finally { if (btn) btn.disabled = false; }
};

/* ================= init ================= */
(function initI18n() {
  const toggle = document.getElementById('lang-toggle');
  if (toggle) toggle.addEventListener('click', function () {
    setLang(lang() === 'ar' ? 'en' : 'ar');
  });
})();
/* Dismissible promo bar above the header (generic message; owner can edit the text in i18n.js). */
function mountPromoBar() {
  try { if (localStorage.getItem('ehf_promo') === '1') return; } catch (e) { /* ignore */ }
  const bar = document.createElement('div');
  bar.id = 'promo-bar';
  bar.innerHTML = '<span data-i18n="promo_bar"></span>' +
    '<button class="promo-close" aria-label="' + esc(t('promo_close')) + '" onclick="dismissPromo()">✕</button>';
  const header = document.querySelector('header.topbar');
  if (header && header.parentNode) header.parentNode.insertBefore(bar, header);
  // Keep the dismiss button's accessible name translated on language switch.
  window.addEventListener('ehf-lang', () => {
    const b = document.querySelector('#promo-bar .promo-close');
    if (b) b.setAttribute('aria-label', t('promo_close'));
  });
}
window.dismissPromo = function () {
  try { localStorage.setItem('ehf_promo', '1'); } catch (e) { /* ignore */ }
  const bar = document.getElementById('promo-bar');
  if (bar) bar.remove();
};

/* Header ZIP widget: static markup lives in index.html; re-render on language
   switch (applyLang re-renders #app, but the topbar is static). */
window.addEventListener('ehf-lang', renderZipWidget);

(async function init() {
  await loadMe();
  await loadPublicSettings(); // tax rate for the checkout preview; safe fallback on failure
  await loadFavs();
  mountPromoBar();
  renderZipWidget(); // === delivery ZIP (Oct 2026) ===
  applyLang();
  loadAnalytics(); // fire-and-forget: a missing analytics ID is a no-op
  // v43: show the running build version in the footer (support/debugging).
  fetch('/api/version').then(r => r.json()).then(j => {
    const el = document.getElementById('app-version');
    if (el && j && j.version) el.textContent = 'Build ' + j.version;
  }).catch(() => {});
  const pathRoute = parsePathRoute();
  const hashRoute = window.location.pathname === '/' && window.location.hash ? parseReturnHash() : null;
  const initial = pathRoute || hashRoute || { route: 'home', arg: null };
  go(initial.route, initial.arg, { replace: true });
})();
