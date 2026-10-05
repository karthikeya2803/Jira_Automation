const form = document.querySelector("#issue-form");
const statusBox = document.querySelector("#form-status");
const submitButton = document.querySelector("#submit-button");
const summaryInput = document.querySelector("#summary");
const summaryCount = document.querySelector("#summary-count");
const connectionBadge = document.querySelector("#connection-badge");
const connectionLabel = document.querySelector("#connection-label");

const fieldNames = ["priority", "applicationName", "summary", "businessImpact", "description"];

async function updateConnectionStatus() {
  try {
    const response = await fetch("/api/health");
    if (!response.ok) throw new Error("Health check failed");
    const health = await response.json();
    if (health.demoMode) {
      connectionBadge.dataset.state = "demo";
      connectionLabel.textContent = "Local demo mode";
    } else if (health.openProjectConfigured) {
      connectionBadge.dataset.state = "connected";
      connectionLabel.textContent = "OpenProject configured";
    } else {
      connectionBadge.dataset.state = "offline";
      connectionLabel.textContent = "OpenProject setup needed";
    }
  } catch {
    connectionBadge.dataset.state = "offline";
    connectionLabel.textContent = "Backend unavailable";
  }
}

function showStatus(message, kind = "error") {
  statusBox.textContent = message;
  statusBox.className = `form-status ${kind}`;
  statusBox.hidden = false;
}

function clearFieldErrors() {
  for (const name of fieldNames) {
    const field = form.elements.namedItem(name);
    const container = field.closest(".field");
    container.classList.remove("invalid");
    container.querySelector(`[data-error-for="${name}"]`).textContent = "";
    field.removeAttribute("aria-invalid");
  }
}

function showFieldErrors(errors) {
  for (const [name, message] of Object.entries(errors)) {
    const field = form.elements.namedItem(name);
    const error = form.querySelector(`[data-error-for="${name}"]`);
    if (!field || !error) continue;
    field.closest(".field").classList.add("invalid");
    field.setAttribute("aria-invalid", "true");
    error.textContent = message;
  }
}

updateConnectionStatus();

summaryInput.addEventListener("input", () => {
  summaryCount.textContent = `${summaryInput.value.length} / 255`;
});

form.addEventListener("input", (event) => {
  if (event.target.name) {
    const error = form.querySelector(`[data-error-for="${event.target.name}"]`);
    if (error) {
      error.textContent = "";
      event.target.closest(".field").classList.remove("invalid");
      event.target.removeAttribute("aria-invalid");
    }
  }
  statusBox.hidden = true;
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearFieldErrors();
  statusBox.hidden = true;

  const formData = new FormData(form);
  const payload = Object.fromEntries(formData.entries());
  for (const key of Object.keys(payload)) {
    payload[key] = payload[key].trim();
  }

  const missing = {};
  for (const name of fieldNames) {
    if (!payload[name]) missing[name] = "This field is required";
  }
  if (Object.keys(missing).length) {
    showFieldErrors(missing);
    showStatus("Complete the required fields before submitting.");
    form.querySelector(`[name="${Object.keys(missing)[0]}"]`).focus();
    return;
  }

  submitButton.disabled = true;
  submitButton.querySelector(".button-label").textContent = "Submitting…";

  try {
    const response = await fetch("/api/issues", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) {
      if (result.fields) showFieldErrors(result.fields);
      showStatus(result.error || "The issue could not be submitted.");
      return;
    }

    const statusMessage = result.demo
      ? result.persistent
        ? `Demo issue created: ${result.id}. Saved locally; not sent to OpenProject.`
        : `Demo submission received: ${result.id}. Nothing was saved or sent to OpenProject.`
      : `Issue created${result.id ? `: #${result.id}` : ""}.`;
    showStatus(statusMessage, "success");
    if (result.url) {
      const issueUrl = result.url.startsWith("http")
        ? result.url
        : `${window.location.origin}${result.url}`;
      const link = document.createElement("a");
      link.href = issueUrl;
      link.textContent = " Open the work package";
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      statusBox.append(link);
    }
    form.reset();
    summaryCount.textContent = "0 / 255";
  } catch {
    showStatus("Could not reach the app backend. Check that the server is running and try again.");
  } finally {
    submitButton.disabled = false;
    submitButton.querySelector(".button-label").textContent = "Create issue";
  }
});
