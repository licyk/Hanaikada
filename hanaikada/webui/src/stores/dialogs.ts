import { defineStore } from 'pinia';
import { ref } from 'vue';
import type { ImageItem, PathRef } from '@/api/types';

export interface TransferState {
  refs: PathRef[];
  copy: boolean;
  /** Set when the destination is already chosen (a drop onto a folder); the dialog then only confirms. */
  rootId: string | null;
  dir: string | null;
}

/**
 * The dialogs every screen shares — move/copy, rename, delete, tags, compare — opened through
 * this store and mounted once in the app shell.
 */
export const useDialogsStore = defineStore('dialogs', () => {
  const transfer = ref<TransferState | null>(null);
  const rename = ref<{ ref: PathRef; name: string; isFile: boolean } | null>(null);
  const remove = ref<{ refs: PathRef[]; onDone?: () => void } | null>(null);
  const tags = ref<{ items: ImageItem[] } | null>(null);
  const compare = ref<{ items: [ImageItem, ImageItem] } | null>(null);
  const newFolder = ref<{ rootId: string; dir: string } | null>(null);

  return {
    transfer,
    rename,
    remove,
    tags,
    compare,
    newFolder,
    openTransfer: (refs: PathRef[], copy: boolean, rootId: string | null = null, dir: string | null = null) => (transfer.value = { refs, copy, rootId, dir }),
    openRename: (r: PathRef, name: string, isFile: boolean) => (rename.value = { ref: r, name, isFile }),
    openDelete: (refs: PathRef[], onDone?: () => void) => (remove.value = { refs, onDone }),
    openTags: (items: ImageItem[]) => (tags.value = { items }),
    openCompare: (items: [ImageItem, ImageItem]) => (compare.value = { items }),
    openNewFolder: (rootId: string, dir: string) => (newFolder.value = { rootId, dir }),
  };
});
