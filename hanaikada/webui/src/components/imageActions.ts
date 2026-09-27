/**
 * What can be done to images and folders from a grid, a context menu or the viewer: one list of
 * actions and one runner, so every screen offers the same things in the same order.
 */
import { useQueryClient } from '@tanstack/vue-query';
import { computed } from 'vue';
import { useRouter } from 'vue-router';
import { api, chunkUrl, downloadUrl, downloadZip, fileUrl, unwrap } from '@/api/client';
import { useMeta } from '@/api/queries/app';
import { keys } from '@/api/queries/keys';
import { useLibraryMutations } from '@/api/queries/library';
import { useCustomTags, useTagMutations } from '@/api/queries/tags';
import type { ImageDetail, ImageItem, PathRef } from '@/api/types';
import type { HostTarget } from '@/host/bridge';
import { type GridEntry, isWholeRoot } from '@/components/gridKeyboard';
import { useI18n } from '@/i18n';
import { toInfotext } from '@/metadata/infotext';
import { encodeQuery } from '@/search/url';
import { useDialogsStore } from '@/stores/dialogs';
import { useHostStore } from '@/stores/host';
import { icons, type MenuItem, useSnackbar } from '@/ui';

export type ActionId =
  | 'open'
  | 'openNewTab'
  | 'favorite'
  | 'unfavorite'
  | 'tags'
  | 'copyPrompt'
  | 'copyInfotext'
  | 'download'
  | 'downloadWorkflow'
  | 'downloadMetadata'
  | 'showInFolder'
  | 'openWithApp'
  | 'moveTo'
  | 'copyTo'
  | 'rename'
  | 'delete'
  | 'zip'
  | 'compare'
  | 'similarSeed'
  | 'similarModel'
  | 'similarPrompt'
  | 'openFolder'
  | 'rescanFolder'
  /** Hand the file to the application framing Hanaikada (``stores/host.ts``). */
  | `sendTo:${string}`;

export async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    // Without a secure context the clipboard API is missing; a hidden textarea still works.
    const area = document.createElement('textarea');
    area.value = text;
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    document.execCommand('copy');
    area.remove();
  }
}

/** Targets Hanaikada names itself; a host may name others. */
const KNOWN_TARGETS = ['txt2img', 'img2img', 'inpaint', 'extras', 'workflow', 'loadImage'];
// Where the WebUI puts its infotext, in the order it reads them.
const INFOTEXT_CHUNKS = ['parameters', 'UserComment', 'comment', 'sidecar:txt'];

export function useImageActions() {
  const { t } = useI18n();
  const qc = useQueryClient();
  const router = useRouter();
  const meta = useMeta();
  const snackbar = useSnackbar();
  const dialogs = useDialogsStore();
  const host = useHostStore();
  const library = useLibraryMutations();
  const tagMutations = useTagMutations();
  const customTags = useCustomTags();
  const favoriteId = computed(() => customTags.data.value?.find((tag) => tag.name === 'favorite')?.id ?? null);

  const refOf = (e: GridEntry): PathRef => (e.kind === 'folder' ? { root_id: e.rootId, path: e.folder.path } : { root_id: e.item.rootId, path: e.item.path });
  const isFavorite = (item: ImageItem) => favoriteId.value != null && (item.image?.tag_ids ?? []).includes(favoriteId.value);

  async function detail(item: ImageItem): Promise<ImageDetail> {
    return qc.fetchQuery({
      queryKey: [...keys.imageByPath(item.rootId, item.path), item.version],
      queryFn: () => unwrap(api.GET('/api/v1/images/by-path', { params: { query: { root_id: item.rootId, path: item.path } } })),
      staleTime: 60_000,
    });
  }

  /**
   * The image's parameters as an A1111 infotext: a WebUI image's own text, exactly as written;
   * anything else's rebuilt from its metadata, so a ComfyUI image sends its real prompt. Null when
   * there is nothing to say.
   */
  async function infotextFor(item: ImageItem): Promise<string | null> {
    const d = await detail(item);
    if (d.info.platform === 'sd-webui') {
      const key = INFOTEXT_CHUNKS.find((k) => d.chunks.includes(k));
      if (key) return (await fetch(chunkUrl(d.record.id, key, true))).text();
    }
    // Without a prompt or steps there are no parameters to hand over, only noise ("Version: …").
    if (!d.info.prompt && d.info.steps == null) return null;
    return toInfotext(d.info);
  }

  const targetLabel = (target: HostTarget) => target.label ?? (KNOWN_TARGETS.includes(target.id) ? t(`send.targets.${target.id}`) : target.id);
  /** "Send to …" items for one file, from what the framing application takes. */
  const sendItems = (item: ImageItem): MenuItem[] => host.targetsFor(item).map((target) => ({ id: `sendTo:${target.id}`, label: targetLabel(target), icon: icons.Send }));

  async function sendTo(targetId: string, item: ImageItem) {
    const target = host.info?.targets.find((x) => x.id === targetId);
    if (!target) return;
    const label = targetLabel(target);
    const needsText = !target.needs?.length || target.needs.includes('infotext');
    const infotext = needsText && item.kind === 'image' ? await infotextFor(item).catch(() => null) : null;
    const url = new URL(fileUrl(item.rootId, item.path, item.version), window.location.href).href;
    const result = await host.send(target, {
      item: { root_id: item.rootId, path: item.path, name: item.name, kind: item.kind, url, version: item.version, size: item.size },
      infotext,
      platform: item.image?.platform ?? null,
    });
    if (result.ok) snackbar.show(t('send.sent', { target: label }));
    else snackbar.error(t('send.failed', { target: label, message: result.message ?? '' }));
  }

  /** The menu for what is selected; ``entries`` is the selection, or the one entry clicked. */
  function menuFor(entries: GridEntry[]): (MenuItem & { divider?: boolean })[] {
    const images = entries.filter((e): e is Extract<GridEntry, { kind: 'image' }> => e.kind === 'image').map((e) => e.item);
    // Favourites and tags live on indexed images; videos, audio and other files are not indexed.
    const taggable = images.filter((i) => i.kind === 'image');
    const folders = entries.filter((e) => e.kind === 'folder');
    const single = entries.length === 1 ? entries[0] : null;
    const local = !!meta.data.value?.local;
    const items: (MenuItem & { divider?: boolean })[] = [];
    if (single?.kind === 'folder') {
      items.push({ id: 'openFolder', label: t('menu.openFolder'), icon: icons.FolderOpen }, { id: 'rescanFolder', label: t('menu.rescanFolder'), icon: icons.RefreshCw });
    }
    if (single?.kind === 'image') {
      const item = single.item;
      const platform = item.image?.platform;
      items.push({ id: 'open', label: t('menu.open'), icon: icons.Expand }, { id: 'openNewTab', label: t('menu.openNewTab'), icon: icons.ExternalLink });
      sendItems(item).forEach((send, i) => items.push({ ...send, divider: i === 0 }));
      if (item.kind === 'image') {
        items.push(isFavorite(item) ? { id: 'unfavorite', label: t('menu.unfavorite'), icon: icons.Heart, divider: true } : { id: 'favorite', label: t('menu.favorite'), icon: icons.Heart, divider: true });
        items.push({ id: 'tags', label: t('menu.tags'), icon: icons.Tag });
        items.push({ id: 'copyPrompt', label: t('menu.copyPrompt'), icon: icons.Copy, divider: true }, { id: 'copyInfotext', label: t('menu.copyInfotext'), icon: icons.FileText });
      }
      items.push({ id: 'download', label: t('menu.download'), icon: icons.Download, divider: true });
      if (platform === 'comfyui') items.push({ id: 'downloadWorkflow', label: t('menu.downloadWorkflow'), icon: icons.FileJson });
      if (platform === 'invokeai') items.push({ id: 'downloadMetadata', label: t('menu.downloadMetadata'), icon: icons.FileJson });
      if (item.image) {
        items.push(
          { id: 'similarSeed', label: t('menu.similarSeed'), icon: icons.Hash, divider: true, disabled: item.image.seed == null },
          { id: 'similarModel', label: t('menu.similarModel'), icon: icons.Layers, disabled: !item.image.model_name },
          { id: 'similarPrompt', label: t('menu.similarPrompt'), icon: icons.ScanSearch, disabled: !item.image.prompt },
        );
      }
    } else if (images.length > 1) {
      if (taggable.length) items.push({ id: 'favorite', label: t('menu.favorite'), icon: icons.Heart }, { id: 'tags', label: t('menu.tags'), icon: icons.Tag });
      if (taggable.length === 2 && entries.length === 2) items.push({ id: 'compare', label: t('selection.compare'), icon: icons.Columns2 });
    }
    if (entries.length > 1 || folders.length) items.push({ id: 'zip', label: t('selection.zip'), icon: icons.Download, divider: true });
    if (single && local) {
      items.push({ id: 'showInFolder', label: t('menu.showInFolder'), icon: icons.FolderOpen, divider: true });
      if (single.kind === 'image') items.push({ id: 'openWithApp', label: t('menu.openWithApp'), icon: icons.ExternalLink });
    }
    // A whole root (in All folders) stays where it is and keeps its name.
    if (entries.some(isWholeRoot)) return items;
    items.push({ id: 'moveTo', label: t('menu.moveTo'), icon: icons.FolderInput, divider: true }, { id: 'copyTo', label: t('menu.copyTo'), icon: icons.Copy });
    if (single) items.push({ id: 'rename', label: t('menu.rename'), icon: icons.Pencil });
    items.push({ id: 'delete', label: t('menu.delete'), icon: icons.Trash2, danger: true, divider: true });
    return items;
  }

  async function setFavorite(items: ImageItem[], on: boolean) {
    if (favoriteId.value == null) return;
    await tagMutations.apply.mutateAsync({ id: favoriteId.value, add: on, body: { image_ids: [], paths: items.map((i) => [i.rootId, i.path] as [string, string]) } });
  }

  function similar(item: ImageItem, by: 'seed' | 'model' | 'prompt') {
    const record = item.image;
    if (!record) return;
    const query =
      by === 'seed' ? { seed: (record.seed ?? undefined) as number | undefined } : by === 'model' ? { models: record.model_name ? [record.model_name] : [] } : { text: (record.prompt ?? '').slice(0, 120), text_in: ['prompt' as const] };
    router.push({ name: 'search', query: { q: encodeQuery(query) } });
  }

  /** Run an action over entries. ``openImage`` and ``openFolder`` come from the screen that asked. */
  async function run(id: ActionId, entries: GridEntry[], hooks: { openImage?: (item: ImageItem) => void; openFolder?: (path: string, rootId: string) => void; afterDelete?: () => void } = {}) {
    const images = entries.filter((e): e is Extract<GridEntry, { kind: 'image' }> => e.kind === 'image').map((e) => e.item);
    if (id.startsWith('sendTo:')) {
      const target = entries.find((e): e is Extract<GridEntry, { kind: 'image' }> => e.kind === 'image');
      if (target) await sendTo(id.slice('sendTo:'.length), target.item).catch((e: Error) => snackbar.error(e.message));
      return;
    }
    // Nothing moves, renames or deletes a whole root, whichever way the action was asked for.
    if ((['moveTo', 'copyTo', 'rename', 'delete'] as ActionId[]).includes(id)) entries = entries.filter((e) => !isWholeRoot(e));
    if (!entries.length) return;
    const refs = entries.map(refOf);
    const first = entries[0];
    const item = images[0];
    try {
      switch (id) {
        case 'open':
          if (item) hooks.openImage?.(item);
          break;
        case 'openFolder':
          if (first?.kind === 'folder') hooks.openFolder?.(first.folder.path, first.rootId);
          break;
        case 'rescanFolder':
          if (first?.kind === 'folder') {
            await unwrap(api.POST('/api/v1/index/scan', { body: { root_id: refs[0].root_id, path: refs[0].path, full: false, reparse: false } }));
          }
          break;
        case 'openNewTab':
          if (item) window.open(fileUrl(item.rootId, item.path, item.version), '_blank', 'noopener');
          break;
        case 'favorite':
        case 'unfavorite':
          await setFavorite(images.filter((i) => i.kind === 'image'), id === 'favorite');
          break;
        case 'tags': {
          const taggable = images.filter((i) => i.kind === 'image');
          if (taggable.length) dialogs.openTags(taggable);
          break;
        }
        case 'copyPrompt': {
          const d = await detail(item);
          await copyText(d.prompt ?? '');
          snackbar.show(t('common.copied'));
          break;
        }
        case 'copyInfotext': {
          await copyText((await infotextFor(item)) ?? '');
          snackbar.show(t('common.copied'));
          break;
        }
        case 'download':
          if (item) downloadUrl(fileUrl(item.rootId, item.path, item.version, true));
          break;
        case 'downloadWorkflow':
        case 'downloadMetadata': {
          const d = await detail(item);
          const order = id === 'downloadWorkflow' ? ['workflow', 'prompt'] : ['invokeai_workflow', 'invokeai_metadata', 'invokeai_graph'];
          const key = order.find((k) => d.chunks.includes(k));
          if (key) downloadUrl(chunkUrl(d.record.id, key));
          break;
        }
        case 'zip':
          await downloadZip(refs, entries.length === 1 && first.kind === 'folder' ? first.folder.name : 'hanaikada');
          break;
        case 'compare':
          if (images.length === 2 && images.every((i) => i.kind === 'image')) dialogs.openCompare([images[0], images[1]]);
          break;
        case 'showInFolder':
        case 'openWithApp':
          await library.open.mutateAsync({ root_id: refs[0].root_id, path: refs[0].path, reveal: id === 'showInFolder' });
          break;
        case 'moveTo':
        case 'copyTo':
          dialogs.openTransfer(refs, id === 'copyTo');
          break;
        case 'rename':
          if (first) dialogs.openRename(refs[0], first.kind === 'folder' ? first.folder.name : first.item.name, first.kind === 'image');
          break;
        case 'delete':
          dialogs.openDelete(refs, hooks.afterDelete);
          break;
        case 'similarSeed':
          if (item) similar(item, 'seed');
          break;
        case 'similarModel':
          if (item) similar(item, 'model');
          break;
        case 'similarPrompt':
          if (item) similar(item, 'prompt');
          break;
      }
    } catch (e) {
      snackbar.error((e as Error).message);
    }
  }

  return { menuFor, run, favoriteId, isFavorite, setFavorite, detail, sendItems };
}
