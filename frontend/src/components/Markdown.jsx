/**
 * Minimal, dependency-free markdown for chat answers (B-025).
 *
 * Renders to React nodes only (never raw HTML), so model output cannot inject markup.
 * Supports: fenced code blocks (also while still streaming), headings, bullet / numbered
 * lists, tables (shown monospaced), **bold**, *italic* and `inline code`. Links are left as text.
 */

function inline(text, keyBase) {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*|\*[^*\s][^*]*\*)/g);
  return parts.map((part, i) => {
    const key = `${keyBase}-${i}`;
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2)
      return <code key={key} className="px-1 py-0.5 rounded bg-gray-100 text-gray-800 font-mono text-[0.85em]">{part.slice(1, -1)}</code>;
    if (part.startsWith('**') && part.endsWith('**') && part.length > 4)
      return <strong key={key}>{part.slice(2, -2)}</strong>;
    if (part.startsWith('*') && part.endsWith('*') && part.length > 2)
      return <em key={key}>{part.slice(1, -1)}</em>;
    return part;
  });
}

export default function Markdown({ text }) {
  const lines = (text ?? '').split('\n');
  const blocks = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.trimStart().startsWith('```')) {                       // fenced code (may be unclosed while streaming)
      const code = [];
      i++;
      while (i < lines.length && !lines[i].trimStart().startsWith('```')) code.push(lines[i++]);
      i++;
      blocks.push(
        <pre key={blocks.length} className="my-2 p-2.5 rounded-lg bg-gray-900 text-gray-100 text-[11px] leading-relaxed overflow-x-auto font-mono whitespace-pre">
          {code.join('\n')}
        </pre>
      );
      continue;
    }

    if (/^\s*\|/.test(line)) {                                       // table rows → monospaced block
      const rows = [];
      while (i < lines.length && /^\s*\|/.test(lines[i])) rows.push(lines[i++]);
      blocks.push(
        <pre key={blocks.length} className="my-2 p-2 rounded-lg bg-gray-50 border border-gray-100 text-[11px] overflow-x-auto font-mono whitespace-pre">
          {rows.join('\n')}
        </pre>
      );
      continue;
    }

    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) {
      blocks.push(<p key={blocks.length} className="mt-3 mb-1 font-bold text-gray-900">{inline(heading[2], `h${blocks.length}`)}</p>);
      i++;
      continue;
    }

    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {                          // list
      const ordered = /^\s*\d+\./.test(line);
      const items = [];
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i]))
        items.push(lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, ''));
      const Tag = ordered ? 'ol' : 'ul';
      blocks.push(
        <Tag key={blocks.length} className={`my-1.5 ml-4 space-y-0.5 ${ordered ? 'list-decimal' : 'list-disc'}`}>
          {items.map((it, k) => <li key={k}>{inline(it, `l${blocks.length}-${k}`)}</li>)}
        </Tag>
      );
      continue;
    }

    if (line.trim() === '') { i++; continue; }

    const para = [];                                                  // paragraph
    while (i < lines.length && lines[i].trim() !== '' && !lines[i].trimStart().startsWith('```')
           && !/^\s*([-*]|\d+\.)\s+/.test(lines[i]) && !/^\s*\|/.test(lines[i]) && !/^#{1,4}\s/.test(lines[i]))
      para.push(lines[i++]);
    blocks.push(<p key={blocks.length} className="my-1.5">{inline(para.join(' '), `p${blocks.length}`)}</p>);
  }

  return <div className="text-xs leading-relaxed text-gray-700 break-words">{blocks}</div>;
}
