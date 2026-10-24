(() => {
  "use strict";

  const root = document.querySelector("[data-dashboard]");
  if (!root) {
    return;
  }

  const REQUEST_TIMEOUT_MS = 8000;
  const HISTORY_LIMIT = 10;
  const SENSOR_KEYS = ["ph", "tds_ppm", "temperature_c"];
  const KNOWN_RECEIVER_STATES = new Set([
    "NOT_CONNECTED",
    "WAITING_FOR_DATA",
    "RECENT_DATA",
    "STALE_DATA",
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
    staleBanner: root.querySelector("[data-stale-banner]"),
    staleMessage: root.querySelector("[data-stale-message]"),
    retry: root.querySelector("[data-retry]"),
    receiverPills: root.querySelectorAll("[data-receiver-status]"),
    latestSource: root.querySelector("[data-latest-source]"),
    latestSequence: root.querySelector("[data-latest-sequence]"),
    transport: root.querySelector("[data-transport-state]"),
    lastContact: root.querySelector("[data-last-contact]"),
    apiStatus: root.querySelector("[data-api-status]"),
    apiDot: root.querySelector("[data-api-dot]"),
    liveStatus: root.querySelector("[data-status-live]"),
    readingsBody: root.querySelector("[data-readings-body]"),
    readingsCount: root.querySelector("[data-readings-count]"),
    chartArea: root.querySelector("[data-chart-area]"),
    chartEmpty: root.querySelector("[data-chart-empty]"),
    chartLanes: root.querySelector("[data-trend-lanes]"),
    chartMeta: root.querySelector("[data-chart-meta]"),
    chartNote: root.querySelector("[data-chart-note]"),
  };

  const sensors = {
    ph: readSensor("ph"),
    tds_ppm: readSensor("tds_ppm"),
    temperature_c: readSensor("temperature_c"),
  };

  const trends = {
    ph: readTrend("ph"),
    tds_ppm: readTrend("tds_ppm"),
    temperature_c: readTrend("temperature_c"),
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

  function readTrend(key) {
    const lane = root.querySelector(`[data-trend-lane="${key}"]`);
    if (!lane) {
      return null;
    }

    return {
      range: lane.querySelector("[data-trend-range]"),
      path: lane.querySelector("[data-trend-path]"),
      dot: lane.querySelector("[data-trend-dot]"),
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
   * Read one nullable measurement without treating a missing value as zero.
   * Returns `undefined` for malformed values.
   */
  function readMeasurement(reading, key) {
    if (!Object.prototype.hasOwnProperty.call(reading, key)) {
      return undefined;
    }

    const value = reading[key];
    if (value === null) {
      return null;
    }

    return typeof value === "number" && Number.isFinite(value) ? value : undefined;
  }

  /**
   * Render the latest reading. Returns false when `available` is true but the
   * payload is malformed, so the dashboard can show an error instead of
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

    const values = {};
    let hasMeasurement = false;

    for (const key of SENSOR_KEYS) {
      const value = readMeasurement(reading, key);
      if (value === undefined) {
        return false;
      }
      values[key] = value;
      if (value !== null) {
        hasMeasurement = true;
      }
    }

    if (!hasMeasurement) {
      return false;
    }

    view.hasReading = true;

    SENSOR_KEYS.forEach((key) => {
      const sensor = sensors[key];
      if (!sensor) {
        return;
      }

      const value = values[key];
      if (value === null) {
        sensor.value.textContent = "—";
        sensor.value.classList.add("is-empty");
        sensor.state.textContent = "No data";
        sensor.state.classList.remove("is-received", "is-error");
        sensor.empty.textContent = "Not included in this reading";
        sensor.card.classList.remove("is-loading");
        return;
      }

      sensor.value.textContent = formatReadingValue(key, value);
      sensor.value.classList.remove("is-empty");
      sensor.state.textContent = "Received";
      sensor.state.classList.remove("is-error");
      sensor.state.classList.add("is-received");
      sensor.empty.textContent = "Latest persisted value";
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

    els.latestSource.textContent =
      typeof data.source === "string" && data.source.length > 0
        ? data.source
        : "—";
    els.latestSequence.textContent = Number.isInteger(data.packet_sequence)
      ? String(data.packet_sequence)
      : "—";

    updateStaleState(data, receivedLabel);
    return true;
  }

  function updateStaleState(data, receivedLabel) {
    const receiver =
      typeof data.receiver === "object" && data.receiver !== null
        ? data.receiver
        : {};
    const isStale =
      data.state === "stale" || receiver.status === "STALE_DATA";

    if (!isStale) {
      els.staleBanner.hidden = true;
      els.staleMessage.textContent = "";
      return;
    }

    const detail =
      typeof data.message === "string" && data.message.length > 0
        ? data.message.replace(/^Latest reading is stale:\s*/i, "")
        : "No new reading has arrived within the freshness threshold.";
    const message = detail.charAt(0).toUpperCase() + detail.slice(1);
    els.staleMessage.textContent = receivedLabel
      ? `${message} Last received ${receivedLabel}.`
      : message;
    els.staleBanner.hidden = false;
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
    els.latestSource.textContent = "—";
    els.latestSequence.textContent = "—";
    els.staleBanner.hidden = true;
    els.staleMessage.textContent = "";
    els.readingsCount.textContent = "0 readings";
    resetReadings();
    resetTrend();
  }

  function applyHistory(data) {
    if (
      !data ||
      typeof data !== "object" ||
      !Array.isArray(data.items)
    ) {
      return false;
    }

    if (data.items.length === 0) {
      els.readingsCount.textContent = "0 readings";
      resetReadings();
      resetTrend();
      return true;
    }

    const items = [];
    for (const item of data.items) {
      if (!item || typeof item !== "object") {
        return false;
      }

      const reading =
        typeof item.readings === "object" && item.readings !== null
          ? item.readings
          : null;
      if (!reading) {
        return false;
      }

      const values = {};
      for (const key of SENSOR_KEYS) {
        const value = readMeasurement(reading, key);
        if (value === undefined) {
          return false;
        }
        values[key] = value;
      }

      const recordedMs =
        typeof item.recorded_at === "string"
          ? Date.parse(item.recorded_at)
          : Number.NaN;
      if (!Number.isFinite(recordedMs)) {
        return false;
      }

      const source =
        typeof item.source === "string" && item.source.length > 0
          ? item.source
          : "—";
      const packetSequence = Number.isInteger(item.packet_sequence)
        ? item.packet_sequence
        : null;

      items.push({
        id: Number.isInteger(item.id) ? item.id : 0,
        values,
        recordedMs,
        recordedLabel: formatTimestamp(item.recorded_at) || "Time unavailable",
        source,
        packetSequence,
      });
    }

    renderReadings(items);
    renderTrend(items);
    els.readingsCount.textContent =
      `${items.length} ${items.length === 1 ? "reading" : "readings"}`;
    return true;
  }

  function makeCell(text, className) {
    const cell = document.createElement("td");
    if (className) {
      cell.className = className;
    }
    cell.textContent = text;
    return cell;
  }

  function renderReadings(items) {
    if (!els.readingsBody) {
      return;
    }

    const fragment = document.createDocumentFragment();

    items.forEach((item) => {
      const row = document.createElement("tr");
      const recordedCell = makeCell(item.recordedLabel, "recorded-cell");
      if (item.source !== "—") {
        const inlineSource = document.createElement("span");
        inlineSource.className = "row-source-inline";
        inlineSource.textContent = item.source;
        recordedCell.append(inlineSource);
      }
      row.append(recordedCell);

      SENSOR_KEYS.forEach((key) => {
        const value = item.values[key];
        const cell = makeCell(
          value === null ? "—" : formatReadingValue(key, value),
          "numeric",
        );
        if (value === null) {
          cell.classList.add("is-empty-value");
        }
        row.append(cell);
      });

      const sourceCell = makeCell(item.source, "source-cell");
      const titleParts = [];
      if (item.source !== "—") {
        titleParts.push(item.source);
      }
      if (item.packetSequence !== null) {
        titleParts.push(`Packet sequence ${item.packetSequence}`);
      }
      if (titleParts.length > 0) {
        sourceCell.title = titleParts.join(" · ");
      }
      row.append(sourceCell);
      fragment.append(row);
    });

    els.readingsBody.replaceChildren(fragment);
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

  function renderTrend(items) {
    if (!els.chartArea) {
      return;
    }

    const chronological = items
      .slice()
      .sort((left, right) => left.recordedMs - right.recordedMs || left.id - right.id);
    const times = chronological.map((item) => item.recordedMs);
    const minTime = Math.min(...times);
    const maxTime = Math.max(...times);
    const width = 600;
    const height = 44;
    const padX = 4;
    const padY = 6;

    SENSOR_KEYS.forEach((key) => {
      const trend = trends[key];
      if (!trend) {
        return;
      }

      const points = chronological.map((item) => {
        const value = item.values[key];
        if (value === null) {
          return { value: null, x: null };
        }

        const x =
          maxTime === minTime
            ? width / 2
            : padX +
              ((item.recordedMs - minTime) / (maxTime - minTime)) *
                (width - padX * 2);
        return { value, x };
      });

      const values = points
        .map((point) => point.value)
        .filter((value) => value !== null);

      if (values.length === 0) {
        trend.range.textContent = "No data";
        trend.path.setAttribute("d", "");
        trend.dot.setAttribute("hidden", "");
        return;
      }

      const minimum = Math.min(...values);
      const maximum = Math.max(...values);
      const yFor = (value) =>
        maximum === minimum
          ? height / 2
          : padY +
            (1 - (value - minimum) / (maximum - minimum)) * (height - padY * 2);

      let pathData = "";
      let hasPreviousPoint = false;
      points.forEach((point) => {
        if (point.value === null) {
          hasPreviousPoint = false;
          return;
        }

        const y = yFor(point.value);
        pathData += `${hasPreviousPoint ? "L" : "M"}${point.x.toFixed(1)} ${y.toFixed(1)} `;
        hasPreviousPoint = true;
      });

      trend.path.setAttribute("d", pathData.trim());
      trend.range.textContent =
        `${formatReadingValue(key, minimum)} – ${formatReadingValue(key, maximum)}`;

      const lastPoint = [...points]
        .reverse()
        .find((point) => point.value !== null);
      if (lastPoint && lastPoint.x !== null) {
        trend.dot.setAttribute("cx", lastPoint.x.toFixed(1));
        trend.dot.setAttribute("cy", yFor(lastPoint.value).toFixed(1));
        trend.dot.removeAttribute("hidden");
      } else {
        trend.dot.setAttribute("hidden", "");
      }
    });

    els.chartEmpty.hidden = true;
    els.chartLanes.hidden = false;
    els.chartArea.classList.add("has-data");
    els.chartMeta.textContent =
      `${items.length} ${items.length === 1 ? "reading" : "readings"}`;
    els.chartNote.textContent = "Recorded time · oldest → newest";
    els.chartArea.setAttribute(
      "aria-label",
      `Sensor trend chart with ${items.length} persisted readings. pH, TDS and temperature each use an independent vertical scale.`,
    );
  }

  function resetTrend() {
    SENSOR_KEYS.forEach((key) => {
      const trend = trends[key];
      if (!trend) {
        return;
      }
      trend.range.textContent = "No data";
      trend.path.setAttribute("d", "");
      trend.dot.setAttribute("hidden", "");
    });

    if (els.chartEmpty) {
      els.chartEmpty.hidden = false;
    }
    if (els.chartLanes) {
      els.chartLanes.hidden = true;
    }
    if (els.chartArea) {
      els.chartArea.classList.remove("has-data");
      els.chartArea.setAttribute(
        "aria-label",
        "Empty sensor trend chart. No persisted readings are available.",
      );
    }
    if (els.chartMeta) {
      els.chartMeta.textContent = "No history";
    }
    if (els.chartNote) {
      els.chartNote.textContent = "No persisted readings";
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
        fetchJson(
          `/api/readings/history?limit=${HISTORY_LIMIT}`,
          controller.signal,
        ),
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

      const [healthResult, readingsResult, historyResult] = results;
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
            "The latest reading returned malformed data. Values were not displayed rather than estimated.";
        }
      } else {
        failureMessage =
          failureMessage ||
          "The latest reading could not be fetched from the dashboard API.";
      }

      if (historyResult.status === "fulfilled") {
        const applied = applyHistory(historyResult.value);
        if (!applied) {
          failureMessage =
            "The reading history returned malformed data. Values were not displayed rather than estimated.";
        }
      } else {
        failureMessage =
          failureMessage ||
          "Recent readings could not be fetched from the dashboard API.";
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

  // Initial hydration. The server-rendered page shows the empty state until
  // the read-only APIs provide persisted measurements.
  loadDashboard();
})();
