import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * Rows that pair a name with a control must let the name shrink.
 *
 * A generated image's file name is often one long unbreakable word (a timestamp, a seed, a model
 * name), so the row's min-content width is the whole name. A flex item keeps `min-width: auto` by
 * default and refuses to go below that, which pushes the row's buttons out of view. `min-width: 0`
 * on the item that holds the text is what makes the ellipsis work and keeps the control in place.
 */
const SRC = join(process.cwd(), 'src');
const ROWS: [file: string, selector: string][] = [
  ['ui/Snackbar.vue', '.text'],
  ['ui/Chip.vue', '.label'],
  ['ui/ContextMenu.vue', '.label'],
  ['components/ImageCell.vue', '.caption'],
  ['components/FolderCell.vue', '.caption'],
  ['components/FolderTree.vue', '.name'],
  ['components/ActivitySheet.vue', '.name'],
  ['components/Viewer.vue', '.title'],
  ['views/BrowseView.vue', '.crumbs'],
  ['views/TagsView.vue', '.name'],
  ['views/StatsView.vue', '.label'],
  ['views/SettingsView.vue', '.root-text'],
];

function rule(file: string, selector: string): string {
  const css = readFileSync(join(SRC, file), 'utf8');
  const match = new RegExp(String.raw`(?:^|\n)\s*${selector.replace('.', '\\.')}\s*\{([^}]*)\}`).exec(css);
  expect(match, `${file} has no rule for ${selector}`).not.toBeNull();
  return match![1];
}

describe('rows that hold a file name', () => {
  it.each(ROWS)('%s %s can shrink below the name', (file, selector) => {
    expect(rule(file, selector)).toContain('min-width: 0');
  });
});
