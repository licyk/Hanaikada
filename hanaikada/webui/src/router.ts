import { reactive } from 'vue';
import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/browse' },
  { path: '/browse', name: 'browse', component: () => import('@/views/BrowseView.vue') },
  { path: '/search', name: 'search', component: () => import('@/views/SearchView.vue') },
  { path: '/tags', name: 'tags', component: () => import('@/views/TagsView.vue') },
  { path: '/stats', name: 'stats', component: () => import('@/views/StatsView.vue') },
  { path: '/settings', name: 'settings', component: () => import('@/views/SettingsView.vue') },
  { path: '/:pathMatch(.*)*', redirect: '/browse' },
];

// Hash history: the UI works at any deployment sub-path with no server-side rewrites.
export const router = createRouter({ history: createWebHashHistory(), routes });

// The address each page was last at, so the navigation goes back to the folder or the search it
// left rather than to the page's start. Memory only: a reload starts every page afresh.
const lastAddress = reactive<Record<string, string>>({});
router.afterEach((to) => {
  if (typeof to.name === 'string') lastAddress[to.name] = to.fullPath;
});

/** Where the navigation takes the page ``name``: its last address in this session, else its start. */
export const addressOf = (name: string): string => lastAddress[name] ?? `/${name}`;
