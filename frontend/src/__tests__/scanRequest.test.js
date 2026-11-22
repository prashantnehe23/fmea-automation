import { describe, it, expect, vi, afterEach } from 'vitest';
import { streamGithubScan, streamScan } from '../api';

function fakeFetch() {
  const calls = [];
  vi.stubGlobal('fetch', vi.fn(async (url, init) => {
    calls.push({ url, body: JSON.parse(init.body) });
    return { ok: true, body: { getReader: () => ({ read: async () => ({ done: true }) }) } };
  }));
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

describe('scan requests', () => {
  it('ask for the ordinary brainstorm unless the deep scan is chosen', async () => {
    const calls = fakeFetch();
    for await (const _ of streamGithubScan('https://github.com/a/b')) { /* drain */ }
    for await (const _ of streamScan('code')) { /* drain */ }
    expect(calls.map(c => c.body.discovery)).toEqual(['scenarios', 'scenarios']);
  });

  it('ask for exploit paths when the deep scan is chosen, for a repository and for pasted code', async () => {
    const calls = fakeFetch();
    for await (const _ of streamGithubScan('https://github.com/a/b', null, null, false, null, undefined, 'paths')) { /* drain */ }
    for await (const _ of streamScan('code', null, null, false, 'paths')) { /* drain */ }
    expect(calls.map(c => c.body.discovery)).toEqual(['paths', 'paths']);
  });
});
