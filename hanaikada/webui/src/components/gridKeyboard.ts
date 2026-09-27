import type { FolderEntry, ImageItem } from '@/api/types';

/**
 * A folder cell. In "All folders" each folder carries its own root, the name to show (told apart
 * from another root's folder of the same name) and whether it is a whole root.
 */
export type GridFolder = FolderEntry & { root_id?: string; display_name?: string; is_root?: boolean };

/** One cell of a grid: a folder (with the root it is in) or an image. */
export type GridEntry = { kind: 'folder'; key: string; rootId: string; folder: GridFolder } | { kind: 'image'; key: string; item: ImageItem };

/** A whole root shown as a folder cannot be moved, copied, renamed or deleted. */
export const isWholeRoot = (entry: GridEntry) => entry.kind === 'folder' && entry.folder.path === '';

/** The drag payload of grid cells: a JSON list of ``{root_id, path}``. */
export const DRAG_TYPE = 'application/x-hanaikada-refs';

/**
 * The grid's keyboard model, kept apart from the component so it can be tested on its own.
 *
 * Arrows move by one cell or one row, Home/End to the ends, PageUp/PageDown by a screen of rows.
 * The result is clamped to the list; ``null`` means the key does not move the focus.
 */
export function moveFocus(index: number, key: string, columns: number, total: number, pageRows = 3): number | null {
  if (total <= 0) return null;
  const current = index < 0 ? -1 : Math.min(index, total - 1);
  const clamp = (i: number) => Math.max(0, Math.min(total - 1, i));
  switch (key) {
    case 'ArrowRight':
      return clamp(current + 1);
    case 'ArrowLeft':
      return current < 0 ? 0 : clamp(current - 1);
    case 'ArrowDown':
      return current < 0 ? 0 : clamp(current + columns);
    case 'ArrowUp':
      return current < 0 ? 0 : clamp(current - columns);
    case 'Home':
      return 0;
    case 'End':
      return total - 1;
    case 'PageDown':
      return clamp(Math.max(current, 0) + columns * pageRows);
    case 'PageUp':
      return clamp(current - columns * pageRows);
    default:
      return null;
  }
}

/** Thumbnail sizes the server makes; a request is rounded up to one of them. */
export const THUMB_SIZES = [128, 256, 384, 512, 768];

/** The thumbnail size to ask for a cell of ``px`` CSS pixels on this screen. */
export function thumbSizeFor(px: number, dpr = typeof window === 'undefined' ? 1 : window.devicePixelRatio || 1): number {
  const want = px * dpr;
  return THUMB_SIZES.find((s) => s >= want) ?? THUMB_SIZES[THUMB_SIZES.length - 1];
}
