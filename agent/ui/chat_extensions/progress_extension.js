(function () {
  if (window.ChatProgressExtensionInitialized) {
    return;
  }
  window.ChatProgressExtensionInitialized = true;

  var config = window.ChatExtensionConfig || {};
  if (!config.extensions_enabled) {
    return;
  }
  if (!window.ChatProgress) {
    return;
  }

  var progressPhrases = ["正在深度思考中", "正在拼命使用工具"]; 
  var activeProgresses = [];

  function isProgressMessage(text) {
    if (!text) return false;
    for (var i = 0; i < progressPhrases.length; i += 1) {
      if (text.indexOf(progressPhrases[i]) !== -1) {
        return true;
      }
    }
    return false;
  }

  function cleanupDetachedProgresses() {
    if (!activeProgresses.length) return;
    activeProgresses = activeProgresses.filter(function (progress) {
      if (!progress || !progress.messageDiv) return false;
      if (document.body.contains(progress.messageDiv)) return true;
      window.ChatProgress.stopProgress(progress);
      return false;
    });
  }

  function finishAllProgresses() {
    if (!activeProgresses.length) return;
    activeProgresses.forEach(function (progress) {
      if (!progress || progress.completed) return;
      progress.completed = true;
      window.ChatProgress.stopProgress(progress);
      window.ChatProgress.updateProgress(progress, 100);
    });
    activeProgresses = [];
  }

  function maybeApplyProgress(messageDiv, contentBlock, content) {
    if (!contentBlock || !messageDiv || messageDiv.dataset.chatProgressApplied === "1") {
      return;
    }
    cleanupDetachedProgresses();
    var text = content || contentBlock.innerText || "";
    if (!isProgressMessage(text)) return;
    var cardParts = window.ChatProgress.createProgressCard();
    contentBlock.appendChild(cardParts.card);
    messageDiv.dataset.chatProgressApplied = "1";
    var progressItem = {
      messageDiv: messageDiv,
      fill: cardParts.fill,
      percent: cardParts.percent,
      timer: null,
      completed: false,
      value: 0
    };
    activeProgresses.push(progressItem);
    window.ChatProgress.updateProgress(progressItem, 0);
    window.ChatProgress.startProgressCycle(progressItem);
  }

  function applyExtension(messageDiv, role, content) {
    if (!messageDiv || role !== "assistant") return;
    if (messageDiv.dataset.chatExtAppliedProgress === "1") return;
    messageDiv.dataset.chatExtAppliedProgress = "1";
    var contentBlock = messageDiv.querySelector(".message-content");
    if (!contentBlock) return;
    var rawText = content || contentBlock.innerText || "";
    if (isProgressMessage(rawText)) {
      finishAllProgresses();
      maybeApplyProgress(messageDiv, contentBlock, rawText);
    } else {
      finishAllProgresses();
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
    if (!container || window.ChatProgressObserver) return;
    var observer = new MutationObserver(function (mutations) {
      mutations.forEach(function (mutation) {
        mutation.addedNodes.forEach(function (node) {
          if (!node || node.nodeType !== 1) return;
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
    window.ChatProgressObserver = observer;
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
