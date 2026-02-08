(function () {
  if (window.ChatExtensionInitialized) {
    return;
  }
  window.ChatExtensionInitialized = true;

  var config = window.ChatExtensionConfig || {};
  if (!config.extensions_enabled) {
    return;
  }

  var templateHtml = null;
  var templateUrl = "/static/chat_extensions/filter.html";
  function escapeRegExp(value) {
    return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function getPublicBaseUrl() {
    var base = (config.public_base_url || window.location.origin || "").trim();
    return base ? base.replace(/\/+$/, "") : "";
  }

  var basePattern = escapeRegExp(getPublicBaseUrl());
  var servicePattern = new RegExp("^" + basePattern + "/agent/[^\\s]+-\\d+(?:/.*)?$", "i");
  var htmlPattern = new RegExp("^" + basePattern + "/html-page/[^\\s/]+/[^\\s]+\\.html(?:\\?.*)?$", "i");
  function fetchTemplate() {
    return fetch(templateUrl)
      .then(function (resp) {
        if (!resp.ok) {
          throw new Error("template load failed");
        }
        return resp.text();
      })
      .then(function (text) {
        templateHtml = text;
      })
      .catch(function () {
        templateHtml = null;
      });
  }

  function ensureTemplate() {
    if (templateHtml) {
      return Promise.resolve();
    }
    return fetchTemplate();
  }

  function findCandidateUrls(container, rawText) {
    var urls = [];
    var anchors = container.querySelectorAll("a[href]");
    anchors.forEach(function (anchor) {
      var href = anchor.getAttribute("href");
      if (!href) {
        return;
      }
      if (servicePattern.test(href) || htmlPattern.test(href)) {
        urls.push(href);
      }
    });
    if (urls.length) {
      return urls;
    }
    if (!rawText) {
      return urls;
    }
    var match;
    var combined = rawText.split(/\s+/);
    for (var i = 0; i < combined.length; i += 1) {
      match = combined[i].trim();
      if (servicePattern.test(match) || htmlPattern.test(match)) {
        urls.push(match);
      }
    }
    return urls;
  }

  function buildCard() {
    if (templateHtml) {
      var wrapper = document.createElement("div");
      wrapper.innerHTML = templateHtml.trim();
      return wrapper.firstElementChild;
    }
    var card = document.createElement("div");
    card.className = "chat-qr-card";
    var text = document.createElement("div");
    text.className = "chat-qr-text";
    text.textContent = "用手机扫一下可直接访问";
    var code = document.createElement("div");
    code.className = "chat-qr-code";
    card.appendChild(text);
    card.appendChild(code);
    return card;
  }

  function renderQr(target, url) {
    if (!window.QRCode) {
      target.dataset.qrUrl = url;
      if (!target.dataset.qrWaiting) {
        target.dataset.qrWaiting = "1";
        var onReady = function () {
          window.removeEventListener("chat-qr-ready", onReady);
          var nextUrl = target.dataset.qrUrl;
          if (nextUrl && window.QRCode) {
            renderQr(target, nextUrl);
          }
        };
        window.addEventListener("chat-qr-ready", onReady);
      }
      return;
    }
    target.innerHTML = "";
    new window.QRCode(target, {
      text: url,
      width: 160,
      height: 160,
      colorDark: "#111827",
      colorLight: "#ffffff",
      correctLevel: window.QRCode.CorrectLevel ? window.QRCode.CorrectLevel.M : 2
    });
  }

  function applyExtension(messageDiv, role, content) {
    if (!messageDiv) {
      return;
    }
    if (role !== "assistant") {
      return;
    }
    if (messageDiv.dataset.chatExtApplied === "1") {
      return;
    }
    messageDiv.dataset.chatExtApplied = "1";
    var contentBlock = messageDiv.querySelector(".message-content");
    if (!contentBlock) {
      return;
    }
    var urls = findCandidateUrls(contentBlock, content || "");
    if (urls.length) {
      var url = urls[0];
      var textValue = (contentBlock.textContent || "").trim();
      if (textValue.indexOf("新增可预览文件") >= 0) {
        return;
      }
      ensureTemplate().then(function () {
        var card = buildCard();
        var code = card.querySelector(".chat-qr-code");
        if (code) {
          renderQr(code, url);
        }
        contentBlock.appendChild(card);
      });
    }
  }

  function scanExisting() {
    var messages = document.querySelectorAll("#chatMessages .message.assistant");
    messages.forEach(function (messageDiv) {
      applyExtension(messageDiv, "assistant", messageDiv.innerText || "");
    });
  }

  function observeMessages() {
    var container = document.getElementById("chatMessages");
    if (!container || window.ChatQrObserver) {
      return;
    }
    var observer = new MutationObserver(function (mutations) {
      mutations.forEach(function (mutation) {
        mutation.addedNodes.forEach(function (node) {
          if (!node || node.nodeType !== 1) {
            return;
          }
          if (node.classList && node.classList.contains("message") && node.classList.contains("assistant")) {
            applyExtension(node, "assistant", node.innerText || "");
            return;
          }
          if (node.querySelectorAll) {
            var assistants = node.querySelectorAll(".message.assistant");
            assistants.forEach(function (messageDiv) {
              applyExtension(messageDiv, "assistant", messageDiv.innerText || "");
            });
          }
        });
      });
    });
    observer.observe(container, { childList: true, subtree: true });
    window.ChatQrObserver = observer;
  }

  var previousApply = window.ChatExtensionApply;
  window.ChatExtensionApply = function (messageDiv, role, content) {
    if (typeof previousApply === "function") {
      previousApply(messageDiv, role, content);
    }
    applyExtension(messageDiv, role, content);
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      scanExisting();
      observeMessages();
    });
  } else {
    scanExisting();
    observeMessages();
  }
})();
