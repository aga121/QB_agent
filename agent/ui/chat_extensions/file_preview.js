(function () {
  if (window.ChatFilePreviewInitialized) {
    return;
  }
  window.ChatFilePreviewInitialized = true;

  var config = window.ChatExtensionConfig || {};
  if (!config.extensions_enabled) {
    return;
  }

  var PREVIEW_MARKER = "preview-file:";
  var IMAGE_EXTS = { ".png": true, ".jpg": true, ".jpeg": true, ".svg": true };
  var HTML_EXTS = { ".html": true, ".htm": true };

  function getSessionId() {
    var container = document.getElementById("chatMessages");
    return container && container.dataset ? container.dataset.sessionId : null;
  }

  function getToken() {
    try {
      return localStorage.getItem("token");
    } catch (e) {
      return null;
    }
  }

  function getExtension(path) {
    if (!path) return "";
    var idx = path.lastIndexOf(".");
    return idx >= 0 ? path.slice(idx).toLowerCase() : "";
  }

  function encodePath(path) {
    var clean = (path || "").replace(/^\/+/, "");
    return clean
      .split("/")
      .map(function (part) {
        return encodeURIComponent(part);
      })
      .join("/");
  }

  function getPublicBaseUrl() {
    var base = (config.public_base_url || window.location.origin || "").trim();
    return base ? base.replace(/\/+$/, "") : "";
  }

  function buildPreviewUrl(payload) {
    var path = payload.path || "";
    var agentId = payload.agent_id || payload.agentId || "";
    var filename = payload.name || payload.filename || (path.split("/").pop() || "");
    if (!path) return null;

    if (!agentId || !filename) return null;
    return getPublicBaseUrl() + "/html-page/" + encodeURIComponent(agentId) + "/" + encodePath(path);
  }

  function buildCard(path, url, isHtml) {
    var card = document.createElement("div");
    card.className = "chat-file-preview-card";

    var header = document.createElement("div");
    header.className = "chat-file-preview-header";

    var name = document.createElement("div");
    name.className = "chat-file-preview-name";
    name.textContent = path;

    var link = document.createElement("a");
    link.className = "chat-file-preview-link";
    link.textContent = "打开";
    link.target = "_blank";
    link.rel = "noopener";
    link.href = url || "#";

    header.appendChild(name);
    header.appendChild(link);

    var body = document.createElement("div");
    body.className = "chat-file-preview-body";

    if (url) {
      if (isHtml) {
        var frame = document.createElement("iframe");
        frame.src = url;
        frame.loading = "lazy";
        frame.title = path;
        frame.dataset.previewPath = path;
        body.appendChild(frame);
      } else {
        var img = document.createElement("img");
        img.src = url;
        img.alt = path;
        img.loading = "lazy";
        body.appendChild(img);
      }
    } else {
      var tip = document.createElement("div");
      tip.className = "chat-file-preview-empty";
      tip.textContent = "无法预览（登录信息缺失）";
      body.appendChild(tip);
    }

    card.appendChild(header);
    card.appendChild(body);
    return card;
  }

  function applyPreview(messageDiv, role) {
    if (!messageDiv || role !== "assistant") {
      return;
    }
    if (messageDiv.dataset.chatPreviewApplied === "1") {
      return;
    }
    messageDiv.dataset.chatPreviewApplied = "1";

    var contentBlock = messageDiv.querySelector(".message-content");
    if (!contentBlock) {
      return;
    }

    var sessionId = getSessionId();
    if (!sessionId) {
      return;
    }
    var walker = document.createTreeWalker(contentBlock, NodeFilter.SHOW_COMMENT, null);
    var markers = [];
    while (walker.nextNode()) {
      var node = walker.currentNode;
      if (node && typeof node.nodeValue === "string" && node.nodeValue.indexOf(PREVIEW_MARKER) === 0) {
        markers.push(node);
      }
    }

    if (!markers.length) {
      return;
    }

    markers.forEach(function (node) {
      var raw = node.nodeValue || "";
      var payloadText = raw.slice(PREVIEW_MARKER.length).trim();
      if (!payloadText) {
        return;
      }
      var payload = null;
      try {
        payload = JSON.parse(payloadText);
      } catch (e) {
        payload = { path: payloadText };
      }
      var path = payload.path || "";
      contentBlock.classList.add("chat-file-preview-host");
      if (messageDiv && messageDiv.classList) {
        messageDiv.classList.add("chat-preview-wide");
      }
      var ext = getExtension(path);
      var url = buildPreviewUrl(payload);
      var card = buildCard(path, url, !!HTML_EXTS[ext]);
      contentBlock.appendChild(card);
    });
  }

  function scanExisting() {
    var messages = document.querySelectorAll("#chatMessages .message.assistant");
    messages.forEach(function (messageDiv) {
      applyPreview(messageDiv, "assistant");
    });
  }

  function observeMessages() {
    var container = document.getElementById("chatMessages");
    if (!container || window.ChatPreviewObserver) {
      return;
    }
    var observer = new MutationObserver(function (mutations) {
      mutations.forEach(function (mutation) {
        mutation.addedNodes.forEach(function (node) {
          if (!node || node.nodeType !== 1) {
            return;
          }
          if (node.classList && node.classList.contains("message") && node.classList.contains("assistant")) {
            applyPreview(node, "assistant");
            return;
          }
          if (node.querySelectorAll) {
            var assistants = node.querySelectorAll(".message.assistant");
            assistants.forEach(function (messageDiv) {
              applyPreview(messageDiv, "assistant");
            });
          }
        });
      });
    });
    observer.observe(container, { childList: true, subtree: true });
    window.ChatPreviewObserver = observer;
  }

  var previousApply = window.ChatExtensionApply;
  window.ChatExtensionApply = function (messageDiv, role, content) {
    if (typeof previousApply === "function") {
      previousApply(messageDiv, role, content);
    }
    applyPreview(messageDiv, role, content);
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

  window.addEventListener("message", function (event) {
    var data = event && event.data;
    if (!data || data.type !== "previewHeight") {
      return;
    }
    var path = data.path;
    var height = parseInt(data.height, 10);
    if (!path || !height || height <= 0) {
      return;
    }
    var maxHeight = 900;
    var minHeight = 240;
    var nextHeight = Math.max(minHeight, Math.min(height, maxHeight));
    var frames = document.querySelectorAll('.chat-file-preview-body iframe[data-preview-path]');
    frames.forEach(function (frame) {
      if (frame.dataset.previewPath === path) {
        frame.style.height = nextHeight + "px";
      }
    });
  });
})();
