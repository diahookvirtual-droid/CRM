
const SHEET_NAME = "Leads";

const HEADERS = [
  "id",
  "name",
  "email",
  "phone",
  "business_name",
  "status",
  "industry",
  "designation",
  "partnership_concept",
  "why_it_fits_shl",
  "proposed_shl_value",
  "contact_verification",
  "source",
  "created_at",
  "updated_at"
];

function getSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(SHEET_NAME);

  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
  }

  if (sheet.getLastRow() === 0) {
    sheet.appendRow(HEADERS);
  }

  return sheet;
}

function jsonResponse(data) {
  return ContentService
    .createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}

function getLeads() {
  const sheet = getSheet();
  const rows = sheet.getDataRange().getValues();

  if (rows.length <= 1) return [];

  const headers = rows[0];

  return rows.slice(1)
    .filter(row => row[0] !== "")
    .map(row => {
      const lead = {};
      headers.forEach((header, index) => {
        lead[header] = row[index];
      });
      return lead;
    });
}

function doGet(e) {
  try {
    return jsonResponse({
      success: true,
      leads: getLeads()
    });
  } catch (error) {
    return jsonResponse({
      success: false,
      error: error.message
    });
  }
}

function doPost(e) {
  const lock = LockService.getScriptLock();

  try {
    lock.waitLock(10000);

    const data = JSON.parse(e.postData.contents);
    const action = data.action;
    const sheet = getSheet();

    if (action === "add") {
      const lead = data.lead;

      if (!lead || !lead.name || !lead.email) {
        throw new Error("Name and email are required.");
      }

      const leads = getLeads();

      if (leads.some(x =>
        String(x.email).toLowerCase() ===
        String(lead.email).toLowerCase()
      )) {
        throw new Error("Email already exists.");
      }

      const now = new Date().toISOString();

      const newLead = HEADERS.map(key => {
        if (key === "id") return lead.id || Utilities.getUuid();
        if (key === "created_at" || key === "updated_at") return now;
        return lead[key] ?? "";
      });

      sheet.appendRow(newLead);

      return jsonResponse({
        success: true,
        message: "Lead added successfully."
      });
    }

    if (action === "update") {
      const lead = data.lead;

      if (!lead || !lead.id) {
        throw new Error("Lead ID is required.");
      }

      const rows = sheet.getDataRange().getValues();
      const idIndex = HEADERS.indexOf("id");
      const rowIndex = rows.findIndex((row, index) =>
        index > 0 && String(row[idIndex]) === String(lead.id)
      );

      if (rowIndex === -1) {
        throw new Error("Lead not found.");
      }

      const existing = rows[rowIndex];
      const updated = HEADERS.map((key, index) => {
        if (key === "id" || key === "created_at") {
          return existing[index];
        }
        if (key === "updated_at") {
          return new Date().toISOString();
        }
        return lead[key] !== undefined ? lead[key] : existing[index];
      });

      sheet.getRange(rowIndex + 1, 1, 1, HEADERS.length)
        .setValues([updated]);

      return jsonResponse({
        success: true,
        message: "Lead updated successfully."
      });
    }

    if (action === "delete") {
      const id = String(data.id || "");
      const rows = sheet.getDataRange().getValues();

      const rowIndex = rows.findIndex((row, index) =>
        index > 0 && String(row[0]) === id
      );

      if (rowIndex === -1) {
        throw new Error("Lead not found.");
      }

      sheet.deleteRow(rowIndex + 1);

      return jsonResponse({
        success: true,
        message: "Lead deleted successfully."
      });
    }

    throw new Error("Invalid action.");

  } catch (error) {
    return jsonResponse({
      success: false,
      error: error.message
    });
  } finally {
    if (lock.hasLock()) lock.releaseLock();
  }
}

function setup() {
  getSheet();
}
