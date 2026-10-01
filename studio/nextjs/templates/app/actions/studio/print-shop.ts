/*
 * Copyright (c) 2026 ROKCT INTELLIGENCE (PTY) LTD
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU Affero General Public License as published
 * by the Free Software Foundation, version 3.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
 * GNU Affero General Public License for more details.
 *
 * You should have received a copy of the GNU Affero General Public License
 * along with this program. If not, see <https://www.gnu.org/licenses/>.
 */

"use server";

import { paasCall, platformCall } from "@/app/services/base/platform-gateway";
import { revalidatePath } from "next/cache";

// Every cmd here is whitelisted by studio's own frappe/manifest.json
// (gateway cmd co-location rule, SDK_ECOSYSTEM.md).

export type Finding = {
  rule: string;
  severity: "error" | "warning" | "info";
  message: string;
  blocking?: boolean;
  fixed?: boolean;
};

export type PreflightReport = {
  score: number;
  blocked: boolean;
  findings: Finding[];
  file_url?: string;
};

export type Layout = {
  sheet: string;
  sheet_mm: [number, number];
  item_mm: [number, number];
  cols: number;
  rows: number;
  rotated: boolean;
  per_sheet: number;
  usage: number;
  sheets?: number;
};

export type Construction = {
  notes: string[];
  warnings: string[];
  overlay_svg: string;
};

// -- construction guides (informational, never scored) ----------------------

export async function getConstruction(candidate: string) {
  return paasCall<Construction>("api.print_shop.get_construction", { candidate });
}

// -- client PDFs ------------------------------------------------------------

export async function preflightPdf(fileData: string, filename: string) {
  return paasCall<PreflightReport>("api.print_shop.preflight_upload", {
    file_data: fileData,
    filename,
  });
}

export async function imposeClientPdf(fileUrl: string, sheet: string, quantity?: number) {
  return paasCall<{ pdf_url: string; layout: Layout }>("api.print_shop.impose_upload", {
    file_url: fileUrl,
    sheet,
    quantity,
  });
}

export async function listSheets() {
  return paasCall<Record<string, [number, number]>>("api.print_shop.list_sheets", {});
}

// -- print jobs ---------------------------------------------------------------

export async function listPrintJobs(status?: string) {
  try {
    return await paasCall<any[]>("api.print_shop.list_print_jobs", { status });
  } catch (error) {
    console.error("Failed to fetch print jobs:", error);
    return [];
  }
}

export async function getPrintJob(printJob: string) {
  return paasCall<any>("api.print_shop.get_print_job", { print_job: printJob });
}

export async function updatePrintJob(printJob: string, values: Record<string, unknown>) {
  const job = await paasCall<any>("api.print_shop.update_print_job", {
    print_job: printJob,
    values,
  });
  revalidatePath(`/studio/print/${printJob}`);
  return job;
}

export async function preparePrintJob(printJob: string, sheet?: string, quantity?: number) {
  const out = await paasCall<{
    press_pdf: string;
    imposed_pdf?: string;
    ticket_pdf: string;
    layout?: Layout;
  }>("api.print_shop.prepare_print_job", { print_job: printJob, sheet, quantity });
  revalidatePath(`/studio/print/${printJob}`);
  return out;
}

// -- proofs and client sign-off ----------------------------------------------

export async function createApprovalLink(candidate: string) {
  return paasCall<{ token: string; name: string; expires_on: string }>(
    "api.design_approval.create_approval_link",
    { candidate },
  );
}

export async function createProof(approval: string) {
  return paasCall<{ proof_url: string; review_url: string }>("api.print_shop.create_proof", {
    approval,
  });
}

export async function sendProof(approval: string, recipients: string, message?: string) {
  return paasCall<{ proof_url: string; review_url: string; sent_to: string[] }>(
    "api.print_shop.send_proof",
    { approval, recipients, message },
  );
}

// Public review page: guest cmds, no session credentials sent.
export async function getReview(token: string) {
  return platformCall<any>("api.design_approval.get_review", { token }, { requireAuth: false });
}

export async function submitReview(token: string, decision: string, comment?: string) {
  return platformCall<{ status: string }>(
    "api.design_approval.submit_review",
    { token, decision, comment },
    { requireAuth: false, throwOnError: true },
  );
}

// -- downloads -----------------------------------------------------------------

export async function renderPreview(candidate: string, construction = false) {
  return paasCall<{ png_url: string }>("api.print_shop.render_preview", {
    candidate,
    construction: construction ? 1 : 0,
  });
}

export async function renderDeliverable(candidate: string, format?: string, construction = false) {
  return paasCall<{ pdf_url: string }>("api.design_request.render_deliverable", {
    candidate,
    format,
    construction: construction ? 1 : 0,
  });
}

export async function renderPages(candidates: string[], format?: string) {
  return paasCall<{ pdf_url: string }>("api.print_shop.render_pages", { candidates, format });
}

export async function brandbook(designSystem: string, logoFileUrl?: string) {
  return paasCall<{ pdf_url: string }>("api.print_shop.brandbook", {
    design_system: designSystem,
    logo_file_url: logoFileUrl,
  });
}

// -- hot folder ----------------------------------------------------------------

export async function getHotFolderStatus() {
  return paasCall<any>("api.print_shop.get_hot_folder_status", {});
}

export async function saveHotFolderSettings(values: Record<string, unknown>) {
  const out = await paasCall<any>("api.print_shop.save_hot_folder_settings", { values });
  revalidatePath("/studio/settings/hot-folder");
  return out;
}

export async function runHotFolder() {
  const out = await paasCall<any[]>("api.print_shop.run_hot_folder", {});
  revalidatePath("/studio/settings/hot-folder");
  return out;
}
