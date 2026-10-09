import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import { defineComponent, h, nextTick, ref } from 'vue';
import { formatBytes, parentPath, pathSegments } from '@/format';
import { translate, translateList } from '@/i18n';
import { windowClass } from '@/theme/breakpoints';
import { DEFAULT_SOURCE_COLOR, generateScheme } from '@/theme/scheme';
import AppDialog from '@/ui/AppDialog.vue';
import Breadcrumbs from '@/ui/Breadcrumbs.vue';
import Chip from '@/ui/Chip.vue';
import EmptyState from '@/ui/EmptyState.vue';
import ExpansionPanel from '@/ui/ExpansionPanel.vue';
import SegmentedButton from '@/ui/SegmentedButton.vue';
import { Blossom } from '@/ui/icons';
import { containerFrom, staggerStyle } from '@/ui/motion/transitions';
import { closeOnEscape, layerOpen, trapFocus, useLayer } from '@/ui/useLayer';
import { useSnackbar } from '@/ui/useSnackbar';

describe('ui components', () => {
  it('SegmentedButton selects one option', async () => {
    const wrapper = mount(SegmentedButton, { props: { modelValue: 'a', options: [{ value: 'a', label: 'A' }, { value: 'b', label: 'B' }], 'onUpdate:modelValue': (v: string) => wrapper.setProps({ modelValue: v }) } });
    const buttons = wrapper.findAll('button');
    expect(buttons[0].attributes('aria-checked')).toBe('true');
    await buttons[1].trigger('click');
    await nextTick();
    expect(wrapper.findAll('button')[1].attributes('aria-checked')).toBe('true');
  });

  it('Breadcrumbs emits the crumb value and marks the last as current', async () => {
    const wrapper = mount(Breadcrumbs, { props: { crumbs: [{ label: 'root', value: '' }, { label: 'a', value: 'a' }, { label: 'b', value: 'a/b' }] } });
    await wrapper.findAll('button')[1].trigger('click');
    expect(wrapper.emitted('navigate')?.[0]).toEqual(['a']);
    expect(wrapper.find('[aria-current="location"]').text()).toBe('b');
  });

  it('Chip toggles and removes', async () => {
    const wrapper = mount(Chip, { props: { label: 'favorite', removable: true, count: 3 } });
    await wrapper.trigger('click');
    expect(wrapper.emitted('click')).toHaveLength(1);
    await wrapper.find('button').trigger('click');
    expect(wrapper.emitted('remove')).toHaveLength(1);
    expect(wrapper.emitted('click')).toHaveLength(1);
    expect(wrapper.text()).toContain('3');
  });

  it('EmptyState renders title and text', () => {
    const wrapper = mount(EmptyState, { props: { icon: Blossom, title: 'Nothing', text: 'here' } });
    expect(wrapper.text()).toContain('Nothing');
    expect(wrapper.text()).toContain('here');
  });

  it('ExpansionPanel shows its content only when open, and reports the change', async () => {
    const wrapper = mount(ExpansionPanel, { props: { label: 'Model card' }, slots: { default: '<p>body</p>' } });
    const header = wrapper.find('button');
    expect(header.attributes('aria-expanded')).toBe('false');
    expect(wrapper.text()).not.toContain('body');

    await header.trigger('click');
    await nextTick();
    expect(header.attributes('aria-expanded')).toBe('true');
    expect(wrapper.text()).toContain('body');
    expect(wrapper.emitted('update:open')?.[0]).toEqual([true]);
    // The header labels the region it opens, so a screen reader announces the pair.
    expect(wrapper.find('[role="region"]').attributes('aria-labelledby')).toBe(header.attributes('id'));
  });

  it('snackbar queue shows one message at a time', () => {
    const s = useSnackbar();
    s.show('one');
    s.show('two', { actionLabel: 'Undo' });
    expect(s.state.queue.map((m) => m.text)).toEqual(['one', 'two']);
    s.dismiss(s.state.queue[0].id);
    expect(s.state.queue[0].text).toBe('two');
    expect(s.state.queue[0].timeout).toBe(6000);
    s.dismiss(s.state.queue[0].id);
  });
});

describe('layers', () => {
  const press = (key: string, init: KeyboardEventInit = {}) => document.dispatchEvent(new KeyboardEvent('keydown', { key, cancelable: true, ...init }));
  const escape = () => press('Escape');
  const Layer = defineComponent({
    setup(_, { expose }) {
      const open = ref(true);
      const { isTop } = useLayer(
        () => open.value,
        closeOnEscape(() => (open.value = false)),
      );
      expose({ open, isTop });
      return () => null;
    },
  });

  it('closes only the topmost layer on Escape, the one under it next', () => {
    // The viewer, then a delete dialog opened from it.
    const viewer = mount(Layer);
    const dialog = mount(Layer);
    const v = viewer.vm as unknown as { open: boolean; isTop: () => boolean };
    const d = dialog.vm as unknown as { open: boolean; isTop: () => boolean };
    expect(d.isTop()).toBe(true);
    expect(v.isTop()).toBe(false);
    escape();
    expect([v.open, d.open]).toEqual([true, false]);
    expect(v.isTop()).toBe(true);
    escape();
    expect(v.open).toBe(false);
    expect(layerOpen()).toBe(false);
    viewer.unmount();
    dialog.unmount();
  });

  it('leaves the stack when unmounted open', () => {
    const wrapper = mount(Layer);
    expect(layerOpen()).toBe(true);
    wrapper.unmount();
    expect(layerOpen()).toBe(false);
  });

  /** A layer recording the keys it is handed, open while ``active`` holds. */
  const probe = (active = ref(true)) => {
    const seen: string[] = [];
    const wrapper = mount(
      defineComponent({
        setup() {
          useLayer(
            () => active.value,
            (e) => seen.push(e.key),
          );
          return () => null;
        },
      }),
    );
    return { seen, wrapper, active };
  };

  it('hands every key to the topmost layer alone', () => {
    const under = probe();
    const over = probe();
    press('ArrowRight');
    over.active.value = false;
    press('Delete');
    expect(over.seen).toEqual(['ArrowRight']);
    expect(under.seen).toEqual(['Delete']);
    under.wrapper.unmount();
    over.wrapper.unmount();
  });

  it('puts a layer back on top when it opens again, and forgets it once closed or gone', () => {
    const first = probe();
    const second = probe();
    first.active.value = false;
    first.active.value = true;
    press('a');
    first.active.value = false;
    first.wrapper.unmount();
    press('b');
    second.wrapper.unmount();
    press('c');
    expect(first.seen).toEqual(['a']);
    expect(second.seen).toEqual(['b']);
    expect(layerOpen()).toBe(false);
  });

  it('leaves a key that a control inside the layer already claimed', () => {
    const { seen, wrapper } = probe();
    const event = new KeyboardEvent('keydown', { key: 'Escape', cancelable: true });
    event.preventDefault();
    document.dispatchEvent(event);
    expect(seen).toEqual([]);
    wrapper.unmount();
  });

  it('keeps Tab cycling inside a container and brings stray focus back in', () => {
    const outside = document.createElement('button');
    const box = document.createElement('div');
    box.innerHTML = '<button id="a"></button><button disabled></button><input id="b" />';
    document.body.append(outside, box);
    const tab = (shiftKey = false) => {
      const event = new KeyboardEvent('keydown', { key: 'Tab', shiftKey, cancelable: true });
      trapFocus(event, box);
      return event.defaultPrevented;
    };
    box.querySelector<HTMLElement>('#b')!.focus();
    expect(tab()).toBe(true);
    expect(document.activeElement?.id).toBe('a');
    expect(tab(true)).toBe(true);
    expect(document.activeElement?.id).toBe('b');
    outside.focus();
    tab();
    expect(document.activeElement?.id).toBe('a');
    outside.remove();
    box.remove();
  });

  it('closes one of two stacked dialogs per Escape, the newer first', async () => {
    // Material's buttons need ElementInternals, which happy-dom lacks.
    const global = { stubs: { IconButton: { props: ['label'], template: '<button type="button" :aria-label="label" />' } } };
    const outer = ref(true);
    const inner = ref(false);
    const wrapper = mount(
      defineComponent({
        setup: () => () => [
          h(AppDialog, { open: outer.value, 'onUpdate:open': (v: boolean) => (outer.value = v), title: 'Outer' }, () => 'outer'),
          h(AppDialog, { open: inner.value, 'onUpdate:open': (v: boolean) => (inner.value = v), title: 'Inner' }, () => 'inner'),
        ],
      }),
      { attachTo: document.body, global },
    );
    inner.value = true;
    await nextTick();
    escape();
    await nextTick();
    expect([outer.value, inner.value]).toEqual([true, false]);
    escape();
    await nextTick();
    expect(outer.value).toBe(false);
    wrapper.unmount();
  });
});

describe('motion helpers', () => {
  it('staggers by 20ms up to a cap', () => {
    expect(staggerStyle(2)['--stagger']).toBe('40ms');
    expect(staggerStyle(100)['--stagger']).toBe('240ms');
  });
  it('container transition starts from the card rectangle', () => {
    const style = containerFrom(new DOMRect(10, 20, 100, 200), new DOMRect(0, 0, 400, 400));
    expect(style['--from-transform']).toBe('translate(10px, 20px) scale(0.25, 0.5)');
    expect(containerFrom(null, new DOMRect(0, 0, 1, 1))).toEqual({});
  });
});

describe('theme', () => {
  it('generates every role as a hex colour, different in light and dark', () => {
    const light = generateScheme(DEFAULT_SOURCE_COLOR, false);
    const dark = generateScheme(DEFAULT_SOURCE_COLOR, true);
    expect(light.primary).toMatch(/^#[0-9a-f]{6}$/);
    expect(light.surface).not.toBe(dark.surface);
    expect(generateScheme('not a colour', false).primary).toBe(generateScheme(DEFAULT_SOURCE_COLOR, false).primary);
  });
  it('maps widths to window size classes', () => {
    expect([599, 600, 839, 840, 1199, 1200, 1600].map(windowClass)).toEqual(['compact', 'medium', 'medium', 'expanded', 'expanded', 'large', 'extra-large']);
  });
});

describe('i18n and formatting', () => {
  it('translates with parameters and falls back to English', () => {
    expect(translate('zh-CN', 'selection.selected', { n: 3 })).toBe('已选择 3 项');
    expect(translate('ja', 'selection.selected', { n: 3 })).toBe('3 件を選択中');
    expect(translate('en', 'selection.selected', { n: 3 })).toBe('3 selected');
    expect(translate('en', 'no.such.key')).toBe('no.such.key');
    expect(translateList('zh-CN', 'stats.days')).toHaveLength(7);
    expect(translateList('ja', 'stats.days')).toEqual(['日', '月', '火', '水', '木', '金', '土']);
  });
  it('formats sizes and paths', () => {
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(null)).toBe('—');
    expect(pathSegments('a/b/c').map((s) => s.path)).toEqual(['a', 'a/b', 'a/b/c']);
    expect(parentPath('a/b/c')).toBe('a/b');
  });
});

describe('navigation', () => {
  async function mountRail() {
    const { createRouter, createMemoryHistory } = await import('vue-router');
    const { default: NavigationRail } = await import('@/ui/NavigationRail.vue');
    const { Settings } = await import('@/ui/icons');
    const view = { template: '<div />' };
    const router = createRouter({ history: createMemoryHistory(), routes: ['/a', '/b', '/settings'].map((path) => ({ path, component: view })) });
    await router.push('/settings');
    const items = [{ to: '/a', label: 'A', icon: Settings }, { to: '/b', label: 'B', icon: Settings }];
    return mount(NavigationRail, { props: { items, footer: [{ to: '/settings', label: 'Settings', icon: Settings }] }, global: { plugins: [router] } });
  }

  it('keeps the footer (Settings) out of the scrolling destinations, at the foot of the rail', async () => {
    const rail = await mountRail();
    const parts = rail.find('nav').element.children;
    expect([...parts].map((el) => el.className)).toEqual(['top', 'dests', 'foot']);
    expect(rail.find('.dests').text()).not.toContain('Settings');
    expect(rail.find('.foot a').attributes('aria-current')).toBe('page');
  });
});
