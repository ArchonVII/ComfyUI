import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";

const EVENT_NAME = "session-watchdog-event";
const EXTENSION_NAME = "comfyui.session_watchdog";
const seenEvents = new Set();

function eventKey(event) {
    return `${event?.id || event?.fingerprint || event?.message || ""}`;
}

function toastSeverity(severity) {
    if (severity === "error") {
        return "error";
    }
    if (severity === "warning") {
        return "warn";
    }
    return "info";
}

function notify(summary, detail, severity = "info", life = 6000) {
    if (app.extensionManager?.toast?.add) {
        app.extensionManager.toast.add({
            severity: toastSeverity(severity),
            summary,
            detail,
            life,
        });
    } else {
        const suffix = detail ? `: ${detail}` : "";
        console.warn(`[Session Watchdog] ${summary}${suffix}`);
    }
}

function notifyEvent(event) {
    if (!event) {
        return;
    }

    const key = eventKey(event);
    if (seenEvents.has(key)) {
        return;
    }
    seenEvents.add(key);

    const summary = event.title || "ComfyUI session alert";
    let detail = event.summary || event.message || "";
    if (event.count > 1) {
        detail = `${detail} Seen ${event.count} times.`;
    }
    const life = event.severity === "error" ? 12000 : 7000;
    notify(summary, detail, event.severity, life);
}

async function fetchEvents() {
    const response = await api.fetchApi("/session-watchdog/events", { cache: "no-store" });
    if (!response.ok) {
        throw new Error(await response.text());
    }
    return await response.json();
}

async function clearEvents() {
    const response = await api.fetchApi("/session-watchdog/events/clear", {
        method: "POST",
    });
    if (!response.ok) {
        throw new Error(await response.text());
    }
    seenEvents.clear();
    return await response.json();
}

function summarizeExistingEvents(data) {
    const events = data?.events || [];
    for (const event of events) {
        seenEvents.add(eventKey(event));
    }

    if (!events.length) {
        return;
    }

    const errors = events.filter((event) => event.severity === "error");
    const warnings = events.filter((event) => event.severity === "warning");
    const selected = errors[0] || warnings[0] || events[0];
    const count = errors.length || warnings.length || events.length;
    const label = errors.length ? "error" : warnings.length ? "warning" : "event";
    notify(
        `Session watchdog has ${count} recent ${label}${count === 1 ? "" : "s"}`,
        selected.summary || selected.message || "",
        selected.severity,
        selected.severity === "error" ? 10000 : 6000
    );
}

api.addEventListener(EVENT_NAME, (event) => {
    notifyEvent(event.detail);
});

window.comfySessionWatchdog = {
    fetchEvents,
    clearEvents,
};

app.registerExtension({
    name: EXTENSION_NAME,

    async setup() {
        try {
            summarizeExistingEvents(await fetchEvents());
        } catch (error) {
            console.warn(`[Session Watchdog] Startup check failed: ${error.message}`);
        }
    },
});
