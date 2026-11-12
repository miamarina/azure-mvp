export function stamp(seconds) {
  const n = Math.max(0, Math.floor(Number(seconds) || 0));
  return `${Math.floor(n / 60).toString().padStart(2, '0')}:${(n % 60).toString().padStart(2, '0')}`;
}

export function sourceLink(source, seconds, offset = 0) {
  const url = new URL(source);
  const n = Number(seconds) + Number(offset);
  if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || !Number.isFinite(n) || n < 0) {
    throw new Error('Invalid source link.');
  }
  if (['youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'].includes(url.hostname)) {
    url.searchParams.delete('start');
    url.searchParams.set('t', `${Math.floor(n)}s`);
    url.hash = '';
  } else {
    url.hash = `t=${Math.floor(n)}`;
  }
  return url.href;
}

export function youtubeId(source) {
  const url = new URL(source);
  const id = url.hostname === 'youtu.be' ? url.pathname.slice(1) :
    ['youtube.com', 'www.youtube.com', 'm.youtube.com'].includes(url.hostname) ? url.searchParams.get('v') : null;
  return id && /^[A-Za-z0-9_-]{11}$/.test(id) ? id : null;
}

export function chapterSegments(value, index) {
  const start = value.notes.chapters[index].segment_index;
  const end = value.notes.chapters[index + 1]?.segment_index ?? value.transcript.segments.length;
  return value.transcript.segments.slice(start, end);
}

const escape = text => String(text).replace(/[\\`*_[\]<>#]/g, '\\$&');
const destination = url => url.replace(/\(/g, '%28').replace(/\)/g, '%29');

export function markdown(value) {
  const {job, transcript, notes} = value;
  const link = seconds => `[${stamp(seconds + Number(job.source_offset_seconds || 0))}](${destination(sourceLink(job.source_url, seconds, job.source_offset_seconds || 0))})`;
  let text = `# ${escape(job.title)}\n\n${escape(job.attribution || '')}\n\nSource: ${job.source_url}\n`;
  if (job.sample) text += '\nSaved example; no new processing was performed.\n';
  text += '\n## Overview\n\n' + notes.overview.map(p => `- ${escape(p.text)} ${link(p.start)}`).join('\n');
  notes.chapters.forEach((chapter, i) => {
    text += `\n\n## ${escape(chapter.title)}\n\n`;
    text += chapterSegments(value, i).map(s => `${link(s.start)} ${escape(s.text)}`).join('\n\n');
  });
  if (notes.key_terms.length) {
    text += '\n\n## Key terms\n\n' + notes.key_terms.map(t => `- **${escape(t.term)}:** ${escape(t.definition)} ${link(t.start)}`).join('\n');
  }
  return text + '\n';
}

export function searchLibrary(values, query) {
  const normalized = query.trim().toLocaleLowerCase();
  if (!normalized) return [];
  return values.flatMap(value => (value.transcript?.segments || [])
    .filter(s => s.text.toLocaleLowerCase().includes(normalized))
    .map(segment => ({id: value.job.id, title: value.job.title, segment})));
}

// The upload handler deduplicates identical bytes/language/trial before queuing.
// Reuse exactly the same request when a cold start loses its response.
export async function uploadRecording(url, options, onRetry = () => {}, fetcher = fetch) {
  for (let attempt = 0; attempt < 3; attempt++) {
    let response;
    try {
      response = await fetcher(url, {...options, signal:AbortSignal.timeout(120000)});
    } catch (error) {
      if (attempt === 2 || !['TypeError', 'TimeoutError', 'AbortError'].includes(error.name)) throw error;
      onRetry(attempt + 2);
      continue;
    }
    if ([502, 503, 504].includes(response.status) && attempt < 2) {
      onRetry(attempt + 2);
      continue;
    }
    const value = await response.json().catch(() => null);
    if (!response.ok) throw new Error(value?.error || `The upload failed (${response.status}). Try again with the same recording and Trial ID.`);
    if (!value?.id) throw new Error('The service returned an unreadable response. Retry the same recording and Trial ID.');
    return value;
  }
}
