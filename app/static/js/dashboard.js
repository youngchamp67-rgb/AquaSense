(() => {
  "use strict";

  const root = document.querySelector("[data-dashboard]");
  if (!root) {
    return;
  }

  const REQUEST_TIMEOUT_MS = 8000;
  const SENSOR_KEYS = ["ph", "tds_ppm", "temperature_c"];
  const KNOWN_RECEIVER_STATES = new Set([
    "NOT_CONNECTED",
    "WAITING_FOR_DATA",
    "CONNECTED",
  ]);

  const configuredInterval = Number.parseInt(root.dataset.pollInterval || "30", 10);
  const pollIntervalMs =
    Number.isFinite(configuredInterval) && configuredInterval >= 10
      ? configuredInterval * 1000
      : 30000;

  const els = {
    refresh: root.querySelector("[data-refresh]"),
    refreshLabel: root.querySelector("[data-refresh-label]"),
    lastUpdated: root.querySelector("[data-last-updated]"),
    lastReceived: root.querySelector("[data-last-received]"),
    errorBanner: root.querySelector("[data-error-banner]"),
    errorMessage: root.querySelector("[data-error-message]"),
    retry: root.querySelector("[data-retry]"),
    receiverPills: root.querySelectorAll("[data-receiver-status]"),
    transport: root.querySelector("[data-transport-state]"),
    lastContact: root.querySelector("[data-last-contact]"),
    apiStatus: root.querySelector("[data-api-status]"),
    apiDot: root.querySelector("[data-api-dot]"),
    liveStatus: root.querySelector("[data-status-live]"),
    readingsBody: root.querySelector("[data-readings-body]"),
    readingsCount: root.querySelector("[data-readings-count]"),
  };

  const sensors = {
    ph: readSensor("ph"),
    tds_ppm: readSensor("tds_ppm"),
    temperature_c: readSensor("temperature_c"),
  };

  const emptyReadingsRow =
    els.readingsBody
      ?.querySelector("[data-empty-readings]")
      ?.cloneNode(true) ?? null;

  const view = {
    hasReading: false,
  };

  let activeRequest = null;

  const numberFormatters = {
    ph: new Intl.NumberFormat(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }),
    tds_ppm: new Intl.NumberFormat(undefined, {
      maximumFractionDigits: 0,
    }),
    temperature_c: new Intl.NumberFormat(undefined, {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    }),
  };

  const timestampFormatter = new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  });

  function readSensor(key) {
    const card = root.querySelector(`[data-sensor-card="${key}"]`);
    if (!card) {
      return null;
    }

    return {
      card,
      value: card.querySelector("[data-sensor-value]"),
      state: card.querySelector("[data-sensor-state]"),
      empty: card.querySelector("[data-sensor-empty]"),
    };
  }

  function formatReadingValue(key, value) {
    return numberFormatters[key].format(value);
  }

  function formatTimestamp(value) {
    if (typeof value !== "string" || value.length === 0) {
      return null;
    }

    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return null;
    }

    return timestampFormatter.format(date);
  }

  function receiverLabel(status) {
    return status.replaceAll("_", " ");
  }

  function setReceiverStatus(status, label) {
    const known = KNOWN_RECEIVER_STATES.has(status);
    const resolvedStatus = known ? status : "UNKNOWN";
    const resolvedLabel =
      typeof label === "string" && label.length > 0
        ? label
        : known
          ? receiverLabel(status)
          : "STATUS UNKNOWN";

    els.receiverPills.forEach((pill) => {
      pill.dataset.status = resolvedStatus;
      pill.textContent = resolvedLabel;
    });
  }

  function setLoading(isLoading) {
    if (els.refresh) {
      els.refresh.disabled = isLoading;
      els.refresh.classList.toggle("is-loading", isLoading);
    }

    if (els.refreshLabel) {
      els.refreshLabel.textContent = isLoading ? "Refreshing…" : "Refresh";
    }

    root.setAttribute("aria-busy", isLoading ? "true" : "false");

    if (isLoading && !view.hasReading) {
      els.lastUpdated.textContent = "Checking…";
      els.lastReceived.textContent = "Contacting dashboard API";
    }
  }

  function announce(message) {
    if (els.liveStatus) {
      els.liveStatus.textContent = message;
    }
  }

  function hideError() {
    els.errorBanner.hidden = true;
    els.apiDot.classList.remove("is-error");
  }

  function showError(message) {
    els.errorMessage.textContent = message;
    els.errorBanner.hidden = false;
    els.apiStatus.textContent = "Unavailable";
    els.apiDot.classList.add("is-error");
    els.apiDot.classList.remove("is-online");
    announce(message);

    // If no reading has ever loaded, make the empty cards explicit about the
    // failure instead of leaving them looking merely unpopulated.
    if (!view.hasReading) {
      renderNoReading();
      els.lastUpdated.textContent = "Unavailable";
      els.lastReceived.textContent = "Check server connection";

      SENSOR_KEYS.forEach((key) => {
        const sensor = sensors[key];
        if (!sensor) {
          return;
        }
        sensor.state.textContent = "Unavailable";
        sensor.state.classList.add("is-error");
        sensor.empty.textContent = "Could not load reading";
      });

      setReceiverStatus("UNKNOWN", "STATUS UNKNOWN");
    }
  }

  function applyHealth(data) {
    const source =
      data && typeof data.data_source === "object" && data.data_source !== null
        ? data.data_source
        : {};

    els.transport.textContent = source.configured ? "Configured" : "Not configured";
    els.apiStatus.textContent = "Online";
    els.apiDot.classList.add("is-online");
    els.apiDot.classList.remove("is-error");

    if (
      source.receiver_status === "NOT_CONNECTED" ||
      source.receiver_status === "WAITING_FOR_DATA"
    ) {
      setReceiverStatus(
        source.receiver_status,
        receiverLabel(source.receiver_status),
      );
    }
  }

  /**
   * Render the latest reading. Returns false when `available` is true but the
   * payload is incomplete, so the dashboard can show an error instead of
   * filling missing values with estimates.
   */
  function applyReadings(data) {
    if (!data || typeof data !== "object") {
      return false;
    }

    const receiver =
      typeof data.receiver === "object" && data.receiver !== null
        ? data.receiver
        : {};

    if (typeof receiver.status === "string") {
      setReceiverStatus(receiver.status, receiver.label);
    }

    if (data.available !== true) {
      renderNoReading();
      return true;
    }

    const reading =
      typeof data.readings === "object" && data.readings !== null
        ? data.readings
        : {};

    const complete = SENSOR_KEYS.every(
      (key) => typeof reading[key] === "number" && Number.isFinite(reading[key]),
    );

    if (!complete) {
      return false;
    }

    view.hasReading = true;

    SENSOR_KEYS.forEach((key) => {
      const sensor = sensors[key];
      if (!sensor) {
        return;
      }

      sensor.value.textContent = formatReadingValue(key, reading[key]);
      sensor.value.classList.remove("is-empty");
      sensor.state.textContent = "Received";
      sensor.state.classList.remove("is-error");
      sensor.state.classList.add("is-received");
      sensor.empty.textContent = "Latest received value";
    });

    const recordedLabel = formatTimestamp(data.recorded_at);
    const receivedLabel = formatTimestamp(data.received_at);

    els.lastUpdated.textContent = recordedLabel || "Time unavailable";
    if (typeof data.recorded_at === "string") {
      els.lastUpdated.title = data.recorded_at;
    } else {
      els.lastUpdated.removeAttribute("title");
    }

    els.lastReceived.textContent = receivedLabel
      ? `Received ${receivedLabel}`
      : "Receive time unavailable";

    els.lastContact.textContent =
      receivedLabel || recordedLabel || "Time unavailable";
    els.readingsCount.textContent = "1 reading";

    renderReadingRow(reading, recordedLabel);
    return true;
  }

  function renderNoReading() {
    view.hasReading = false;

    SENSOR_KEYS.forEach((key) => {
      const sensor = sensors[key];
      if (!sensor) {
        return;
      }

      sensor.value.textContent = "—";
      sensor.value.classList.add("is-empty");
      sensor.state.textContent = "No data";
      sensor.state.classList.remove("is-received", "is-error");
      sensor.empty.textContent = "No reading received";
      sensor.card.classList.remove("is-loading");
    });

    els.lastUpdated.textContent = "No data received";
    els.lastUpdated.removeAttribute("title");
    els.lastReceived.textContent = "Awaiting receiver";
    els.lastContact.textContent = "—";
    els.readingsCount.textContent = "0 readings";
    resetReadings();
  }

  function renderReadingRow(reading, recordedLabel) {
    if (!els.readingsBody) {
      return;
    }

    const row = document.createElement("tr");
    const cells = [
      { text: recordedLabel || "Time unavailable" },
      { text: formatReadingValue("ph", reading.ph), className: "numeric" },
      { text: formatReadingValue("tds_ppm", reading.tds_ppm), className: "numeric" },
      {
        text: formatReadingValue("temperature_c", reading.temperature_c),
        className: "numeric",
      },
      { text: "Received", className: "reading-status" },
    ];

    cells.forEach(({ text, className }) => {
      const cell = document.createElement("td");
      if (className) {
        cell.className = className;
      }
      cell.textContent = text;
      row.append(cell);
    });

    els.readingsBody.replaceChildren(row);
  }

  function resetReadings() {
    if (!els.readingsBody) {
      return;
    }

    if (emptyReadingsRow) {
      els.readingsBody.replaceChildren(emptyReadingsRow.cloneNode(true));
    } else {
      els.readingsBody.replaceChildren();
    }
  }

  async function fetchJson(url, signal) {
    const response = await fetch(url, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal,
    });

    let payload;
    try {
      payload = await response.json();
    } catch {
      throw new Error("The API returned an unreadable response.");
    }

    if (!response.ok || !payload || payload.ok !== true) {
      const message =
        payload && payload.error && typeof payload.error.message === "string"
          ? payload.error.message
          : `The API request failed (HTTP ${response.status}).`;
      throw new Error(message);
    }

    return payload.data;
  }

  async function loadDashboard({ announceUpdate = false, silent = false } = {}) {
    if (activeRequest) {
      activeRequest.abort();
    }

    const controller = new AbortController();
    activeRequest = controller;
    const timeoutId = window.setTimeout(
      () => controller.abort(),
      REQUEST_TIMEOUT_MS,
    );

    if (!silent) {
      setLoading(true);
    }

    try {
      const results = await Promise.allSettled([
        fetchJson("/api/health", controller.signal),
        fetchJson("/api/readings/latest", controller.signal),
      ]);

      // A newer refresh superseded this request; let that one own the UI.
      if (activeRequest !== controller) {
        return;
      }

      if (controller.signal.aborted) {
        showError(
          `The dashboard API did not respond within ${REQUEST_TIMEOUT_MS / 1000} seconds.`,
        );
        return;
      }

      const [healthResult, readingsResult] = results;
      let failureMessage = null;

      if (healthResult.status === "fulfilled") {
        applyHealth(healthResult.value);
      } else {
        failureMessage =
          "The dashboard API could not be reached. Check that the Flask server is running.";
      }

      if (readingsResult.status === "fulfilled") {
        const applied = applyReadings(readingsResult.value);
        if (!applied) {
          failureMessage =
            "The receiver returned an incomplete reading. Values were not displayed rather than estimated.";
        }
      } else {
        failureMessage =
          failureMessage ||
          "The latest reading could not be fetched from the dashboard API.";
      }

      if (failureMessage) {
        showError(failureMessage);
      } else {
        hideError();
        if (announceUpdate) {
          announce("Dashboard data refreshed.");
        }
      }
    } finally {
      window.clearTimeout(timeoutId);

      if (activeRequest === controller) {
        activeRequest = null;
        // Reset even for a silent poll: it may have superseded an interactive
        // request, and leaving the refresh button disabled would be wrong.
        setLoading(false);
      }
    }
  }

  if (els.refresh) {
    els.refresh.addEventListener("click", () => {
      loadDashboard({ announceUpdate: true });
    });
  }

  if (els.retry) {
    els.retry.addEventListener("click", () => {
      loadDashboard({ announceUpdate: true });
    });
  }

  window.addEventListener("offline", () => {
    showError("Your browser is offline. Reconnect to reach the local dashboard API.");
  });

  window.addEventListener("online", () => {
    loadDashboard({ announceUpdate: true });
  });

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      loadDashboard({ silent: true });
    }
  });

  window.setInterval(() => {
    if (document.visibilityState === "visible" && navigator.onLine !== false) {
      loadDashboard({ silent: true });
    }
  }, pollIntervalMs);

  // Initial hydration. The server-rendered page already shows the honest
  // empty state; this confirms it against the API and wires up live polling.
  loadDashboard();
})();
