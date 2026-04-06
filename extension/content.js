const FALLBACK_POLL_MS = 3000;
const MUTATION_DEBOUNCE_MS = 150;

let lastTicker = null;
let tickTimer = null;

const EXCHANGE_PREFIXES = new Set([
  "NASDAQ",
  "NYSE",
  "AMEX",
  "ARCA",
  "BATS",
  "CBOE",
  "OTC",
  "TVC",
  "INDEX",
  "SP",
  "DJ",
  "FOREX",
  "BINANCE",
  "CRYPTO"
]);

const US_EQUITY_EXCHANGES = new Set(["NASDAQ", "NYSE", "AMEX", "ARCA", "BATS", "CBOE", "OTC"]);

const IGNORE_SYMBOLS = new Set(["SP500", "NASDAQ100", "DJI", "US2000", "VIX", "DXY",
  "SPX"]);

function sanitizeTickerValue(raw) {
  if (!raw || typeof raw !== "string") {
    return null;
  }

  let value = raw.trim().toUpperCase().replace(/\s+/g, "");
  if (!value) {
    return null;
  }

  value = value.replace(/[^A-Z0-9.\-]/g, "");
  if (!/^[A-Z][A-Z0-9.\-]{0,14}$/.test(value)) {
    return null;
  }
  if (EXCHANGE_PREFIXES.has(value) || IGNORE_SYMBOLS.has(value)) {
    return null;
  }
  return value;
}

function extractQualifiedUsTicker(raw) {
  if (!raw || typeof raw !== "string") {
    return null;
  }

  const normalized = raw.trim().toUpperCase().replace(/\s+/g, "");
  const match = normalized.match(/\b([A-Z]{2,12})[:\-]([A-Z0-9][A-Z0-9.\-]{0,14})\b/);
  if (!match) {
    return null;
  }

  const exchange = match[1];
  const ticker = sanitizeTickerValue(match[2]);
  if (!ticker || !US_EQUITY_EXCHANGES.has(exchange)) {
    return null;
  }
  return ticker;
}

function extractTickerFromSymbolField(raw) {
  return extractQualifiedUsTicker(raw) || sanitizeTickerValue(raw);
}

function tickerFromUrl() {
  let url;
  try {
    url = new URL(window.location.href);
  } catch (_err) {
    return null;
  }

  for (const key of ["symbol", "ticker"]) {
    const queryValue = url.searchParams.get(key);
    if (queryValue) {
      const queryTicker = extractTickerFromSymbolField(decodeURIComponent(queryValue));
      if (queryTicker) {
        return queryTicker;
      }
    }
  }

  const hash = (url.hash.startsWith("#") ? url.hash.slice(1) : url.hash).replace(/^\?/, "");
  const hashParams = new URLSearchParams(hash);
  for (const key of ["symbol", "ticker"]) {
    const hashValue = hashParams.get(key);
    if (hashValue) {
      const hashTicker = extractTickerFromSymbolField(decodeURIComponent(hashValue));
      if (hashTicker) {
        return hashTicker;
      }
    }
  }

  const symbolPathMatch = url.pathname.match(/\/symbols\/([A-Za-z0-9.\-]+)-([A-Za-z0-9.\-]+)\/?/);
  if (!symbolPathMatch) {
    return null;
  }

  const exchange = symbolPathMatch[1].toUpperCase();
  if (!US_EQUITY_EXCHANGES.has(exchange)) {
    return null;
  }
  return sanitizeTickerValue(symbolPathMatch[2]);
}

function tickerFromTitle() {
  const title = (document.title || "").trim();
  if (!title) {
    return null;
  }

  const qualified = extractQualifiedUsTicker(title);
  if (qualified) {
    return qualified;
  }

  const firstWord = title.split(/\s+/)[0] || "";
  if (!/^[A-Z0-9.\-:]{1,20}$/.test(firstWord)) {
    return null;
  }
  return extractTickerFromSymbolField(firstWord);
}

function tickerFromDom() {
  const selectorList = [
    '[data-name="legend-source-item"]',
    '[data-name="header-toolbar-symbol-search"]',
    '[data-name="symbol-edit-button"]'
  ];

  for (const selector of selectorList) {
    const nodes = document.querySelectorAll(selector);
    for (const node of nodes) {
      const attributeCandidates = [
        node.getAttribute("data-symbol-short"),
        node.getAttribute("data-symbol-full"),
        node.getAttribute("data-symbol"),
        node.getAttribute("data-ticker")
      ];

      const symbolChildren = node.querySelectorAll("[data-symbol-short], [data-symbol-full], [data-symbol], [data-ticker]");
      for (const child of symbolChildren) {
        attributeCandidates.push(
          child.getAttribute("data-symbol-short"),
          child.getAttribute("data-symbol-full"),
          child.getAttribute("data-symbol"),
          child.getAttribute("data-ticker")
        );
      }

      for (const candidate of attributeCandidates) {
        const ticker = extractTickerFromSymbolField(candidate || "");
        if (ticker) {
          return ticker;
        }
      }

      const links = node.querySelectorAll('a[href*="/symbols/"]');
      for (const link of links) {
        const href = link.getAttribute("href") || "";
        const hrefMatch = href.match(/\/symbols\/([A-Za-z0-9.\-]+-[A-Za-z0-9.\-]+)\/?/);
        if (!hrefMatch) {
          continue;
        }
        const linkTicker = extractTickerFromSymbolField(hrefMatch[1]);
        if (linkTicker) {
          return linkTicker;
        }
      }

      const textTicker = extractQualifiedUsTicker(node.textContent || "");
      if (textTicker) {
        return textTicker;
      }
    }
  }
  return null;
}

function detectTicker() {
  return tickerFromTitle() || tickerFromUrl() || tickerFromDom();
}

function pushTicker(ticker) {
  try {
    chrome.runtime.sendMessage({ type: "ticker", ticker });
  } catch (_err) {
    // Ignore transient extension runtime failures.
  }
}

async function tick() {
  if (document.visibilityState !== "visible") {
    return;
  }
  const ticker = detectTicker();
  if (!ticker || ticker === lastTicker) {
    return;
  }
  lastTicker = ticker;
  pushTicker(ticker);
}

function scheduleTick(delay = 0) {
  if (tickTimer !== null) {
    clearTimeout(tickTimer);
  }
  tickTimer = window.setTimeout(() => {
    tickTimer = null;
    void tick();
  }, delay);
}

function startObservers() {
  const observer = new MutationObserver(() => {
    scheduleTick(MUTATION_DEBOUNCE_MS);
  });

  if (document.documentElement) {
    observer.observe(document.documentElement, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["data-symbol-short", "data-symbol-full", "data-symbol", "data-ticker", "href"]
    });
  }

  window.addEventListener("hashchange", () => scheduleTick(0));
  window.addEventListener("popstate", () => scheduleTick(0));
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") {
      scheduleTick(0);
    }
  });

  scheduleTick(0);
  window.setInterval(() => {
    if (document.visibilityState === "visible") {
      void tick();
    }
  }, FALLBACK_POLL_MS);
}

startObservers();




