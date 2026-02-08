(function () {
  if (window.ChatProgress) {
    return;
  }

  function updateProgress(progress, value) {
    if (!progress) return;
    var safeValue = Math.max(0, Math.min(100, value));
    progress.value = safeValue;
    progress.fill.style.width = safeValue + "%";
    progress.percent.textContent = safeValue + "%";
  }

  function stopProgress(progress) {
    if (!progress || !progress.timer) return;
    clearInterval(progress.timer);
    progress.timer = null;
  }

  function startProgressCycle(progress) {
    progress.startTime = Date.now();
    progress.duration = 10000 + Math.random() * 10000;
    progress.maxHold = 80 + Math.floor(Math.random() * 20);
    progress.speed = 1;
    progress.nextSpeedAt = progress.startTime;
    progress.timer = setInterval(function () {
      if (progress.completed) {
        stopProgress(progress);
        return;
      }
      var now = Date.now();
      if (now >= progress.nextSpeedAt) {
        progress.speed = 0.6 + Math.random() * 1.0;
        progress.nextSpeedAt = now + 400 + Math.random() * 500;
      }
      var elapsed = now - progress.startTime;
      var ratio = elapsed / progress.duration;
      if (ratio >= 1) {
        updateProgress(progress, progress.maxHold);
        stopProgress(progress);
        return;
      }
      var eased = ratio * ratio * (3 - 2 * ratio);
      var current = progress.value / progress.maxHold;
      var target = eased;
      if (target < current) target = current;
      var step = (target - current) * (0.25 * progress.speed);
      var nextValue = Math.floor(Math.min(target, current + step) * progress.maxHold);
      if (nextValue <= progress.value) {
        nextValue = Math.min(progress.value + 1, Math.floor(target * progress.maxHold));
      }
      updateProgress(progress, nextValue);
    }, 120);
  }

  function createProgressCard() {
    var card = document.createElement("div");
    card.className = "chat-progress-card";
    var bar = document.createElement("div");
    bar.className = "chat-progress-bar";
    var fill = document.createElement("div");
    fill.className = "chat-progress-fill";
    bar.appendChild(fill);
    var meta = document.createElement("div");
    meta.className = "chat-progress-meta";
    var percent = document.createElement("span");
    percent.className = "chat-progress-percent";
    percent.textContent = "0%";
    meta.appendChild(percent);
    card.appendChild(bar);
    card.appendChild(meta);
    return { card: card, fill: fill, percent: percent };
  }

  window.ChatProgress = {
    createProgressCard: createProgressCard,
    startProgressCycle: startProgressCycle,
    stopProgress: stopProgress,
    updateProgress: updateProgress
  };
})();
