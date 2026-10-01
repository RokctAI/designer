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


export type Candidate = {
  name: string;
  slot: number;
  attempt: number;
  score_before: number | null;
  score_after: number | null;
  passed: number;
  selected: number;
  svg_url: string | null;
  raw_url: string | null;
};

export type RequestStatus = {
  name?: string;
  status: string;
  error_message: string | null;
  candidates: Candidate[];
};

export type NewDesignRequest = {
  prompt?: string;
  design_system?: string;
  format?: string;
  source_mode: "Generated" | "Uploaded Artwork";
  title?: string;
  customer?: string;
  n_candidates?: number;
  file_urls?: string[];
};

export type Finding = {
  rule: string;
  severity: "error" | "warning" | "info";
  message: string;
  blocking?: boolean;
  fixed?: boolean;
};
