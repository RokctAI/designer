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


export type Format = {
  name: string;
  width: number;
  height: number;
  category: string;
  description: string;
};

export type PaletteColour = { hex: string; coverage: number };

export type DesignSystem = {
  name: string;
  system_name: string;
  brand_name?: string;
  customer?: string;
  tokens: { name: string; hex: string; role: string }[];
  fonts: { name: string; descriptor: string }[];
  max_colors?: number;
  gradient?: { allowed: boolean; max_stops: number };
  contrast?: { min_text: number; min_large_text: number; large_text_size: number };
};
