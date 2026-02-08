(function () {
  if (window.ChatPendingResponseInitialized) {
    return;
  }
  window.ChatPendingResponseInitialized = true;

  var config = window.ChatExtensionConfig || {};
  if (!config.extensions_enabled) {
    return;
  }
  if (!window.ChatProgress) {
    return;
  }

  var pendingResponse = null;

  function removePendingResponse() {
    if (pendingResponse && pendingResponse.parentNode) {
      pendingResponse.parentNode.removeChild(pendingResponse);
    }
    pendingResponse = null;
  }

  function buildPendingResponse() {
    var messageDiv = document.createElement("div");
    messageDiv.className = "message assistant chat-pending-response";
    var displayName = window.currentContactName || "AI";
    messageDiv.innerHTML =
      '<div class="assistant-message">' +
      '<div class="assistant-info">' +
      '<span class="assistant-name"><i class="fas fa-crown"></i>' +
      displayName +
      "</span>" +
      '<span class="assistant-status">在线</span>' +
      "</div>" +
      '<div class="message-content">正在响应中</div>' +
      "</div>";
    return messageDiv;
  }

  function updatePendingResponseText() {
    if (!pendingResponse || !document.body.contains(pendingResponse)) {
      return;
    }
    var titleEl = document.getElementById("chatTitle");
    var subtitleEl = document.getElementById("chatSubtitle");
    var titleText = titleEl ? titleEl.textContent || "" : "";
    var subtitleText = subtitleEl ? subtitleEl.textContent || "" : "";
    var pendingText = "正在响应中";
    if (titleText.indexOf("正在建立连接") !== -1 || subtitleText.indexOf("断线重连") !== -1) {
      pendingText = "已掉线，首次建立连接或断线重连可能需要几秒钟";
    }

    var contentBlock = pendingResponse.querySelector(".message-content");
    if (contentBlock) {
      var textNode = contentBlock.firstChild;
      if (textNode && textNode.nodeType === Node.TEXT_NODE) {
        textNode.textContent = pendingText;
      } else {
        contentBlock.insertBefore(document.createTextNode(pendingText), contentBlock.firstChild);
      }
    }
  }

  function ensurePendingResponse(container) {
    if (!container) {
      return;
    }
    if (pendingResponse && document.body.contains(pendingResponse)) {
      updatePendingResponseText();
      return;
    }
    pendingResponse = buildPendingResponse();
    pendingResponse.dataset.chatExtApplied = "1";
    pendingResponse.dataset.chatProgressApplied = "1";
    var contentBlock = pendingResponse.querySelector(".message-content");
    if (contentBlock) {
      var cardParts = window.ChatProgress.createProgressCard();
      contentBlock.appendChild(cardParts.card);
      var progressItem = {
        messageDiv: pendingResponse,
        fill: cardParts.fill,
        percent: cardParts.percent,
        timer: null,
        completed: false,
        value: 0
      };
      window.ChatProgress.updateProgress(progressItem, 0);
      window.ChatProgress.startProgressCycle(progressItem);
    }
    container.appendChild(pendingResponse);
    container.scrollTop = container.scrollHeight;
  }

  function applyExtension(messageDiv, role) {
    if (!messageDiv) return;
    if (role === "user") {
      var container = document.getElementById("chatMessages");
      ensurePendingResponse(container);
      return;
    }
    if (role === "assistant") {
      if (messageDiv.classList && messageDiv.classList.contains("chat-pending-response")) {
        return;
      }
      removePendingResponse();
    }
  }

  function observeMessages() {
    var container = document.getElementById("chatMessages");
    if (!container || window.ChatPendingObserver) return;
    var observer = new MutationObserver(function (mutations) {
      mutations.forEach(function (mutation) {
        mutation.addedNodes.forEach(function (node) {
          if (!node || node.nodeType !== 1) return;
          if (node.classList && node.classList.contains("message")) {
            if (node.classList.contains("assistant")) {
              applyExtension(node, "assistant");
              return;
            }
            if (node.classList.contains("user")) {
              applyExtension(node, "user");
              return;
            }
          }
        });
      });
    });
    observer.observe(container, { childList: true, subtree: true });
    window.ChatPendingObserver = observer;
  }

  var previousApply = window.ChatExtensionApply;
  window.ChatExtensionApply = function (messageDiv, role, content) {
    if (typeof previousApply === "function") {
      previousApply(messageDiv, role, content);
    }
    applyExtension(messageDiv, role, content);
  };

  window.updatePendingResponseText = updatePendingResponseText;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      observeMessages();
    });
  } else {
    observeMessages();
  }
})();
