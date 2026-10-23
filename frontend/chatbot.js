/* SoukBot — site assistant for the customer marketplace (v2).
   Rule-based + live data: answers come from a built-in knowledge base plus
   LIVE data from the site's own API (/api/vendors, /api/dishes, /api/orders).
   v2 adds: typo-tolerant fuzzy matching, Arabic spelling normalization,
   conversation memory (follow-ups like "how much is it?"), deal + recommendation
   + live order-tracking intents. Never invents data — if the API has no
   answer, it says so. */
(function () {
  'use strict';

  var cache = { vendors: null, dishes: null };
  var panelOpen = false;
  var chatted = false; // true once the user has sent a message

  /* Language: follows the site's ehf_lang choice. P(en, ar) picks the string. */
  function isAr() {
    try { return localStorage.getItem('ehf_lang') === 'ar'; } catch (e) { return false; }
  }
  function P(en, ar) { return isAr() ? ar : en; }

  /* Arabic dish keywords -> English search terms (dish names in the DB are English). */
  var AR_DISH_MAP = {
    'كشري': ['koshary', 'koshari'], 'ملوخية': ['molokhia'], 'ملوخيه': ['molokhia'],
    'محشي': ['mahshi'], 'ورق عنب': ['grape leaves'], 'فطير': ['feteer'],
    'حواوشي': ['hawawshi'], 'كفتة': ['kofta'], 'كباب': ['kebab'],
    'فراخ': ['chicken'], 'دجاج': ['chicken'], 'لحمة': ['beef', 'meat'],
    'سمك': ['fish'], 'جمبري': ['shrimp'], 'كابوريا': ['crab'], 'سبيط': ['calamari'],
    'طعمية': ['taameya'], 'فول': ['ful', 'fava'], 'فلافل': ['falafel'],
    'بامية': ['bamia', 'okra'], 'شوربة': ['soup'], 'عدس': ['lentil'],
    'رز': ['rice'], 'أرز': ['rice'], 'مكرونة': ['macaroni'], 'بشاميل': ['bechamel'],
    'فتة': ['fatta'], 'حمام': ['pigeon'], 'بط': ['duck'], 'كبدة': ['liver'],
    'سجق': ['sausage'], 'شاورما': ['shawarma'], 'سلطة': ['salad'],
    'طحينة': ['tahini'], 'حمص': ['hummus'], 'مخلل': ['pickle'], 'طرشي': ['torshi'],
    'زيتون': ['olives'], 'جبنة': ['cheese'], 'حلاوة': ['halva'],
    'بسبوسة': ['basbousa'], 'كنافة': ['knafeh'], 'كحك': ['kahk'],
    'بلح': ['dates'], 'تمر': ['dates'], 'شاي': ['tea'], 'كركديه': ['hibiscus', 'karkadeh'],
    'سحلب': ['sahlab'], 'عيش': ['bread'], 'عسل': ['molasses']
  };
  var AR_STOP = { 'في': 1, 'من': 1, 'على': 1, 'الى': 1, 'إلى': 1, 'هل': 1, 'عندكم': 1, 'عندك': 1,
    'ايه': 1, 'إيه': 1, 'ما': 1, 'ماذا': 1, 'كيف': 1, 'ازاي': 1, 'إزاي': 1, 'لو': 1, 'سمحت': 1,
    'عايز': 1, 'عاوز': 1, 'ممكن': 1, 'فيه': 1, 'ده': 1, 'دي': 1, 'دا': 1, 'اللي': 1, 'و': 1 };
  /* Arabic vendor-name aliases -> English name fragments for matching. */
  var VENDOR_ALIASES = { 'عمر': 'omar', 'كابوس': 'caboose', 'النيل': 'nile',
    'سامية': 'samia', 'مخبز': 'bakery', 'بقالة': 'groceries' };

  /* ---------- v2: smarter matching + conversation memory ---------- */
  var ctx = { dish: null, vendor: null }; // remembers what you're talking about

  function lev(a, b) { // Levenshtein distance — typo tolerance ("koshry" ~ "koshary")
    if (a === b) return 0;
    var al = a.length, bl = b.length;
    if (!al) return bl; if (!bl) return al;
    var row = [], i, j;
    for (i = 0; i <= bl; i++) row[i] = i;
    for (i = 1; i <= al; i++) {
      var prev = i;
      for (j = 1; j <= bl; j++) {
        var cur = Math.min(row[j] + 1, prev + 1, row[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
        row[j - 1] = prev; prev = cur;
      }
      row[bl] = prev;
    }
    return row[bl];
  }
  function normAr(s) { // unify hamza / ta-marbuta / alef-maqsura spellings
    return String(s).replace(/[أإآ]/g, 'ا').replace(/ة/g, 'ه').replace(/ى/g, 'ي')
      .replace(/ؤ/g, 'و').replace(/ئ/g, 'ي');
  }
  var AR_DISH_NORM = {}; // normalized Arabic dish keywords -> English search terms
  Object.keys(AR_DISH_MAP).forEach(function (k) { AR_DISH_NORM[normAr(k)] = AR_DISH_MAP[k]; });
  var AR_STOP_NORM = {};
  Object.keys(AR_STOP).forEach(function (k) { AR_STOP_NORM[normAr(k)] = 1; });

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function money(n) {
    n = Number(n);
    return '$' + (isNaN(n) ? '0.00' : n.toFixed(2));
  }
  function getJSON(path) {
    return fetch('/api' + path).then(function (r) {
      if (!r.ok) throw new Error('api');
      return r.json();
    });
  }
  function loadData() {
    if (cache.vendors) return Promise.resolve(cache);
    return Promise.all([
      getJSON('/vendors').catch(function () { return []; }),
      getJSON('/dishes').catch(function () { return []; })
    ]).then(function (res) {
      cache.vendors = res[0] || [];
      cache.dishes = res[1] || [];
      return cache;
    });
  }
  function vendorById(id) {
    for (var i = 0; i < cache.vendors.length; i++) {
      if (cache.vendors[i].id === id) return cache.vendors[i];
    }
    return null;
  }
  function fulfillText(v) {
    var f = (v.fulfillment || 'pickup').toLowerCase();
    var fee = Number(v.delivery_fee) || 0;
    if (isAr()) {
      if (f === 'pickup') return 'استلام فقط';
      if (f === 'delivery') return 'توصيل فقط';
      return 'استلام وتوصيل' + (fee > 0 ? ' (رسوم توصيل ' + money(fee) + ')' : ' (توصيل مجاني)');
    }
    if (f === 'pickup') return 'pickup only';
    if (f === 'delivery') return 'delivery only';
    return 'pickup & delivery' + (fee > 0 ? ' (' + money(fee) + ' delivery fee)' : ' (free delivery)');
  }
  function goVendor(id) {
    if (window.go) window.go('vendor', id);
  }

  var STOP = { do: 1, you: 1, have: 1, any: 1, the: 1, and: 1, with: 1, for: 1, what: 1, is: 1,
    are: 1, there: 1, their: 1, menu: 1, show: 1, me: 1, find: 1, looking: 1, like: 1, want: 1,
    get: 1, can: 1, i: 1, a: 1, an: 1, of: 1, to: 1, in: 1, on: 1, does: 1, it: 1, this: 1,
    that: 1, please: 1, some: 1, sell: 1, sold: 1 };

  function searchDishes(text) {
    var ar = isAr();
    // unicode-aware tokenization so Arabic words survive the cleanup
    var words = text.toLowerCase().replace(/[^\p{L}\p{N}\s]/gu, ' ').split(/\s+/)
      .filter(function (w) { return w.length >= (ar ? 2 : 3) && !STOP[w] && !AR_STOP[w]; });
    if (ar) words = words.map(function (w) { return normAr(w); })
      .filter(function (w) { return w.length >= 2 && !AR_STOP_NORM[w]; });
    // expand Arabic dish keywords to their English search terms
    var mapped = [];
    if (ar) {
      words.forEach(function (w) {
        var m = AR_DISH_NORM[w];
        if (m) m.forEach(function (e) { mapped.push(e); });
      });
    }
    var all = words.concat(mapped);
    if (!all.length) return [];
    var scored = [];
    cache.dishes.forEach(function (d) {
      var hay = ((d.name || '') + ' ' + (d.name_ar || '') + ' ' + (d.description || '')).toLowerCase();
      var score = 0;
      all.forEach(function (w) {
        if (hay.indexOf(w) !== -1) { score += 2; return; }
        // typo tolerance: close match against dish name/description words
        if (w.length >= 4) {
          var dw = hay.split(/[^a-z\u0600-\u06ff]+/);
          for (var i = 0; i < dw.length; i++) {
            if (dw[i].length >= 4 && lev(w, dw[i]) <= 2) { score += 1; break; }
          }
        }
      });
      if (score > 0) scored.push({ d: d, score: score });
    });
    scored.sort(function (a, b) {
      if (b.score !== a.score) return b.score - a.score;
      return (b.d.available ? 1 : 0) - (a.d.available ? 1 : 0);
    });
    return scored.slice(0, 5).map(function (s) { return s.d; });
  }

  function effPrice(d) {
    if (d.sale_price != null && d.sale_price !== '') return Number(d.sale_price);
    var disc = Number(d.discount_percent) || 0;
    return Math.round(Number(d.price) * (1 - disc / 100) * 100) / 100;
  }

  function dishLine(d) {
    var v = vendorById(d.vendor_id);
    var vname = v ? v.name : P('a vendor', 'بائع');
    var avail = d.available ? '' : P(' <em>(currently unavailable)</em>', ' <em>(غير متاح حالياً)</em>');
    var disc = Number(d.discount_percent) || 0;
    var price = disc > 0
      ? '<s>' + money(d.price) + '</s> <strong>' + money(effPrice(d)) + '</strong> (-' + disc + '%)'
      : money(d.price);
    // v52: Arabic dish name in AR mode when the dish has one.
    var dName = (isAr() && d.name_ar) ? d.name_ar : d.name;
    return '• <a href="#" data-chat-vendor="' + d.vendor_id + '"><strong>' + esc(dName) + '</strong></a>' +
      ' — ' + price + P(' at ', ' عند ') + esc(vname) + avail;
  }

  function answer(text) {
    var t = text.toLowerCase().trim();
    var raw = text.trim();
    var ar = isAr();
    if (!t) return Promise.resolve(P('Ask me about the menu, ordering, pickup/delivery, or payments 🙂',
      'اسألني عن المنيو، أو طريقة الطلب، أو الاستلام والتوصيل، أو الدفع 🙂'));

    // greeting
    if (/^(hi|hello|hey|salam|ahlan|ezayak|good (morning|afternoon|evening))\b/.test(t) ||
        (ar && /^(سلام|اهلا|أهلا|ازيك|إزيك|هاي|صباح الخير|مساء الخير|السلام عليكم)/.test(raw))) {
      return Promise.resolve(P(
        'Ahlan! 👋 I\'m SoukBot. I can help with the menu, how ordering works, pickup/delivery, and payments. What\'s on your mind?',
        'أهلاً! 👋 أنا SoukBot. أقدر أساعدك في المنيو، وإزاي تطلب، والاستلام والتوصيل، والدفع. بتفكر في إيه؟'));
    }
    // thanks / bye
    if (/^(thanks|thank you|thx|shukran)\b/.test(t) || (ar && /شكرا|متشكر/.test(normAr(raw)))) {
      return Promise.resolve(P('You\'re welcome! 😊 Anything else I can help with?',
        'العفو! 😊 أقدر أساعدك في حاجة تانية؟'));
    }
    if (/^(bye|goodbye|see you)\b/.test(t) || (ar && /مع السلامه|باي/.test(normAr(raw)))) {
      return Promise.resolve(P('Ma\'a salama! 👋 I\'ll be here when you\'re hungry.',
        'مع السلامة! 👋 هتلاقيني هنا لما تجوع.'));
    }
    // deals / discounts — live from the menu
    if (/deal|discount|sale|offer|promo/.test(t) || (ar && /خصم|عرض|عروض|تخفيض/.test(normAr(raw)))) {
      var deals = cache.dishes.filter(function (d) { return (Number(d.discount_percent) || 0) > 0 && d.available; })
        .sort(function (a, b) { return (Number(b.discount_percent) || 0) - (Number(a.discount_percent) || 0); })
        .slice(0, 5);
      if (deals.length) ctx.dish = deals[0];
      if (!deals.length) {
        return Promise.resolve(P('No deals running right now — check back soon! 🏷️',
          'مفيش عروض شغالة دلوقتي — تابعنا قريب! 🏷️'));
      }
      return Promise.resolve(P('🔥 Today\'s deals:<br>', '🔥 عروض النهاردة:<br>') + deals.map(dishLine).join('<br>'));
    }
    // recommendations
    if (/recommend|suggest|what.*(good|best|popular)/.test(t) ||
        (ar && /رشح|اقترح|ايه الحلو|الاحسن|تنصح|مشهور/.test(normAr(raw)))) {
      var avail = cache.dishes.filter(function (d) { return d.available; });
      if (!avail.length) {
        return Promise.resolve(P('The menu looks empty right now — try again later.',
          'المنيو فاضي دلوقتي — جرب كمان شوية.'));
      }
      var picks = [], pool = avail.slice();
      while (picks.length < 3 && pool.length) picks.push(pool.splice(Math.floor(Math.random() * pool.length), 1)[0]);
      ctx.dish = picks[0];
      ctx.vendor = vendorById(picks[0].vendor_id);
      return Promise.resolve(P('Here\'s what I\'d go for:<br>', 'دي ترشيحاتي:<br>') + picks.map(dishLine).join('<br>') +
        P('<br><br>Ask me "how much is it?" about any of them 🙂', '<br><br>اسألني "بكام؟" عن أي واحد فيهم 🙂'));
    }
    // order tracking — live from the API when logged in
    if (/my order|order status|track.*order|where.*\border\b/.test(t) ||
        (ar && /طلباتي|فين الطلب|حاله الطلب|تتبع/.test(normAr(raw)))) {
      var tok = null;
      try { tok = localStorage.getItem('ehf_token'); } catch (e) {}
      if (!tok) {
        return Promise.resolve(P('Log in first, then I can look up your latest order — or open <strong>My Orders</strong> anytime.',
          'سجّل الدخول الأول وبعدين أقدر أجيب لك آخر طلب — أو افتح <strong>طلباتي</strong> في أي وقت.'));
      }
      return fetch('/api/orders', { headers: { 'Authorization': 'Bearer ' + tok } })
        .then(function (r) { if (!r.ok) throw new Error('api'); return r.json(); })
        .then(function (orders) {
          if (!orders || !orders.length) {
            return P('You have no orders yet — browse the menu and place your first one! 🍲',
              'معندكش طلبات لسه — تصفح المنيو واعمل أول طلب! 🍲');
          }
          var o = orders[0], v = vendorById(o.vendor_id);
          ctx.vendor = v;
          return P('Your latest order', 'آخر طلب ليك') + ' #' + o.id +
            (v ? ' (' + esc(v.name) + ')' : '') +
            P(' is: ', ' حالته: ') + '<strong>' + esc(o.status) + '</strong> · ' + money(Number(o.total) || 0) +
            P('<br>Full details under <strong>My Orders</strong>.', '<br>التفاصيل الكاملة في <strong>طلباتي</strong>.');
        })
        .catch(function () {
          return P('I couldn\'t pull your orders just now — check <strong>My Orders</strong> directly.',
            'مش قادر أجيب طلباتك دلوقتي — شوف <strong>طلباتي</strong> مباشرة.');
        });
    }
    // removed methods — point to what we actually accept
    if (/apple pay|google pay/.test(t) || (ar && /آبل|جوجل/.test(normAr(raw)))) {
      return Promise.resolve(P(
        'We don\'t accept Apple Pay or Google Pay — you can pay by credit card (charged securely via Stripe), Zelle, Venmo, or cash.',
        'مش بنقبل آبل باي أو جوجل باي — تقدر تدفع بالبطاقة (بتتخصم بشكل آمن عبر Stripe) أو Zelle أو Venmo أو كاش.'));
    }
    // payments — honest about how each method works
    if (/pay|payment|zelle|venmo|card|credit|cash|charg/.test(t) ||
        (ar && /دفع|ادفع|فلوس|كاش|كارت|بطاق|فيزا|زيل|فينمو/.test(normAr(raw)))) {
      return Promise.resolve(P(
        'You can pay by credit card, Zelle, Venmo, or cash. Card payments are charged securely online through Stripe; Zelle, Venmo, and cash are recorded on your order and you settle them directly with the vendor.',
        'تقدر تدفع بالبطاقة أو Zelle أو Venmo أو كاش. البطاقة بتتخصم بشكل آمن أونلاين عبر Stripe؛ وZelle وVenmo والكاش بيتسجلوا على طلبك وبتتحاسب عليهم مباشرة مع البائع.'));
    }
    // delivery fees
    if (/fee|delivery fee|delivery cost|shipping|how much.*deliver/.test(t) ||
        (ar && /رسوم|بكام التوصيل|سعر التوصيل|تكلفة التوصيل|شحن/.test(raw))) {
      if (!cache.vendors.length) return Promise.resolve(P(
        'I couldn\'t load vendor info just now — try again in a moment.',
        'معلومات البائعين مش متاحة دلوقتي — جرب كمان شوية.'));
      var lines = cache.vendors.map(function (v) {
        var f = (v.fulfillment || 'pickup').toLowerCase();
        var fee = Number(v.delivery_fee) || 0;
        var detail = ar
          ? (f === 'pickup' ? 'استلام فقط' : (fee > 0 ? 'رسوم توصيل ' + money(fee) : 'توصيل مجاني'))
          : (f === 'pickup' ? 'pickup only' : (fee > 0 ? money(fee) + ' delivery fee' : 'free delivery'));
        return '• <strong>' + esc(v.name) + '</strong>: ' + detail;
      });
      return Promise.resolve(P('Delivery fees by vendor:<br>', 'رسوم التوصيل حسب البائع:<br>') + lines.join('<br>'));
    }
    // pickup / delivery
    if (/pickup|pick up|deliver/.test(t) ||
        (ar && /استلام|استلم|توصيل|يوصل|دليفري|توصل/.test(raw))) {
      if (!cache.vendors.length) return Promise.resolve(P(
        'I couldn\'t load vendor info just now — try again in a moment.',
        'معلومات البائعين مش متاحة دلوقتي — جرب كمان شوية.'));
      var out = cache.vendors.map(function (v) {
        return '• <strong>' + esc(v.name) + '</strong>: ' + fulfillText(v);
      });
      return Promise.resolve(P('Here\'s how each vendor fulfills orders:<br>', 'كل بائع بيوصّل إزاي:<br>') + out.join('<br>') +
        P('<br><br>You choose pickup (with a time) or delivery (with your address) at checkout.',
          '<br><br>بتختار الاستلام (مع معاد) أو التوصيل (مع عنوانك) عند إتمام الطلب.'));
    }
    // hours — we have no hours data, say so honestly
    if (/hour|open|close|when.*(open|close)/.test(t) ||
        (ar && /مواعيد|ساعات|امتى|مفتوح|فاتح|يقفل|بيفتح/.test(raw))) {
      var v0 = cache.vendors[0];
      var contact = v0 && v0.phone ? P(' You can call ' + esc(v0.name) + ' at ' + esc(v0.phone) + '.',
        ' تقدر تكلم ' + esc(v0.name) + ' على ' + esc(v0.phone) + '.') : '';
      return Promise.resolve(P(
        'I don\'t have listed opening hours — each home cook sets their own schedule. You pick a pickup time at checkout, which the vendor confirms.',
        'مفيش مواعيد معلنة — كل طباخ بيحدد جدوله بنفسه. بتختار معاد الاستلام عند إتمام الطلب، والبائع بيأكده.') + contact);
    }
    // how to order
    if (/how (do|can|to) (i|we|you) order|how to order|how does (this|it|ordering) work|place.*order/.test(t) ||
        (ar && /ازاي اطلب|اطلب ازاي|طريقه الطلب|خطوات الطلب|ازاي اشتري/.test(normAr(raw)))) {
      return Promise.resolve(P(
        'Ordering is 3 steps:<br>1️⃣ Browse the menu and add dishes to your cart.<br>2️⃣ At checkout choose pickup (pick a time) or delivery (enter your address), plus your payment method.<br>3️⃣ Place the order — the vendor is notified and you can track it under <strong>My Orders</strong>.',
        'الطلب ٣ خطوات:<br>1️⃣ تصفح المنيو وضيف الأطباق للسلة.<br>2️⃣ عند إتمام الطلب اختار الاستلام (حدد معاد) أو التوصيل (اكتب عنوانك)، وطريقة الدفع.<br>3️⃣ أكّد الطلب — البائع بيستلم إشعار وتقدر تتابعه من <strong>طلباتي</strong>.'));
    }
    // vendor info — match by name (English words + Arabic aliases, spelling-normalized)
    var matchedVendor = null;
    var tEn = t;
    var rawN = ar ? normAr(raw) : raw;
    if (ar) {
      Object.keys(VENDOR_ALIASES).forEach(function (k) {
        if (rawN.indexOf(normAr(k)) !== -1) tEn += ' ' + VENDOR_ALIASES[k];
      });
    }
    cache.vendors.forEach(function (v) {
      var nameWords = v.name.toLowerCase().split(/[^a-z]+/).filter(function (w) { return w.length >= 4; });
      for (var i = 0; i < nameWords.length; i++) {
        if (tEn.indexOf(nameWords[i]) !== -1) { matchedVendor = v; break; }
      }
    });
    if (matchedVendor) ctx.vendor = matchedVendor;
    if (matchedVendor || /who (is|are)|about.*vendor|vendors|cooks/.test(t) ||
        (ar && /مين|البائع|الطباخ|الشيف|بيطبخ|المحلات/.test(raw))) {
      if (matchedVendor) {
        var v = matchedVendor;
        var dishes = cache.dishes.filter(function (d) { return d.vendor_id === v.id && d.available; }).length;
        return Promise.resolve('<strong>' + esc(v.name) + '</strong>' +
          (v.tagline ? ' — ' + esc(v.tagline) : '') +
          '<br>📍 ' + esc(v.area || P('local', 'محلي')) + ' · ' + fulfillText(v) +
          (v.phone ? '<br>📞 ' + esc(v.phone) : '') +
          '<br>🍽️ ' + dishes + P(' dish' + (dishes === 1 ? '' : 'es') + ' on the menu right now. ',
            ' طبق في المنيو دلوقتي. ') +
          '<a href="#" data-chat-vendor="' + v.id + '">' + P('Browse their menu →', '← تصفح المنيو') + '</a>');
      }
      var list = cache.vendors.map(function (x) {
        return '• <a href="#" data-chat-vendor="' + x.id + '"><strong>' + esc(x.name) + '</strong></a> — ' + esc(x.area || '');
      });
      return Promise.resolve(P('Our vendors:<br>', 'البائعون:<br>') + list.join('<br>') +
        P('<br><br>Tap one to browse their menu, or ask me about a specific cook.',
          '<br><br>اضغط على واحد لتصفح المنيو، أو اسألني عن طباخ معين.'));
    }
    // account / signup — checked before dish search so "عايز اعمل حساب" doesn't misfire
    if (/sign up|signup|register|account|log in|login/.test(t) ||
        (ar && /حساب|تسجيل|دخول|اشترك|عضوية/.test(raw))) {
      return Promise.resolve(P(
        'You can sign up from the top-right of the site — just name, email, and password (phone and address are optional). Signing in lets you track orders, reorder, and save favorites.',
        'تقدر تسجل من أعلى الصفحة — الاسم والبريد وكلمة المرور بس (الهاتف والعنوان اختياري). تسجيل الدخول يخليك تتابع طلباتك وتعيد الطلب وتحفظ المفضلة.'));
    }
    // follow-ups about the dish we're discussing ("how much is it?", "بكام؟", "is it available?")
    if (ctx.dish && (/how much|howmuch|price|cost/.test(t) || (ar && /بكام|سعره|سعرها|سعر/.test(rawN)))) {
      var cd = ctx.dish, cdisc = Number(cd.discount_percent) || 0;
      return Promise.resolve('<strong>' + esc(cd.name) + '</strong> ' +
        (cdisc > 0
          ? P('is on sale: ', 'عليه خصم: ') + '<s>' + money(cd.price) + '</s> <strong>' + money(effPrice(cd)) + '</strong>'
          : P('costs ', 'سعره ') + '<strong>' + money(cd.price) + '</strong>') +
        (cd.available ? '' : P(' <em>(currently unavailable)</em>', ' <em>(غير متاح حالياً)</em>')));
    }
    if (ctx.dish && (/available|in stock|in-stock/.test(t) || (ar && /متاح|موجود|متوفر/.test(rawN)))) {
      var ad = ctx.dish;
      return Promise.resolve(ad.available
        ? P('Yes! ', 'أيوه! ') + '<strong>' + esc(ad.name) + '</strong>' + P(' is available right now. 🍲', ' متاح دلوقتي. 🍲')
        : P('Sadly, ', 'للأسف ') + '<strong>' + esc(ad.name) + '</strong>' + P(' is not available right now.', ' مش متاح دلوقتي.'));
    }
    // dish search
    if (/do you have|is there|menu|dish|food|eat|koshary|koshari|molokhia|mahshi|feteer|hawawshi/.test(t) ||
        (ar && /عندكم|منيو|طبق|نفسي|أكل|اكل/.test(raw)) || t.split(/\s+/).length <= 3) {
      var hits = searchDishes(ar ? raw : t);
      if (!hits.length) {
        return Promise.resolve(P(
          'Hmm, I couldn\'t find that dish in the live menu. Try another name — e.g. "koshary", "molokhia", or "feteer".',
          'همم، مش لاقي الطبق ده في المنيو الحالي. جرّب اسم تاني — زي "كشري" أو "ملوخية" أو "فطير".'));
      }
      ctx.dish = hits[0];
      ctx.vendor = vendorById(hits[0].vendor_id);
      return Promise.resolve(P('Here\'s what I found:<br>', 'لقيت دول:<br>') + hits.map(dishLine).join('<br>') +
        P('<br><br>Tap a dish to see the vendor\'s menu. You can also ask "how much is it?" 🙂',
          '<br><br>اضغط على الطبق لعرض منيو البائع. وتقدر تسأل "بكام؟" 🙂'));
    }
    // fallback
    return Promise.resolve(P(
      'I can help with the <strong>menu</strong>, <strong>deals</strong>, <strong>ordering</strong>, <strong>pickup/delivery</strong>, and <strong>payments</strong>. Try "do you have koshary?", "any deals?", or "where is my order?" 🙂',
      'أقدر أساعدك في <strong>المنيو</strong> و<strong>العروض</strong> و<strong>طريقة الطلب</strong> و<strong>الاستلام والتوصيل</strong> و<strong>الدفع</strong>. جرّب "عندكم كشري؟" أو "فيه عروض؟" أو "فين الطلب بتاعي؟" 🙂'));
  }

  /* ---------- UI ---------- */
  function addMsg(html, who) {
    var box = document.getElementById('chatbot-msgs');
    var div = document.createElement('div');
    div.className = 'chatbot-msg ' + who;
    if (who === 'bot') div.innerHTML = html; else div.textContent = html;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
  }

  var CHIPS = {
    en: ['How do I order?', 'Do you deliver?', 'How do payments work?', 'Do you have koshary?'],
    ar: ['إزاي أطلب؟', 'بتوصّلوا؟', 'الدفع إزاي؟', 'عندكم كشري؟']
  };
  function chatLang() { return isAr() ? 'ar' : 'en'; }
  function greetingHTML() {
    return P('Ahlan! 👋 I\'m <strong>SoukBot</strong>. Ask me about the menu, ordering, pickup/delivery, or payments.',
      'أهلاً! 👋 أنا <strong>SoukBot</strong>. اسألني عن المنيو، أو إزاي تطلب، أو الاستلام والتوصيل، أو الدفع.');
  }
  function buildChips(box) {
    var chips = document.createElement('div');
    chips.className = 'chatbot-chips';
    chips.id = 'chatbot-chips';
    CHIPS[chatLang()].forEach(function (q) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'chatbot-chip';
      b.textContent = q;
      b.addEventListener('click', function () { handleUser(q); });
      chips.appendChild(b);
    });
    box.appendChild(chips);
  }

  /* ---------- AI backend (Gemini) with local rule-based fallback ---------- */
  function askAI(text) {
    return fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: String(text).slice(0, 1000), language: chatLang() })
    }).then(function (r) {
      if (!r.ok) throw new Error('chat');
      return r.json();
    }).then(function (d) {
      // source "ai" = Gemini answered; anything else -> use the local engine.
      // Escape the model output as plain text (it must never inject HTML).
      if (d && d.source === 'ai' && d.reply) return esc(String(d.reply)).replace(/\n/g, '<br>');
      throw new Error('no-ai');
    });
  }

  function handleUser(text) {
    addMsg(text, 'user');
    chatted = true;
    var input = document.getElementById('chatbot-input');
    input.value = '';
    input.disabled = true;
    addMsg('…', 'bot');
    function showReply(reply) {
      var box = document.getElementById('chatbot-msgs');
      box.removeChild(box.lastChild); // remove the "…"
      addMsg(reply, 'bot');
      input.disabled = false;
      input.focus();
    }
    function showError() {
      var box = document.getElementById('chatbot-msgs');
      box.removeChild(box.lastChild);
      addMsg(P('Hmm, something hiccuped on my end — try again in a moment.', 'حصلت مشكلة من عندي — جرب كمان شوية.'), 'bot');
      input.disabled = false;
    }
    // Gemini backend first; the local rule-based engine stays as the fallback
    // (also covers: no API key configured, or the endpoint unreachable).
    askAI(text).then(showReply, function () {
      loadData().then(function () { return answer(text); }).then(showReply, showError);
    });
  }

  function toggle(force) {
    panelOpen = (typeof force === 'boolean') ? force : !panelOpen;
    document.getElementById('chatbot-panel').classList.toggle('open', panelOpen);
    if (panelOpen) {
      var box = document.getElementById('chatbot-msgs');
      if (!box.children.length) {
        addMsg(greetingHTML(), 'bot');
        buildChips(box);
      }
      setTimeout(function () { document.getElementById('chatbot-input').focus(); }, 50);
    }
  }

  /* Refresh chrome strings when the site language changes. */
  function refreshChrome() {
    var fab = document.getElementById('chatbot-fab');
    if (fab) fab.setAttribute('aria-label', P('Chat with SoukBot', 'دردش مع SoukBot'));
    var head = document.querySelector('#chatbot-panel .chatbot-head span');
    if (head) head.textContent = P('💬 Ask SoukBot', '💬 اسأل SoukBot');
    var close = document.querySelector('#chatbot-panel .chatbot-close');
    if (close) close.setAttribute('aria-label', P('Close chat', 'إغلاق الدردشة'));
    var input = document.getElementById('chatbot-input');
    if (input) input.setAttribute('placeholder', P('Ask about the menu…', 'اسأل عن المنيو…'));
    var sendBtn = document.querySelector('#chatbot-form button[type="submit"]');
    if (sendBtn) sendBtn.textContent = P('Send', 'إرسال');
    // rebuild suggestion chips if the conversation hasn't started yet
    var chips = document.getElementById('chatbot-chips');
    if (chips && !chatted) {
      var box = document.getElementById('chatbot-msgs');
      chips.remove();
      var first = box.querySelector('.chatbot-msg.bot');
      if (first) first.innerHTML = greetingHTML();
      buildChips(box);
    }
  }
  document.addEventListener('ehf-lang', refreshChrome);

  function mount() {
    if (document.getElementById('chatbot-fab')) return; // already mounted
    var fab = document.createElement('button');
    fab.id = 'chatbot-fab';
    fab.className = 'chatbot-fab';
    fab.setAttribute('aria-label', P('Chat with SoukBot', 'دردش مع SoukBot'));
    fab.textContent = '💬';
    fab.addEventListener('click', function () { toggle(); });

    var panel = document.createElement('div');
    panel.id = 'chatbot-panel';
    panel.className = 'chatbot-panel';
    panel.innerHTML =
      '<div class="chatbot-head"><span>' + P('💬 Ask SoukBot', '💬 اسأل SoukBot') + '</span>' +
      '<button type="button" class="chatbot-close" aria-label="' + P('Close chat', 'إغلاق الدردشة') + '">✕</button></div>' +
      '<div class="chatbot-msgs" id="chatbot-msgs"></div>' +
      '<form class="chatbot-input" id="chatbot-form">' +
      '<input id="chatbot-input" type="text" placeholder="' + P('Ask about the menu…', 'اسأل عن المنيو…') + '" autocomplete="off" maxlength="300">' +
      '<button type="submit">' + P('Send', 'إرسال') + '</button></form>';
    panel.querySelector('.chatbot-close').addEventListener('click', function () { toggle(false); });
    panel.querySelector('#chatbot-form').addEventListener('submit', function (e) {
      e.preventDefault();
      var v = document.getElementById('chatbot-input').value.trim();
      if (v) handleUser(v);
    });
    // dish/vendor links inside bot messages -> jump to the vendor menu
    panel.addEventListener('click', function (e) {
      var a = e.target.closest ? e.target.closest('[data-chat-vendor]') : null;
      if (a) {
        e.preventDefault();
        toggle(false);
        goVendor(Number(a.getAttribute('data-chat-vendor')));
      }
    });

    document.body.appendChild(fab);
    document.body.appendChild(panel);
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && panelOpen) toggle(false);
    });
    // warm the cache so first question answers fast
    loadData();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }
})();
