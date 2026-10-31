/**
 * CertifyPro Frontend Logic
 * Implements a 3-step wizard workflow and talks to the Flask REST API.
 */

// If opened via VS Code Live Server (port 5500/5501) or file://, direct requests to Flask backend at port 5000
const isBackendDirect = window.location.port === "5000";
const targetHost = (window.location.hostname === "localhost") ? "localhost" : "127.0.0.1";
const API_BASE = isBackendDirect ? "" : `http://${targetHost}:5000`;

// Application State
const appState = {
  currentStep: 1,
  csvUrl: "",
  nameColumn: "",
  eventName: "National Workshop 2025",
  totalStudents: 0,
  allStudents: [],
  selectedTemplate: "professional",
  customTemplateId: "",
  folderId: "",
  serviceAccountConfigured: false,
  serviceAccountEmail: null
};

// DOM References
const step1 = document.getElementById("step1");
const step2 = document.getElementById("step2");
const step3 = document.getElementById("step3");

const node1 = document.getElementById("node1");
const node2 = document.getElementById("node2");
const node3 = document.getElementById("node3");

const csvUrlInput = document.getElementById("csvUrl");
const nameColumnSelect = document.getElementById("nameColumnSelect");
const eventNameInput = document.getElementById("eventNameInput");
const previewBtn = document.getElementById("previewBtn");
const previewCard = document.getElementById("previewCard");
const previewBody = document.getElementById("previewBody");
const previewCount = document.getElementById("previewCount");
const btnNext1 = document.getElementById("btnNext1");

const templateBoxes = document.querySelectorAll(".template-box");
const customFileInput = document.getElementById("customFileInput");
const customCanvasPreview = document.getElementById("customCanvasPreview");
const customCanvasStatus = document.getElementById("customCanvasStatus");
const customLabelDesc = document.getElementById("customLabelDesc");
const customControlsCard = document.getElementById("customControlsCard");
const customTextColor = document.getElementById("customTextColor");
const customVerticalPosition = document.getElementById("customVerticalPosition");
const customOnlyName = document.getElementById("customOnlyName");
const previewEventTexts = document.querySelectorAll(".preview-event-text");
const btnBack2 = document.getElementById("btnBack2");
const btnNext2 = document.getElementById("btnNext2");

const saBadge = document.getElementById("saBadge");
const saInfoText = document.getElementById("saInfoText");
const btnUploadKey = document.getElementById("btnUploadKey");
const serviceAccountFileInput = document.getElementById("serviceAccountFileInput");

const folderIdInput = document.getElementById("folderId");
const sumEvent = document.getElementById("sumEvent");
const sumTemplate = document.getElementById("sumTemplate");
const sumCount = document.getElementById("sumCount");
const btnGenerateDrive = document.getElementById("btnGenerateDrive");
const btnGenerateZip = document.getElementById("btnGenerateZip");
const loadingState = document.getElementById("loadingState");
const loadingMsg = document.getElementById("loadingMsg");
const resultsCard = document.getElementById("resultsCard");
const statUploaded = document.getElementById("statUploaded");
const statFailed = document.getElementById("statFailed");
const statLbl = document.getElementById("statLbl");
const zipDownloadBanner = document.getElementById("zipDownloadBanner");
const linksList = document.getElementById("linksList");
const btnBack3 = document.getElementById("btnBack3");
const btnReset = document.getElementById("btnReset");

// Update Event text across UI whenever changed
if (eventNameInput) {
  eventNameInput.addEventListener("input", (e) => {
    const val = e.target.value.trim() || "Event Name";
    appState.eventName = val;
    previewEventTexts.forEach(el => el.textContent = val);
    if (sumEvent) sumEvent.textContent = val;
  });
}

// Column selector change listener
if (nameColumnSelect) {
  nameColumnSelect.addEventListener("change", async () => {
    appState.nameColumn = nameColumnSelect.value;
    if (appState.csvUrl) {
      loadPreview();
    }
  });
}

// Navigation Helper
function saveAppState() {
  try {
    sessionStorage.setItem("certifyPro_state", JSON.stringify({
      currentStep: appState.currentStep,
      csvUrl: appState.csvUrl,
      nameColumn: appState.nameColumn,
      eventName: appState.eventName,
      totalStudents: appState.totalStudents,
      allStudents: appState.allStudents,
      selectedTemplate: appState.selectedTemplate,
      customTemplateId: appState.customTemplateId
    }));
  } catch(e) {}
}

function restoreAppState() {
  try {
    const saved = sessionStorage.getItem("certifyPro_state");
    if (!saved) return;
    const data = JSON.parse(saved);
    if (!data || !data.csvUrl) return;

    Object.assign(appState, data);

    if (csvUrlInput) csvUrlInput.value = appState.csvUrl;
    if (eventNameInput) eventNameInput.value = appState.eventName;

    // Restore step cards
    if (appState.currentStep > 1) {
      setStep(appState.currentStep, false);
      if (btnNext1) btnNext1.disabled = false;
    }

    // Restore template selection
    if (appState.selectedTemplate) {
      templateBoxes.forEach(b => {
        b.classList.toggle("selected", b.dataset.template === appState.selectedTemplate);
      });
      if (appState.selectedTemplate === "custom" && customControlsCard) {
        customControlsCard.classList.remove("hidden");
      }
    }
  } catch(e) {}
}

function setStep(step, save = true) {
  appState.currentStep = step;
  if (save) saveAppState();

  // Toggle step cards
  step1.classList.toggle("hidden", step !== 1);
  step2.classList.toggle("hidden", step !== 2);
  step3.classList.toggle("hidden", step !== 3);

  // Update progress indicators
  node1.classList.toggle("active", step >= 1);
  node2.classList.toggle("active", step >= 2);
  node3.classList.toggle("active", step >= 3);

  if (step === 3) {
    checkServiceAccountStatus();
  }

  window.scrollTo({ top: 0, behavior: "smooth" });
}

// Helper to safely parse JSON from responses
async function parseJsonResponse(res) {
  const text = await res.text();
  try {
    return JSON.parse(text);
  } catch (e) {
    if (res.status === 404) {
      throw new Error(`API endpoint not found on ${res.url}. Please verify Flask is running on http://127.0.0.1:5000`);
    }
    throw new Error(`Server returned non-JSON response (${res.status}): ${text.slice(0, 150)}...`);
  }
}

// Check Google Cloud Service Account status from backend
async function checkServiceAccountStatus() {
  try {
    const res = await fetch(`${API_BASE}/api/status`);
    const data = await parseJsonResponse(res);

    if (data.service_account_configured) {
      appState.serviceAccountConfigured = true;
      appState.serviceAccountEmail = data.service_account_email;
      if (saBadge) {
        saBadge.className = "sa-badge sa-badge-ok";
        saBadge.textContent = "✔ Google Drive Key Active";
      }
      if (saInfoText) {
        saInfoText.innerHTML = `
          <strong>Service Account Email:</strong> <code>${escapeHtml(data.service_account_email)}</code>
          <br><small style="color:#059669;">Make sure this email is added as an <strong>Editor</strong> to your Google Drive folder!</small>
        `;
      }
    } else {
      appState.serviceAccountConfigured = false;
      if (saBadge) {
        saBadge.className = "sa-badge sa-badge-warn";
        saBadge.textContent = "⚠️ Google Drive Key Not Configured";
      }
      if (saInfoText) {
        saInfoText.innerHTML = `
          Upload your Google Cloud <code>service_account.json</code> key file to upload to Drive, or click <strong>Download All as ZIP</strong> below.
        `;
      }
    }
  } catch (err) {
    if (saBadge) {
      saBadge.className = "sa-badge sa-badge-warn";
      saBadge.textContent = "Backend Connection Error";
    }
  }
}

// ─────────────────────────────────────────────────────────────
// STEP 1: CSV Validation & Preview
// ─────────────────────────────────────────────────────────────
async function loadPreview() {
  const url = csvUrlInput.value.trim();
  if (!url) {
    alert("Please enter a Google Sheet, Drive CSV, or direct CSV URL.");
    return;
  }

  previewBtn.disabled = true;
  previewBtn.innerText = "Fetching...";

  try {
    const res = await fetch(`${API_BASE}/api/preview-csv`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: url,
        name_column: (nameColumnSelect && nameColumnSelect.value) ? nameColumnSelect.value : ""
      })
    }).catch(err => {
      throw new Error(`Cannot connect to the Flask server at http://127.0.0.1:5000.\n\nMake sure the backend is running in your terminal:\n.\\venv\\Scripts\\python backend\\app.py`);
    });

    const data = await parseJsonResponse(res);

    if (!res.ok) {
      throw new Error(data.error || "Failed to load CSV data.");
    }

    // Populate column options dropdown
    if (data.columns && data.columns.length > 0 && nameColumnSelect) {
      const currentSelected = nameColumnSelect.value || data.detected_name_column;
      nameColumnSelect.innerHTML = "";
      data.columns.forEach(col => {
        const opt = document.createElement("option");
        opt.value = col;
        opt.textContent = col + (col === data.detected_name_column ? " (Auto-Detected Name)" : "");
        if (col === currentSelected) {
          opt.selected = true;
        }
        nameColumnSelect.appendChild(opt);
      });
      appState.nameColumn = currentSelected;
    }

    // Populate table preview
    previewBody.innerHTML = "";
    data.preview.forEach((row, idx) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td style="font-weight: 600; color: #6b7280;">${idx + 1}</td>
        <td><strong>${escapeHtml(row["Student Name"])}</strong></td>
      `;
      previewBody.appendChild(tr);
    });

    previewCount.innerText = `${data.total_count} students found`;
    previewCard.classList.remove("hidden");

    appState.csvUrl = url;
    appState.totalStudents = data.total_count;
    appState.allStudents = data.all_student_names || [];
    btnNext1.disabled = false;
  } catch (err) {
    alert(err.message);
    previewCard.classList.add("hidden");
    btnNext1.disabled = true;
  } finally {
    previewBtn.disabled = false;
    previewBtn.innerHTML = "<span>👁️</span> Load & Preview";
  }
}

previewBtn.addEventListener("click", loadPreview);
btnNext1.addEventListener("click", () => setStep(2));

// ─────────────────────────────────────────────────────────────
// STEP 2: Template Selection & Custom Upload
// ─────────────────────────────────────────────────────────────
templateBoxes.forEach((box) => {
  box.addEventListener("click", () => {
    templateBoxes.forEach((b) => b.classList.remove("selected"));
    box.classList.add("selected");
    const val = box.dataset.template;
    appState.selectedTemplate = val;

    // Toggle custom fine-tuning options
    if (val === "custom") {
      customControlsCard.classList.remove("hidden");
      customFileInput.click();
    } else {
      customControlsCard.classList.add("hidden");
    }
  });
});

// Handle custom background image upload
customFileInput.addEventListener("change", async () => {
  const file = customFileInput.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append("template_file", file);

  customCanvasStatus.innerText = "Uploading template...";
  customLabelDesc.innerText = "Uploading background...";

  try {
    const res = await fetch(`${API_BASE}/api/upload-template`, {
      method: "POST",
      body: formData
    }).catch(err => {
      throw new Error(`Cannot connect to the backend server at http://127.0.0.1:5000.`);
    });

    const data = await parseJsonResponse(res);
    if (!res.ok) throw new Error(data.error || "Upload failed");

    appState.customTemplateId = data.template_id || ""; saveAppState();
    customLabelDesc.innerText = `Uploaded: ${file.name}`;
    customCanvasStatus.innerText = "Custom Background Loaded ✔";

    // Show image preview inside card
    const reader = new FileReader();
    reader.onload = (e) => {
      customCanvasPreview.style.backgroundImage = `url(${e.target.result})`;
      customCanvasPreview.style.backgroundSize = "cover";
      customCanvasPreview.style.backgroundPosition = "center";
      customCanvasPreview.innerHTML = `
        <div style="background:rgba(0,0,0,0.6); color:#fff; padding:4px 8px; border-radius:4px; font-size:0.6rem;">
          ${escapeHtml(file.name)}
        </div>
      `;
    };
    reader.readAsDataURL(file);
    customControlsCard.classList.remove("hidden");
  } catch (err) {
    alert(err.message);
    customLabelDesc.innerText = "Upload failed. Try again.";
    customCanvasStatus.innerText = "Upload Certificate (.png/.jpg)";
  }
});

btnBack2.addEventListener("click", () => setStep(1));
btnNext2.addEventListener("click", () => {
  // Populate Step 3 summary
  if (sumEvent) sumEvent.innerText = appState.eventName || "Event Name";
  if (sumTemplate) sumTemplate.innerText = capitalize(appState.selectedTemplate);
  if (sumCount) sumCount.innerText = appState.totalStudents;
  setStep(3);
});

// ─────────────────────────────────────────────────────────────
// STEP 3: Google Drive Service Account Upload & Execution
// ─────────────────────────────────────────────────────────────
if (btnUploadKey) {
  btnUploadKey.addEventListener("click", () => {
    serviceAccountFileInput.click();
  });
}

if (serviceAccountFileInput) {
  serviceAccountFileInput.addEventListener("change", async () => {
    const file = serviceAccountFileInput.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append("key_file", file);

    try {
      const res = await fetch(`${API_BASE}/api/upload-service-account`, {
        method: "POST",
        body: formData
      });
      const data = await parseJsonResponse(res);

      if (!res.ok) throw new Error(data.error || "Failed to upload key file.");

      alert("✅ " + data.message);
      checkServiceAccountStatus();
    } catch (err) {
      alert("❌ Error: " + err.message);
    }
  });
}

// Generic generation function supporting both Google Drive & ZIP
async function executeGeneration(action) {
  const folderId = (folderIdInput && folderIdInput.value) ? folderIdInput.value.trim() : "";

  btnGenerateDrive.disabled = true;
  btnGenerateZip.disabled = true;
  loadingState.classList.remove("hidden");
  resultsCard.classList.add("hidden");
  zipDownloadBanner.classList.add("hidden");
  linksList.innerHTML = "";

  loadingMsg.innerText = action === "drive" 
    ? "Rendering certificates and uploading to Google Drive..."
    : "Rendering certificates and bundling into ZIP file...";

  try {
    const payload = {
      action: action,
      students: appState.allStudents || [],
      csv_url: appState.csvUrl || "",
      name_column: appState.nameColumn || "",
      event_name: appState.eventName || "Event",
      template: appState.selectedTemplate || "professional",
      template_id: appState.customTemplateId || "",
      folder_id: folderId,
      custom_settings: {
        text_color: customTextColor ? customTextColor.value : "#111827",
        name_y: customVerticalPosition ? customVerticalPosition.value : "0.48",
        only_name: customOnlyName ? customOnlyName.value === "true" : true
      }
    };

    const res = await fetch(`${API_BASE}/api/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).catch(err => {
      throw new Error(`Cannot connect to backend server at http://127.0.0.1:5000.`);
    });

    const data = await parseJsonResponse(res);

    if (!res.ok) throw new Error(data.error || "Generation request failed");

    statUploaded.innerText = data.success_count;
    statFailed.innerText = data.failed_count;
    statLbl.innerText = action === "drive" && !data.fallback_to_zip ? "Uploaded to Drive" : "Generated in ZIP";

    if (data.download_zip_url) {
      zipDownloadBanner.classList.remove("hidden");
      zipDownloadBanner.innerHTML = `
        <a href="${API_BASE}${data.download_zip_url}" class="btn btn-primary" download style="display:inline-flex; align-items:center; gap:0.5rem; text-decoration:none;">
          <span>⬇️</span> Download All Certificates (.ZIP)
        </a>
      `;
      // Auto-trigger download
      window.location.href = `${API_BASE}${data.download_zip_url}`;

      if (data.fallback_to_zip) {
        alert("ℹ️ Google Drive key not configured yet, so all certificates were packaged and downloaded as a ZIP file!");
      }
    }

    // Render results
    data.results.forEach((item) => {
      const row = document.createElement("div");
      row.className = "result-item";
      const linkHtml = item.drive_link 
        ? `<a href="${item.drive_link}" target="_blank" rel="noopener">Open in Drive ↗</a>`
        : `<span style="color:#059669; font-weight:600;">Saved in ZIP</span>`;

      row.innerHTML = `
        <span>✅ <strong>${escapeHtml(item.student_name)}</strong> — ${escapeHtml(item.event)}</span>
        ${linkHtml}
      `;
      linksList.appendChild(row);
    });

    data.errors.forEach((err) => {
      const row = document.createElement("div");
      row.className = "result-item";
      row.innerHTML = `
        <span style="color:#b91c1c;">❌ <strong>${escapeHtml(err.student_name)}</strong>: ${escapeHtml(err.error)}</span>
      `;
      linksList.appendChild(row);
    });

    resultsCard.classList.remove("hidden");
  } catch (err) {
    alert("Error: " + err.message);
  } finally {
    btnGenerateDrive.disabled = false;
    btnGenerateZip.disabled = false;
    loadingState.classList.add("hidden");
  }
}

btnGenerateDrive.addEventListener("click", () => executeGeneration("drive"));
btnGenerateZip.addEventListener("click", () => executeGeneration("zip"));

btnBack3.addEventListener("click", () => setStep(2));
btnReset.addEventListener("click", () => {
  csvUrlInput.value = "";
  if (folderIdInput) folderIdInput.value = "";
  previewCard.classList.add("hidden");
  resultsCard.classList.add("hidden");
  btnNext1.disabled = true;
  appState.csvUrl = "";
  appState.totalStudents = 0;
  appState.allStudents = [];
  appState.customTemplateId = "";
  sessionStorage.removeItem("certifyPro_state"); setStep(1);
});

// Helpers
function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function capitalize(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}


// Auto-restore state on page load/reload
restoreAppState();
