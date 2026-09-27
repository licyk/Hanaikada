import type { components } from '@/api/schema';

/** Shorthand for the generated schemas. */
export type S = components['schemas'];

export type SettingsView = S['SettingsView'];
export type AppMeta = S['AppMeta'];
export type RootInfo = S['RootInfo'];
export type FolderListing = S['FolderListing'];
export type FolderEntry = S['FolderEntry'];
export type CombinedFolder = S['CombinedFolder'];
export type FileEntry = S['FileEntry'];
export type CoverImage = S['CoverImage'];
export type TreeNode = S['TreeNode'];
export type PathRef = S['PathRef'];
export type ImageRecord = S['ImageRecord'];
export type ImageDetail = S['ImageDetail'];
export type GenerationInfo = S['GenerationInfo'];
export type RawView = S['RawView'];
export type RawChunk = S['RawChunk'];
export type ParseResult = S['ParseResult'];
export type SearchQuery = S['SearchQuery'];
export type SearchPage = S['SearchPage'];
export type Facets = S['Facets'];
export type FacetValue = S['FacetValue'];
export type Stats = S['Stats'];
export type Tag = S['Tag'];
export type TagType = Tag['type'];
export type ScanStatus = S['ScanStatus'];
export type RootScanState = S['RootScanState'];
export type RootIndexSummary = S['RootIndexSummary'];
export type OperationResult = S['OperationResult'];
export type ListSort = 'name' | 'mtime' | 'ctime' | 'size' | 'random';
export type SearchSort = SearchQuery['sort'];

/** Socket event payloads, typed from the same schema as REST. */
export type ServerEvents = { [K in keyof S['ServerEvents']]: S['ServerEvents'][K] };

/**
 * One image as the grid and the viewer see it, whichever list it came from: a folder listing
 * (which may not be indexed yet) or a search result (always indexed).
 */
export interface ImageItem {
  key: string;
  kind: FileEntry['kind'];
  rootId: string;
  path: string;
  name: string;
  version: string;
  size: number;
  mtime: string;
  indexed: boolean;
  image: ImageRecord | null;
}

export function itemFromRecord(record: ImageRecord): ImageItem {
  return { key: `${record.root_id}:${record.path}`, kind: 'image', rootId: record.root_id, path: record.path, name: record.name, version: record.version, size: record.size, mtime: record.mtime, indexed: true, image: record };
}

export function itemFromEntry(rootId: string, entry: FileEntry): ImageItem {
  return { key: `${rootId}:${entry.path}`, kind: entry.kind, rootId, path: entry.path, name: entry.name, version: entry.version, size: entry.size, mtime: entry.mtime, indexed: entry.indexed, image: entry.image ?? null };
}
