/** @vitest-environment happy-dom */
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { WORKBENCH_LAYOUT_IDS } from '../../components/layout/workbenchLayoutIds';
import { TeamWorkspaceFrame } from './TeamWorkspaceFrame';

describe('shared Teams workspace frame', () => {
  it('keeps the team picker and actions in their owning panel headers', () => {
    const host = document.createElement('div');
    host.innerHTML = renderToStaticMarkup(
      <TeamWorkspaceFrame
        title="流程画布"
        layoutId={WORKBENCH_LAYOUT_IDS.teams}
        railTitle={<span>团队选择</span>}
        rail={<p>团队导航</p>}
        toolbar={<button data-testid="frame-action">刷新</button>}
        canvas={<p>真实画布</p>}
        inspectorTitle="节点详情"
        inspector={<p>真实详情</p>}
      />,
    );

    expect(host.querySelectorAll('[data-team-panel]')).toHaveLength(3);
    expect(
      host.querySelector('[data-team-panel="navigation"] [data-vui="team-workspace-panel-header"]')?.textContent,
    ).toContain('团队选择');
    expect(
      host.querySelector('[data-team-panel="content"] [data-vui="team-workspace-panel-header"] [data-testid="frame-action"]'),
    ).not.toBeNull();
    expect(host.querySelector('[data-vui="canvas-workbench-toolbar"]')).toBeNull();
    expect(host.querySelector('[data-team-panel="inspector"]')?.textContent).toContain('真实详情');
  });

  it('uses rail surfaces around one flat chat panel with the shared canvas layout', () => {
    const host = document.createElement('div');
    host.innerHTML = renderToStaticMarkup(
      <TeamWorkspaceFrame
        title="流程画布"
        layoutId={WORKBENCH_LAYOUT_IDS.teams}
        railTitle="团队选择"
        rail={<p>团队导航</p>}
        canvas={<p>真实画布</p>}
        inspectorTitle="节点详情"
        inspector={<p>真实详情</p>}
      />,
    );

    const page = host.querySelector<HTMLElement>('[data-vui="workbench-page"]');
    expect(page?.className).toContain('!bg-vui-surface-rail');
    expect(page?.className).toContain('[--shell-surface:var(--vui-surface-rail)]');
    expect(page?.className).toContain('!p-1');
    expect(page?.className).not.toContain('!p-3');

    const workspace = host.querySelector<HTMLElement>('[data-vui="split-workspace"]');
    expect(workspace?.getAttribute('data-vui-layout-id')).toBe(WORKBENCH_LAYOUT_IDS.teams);
    expect(workspace?.className).toContain('[&>[data-vui=split-main]]:mx-1');

    for (const region of ['navigation', 'inspector']) {
      const panel = host.querySelector<HTMLElement>(`[data-team-panel="${region}"]`);
      expect(panel?.className).toContain('!bg-vui-surface-rail');
      expect(panel?.className).toContain('!rounded-none');
      expect(panel?.className).toContain('!border-0');
      expect(panel?.className).not.toContain('--shell-surface:var(--vui-surface-chat)');
    }

    const content = host.querySelector<HTMLElement>('[data-team-panel="content"]');
    expect(content?.className).toContain('--shell-surface:var(--vui-surface-chat)');
    expect(content?.className).toContain('--vui-surface-panel:var(--vui-surface-chat)');
    expect(content?.className).toContain('rounded-[var(--vui-radius-panel-soft)]');
    expect(content?.className).toContain('shadow-none');
    expect(content?.getAttribute('data-elevation')).toBe('flat');
  });

  it('keeps the team switcher available when there is no current experiment', () => {
    const host = document.createElement('div');
    host.innerHTML = renderToStaticMarkup(
      <TeamWorkspaceFrame title="流程画布" railTitle="团队选择" canvas={<p>先选择研究题目</p>} />,
    );

    expect(host.querySelector('[data-team-panel="navigation"]')?.textContent).toContain('团队选择');
    expect(host.querySelector('[data-team-panel="content"]')?.textContent).toContain('先选择研究题目');
    expect(host.querySelector('[data-team-panel="inspector"]')).toBeNull();
  });
});
