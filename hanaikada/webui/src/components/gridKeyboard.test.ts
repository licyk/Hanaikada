import { describe, expect, it } from 'vitest';
import { type GridEntry, isWholeRoot, moveFocus, thumbSizeFor } from '@/components/gridKeyboard';

describe('grid keyboard model', () => {
  // A grid of 10 items in rows of 4:  0 1 2 3 / 4 5 6 7 / 8 9
  const move = (from: number, key: string) => moveFocus(from, key, 4, 10, 2);

  it('moves by cells and rows, clamped to the list', () => {
    expect(move(5, 'ArrowRight')).toBe(6);
    expect(move(5, 'ArrowLeft')).toBe(4);
    expect(move(5, 'ArrowDown')).toBe(9);
    expect(move(6, 'ArrowDown')).toBe(9);
    expect(move(1, 'ArrowUp')).toBe(0);
    expect(move(9, 'ArrowRight')).toBe(9);
    expect(move(0, 'ArrowLeft')).toBe(0);
  });

  it('starts at the first cell when nothing is focused', () => {
    expect(move(-1, 'ArrowDown')).toBe(0);
    expect(move(-1, 'ArrowRight')).toBe(0);
  });

  it('jumps to the ends and by pages', () => {
    expect(move(5, 'Home')).toBe(0);
    expect(move(5, 'End')).toBe(9);
    expect(move(0, 'PageDown')).toBe(8);
    expect(move(9, 'PageUp')).toBe(1);
  });

  it('ignores other keys and empty grids', () => {
    expect(move(3, 'a')).toBeNull();
    expect(moveFocus(0, 'ArrowRight', 4, 0)).toBeNull();
  });

  it('asks for a thumbnail large enough for the screen', () => {
    expect(thumbSizeFor(200, 1)).toBe(256);
    expect(thumbSizeFor(200, 2)).toBe(512);
    expect(thumbSizeFor(1000, 2)).toBe(768);
  });
});

describe('whole roots in All folders', () => {
  const folder = (path: string): GridEntry => ({ kind: 'folder', key: `d:r1:${path}`, rootId: 'r1', folder: { name: 'x', path, mtime: null, label: null, cover: [], root_id: 'r1', is_root: path === '' } });
  it('treats a folder at a root\'s top as the root itself', () => {
    expect(isWholeRoot(folder(''))).toBe(true);
    expect(isWholeRoot(folder('outputs/txt2img-images'))).toBe(false);
  });
});
