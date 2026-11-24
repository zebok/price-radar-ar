/* ChangoRadar — E-Commerce Price Comparator & BI Dashboard (Vanilla ES6, zero deps) */

(() => {
  "use strict";

  const STORE_META = {
    carrefour: { label: "Carrefour", color: "#004e9a", cls: "store-carrefour" },
    coto:      { label: "Coto",      color: "#c8102e", cls: "store-coto" },
    dia:       { label: "Dia",       color: "#e30613", cls: "store-dia" },
    jumbo:     { label: "Jumbo",     color: "#00843d", cls: "store-jumbo" },
    disco:     { label: "Disco",     color: "#9b1c1c", cls: "store-disco" },
    vea:       { label: "Vea",       color: "#7e1d4f", cls: "store-vea" },
  };

  const CATEGORIES = [
    { id: "all",        label: "Todos" },
    { id: "almacen",    label: "Almacén" },
    { id: "desayuno",   label: "Desayuno" },
    { id: "lacteos",    label: "Lácteos" },
    { id: "bebidas",    label: "Bebidas" },
    { id: "carnes",     label: "Carnes" },
    { id: "verduleria", label: "Verdulería" },
    { id: "congelados", label: "Congelados" },
    { id: "limpieza",   label: "Limpieza" },
    { id: "perfumeria", label: "Perfumería" },
  ];

  const ICONS = {
    moon: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/></svg>',
    sun: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M4.93 4.93l1.41 1.41m11.32 11.32 1.41 1.41M2 12h2m16 0h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>',
    heartOutline: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/></svg>',
    heartFilled: '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/></svg>',
    box: '<svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z"/><path d="m3.3 7 8.7 5 8.7-5M12 22V12"/></svg>',
  };

  const EXCLUSION_PRESETS = [
    { id: "vinos",        label: "Vinos / Espumantes",   keywords: ["vino", "malbec", "cabernet", "espumante", "champagne"] },
    { id: "azucar",       label: "Azúcar / Edulcorante", keywords: ["azucar", "edulcorante", "stevia", "sucralosa"] },
    { id: "te",           label: "Té en saquitos",       keywords: ["te negro", "te verde", "saquitos de te", "manzanilla"] },
    { id: "golosinas",    label: "Golosinas",            keywords: ["caramelo", "chicle", "gomitas", "chupetin"] },
    { id: "jugo_polvo",   label: "Jugos en polvo",       keywords: ["jugo en polvo", "tang", "clight", "rinde dos"] },
    { id: "mascotas_beb", label: "Mascotas y Bebés",     keywords: ["alimento para perro", "alimento para gato", "panales", "chupete"] },
  ];

  const STARTER_CART = [
    { query: "yerba playadito", qty: 1 },
    { query: "leche", qty: 2 },
    { query: "aceite girasol", qty: 1 },
    { query: "arroz", qty: 1 },
    { query: "fideos", qty: 2 },
    { query: "detergente", qty: 1 },
    { query: "papel higienico", qty: 1 },
  ];

  const LS = {
    theme: "cr_theme",
    favorites: "cr_favorites_v2",
    cart: "cr_cart_v2",
    exclusions: "cr_exclusions_v2",
  };

  const state = {
    activeTab: "compare",
    catalog: { meta: {}, items: [] },
    analytics: null,
    quality: null,
    selectedCategory: "all",
    onlyComparable: false,
    onlyDeals: false,
    onlyFavs: false,
    renderedLimit: 32,
    filteredItems: [],
    expandedCards: new Set(),
    favorites: loadJSON(LS.favorites, []),
    cart: loadJSON(LS.cart, []),
    exclusions: loadJSON(LS.exclusions, { presets: [], custom: [] }),
    lastCartOptimization: null,
  };

  // ── Utilities ──────────────────────────────────────────────
  function loadJSON(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch { return fallback; }
  }

  function saveJSON(key, val) {
    try { localStorage.setItem(key, JSON.stringify(val)); } catch { /* ignore */ }
  }

  function norm(text) {
    return String(text || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
  }

  function fmtARS(val) {
    if (val === null || val === undefined || Number.isNaN(Number(val))) return "-";
    return "$" + Math.round(Number(val)).toLocaleString("es-AR");
  }

  function fmtARSExact(val) {
    if (val === null || val === undefined || Number.isNaN(Number(val))) return "-";
    return "$" + Number(val).toLocaleString("es-AR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function esc(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function storeInfo(key) {
    const k = String(key || "").toLowerCase();
    return STORE_META[k] || { label: key || "Súper", color: "#475569", cls: "store-default" };
  }

  function imgFallbackHTML() {
    return `<div class="ecom-img-fallback">${ICONS.box}<span>Sin foto</span></div>`;
  }

  let toastTimer = null;
  function showToast(msg) {
    const el = document.getElementById("toast");
    el.textContent = msg;
    el.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.add("hidden"), 2400);
  }

  // ── Theme ──────────────────────────────────────────────────
  function initTheme() {
    const saved = localStorage.getItem(LS.theme) || "light";
    const toggleBtn = document.getElementById("theme-toggle");
    document.documentElement.setAttribute("data-theme", saved);
    toggleBtn.innerHTML = saved === "dark" ? ICONS.sun : ICONS.moon;
    toggleBtn.addEventListener("click", () => {
      const next = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
      document.documentElement.setAttribute("data-theme", next);
      localStorage.setItem(LS.theme, next);
      toggleBtn.innerHTML = next === "dark" ? ICONS.sun : ICONS.moon;
    });
  }

  // ── Navigation & Drawer ────────────────────────────────────
  function switchTab(target) {
    state.activeTab = target;
    document.querySelectorAll(".nav-tab").forEach((b) => {
      const active = b.dataset.tab === target;
      b.classList.toggle("active", active);
      b.setAttribute("aria-selected", String(active));
    });
    document.querySelectorAll(".view").forEach((v) => {
      v.classList.toggle("active", v.id === `tab-${target}`);
    });
    if (target === "cart") renderCart();
    if (target === "analytics") renderAnalyticsTab();
  }

  function initNavigation() {
    document.querySelectorAll(".nav-tab").forEach((b) => {
      b.addEventListener("click", () => switchTab(b.dataset.tab));
    });
    document.getElementById("brand-home").addEventListener("click", (e) => {
      e.preventDefault();
      switchTab("compare");
    });
    document.getElementById("header-cart-btn").addEventListener("click", () => switchTab("cart"));

    document.querySelectorAll(".seg-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".seg-btn").forEach((b) => b.classList.toggle("active", b === btn));
        document.getElementById("subtab-gondola").classList.toggle("hidden", btn.dataset.subtab !== "gondola");
        document.getElementById("subtab-barrio").classList.toggle("hidden", btn.dataset.subtab !== "barrio");
      });
    });

    // Slide-over Drawer de filtros
    const openDrawer = () => {
      renderExclusionsDrawer();
      document.getElementById("drawer-backdrop").classList.remove("hidden");
      document.getElementById("filters-drawer").classList.remove("hidden");
    };
    const closeDrawer = () => {
      document.getElementById("drawer-backdrop").classList.add("hidden");
      document.getElementById("filters-drawer").classList.add("hidden");
    };
    document.getElementById("open-filters-btn").addEventListener("click", openDrawer);
    document.getElementById("close-filters-btn").addEventListener("click", closeDrawer);
    document.getElementById("drawer-backdrop").addEventListener("click", closeDrawer);
  }

  // ── Data Loading ───────────────────────────────────────────
  async function loadAllData() {
    try {
      const [catRes, anaRes, qualRes] = await Promise.all([
        fetch("./data/catalog.json"),
        fetch("./data/analytics.json").catch(() => null),
        fetch("./data/quality.json").catch(() => null),
      ]);
      if (!catRes.ok) throw new Error(`HTTP ${catRes.status}`);
      state.catalog = await catRes.json();
      if (anaRes && anaRes.ok) state.analytics = await anaRes.json();
      if (qualRes && qualRes.ok) state.quality = await qualRes.json();

      for (const item of state.catalog.items) {
        item._search = norm(`${item.name} ${item.brand || ""} ${item.ean || ""}`);
      }

      renderFreshness();
      populateSuggestions();
      renderCategoryStrip();
      updateBadges();
      applyFilters();
    } catch (err) {
      document.getElementById("freshness-pill").textContent = "Sin datos";
      document.getElementById("compare-grid").innerHTML = `
        <div class="empty-state">
          <h3>No se encontró el catálogo de precios</h3>
          <p class="muted">Corré <code>uv run scraper serve --demo</code> o <code>uv run scraper export-web --demo</code>.</p>
          <p class="small muted">${esc(err.message)}</p>
        </div>`;
    }
  }

  function renderFreshness() {
    const meta = state.catalog.meta || {};
    const entries = Object.values(meta.stores_freshness || {});
    const pill = document.getElementById("freshness-pill");
    const banner = document.getElementById("stale-banner");

    if (!entries.length) {
      pill.textContent = `Actualizado ${meta.latest_dt || "-"}`;
      return;
    }

    const carried = entries.filter((e) => e.status === "carried_forward" || e.age_days > 0);
    pill.textContent = `● ${meta.latest_dt || "Hoy"} · ${entries.length} cadenas`;
    pill.style.color = carried.length ? "var(--warning)" : "var(--success)";

    if (carried.length) {
      const detail = carried.map((c) => `${storeInfo(c.store).label} (${c.last_dt})`).join(", ");
      banner.textContent = `Modo resiliencia (Carry-Forward): conservando últimos precios válidos de ${detail}.`;
      banner.classList.remove("hidden");
    } else {
      banner.classList.add("hidden");
    }
  }

  function populateSuggestions() {
    const dl = document.getElementById("product-suggestions");
    dl.innerHTML = state.catalog.items.slice(0, 200).map((it) => `<option value="${esc(it.name)}"></option>`).join("");
  }

  function updateBadges() {
    const totalUnits = state.cart.reduce((acc, c) => acc + (c.qty || 1), 0);
    const cb = document.getElementById("cart-badge");
    cb.textContent = String(totalUnits);
    cb.classList.toggle("hidden", totalUnits === 0);

    const favCount = document.getElementById("fav-count");
    favCount.textContent = state.favorites.length ? `(${state.favorites.length})` : "";

    const activeStore = document.getElementById("filter-store")?.value || "all";
    const hasCustomFilters = activeStore !== "all" || getActiveExclusions().length > 0;
    document.getElementById("filters-dot").classList.toggle("hidden", !hasCustomFilters);
  }

  // ── Exclusions (Client-side localStorage only) ─────────────
  function getActiveExclusions() {
    const set = new Set();
    for (const id of state.exclusions.presets || []) {
      const p = EXCLUSION_PRESETS.find((x) => x.id === id);
      if (p) p.keywords.forEach((k) => set.add(norm(k)));
    }
    for (const c of state.exclusions.custom || []) {
      const n = norm(c);
      if (n) set.add(n);
    }
    return Array.from(set);
  }

  function isExcluded(item, keywords) {
    if (!keywords.length) return false;
    const hay = item._search || norm(item.name);
    for (const kw of keywords) {
      if (kw.length <= 3) {
        const re = new RegExp(`\\b${kw.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`);
        if (re.test(hay)) return true;
      } else if (hay.includes(kw)) {
        return true;
      }
    }
    return false;
  }

  // ── Storefront Filters & Categories ────────────────────────
  function renderCategoryStrip() {
    const counts = { all: state.catalog.items.length };
    for (const it of state.catalog.items) {
      counts[it.cat || "otros"] = (counts[it.cat || "otros"] || 0) + 1;
    }
    const strip = document.getElementById("category-strip");
    strip.innerHTML = CATEGORIES
      .filter((c) => c.id === "all" || (counts[c.id] || 0) > 0)
      .map((c) => {
        const active = state.selectedCategory === c.id ? "active" : "";
        return `<button class="cat-pill ${active}" data-cat="${c.id}" type="button">${esc(c.label)}</button>`;
      })
      .join("");

    strip.querySelectorAll(".cat-pill").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.selectedCategory = btn.dataset.cat;
        state.renderedLimit = 32;
        renderCategoryStrip();
        applyFilters();
      });
    });
  }

  function initStorefrontEvents() {
    const searchEl = document.getElementById("search-input");
    const clearBtn = document.getElementById("clear-search-btn");
    let timer = null;

    searchEl.addEventListener("input", () => {
      clearBtn.classList.toggle("hidden", !searchEl.value.trim());
      if (state.activeTab !== "compare" && searchEl.value.trim()) {
        switchTab("compare");
      }
      clearTimeout(timer);
      timer = setTimeout(() => {
        state.renderedLimit = 32;
        applyFilters();
      }, 80);
    });

    clearBtn.addEventListener("click", () => {
      searchEl.value = "";
      clearBtn.classList.add("hidden");
      state.renderedLimit = 32;
      applyFilters();
      searchEl.focus();
    });

    const wireTogglePill = (id, prop) => {
      const btn = document.getElementById(id);
      btn.addEventListener("click", () => {
        state[prop] = !state[prop];
        btn.classList.toggle("active", state[prop]);
        state.renderedLimit = 32;
        applyFilters();
      });
    };
    wireTogglePill("pill-comparable", "onlyComparable");
    wireTogglePill("pill-deals", "onlyDeals");
    wireTogglePill("pill-favs", "onlyFavs");

    document.getElementById("filter-sort").addEventListener("change", () => {
      state.renderedLimit = 32;
      applyFilters();
    });

    document.getElementById("filter-store").addEventListener("change", () => {
      state.renderedLimit = 32;
      updateBadges();
      applyFilters();
    });

    document.getElementById("load-more-btn").addEventListener("click", () => {
      state.renderedLimit += 32;
      renderGrid();
    });
  }

  function applyFilters() {
    const q = norm(document.getElementById("search-input").value);
    const words = q ? q.split(/\s+/).filter(Boolean) : [];
    const storeFilter = document.getElementById("filter-store").value;
    const sortBy = document.getElementById("filter-sort").value;
    const excl = getActiveExclusions();
    const favIds = new Set(state.favorites.map((f) => f.id));

    const out = [];
    for (const item of state.catalog.items) {
      if (state.selectedCategory !== "all" && item.cat !== state.selectedCategory) continue;
      if (state.onlyComparable && item.n < 2) continue;
      if (state.onlyDeals && !(item.disc >= 5 || item.hp)) continue;
      if (state.onlyFavs && !favIds.has(item.id)) continue;
      if (storeFilter !== "all" && (!item.s || !item.s[storeFilter])) continue;
      if (isExcluded(item, excl)) continue;

      if (words.length && !words.every((w) => item._search.includes(w))) continue;
      out.push(item);
    }

    if (sortBy === "price_asc") out.sort((a, b) => a.min - b.min);
    else if (sortBy === "unit_asc") out.sort((a, b) => (a.up || a.min) - (b.up || b.min));
    else if (sortBy === "spread_desc") out.sort((a, b) => (b.sp - a.sp) || (b.n - a.n));
    else if (sortBy === "discount_desc") out.sort((a, b) => (b.disc - a.disc) || ((b.hp ? 1 : 0) - (a.hp ? 1 : 0)) || (a.min - b.min));
    else out.sort((a, b) => (b.n - a.n) || (b.sp - a.sp) || (a.min - b.min));

    state.filteredItems = out;
    document.getElementById("results-count").textContent =
      `${out.length.toLocaleString("es-AR")} ${out.length === 1 ? "producto" : "productos"}`;

    renderGrid();
  }

  // ── Cart & Favorites Helpers ───────────────────────────────
  function isFavorite(id) {
    return state.favorites.some((f) => f.id === id);
  }

  function toggleFavorite(item) {
    const idx = state.favorites.findIndex((f) => f.id === item.id);
    if (idx >= 0) {
      state.favorites.splice(idx, 1);
      showToast("Quitado de favoritos");
    } else {
      state.favorites.push({ id: item.id, ean: item.ean || null, name: item.name });
      showToast("Guardado en favoritos");
    }
    saveJSON(LS.favorites, state.favorites);
    updateBadges();
  }

  function getCartEntry(itemId, queryText) {
    return state.cart.find((c) => (itemId && c.itemId === itemId) || norm(c.query) === norm(queryText));
  }

  function changeCartQty(queryText, delta, itemId = null) {
    const clean = String(queryText || "").trim();
    if (!clean) return;
    const idx = state.cart.findIndex((c) => (itemId && c.itemId === itemId) || norm(c.query) === norm(clean));
    if (idx >= 0) {
      state.cart[idx].qty += delta;
      if (state.cart[idx].qty <= 0) state.cart.splice(idx, 1);
    } else if (delta > 0) {
      state.cart.push({ query: clean, qty: delta, itemId });
      showToast(`Agregado al changuito`);
    }
    saveJSON(LS.cart, state.cart);
    updateBadges();
  }

  // ── E-Commerce Card Renderer ───────────────────────────────
  function buildEcomCardHTML(item) {
    const fav = isFavorite(item.id);
    const cartEntry = getCartEntry(item.id, item.name);
    const stores = Object.entries(item.s || {}).sort((a, b) => a[1].p - b[1].p);
    const expanded = state.expandedCards.has(item.id);
    const visibleStores = expanded ? stores : stores.slice(0, 4);
    const hiddenCount = stores.length - visibleStores.length;

    const bestEntry = stores.length ? stores[0][1] : null;
    const bestHasDirectDisc = Boolean(bestEntry && bestEntry.d >= 5 && bestEntry.lp > bestEntry.p);

    const mediaHTML = item.img
      ? `<img class="ecom-img" src="${esc(item.img)}" alt="${esc(item.name)}" loading="lazy">`
      : imgFallbackHTML();

    const unitText = item.u && item.u !== "$/item" && item.up
      ? `${fmtARS(item.up)} ${esc(item.u.replace("$/", "/"))}`
      : "";

    const bestLabel = storeInfo(item.best).label;
    const trend = item.ean ? state.analytics?.product_trends?.[item.ean] : null;
    let metaLineHTML = "";
    let metaCls = "ecom-meta-line";
    if (state.onlyFavs && trend && trend.dir !== "estable") {
      if (trend.dir === "subio") {
        metaCls += " trend-up";
        metaLineHTML = `Subió ${trend.pct}% esta semana`;
      } else {
        metaCls += " trend-down";
        metaLineHTML = `Bajó ${Math.abs(trend.pct)}% esta semana`;
      }
    } else if (item.n >= 2) {
      metaLineHTML = `Más barato en <strong>${esc(bestLabel)}</strong> · ${item.n} supermercados`;
    } else {
      metaLineHTML = `Disponible en <strong>${esc(bestLabel)}</strong>`;
    }

    const minP = stores.length ? stores[0][1].p : 0;
    const maxP = stores.length ? stores[stores.length - 1][1].p : 0;
    const totalSpreadPct = minP > 0 ? ((maxP - minP) / minP) * 100 : 0;

    const priceRowsHTML = visibleStores
      .map(([sKey, info], idx) => {
        const meta = storeInfo(sKey);
        const deltaPct = minP > 0 ? ((info.p - minP) / minP) * 100 : 0;

        let tierCls = "";
        if (stores.length >= 2 && totalSpreadPct >= 3) {
          if (deltaPct <= 1.5) tierCls = "tier-best";
          else if (deltaPct >= 18 || (idx === stores.length - 1 && deltaPct >= 10)) tierCls = "tier-expensive";
          else if (deltaPct >= 8) tierCls = "tier-mid-high";
        }

        const hasDirectDisc = Boolean(info.d >= 5 && info.lp > info.p);
        const promoBadgeHTML = hasDirectDisc
          ? `<span class="row-disc">-${Math.round(info.d)}%</span>`
          : info.pl
            ? `<span class="row-promo">${esc(info.pl)}</span>`
            : "";

        const secondaryPriceHTML = hasDirectDisc
          ? `<span class="row-lp">${fmtARS(info.lp)}</span>`
          : (stores.length >= 2 && deltaPct >= 8)
            ? `<span class="row-delta">+${Math.round(deltaPct)}%</span>`
            : "";

        const href = info.url ? esc(info.url) : "#";
        const target = info.url ? 'target="_blank" rel="noopener noreferrer"' : "";
        return `
          <a class="price-row ${tierCls}" href="${href}" ${target} title="Abrir producto en ${esc(meta.label)}">
            <span class="price-row-store">
              <span class="store-dot" style="background:${meta.color}"></span>
              <span class="store-label">${esc(meta.label)}</span>
              ${promoBadgeHTML}
            </span>
            <span class="price-row-right">
              ${secondaryPriceHTML}
              <span class="row-price">${fmtARS(info.p)}</span>
              <span class="row-arrow">↗</span>
            </span>
          </a>`;
      })
      .join("");

    const moreBtnHTML = hiddenCount > 0
      ? `<button class="more-stores-btn" data-action="more" type="button">+ Ver ${hiddenCount} ${hiddenCount === 1 ? "súper más" : "súpers más"}</button>`
      : "";

    const ctaHTML = cartEntry
      ? `<div class="cta-stepper">
           <button data-action="dec" type="button" aria-label="Restar">−</button>
           <span>${cartEntry.qty} en changuito</span>
           <button data-action="inc" type="button" aria-label="Sumar">+</button>
         </div>`
      : `<button class="cta-add" data-action="add" type="button">+ Agregar al changuito</button>`;

    return `
      <article class="ecom-card" data-id="${esc(item.id)}">
        <div class="ecom-media">
          <button class="ecom-fav ${fav ? "active" : ""}" data-action="fav" type="button" title="${fav ? "Quitar de favoritos" : "Guardar en favoritos"}" aria-label="Favorito">
            ${fav ? ICONS.heartFilled : ICONS.heartOutline}
          </button>
          ${mediaHTML}
        </div>
        <div class="ecom-body">
          <div class="ecom-brand">${esc(item.brand || "Supermercado")}</div>
          <h3 class="ecom-title" title="${esc(item.name)}">${esc(item.name)}</h3>
          <div class="ecom-hero-price">
            <span class="price-main">${fmtARS(item.min)}</span>
            ${bestHasDirectDisc ? `<span class="price-regular">${fmtARS(bestEntry.lp)}</span><span class="price-disc-tag">-${Math.round(bestEntry.d)}%</span>` : ""}
          </div>
          ${unitText ? `<div class="price-unit">${unitText}</div>` : ""}
          <div class="${metaCls}">${metaLineHTML}</div>
          <div class="price-list">
            ${priceRowsHTML}
            ${moreBtnHTML}
          </div>
          <div class="ecom-foot">${ctaHTML}</div>
        </div>
      </article>`;
  }

  function renderGrid() {
    const grid = document.getElementById("compare-grid");
    const loadBtn = document.getElementById("load-more-btn");

    if (!state.filteredItems.length) {
      grid.innerHTML = `
        <div class="empty-state">
          <h3>No encontramos productos con esos filtros</h3>
          <p class="muted">Probá con otra búsqueda o tocá Filtros para revisar tus preferencias.</p>
        </div>`;
      loadBtn.classList.add("hidden");
      return;
    }

    const slice = state.filteredItems.slice(0, state.renderedLimit);
    grid.innerHTML = slice.map(buildEcomCardHTML).join("");

    grid.querySelectorAll(".ecom-img").forEach((img) => {
      img.addEventListener("error", () => {
        const wrap = document.createElement("div");
        wrap.innerHTML = imgFallbackHTML();
        if (wrap.firstElementChild) img.replaceWith(wrap.firstElementChild);
      }, { once: true });
    });

    grid.querySelectorAll(".ecom-card").forEach((card) => {
      const id = card.dataset.id;
      const item = slice.find((x) => x.id === id);
      if (!item) return;

      card.querySelector('[data-action="fav"]')?.addEventListener("click", () => {
        toggleFavorite(item);
        if (state.onlyFavs) applyFilters();
        else card.outerHTML = buildEcomCardHTML(item), rebindSingleCard(grid, item);
      });

      card.querySelector('[data-action="more"]')?.addEventListener("click", () => {
        state.expandedCards.add(item.id);
        renderGrid();
      });

      card.querySelector('[data-action="add"]')?.addEventListener("click", () => {
        changeCartQty(item.name, 1, item.id);
        renderGrid();
      });

      card.querySelector('[data-action="inc"]')?.addEventListener("click", () => {
        changeCartQty(item.name, 1, item.id);
        renderGrid();
      });

      card.querySelector('[data-action="dec"]')?.addEventListener("click", () => {
        changeCartQty(item.name, -1, item.id);
        renderGrid();
      });
    });

    loadBtn.classList.toggle("hidden", state.filteredItems.length <= state.renderedLimit);
    loadBtn.textContent = `Mostrar más (${slice.length} de ${state.filteredItems.length.toLocaleString("es-AR")})`;
  }

  function rebindSingleCard(grid, item) {
    // Re-render limpio del card cuando se cambia favorito
    renderGrid();
  }

  // ── Drawer: Exclusions & Favorites Export/Import ───────────
  function initDrawerControls() {
    document.getElementById("excl-custom-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const input = document.getElementById("excl-custom-input");
      const val = norm(input.value);
      if (val && !state.exclusions.custom.includes(val)) {
        state.exclusions.custom.push(val);
        saveJSON(LS.exclusions, state.exclusions);
        input.value = "";
        updateBadges();
        renderExclusionsDrawer();
        applyFilters();
      }
    });

    document.getElementById("excl-reset-btn").addEventListener("click", () => {
      state.exclusions = { presets: [], custom: [] };
      saveJSON(LS.exclusions, state.exclusions);
      updateBadges();
      renderExclusionsDrawer();
      applyFilters();
      showToast("Exclusiones personales limpiadas");
    });

    document.getElementById("fav-export-btn").addEventListener("click", () => {
      const blob = new Blob([JSON.stringify(state.favorites, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "changoradar_favoritos.json";
      a.click();
      URL.revokeObjectURL(url);
    });

    document.getElementById("fav-import-input").addEventListener("change", (e) => {
      const file = e.target.files?.[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = () => {
        try {
          const parsed = JSON.parse(String(reader.result));
          if (Array.isArray(parsed)) {
            state.favorites = parsed;
            saveJSON(LS.favorites, state.favorites);
            updateBadges();
            applyFilters();
            showToast(`Importados ${parsed.length} favoritos`);
          }
        } catch {
          showToast("Archivo JSON inválido");
        }
      };
      reader.readAsText(file);
    });
  }

  function renderExclusionsDrawer() {
    const presetsEl = document.getElementById("exclusion-presets");
    presetsEl.innerHTML = EXCLUSION_PRESETS
      .map((p) => {
        const active = (state.exclusions.presets || []).includes(p.id);
        return `<button class="filter-pill ${active ? "active" : ""}" data-preset="${p.id}" type="button">${esc(p.label)}</button>`;
      })
      .join("");

    presetsEl.querySelectorAll("[data-preset]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = btn.dataset.preset;
        const list = state.exclusions.presets || [];
        const i = list.indexOf(id);
        if (i >= 0) list.splice(i, 1);
        else list.push(id);
        state.exclusions.presets = list;
        saveJSON(LS.exclusions, state.exclusions);
        updateBadges();
        renderExclusionsDrawer();
        applyFilters();
      });
    });

    const tagsEl = document.getElementById("excl-active-tags");
    tagsEl.innerHTML = (state.exclusions.custom || [])
      .map((kw, idx) => `<button class="filter-pill active" data-del-kw="${idx}" type="button">${esc(kw)} ×</button>`)
      .join("");
    tagsEl.querySelectorAll("[data-del-kw]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.exclusions.custom.splice(Number(btn.dataset.delKw), 1);
        saveJSON(LS.exclusions, state.exclusions);
        updateBadges();
        renderExclusionsDrawer();
        applyFilters();
      });
    });
  }

  // ── VISTA 2: MI CHANGUITO ──────────────────────────────────
  function findMatches(query, itemId = null) {
    if (itemId) {
      const exact = state.catalog.items.find((i) => i.id === itemId);
      if (exact) return [exact];
    }
    const stop = new Set(["de", "la", "el", "en", "con", "sin", "x", "kg", "gr", "g", "ml", "l"]);
    const raw = norm(query).replace(/[/\-]/g, " ").split(/\s+/).filter((w) => w.length > 1);
    const words = raw.filter((w) => !stop.has(w));
    const searchWords = words.length ? words : raw;
    if (!searchWords.length) return [];
    return state.catalog.items.filter((it) => searchWords.every((w) => it._search.includes(w)));
  }

  function optimizeCart() {
    const stores = Object.keys(STORE_META);
    const totals = {};
    stores.forEach((s) => { totals[s] = { store: s, total: 0, found: 0 }; });

    const rows = [];
    let splitTotal = 0;
    let splitCovered = 0;

    for (const entry of state.cart) {
      const matches = findMatches(entry.query, entry.itemId);
      let bestStore = null, bestPrice = null, bestName = null, bestUrl = null;

      for (const s of stores) {
        let sMin = null, sName = null, sUrl = null;
        for (const m of matches) {
          const info = m.s?.[s];
          if (info && (sMin === null || info.p < sMin)) {
            sMin = info.p; sName = m.name; sUrl = info.url || null;
          }
        }
        if (sMin !== null) {
          const line = sMin * entry.qty;
          totals[s].total += line;
          totals[s].found += 1;
          if (bestPrice === null || line < bestPrice) {
            bestPrice = line; bestStore = s; bestName = sName; bestUrl = sUrl;
          }
        }
      }

      if (bestPrice !== null) {
        splitTotal += bestPrice;
        splitCovered += 1;
      }
      rows.push({ query: entry.query, qty: entry.qty, bestStore, bestName, bestPrice, bestUrl });
    }

    const ranked = Object.values(totals)
      .filter((s) => s.found > 0)
      .sort((a, b) => (b.found - a.found) || (a.total - b.total));

    return { ranked, bestSingle: ranked[0] || null, splitTotal, splitCovered, totalItems: state.cart.length, rows };
  }

  function initCartEvents() {
    document.getElementById("cart-add-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const input = document.getElementById("cart-item-input");
      const qty = Math.max(1, parseInt(document.getElementById("cart-qty-input").value, 10) || 1);
      changeCartQty(input.value, qty);
      input.value = "";
      document.getElementById("cart-qty-input").value = "1";
      renderCart();
    });

    document.getElementById("cart-load-starter").addEventListener("click", () => {
      state.cart = STARTER_CART.map((x) => ({ ...x, itemId: null }));
      saveJSON(LS.cart, state.cart);
      updateBadges();
      renderCart();
      showToast("Canasta ejemplo cargada");
    });

    document.getElementById("cart-load-favs").addEventListener("click", () => {
      if (!state.favorites.length) { showToast("Todavía no marcaste favoritos"); return; }
      state.favorites.forEach((f) => changeCartQty(f.name, 1, f.id));
      renderCart();
    });

    document.getElementById("cart-clear").addEventListener("click", () => {
      state.cart = [];
      saveJSON(LS.cart, state.cart);
      updateBadges();
      renderCart();
      renderGrid();
    });

    document.getElementById("cart-copy-wa").addEventListener("click", copyCartWA);
  }

  function renderCart() {
    const listEl = document.getElementById("cart-items-list");
    const summaryEl = document.getElementById("cart-summary-section");

    if (!state.cart.length) {
      listEl.innerHTML = `<div class="empty-state" style="border:none;padding:24px">Tu changuito está vacío. Agregá productos desde la Tienda o tocá "Canasta ejemplo".</div>`;
      summaryEl.classList.add("hidden");
      return;
    }

    listEl.innerHTML = state.cart.map((c, idx) => `
      <div class="cart-row">
        <span><strong>${esc(c.query)}</strong></span>
        <div class="cart-qty-ctrl">
          <button class="btn btn-ghost btn-sm" data-dec="${idx}" type="button">−</button>
          <span>${c.qty}</span>
          <button class="btn btn-ghost btn-sm" data-inc="${idx}" type="button">+</button>
          <button class="btn btn-ghost btn-sm" data-del="${idx}" type="button" aria-label="Eliminar">×</button>
        </div>
      </div>`).join("");

    listEl.querySelectorAll("[data-dec]").forEach((b) => b.addEventListener("click", () => {
      const i = Number(b.dataset.dec);
      state.cart[i].qty = Math.max(1, state.cart[i].qty - 1);
      saveJSON(LS.cart, state.cart); updateBadges(); renderCart();
    }));
    listEl.querySelectorAll("[data-inc]").forEach((b) => b.addEventListener("click", () => {
      state.cart[Number(b.dataset.inc)].qty += 1;
      saveJSON(LS.cart, state.cart); updateBadges(); renderCart();
    }));
    listEl.querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", () => {
      state.cart.splice(Number(b.dataset.del), 1);
      saveJSON(LS.cart, state.cart); updateBadges(); renderCart(); renderGrid();
    }));

    const opt = optimizeCart();
    state.lastCartOptimization = opt;
    summaryEl.classList.remove("hidden");

    const sCard = document.getElementById("cart-best-single");
    const spCard = document.getElementById("cart-best-split");

    if (opt.bestSingle) {
      const cov = Math.round((opt.bestSingle.found / opt.totalItems) * 100);
      sCard.innerHTML = `
        <span class="kpi-lbl">Mejor Compra en 1 Súper</span>
        <span class="kpi-val">${esc(storeInfo(opt.bestSingle.store).label)} · ${fmtARS(opt.bestSingle.total)}</span>
        <span class="kpi-sub">Cubre ${opt.bestSingle.found}/${opt.totalItems} ítems (${cov}%)</span>`;
    } else {
      sCard.innerHTML = `<span class="kpi-lbl">Mejor Compra Única</span><span class="kpi-sub">Sin coincidencias</span>`;
    }

    const sav = opt.bestSingle ? Math.max(0, opt.bestSingle.total - opt.splitTotal) : 0;
    const savPct = opt.bestSingle && opt.bestSingle.total > 0 ? ((sav / opt.bestSingle.total) * 100).toFixed(1) : "0.0";
    spCard.innerHTML = `
      <span class="kpi-lbl">Compra Partida Óptima</span>
      <span class="kpi-val">${fmtARS(opt.splitTotal)}</span>
      <span class="kpi-sub">${sav > 0 ? `Diferencia de ${fmtARS(sav)} (${savPct}%) dividiendo entre súpers` : `Cubre ${opt.splitCovered}/${opt.totalItems} ítems`}</span>`;

    const maxT = Math.max(...opt.ranked.map((r) => r.total), 1);
    document.getElementById("cart-store-bars").innerHTML = opt.ranked.map((r) => {
      const info = storeInfo(r.store);
      const w = Math.max(10, Math.round((r.total / maxT) * 100));
      return `
        <div class="bar-row">
          <strong>${esc(info.label)}</strong>
          <div class="bar-track"><div class="bar-fill" style="width:${w}%;background:${info.color}"></div></div>
          <span class="num"><strong>${fmtARS(r.total)}</strong> <span class="small muted">(${r.found}/${opt.totalItems})</span></span>
        </div>`;
    }).join("");

    document.querySelector("#cart-detail-table tbody").innerHTML = opt.rows.map((r) => {
      if (!r.bestStore) return `<tr><td>${esc(r.query)}</td><td>${r.qty}</td><td colspan="3" class="muted">Sin coincidencias</td></tr>`;
      const meta = storeInfo(r.bestStore);
      const link = r.bestUrl ? `<a href="${esc(r.bestUrl)}" target="_blank" rel="noopener">${esc(r.bestName)} ↗</a>` : esc(r.bestName);
      return `
        <tr>
          <td><strong>${esc(r.query)}</strong></td>
          <td>${r.qty}</td>
          <td><span class="store-tag ${meta.cls}">${esc(meta.label)}</span></td>
          <td>${link}</td>
          <td class="num"><strong>${fmtARS(r.bestPrice)}</strong></td>
        </tr>`;
    }).join("");
  }

  function copyCartWA() {
    const opt = state.lastCartOptimization;
    if (!opt || !opt.rows.length) return;
    const lines = ["*Changuito Optimizado (ChangoRadar)*"];
    if (opt.bestSingle) lines.push(`- 1 solo súper: *${storeInfo(opt.bestSingle.store).label}* (${fmtARS(opt.bestSingle.total)})`);
    lines.push(`- Compra partida: *${fmtARS(opt.splitTotal)}*`, "");
    const byStore = {};
    for (const r of opt.rows) {
      if (!r.bestStore) continue;
      byStore[r.bestStore] = byStore[r.bestStore] || [];
      byStore[r.bestStore].push(r);
    }
    for (const [sKey, items] of Object.entries(byStore)) {
      const sub = items.reduce((a, b) => a + (b.bestPrice || 0), 0);
      lines.push(`*${storeInfo(sKey).label}* (${fmtARS(sub)}):`);
      items.forEach((it) => lines.push(`- ${it.qty}x ${it.bestName} — ${fmtARS(it.bestPrice)}`));
      lines.push("");
    }
    navigator.clipboard?.writeText(lines.join("\n").trim())
      .then(() => showToast("Lista copiada para pegar en WhatsApp"))
      .catch(() => showToast("No se pudo copiar al portapapeles"));
  }

  // ── VISTA 3: EVALUADOR PROMOS & BARRIO ─────────────────────
  function initPromoEvents() {
    const pt = document.getElementById("promo-type");
    pt.addEventListener("change", () => {
      document.getElementById("promo-direct-pct-wrap").classList.toggle("hidden", pt.value !== "direct_pct");
    });

    document.getElementById("promo-form").addEventListener("submit", (e) => {
      e.preventDefault();
      evaluatePromo();
    });

    document.getElementById("barrio-form").addEventListener("submit", (e) => {
      e.preventDefault();
      evaluateBarrio();
    });
  }

  function evaluatePromo() {
    const product = document.getElementById("promo-product").value.trim();
    const store = document.getElementById("promo-store").value;
    const regPrice = parseFloat(document.getElementById("promo-price").value);
    const pType = document.getElementById("promo-type").value;
    const directPct = parseFloat(document.getElementById("promo-direct-pct").value) || 0;
    const bankPct = parseFloat(document.getElementById("promo-bank-pct").value) || 0;

    let units = 1, total = regPrice, desc = "Precio regular";
    if (pType === "2do_al_70") { units = 2; total = regPrice * 1.3; desc = "2do al 70% (35% off prom.)"; }
    else if (pType === "2do_al_80") { units = 2; total = regPrice * 1.2; desc = "2do al 80% (40% off prom.)"; }
    else if (pType === "2do_al_50") { units = 2; total = regPrice * 1.5; desc = "2do al 50% (25% off prom.)"; }
    else if (pType === "3x2") { units = 3; total = regPrice * 2; desc = "3x2 (33.3% off prom.)"; }
    else if (pType === "4x3") { units = 4; total = regPrice * 3; desc = "4x3 (25% off prom.)"; }
    else if (pType === "direct_pct") { total = regPrice * (1 - directPct / 100); desc = `${directPct}% off directo`; }
    if (bankPct > 0) { total *= (1 - bankPct / 100); desc += ` + ${bankPct}% banco`; }

    const effUnit = total / units;
    const effDisc = regPrice > 0 ? ((regPrice - effUnit) / regPrice) * 100 : 0;

    const matches = findMatches(product);
    const byStore = {};
    for (const m of matches) {
      for (const [sKey, info] of Object.entries(m.s || {})) {
        if (!byStore[sKey] || info.p < byStore[sKey].price) {
          byStore[sKey] = { store: sKey, price: info.p, name: m.name, url: info.url };
        }
      }
    }
    const comps = Object.values(byStore).sort((a, b) => a.price - b.price);
    const cheapest = comps[0] || null;

    let cls = "pill-neutral", verdict = "PRECIO JUSTO";
    let text = `Pagás ${fmtARSExact(effUnit)} c/u (${effDisc.toFixed(1)}% menos que el precio de lista).`;

    if (cheapest) {
      const diffPct = ((cheapest.price - effUnit) / cheapest.price) * 100;
      if (effUnit > cheapest.price * 1.05) {
        cls = "pill-danger"; verdict = "CAZABOBOS / FALSO DESCUENTO";
        text = `Con "${desc}" pagás ${fmtARSExact(effUnit)} c/u en ${storeInfo(store).label}, pero en ${storeInfo(cheapest.store).label} está a ${fmtARSExact(cheapest.price)} sin promo (${Math.abs(diffPct).toFixed(1)}% más barato).`;
      } else if (diffPct >= 15) {
        cls = "pill-success"; verdict = "OPORTUNIDAD REAL";
        text = `Pagás ${fmtARSExact(effUnit)} c/u, un ${diffPct.toFixed(1)}% menos que el mejor rival (${storeInfo(cheapest.store).label} a ${fmtARSExact(cheapest.price)}).`;
      } else if (diffPct >= 5) {
        cls = "pill-success"; verdict = "BUEN PRECIO";
        text = `Queda ${diffPct.toFixed(1)}% por debajo de ${storeInfo(cheapest.store).label} (${fmtARSExact(cheapest.price)}).`;
      } else {
        text = `Alineado al mercado: ${fmtARSExact(effUnit)} c/u vs ${fmtARSExact(cheapest.price)} en ${storeInfo(cheapest.store).label}.`;
      }
    }

    const compTable = comps.length
      ? `<div class="table-wrap" style="margin-top:14px"><table class="data-table">
           <thead><tr><th>Cadena</th><th>Producto</th><th class="num">Precio</th></tr></thead>
           <tbody>${comps.map((c) => `
             <tr>
               <td><span class="store-tag ${storeInfo(c.store).cls}">${esc(storeInfo(c.store).label)}</span></td>
               <td>${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.name)} ↗</a>` : esc(c.name)}</td>
               <td class="num"><strong>${fmtARSExact(c.price)}</strong></td>
             </tr>`).join("")}</tbody></table></div>`
      : `<p class="small muted">Sin competidores exactos en el catálogo cargado.</p>`;

    const box = document.getElementById("promo-result");
    box.innerHTML = `
      <div style="display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px">
        <span class="pill ${cls}" style="font-size:0.88rem;padding:5px 12px">${verdict}</span>
        <span class="small muted">${esc(desc)}</span>
      </div>
      <p style="margin:6px 0 12px">${esc(text)}</p>
      <div class="funnel-grid">
        <div class="funnel-step"><div class="step-lbl">Efectivo c/u</div><div class="step-num">${fmtARSExact(effUnit)}</div></div>
        <div class="funnel-step"><div class="step-lbl">Descuento real</div><div class="step-num">${effDisc.toFixed(1)}%</div></div>
        <div class="funnel-step"><div class="step-lbl">Total (${units} u.)</div><div class="step-num">${fmtARSExact(total)}</div></div>
        <div class="funnel-step"><div class="step-lbl">Mejor rival</div><div class="step-num">${cheapest ? fmtARSExact(cheapest.price) : "-"}</div></div>
      </div>
      ${compTable}`;
    box.classList.remove("hidden");
  }

  function evaluateBarrio() {
    const product = document.getElementById("barrio-product").value.trim();
    const qty = Math.max(0.05, parseFloat(document.getElementById("barrio-qty").value) || 1);
    const unit = document.getElementById("barrio-unit").value;
    const paidTotal = parseFloat(document.getElementById("barrio-paid").value);
    const paidUnit = paidTotal / qty;

    const matches = findMatches(product);
    const box = document.getElementById("barrio-result");
    if (!matches.length) {
      box.innerHTML = `<p class="muted">No encontramos "${esc(product)}" en el catálogo cargado.</p>`;
      box.classList.remove("hidden");
      return;
    }

    const useU = unit === "kg" || unit === "L";
    const targetM = unit === "kg" ? "$/kg" : unit === "L" ? "$/L" : null;
    const refs = [];
    for (const m of matches) {
      for (const [sKey, info] of Object.entries(m.s || {})) {
        const val = (useU && m.u === targetM && info.up) ? info.up : info.p;
        refs.push({ store: sKey, unitPrice: val, packPrice: info.p, name: m.name, u: m.u });
      }
    }
    refs.sort((a, b) => a.unitPrice - b.unitPrice);
    const best = refs[0];
    const avg = refs.reduce((a, b) => a + b.unitPrice, 0) / refs.length;
    const expectedBest = best.unitPrice * qty;
    const diff = expectedBest - paidTotal;
    const diffPct = expectedBest > 0 ? (diff / expectedBest) * 100 : 0;

    box.innerHTML = `
      <span class="pill ${diff >= 0 ? "pill-success" : "pill-warning"}" style="font-size:0.88rem;padding:5px 12px">
        ${diff >= 0 ? `Buen precio en el barrio (${fmtARS(diff)} / ${diffPct.toFixed(1)}% menos que el súper más barato)` : `Pagaste ${fmtARS(Math.abs(diff))} (${Math.abs(diffPct).toFixed(1)}%) más que el mejor súper`}
      </span>
      <div class="funnel-grid" style="margin-top:12px">
        <div class="funnel-step"><div class="step-lbl">Pagaste (/${esc(unit)})</div><div class="step-num">${fmtARSExact(paidUnit)}</div></div>
        <div class="funnel-step"><div class="step-lbl">Mejor súper (${esc(storeInfo(best.store).label)})</div><div class="step-num">${fmtARSExact(best.unitPrice)}</div></div>
        <div class="funnel-step"><div class="step-lbl">Promedio súper</div><div class="step-num">${fmtARSExact(avg)}</div></div>
        <div class="funnel-step"><div class="step-lbl">Equiv. en súper</div><div class="step-num">${fmtARSExact(expectedBest)}</div></div>
      </div>
      <p class="small muted">Referencia: ${esc(best.name)} (${fmtARSExact(best.packPrice)} · ${esc(best.u)}).</p>`;
    box.classList.remove("hidden");
  }

  // ── VISTA 4: ANALYTICS BI & DATA QUALITY ───────────────────
  function renderAnalyticsTab() {
    const ana = state.analytics;
    const qual = state.quality;
    const kpiGrid = document.getElementById("bi-kpi-grid");
    if (!ana && !qual) {
      kpiGrid.innerHTML = `<div class="panel empty-state">Sin datos analíticos disponibles.</div>`;
      return;
    }

    const meta = state.catalog.meta || {};
    const wt = ana?.weekly_trends || {};
    const qk = qual?.quality_kpis || {};
    const infl = Number(wt.basket_weekly_inflation_pct || 0);

    kpiGrid.innerHTML = `
      <div class="panel kpi-box accent-teal">
        <span class="kpi-lbl">Catálogo Consolidado</span>
        <span class="kpi-val">${(meta.total_items || 0).toLocaleString("es-AR")}</span>
        <span class="kpi-sub">${(meta.cross_store_items || 0).toLocaleString("es-AR")} comparables (2+ súpers)</span>
      </div>
      <div class="panel kpi-box">
        <span class="kpi-lbl">Variación del Período</span>
        <span class="kpi-val" style="color:${infl > 0 ? "var(--danger)" : "var(--success)"}">${infl > 0 ? "+" : ""}${infl.toFixed(2)}%</span>
        <span class="kpi-sub">${wt.start_date && wt.end_date ? `${wt.start_date} → ${wt.end_date}` : "Requiere 2+ días"}</span>
      </div>
      <div class="panel kpi-box">
        <span class="kpi-lbl">Calidad Enlaces &amp; Fotos</span>
        <span class="kpi-val">${qk.url_coverage_pct ?? 100}% / ${qk.image_coverage_pct ?? 0}%</span>
        <span class="kpi-sub">EAN válido: ${qk.ean_coverage_pct ?? 0}%</span>
      </div>
      <div class="panel kpi-box">
        <span class="kpi-lbl">Salud de Fuentes</span>
        <span class="kpi-val">${qk.stores_total || Object.keys(meta.stores_freshness || {}).length} / 6</span>
        <span class="kpi-sub">Carry-forward: ${(qk.carried_forward_stores || []).length}</span>
      </div>`;

    renderCompetitiveness(ana?.competitiveness || []);
    renderInflation(ana?.basket_history || []);
    renderMovers(wt);
    renderCazabobos(ana?.cazabobos_examples || []);
    renderStockup(ana?.stockup_deals || []);
    renderQuality(qual);
  }

  function renderCompetitiveness(rows) {
    const chartBox = document.getElementById("chart-competitiveness");
    const tbody = document.querySelector("#table-competitiveness tbody");
    if (!rows.length) { chartBox.innerHTML = `<p class="muted small">Sin datos comparativos.</p>`; tbody.innerHTML = ""; return; }

    const maxWin = Math.max(...rows.map((r) => Number(r.win_rate_pct || 0)), 10);
    const rowH = 32;
    const svgH = rows.length * rowH + 12;
    const bars = rows.map((r, i) => {
      const info = storeInfo(r.store);
      const val = Number(r.win_rate_pct || 0);
      const w = Math.max(4, Math.round((val / maxWin) * 280));
      const y = i * rowH + 6;
      return `
        <text x="4" y="${y + 15}" fill="currentColor" font-size="12" font-weight="700">${esc(info.label)}</text>
        <rect x="92" y="${y + 4}" width="280" height="15" rx="7" fill="var(--surface-subtle)"/>
        <rect x="92" y="${y + 4}" width="${w}" height="15" rx="7" fill="${info.color}"/>
        <text x="382" y="${y + 15}" fill="currentColor" font-size="12" font-weight="700">${val.toFixed(1)}%</text>`;
    }).join("");
    chartBox.innerHTML = `<svg viewBox="0 0 440 ${svgH}" role="img" aria-label="Win-rate por cadena">${bars}</svg>`;

    tbody.innerHTML = rows.map((r) => {
      const info = storeInfo(r.store);
      const idx = Number(r.price_index_vs_median || 100);
      const cls = idx < 98 ? "pill-success" : idx > 103 ? "pill-danger" : "pill-neutral";
      return `
        <tr>
          <td><span class="store-tag ${info.cls}">${esc(info.label)}</span></td>
          <td class="num">${Number(r.catalog_products || 0).toLocaleString("es-AR")}</td>
          <td class="num"><strong>${Number(r.win_rate_pct || 0).toFixed(1)}%</strong></td>
          <td class="num"><span class="pill ${cls}">${idx.toFixed(1)}</span></td>
          <td class="num">${r.deals_15pct_plus || 0}</td>
        </tr>`;
    }).join("");
  }

  function renderInflation(rows) {
    const box = document.getElementById("chart-inflation");
    const legend = document.getElementById("inflation-legend");
    if (!rows.length) { box.innerHTML = `<p class="muted small">Se necesitan ≥2 snapshots diarios.</p>`; legend.innerHTML = ""; return; }

    const dates = Array.from(new Set(rows.map((r) => r.dt))).sort();
    const byStore = {};
    for (const r of rows) {
      byStore[r.store] = byStore[r.store] || {};
      byStore[r.store][r.dt] = Number(r.basket_cost_ars || 0);
    }
    const stores = Object.keys(byStore).sort((a, b) => (a === "split_optimal" ? -1 : b === "split_optimal" ? 1 : a.localeCompare(b)));
    const vals = rows.map((r) => Number(r.basket_cost_ars || 0)).filter((v) => v > 0);
    const minV = Math.min(...vals) * 0.94, maxV = Math.max(...vals) * 1.04;
    const spanV = Math.max(1, maxV - minV);
    const W = 460, H = 205, pL = 58, pR = 16, pT = 14, pB = 28;
    const xFor = (i) => dates.length === 1 ? pL + (W - pL - pR) / 2 : pL + (i / (dates.length - 1)) * (W - pL - pR);
    const yFor = (v) => pT + (H - pT - pB) - ((v - minV) / spanV) * (H - pT - pB);

    const grid = [0, 0.5, 1].map((t) => {
      const v = minV + t * spanV, y = yFor(v);
      return `<line x1="${pL}" y1="${y}" x2="${W - pR}" y2="${y}" stroke="var(--border)" stroke-dasharray="3 3"/>
              <text x="${pL - 6}" y="${y + 4}" text-anchor="end" fill="var(--text-faint)" font-size="10">${fmtARS(v)}</text>`;
    }).join("");
    const xLbls = dates.map((d, i) => `<text x="${xFor(i)}" y="${H - 8}" text-anchor="middle" fill="var(--text-faint)" font-size="10">${esc(d.slice(5))}</text>`).join("");
    const lines = stores.map((s) => {
      const col = s === "split_optimal" ? "#0f766e" : storeInfo(s).color;
      const dash = s === "split_optimal" ? 'stroke-dasharray="5 4"' : "";
      const pts = dates.map((d, i) => byStore[s][d] > 0 ? [xFor(i), yFor(byStore[s][d])] : null).filter(Boolean);
      if (!pts.length) return "";
      const dStr = pts.map((p, i) => `${i === 0 ? "M" : "L"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
      const dots = pts.map((p) => `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="3.5" fill="${col}"/>`).join("");
      return `<path d="${dStr}" fill="none" stroke="${col}" stroke-width="${s === "split_optimal" ? 2.6 : 2}" ${dash}/>${dots}`;
    }).join("");

    box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Evolución de canasta">${grid}${xLbls}${lines}</svg>`;
    legend.innerHTML = stores.map((s) => {
      const lbl = s === "split_optimal" ? "Compra Partida" : storeInfo(s).label;
      const col = s === "split_optimal" ? "#0f766e" : storeInfo(s).color;
      return `<span class="pill pill-neutral"><span class="store-dot" style="background:${col}"></span>${esc(lbl)}</span>`;
    }).join("");
  }

  function renderMovers(wt) {
    const mk = (arr, up) => (!arr || !arr.length)
      ? `<p class="muted small">Sin variaciones registradas.</p>`
      : arr.slice(0, 8).map((r) => `
          <div class="trend-row">
            <div><strong>${esc(r.name)}</strong><div class="small muted">${esc(storeInfo(r.store).label)} · ${fmtARS(r.price_start)} → ${fmtARS(r.price_end)}</div></div>
            <span class="pill ${up ? "pill-danger" : "pill-success"}">${up ? "+" : ""}${Number(r.change_pct).toFixed(1)}%</span>
          </div>`).join("");
    document.getElementById("bi-top-increases").innerHTML = mk(wt.top_increases, true);
    document.getElementById("bi-top-drops").innerHTML = mk(wt.top_drops, false);
  }

  function renderCazabobos(rows) {
    const tbody = document.querySelector("#table-cazabobos tbody");
    if (!rows.length) {
      tbody.innerHTML = `<tr><td colspan="6" class="muted">Sin falsos descuentos detectados en el snapshot actual.</td></tr>`;
      return;
    }
    tbody.innerHTML = rows.map((r) => `
      <tr>
        <td><strong>${esc(r.product_name)}</strong></td>
        <td><span class="store-tag ${storeInfo(r.promo_store).cls}">${esc(storeInfo(r.promo_store).label)}</span> <span class="small muted">(-${r.advertised_discount_pct}%)</span></td>
        <td class="num">${fmtARS(r.promo_price)}</td>
        <td><span class="store-tag ${storeInfo(r.rival_store).cls}">${esc(storeInfo(r.rival_store).label)}</span></td>
        <td class="num"><strong>${fmtARS(r.rival_price)}</strong></td>
        <td class="num"><span class="pill pill-danger">+${r.overprice_vs_rival_pct}%</span></td>
      </tr>`).join("");
  }

  function renderStockup(deals) {
    const el = document.getElementById("bi-stockup-grid");
    if (!deals.length) { el.innerHTML = `<p class="muted small">Sin oportunidades ≥15% en este snapshot.</p>`; return; }
    el.innerHTML = deals.slice(0, 12).map((d) => `
      <div class="stockup-card">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <span class="store-tag ${storeInfo(d.store).cls}">${esc(storeInfo(d.store).label)}</span>
          <span class="pill pill-success">-${d.discount_pct}%</span>
        </div>
        <strong>${esc(d.name)}</strong>
        <div style="display:flex;justify-content:space-between;align-items:baseline">
          <span style="font-weight:800;font-size:1.08rem">${fmtARS(d.price)}</span>
          <span class="small muted">${d.list_price ? `<s>${fmtARS(d.list_price)}</s>` : ""}</span>
        </div>
        ${d.product_url ? `<a class="small" href="${esc(d.product_url)}" target="_blank" rel="noopener">Ver en tienda ↗</a>` : ""}
      </div>`).join("");
  }

  function renderQuality(qual) {
    const funnel = document.getElementById("quality-funnel");
    const tbody = document.querySelector("#table-quality-stores tbody");
    if (!qual) { funnel.innerHTML = ""; tbody.innerHTML = ""; return; }
    const f = qual.funnel || {};
    const drops = Object.values(f.silver_cleaning_drops || {}).reduce((a, b) => a + Number(b || 0), 0);

    funnel.innerHTML = `
      <div class="funnel-step"><div class="step-lbl">1. Bronze Ingresados</div><div class="step-num">${(f.bronze_rows || 0).toLocaleString("es-AR")}</div></div>
      <div class="funnel-step"><div class="step-lbl">2. Descartes Técnicos</div><div class="step-num">${drops.toLocaleString("es-AR")}</div></div>
      <div class="funnel-step"><div class="step-lbl">3. Silver Activos</div><div class="step-num">${(f.active_silver_rows || 0).toLocaleString("es-AR")}</div></div>
      <div class="funnel-step"><div class="step-lbl">4. Gold EANs Comparables</div><div class="step-num">${(f.gold_cross_store_eans || 0).toLocaleString("es-AR")}</div></div>`;

    tbody.innerHTML = (qual.stores || []).map((s) => {
      const info = storeInfo(s.store_key);
      const fresh = s.freshness_status === "fresh";
      return `
        <tr>
          <td><span class="store-tag ${info.cls}">${esc(info.label)}</span></td>
          <td>${esc(String(s.status || "-").toUpperCase())}</td>
          <td><span class="pill ${fresh ? "pill-success" : "pill-warning"}">${fresh ? "Actualizado hoy" : `Carry-forward (-${s.age_days || 1}d)`}</span></td>
          <td class="num">${esc(s.last_dt || "-")}</td>
          <td class="num">${Number(s.active_products || 0).toLocaleString("es-AR")}</td>
          <td class="num">${s.success_rate_pct !== null && s.success_rate_pct !== undefined ? `${s.success_rate_pct}%` : "-"}</td>
          <td class="num">${s.avg_latency_ms ? `${s.avg_latency_ms} ms` : "-"}</td>
        </tr>`;
    }).join("");
  }

  // ── Service Worker & Bootstrap ─────────────────────────────
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => navigator.serviceWorker.register("./sw.js").catch(() => {}));
  }

  document.addEventListener("DOMContentLoaded", () => {
    initTheme();
    initNavigation();
    initStorefrontEvents();
    initDrawerControls();
    initCartEvents();
    initPromoEvents();
    loadAllData();
  });
})();
