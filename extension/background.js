const HOST_NAME = "com.tradingsector.bridge";

function isTrustedTradingViewUrl(rawUrl) {
  try {
    const url = new URL(rawUrl);
    return (
      (url.protocol === "http:" || url.protocol === "https:") &&
      (url.hostname === "tradingview.com" || url.hostname.endsWith(".tradingview.com"))
    );
  } catch (_err) {
    return false;
  }
}

function postTicker(ticker) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendNativeMessage(HOST_NAME, { type: "ticker", ticker }, (response) => {
      const runtimeError = chrome.runtime.lastError;
      if (runtimeError) {
        reject(new Error(runtimeError.message));
        return;
      }
      if (!response || !response.ok) {
        reject(new Error(response && response.error ? response.error : "Native host rejected ticker"));
        return;
      }
      resolve(response);
    });
  });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.type !== "ticker" || !message.ticker || typeof message.ticker !== "string") {
    return false;
  }

  if (!sender || !sender.url || !isTrustedTradingViewUrl(sender.url)) {
    sendResponse({ ok: false, ignored: true });
    return false;
  }

  postTicker(message.ticker)
    .then((response) => {
      sendResponse({ ok: true, ticker: response.ticker });
    })
    .catch((err) => {
      console.warn("Native host error:", err);
      sendResponse({ ok: false, error: err.message });
    });

  return true;
});
