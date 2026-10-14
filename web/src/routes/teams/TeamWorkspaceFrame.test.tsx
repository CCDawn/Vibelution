/** @vitest-environment happy-dom */
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { TeamWorkspaceFrame } from './TeamWorkspaceFrame';
describe('shared Teams workspace frame',()=>{
 it('keeps the team picker and actions in their owning panel headers',()=>{
  const host=document.createElement('div');
  host.innerHTML=renderToStaticMarkup(<TeamWorkspaceFrame title="流程画布" railTitle={<span>团队选择</span>} rail={<p>团队导航</p>} toolbar={<button data-testid="frame-action">刷新</button>} canvas={<p>真实画布</p>} inspectorTitle="节点详情" inspector={<p>真实详情</p>} />);
  expect(host.querySelectorAll('[data-team-panel]')).toHaveLength(3);
  expect(host.querySelector('[data-team-panel="navigation"] [data-vui="team-workspace-panel-header"]')?.textContent).toContain('团队选择');
  expect(host.querySelector('[data-team-panel="content"] [data-vui="team-workspace-panel-header"] [data-testid="frame-action"]')).not.toBeNull();
  expect(host.querySelector('[data-vui="canvas-workbench-toolbar"]')).toBeNull();
  expect(host.querySelector('[data-team-panel="inspector"]')?.textContent).toContain('真实详情');
 });
 it('keeps the team switcher available when there is no current experiment',()=>{
  const host=document.createElement('div');host.innerHTML=renderToStaticMarkup(<TeamWorkspaceFrame title="流程画布" railTitle="团队选择" canvas={<p>先选择研究题目</p>} />);
  expect(host.querySelector('[data-team-panel="navigation"]')?.textContent).toContain('团队选择');
  expect(host.querySelector('[data-team-panel="content"]')?.textContent).toContain('先选择研究题目');
  expect(host.querySelector('[data-team-panel="inspector"]')).toBeNull();
 });
});
