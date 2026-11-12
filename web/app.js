import {stamp, sourceLink, youtubeId, chapterSegments, markdown, searchLibrary, uploadRecording} from './lib.mjs';

const $ = id => document.getElementById(id);
const config = window.STUDYNOTES_CONFIG || {};
const apiBase = (config.apiBase || '').replace(/\/$/, '');
const cache = new Map();
let lectures = [], selected = null, current = null, loading = false, toastTimer;
let searchVersion = 0;
const element = (tag, value, className) => {
  const node = document.createElement(tag);
  node.textContent = value;
  if (className) node.className = className;
  return node;
};

function toast(message) {
  $('toast').textContent = message; $('toast').hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => {$('toast').hidden = true;}, 6000);
}

async function json(url, options = {}) {
  const response = await fetch(url, {...options, cache:'no-store', signal:AbortSignal.timeout(120000)});
  const value = await response.json().catch(() => ({error:'The service returned an unreadable response.'}));
  if (!response.ok) throw new Error(value.error || `The request failed (${response.status}).`);
  return value;
}

function renderLibrary() {
  $('lecture-count').textContent = lectures.length;
  $('library').replaceChildren();
  for (const lecture of lectures) {
    const job = cache.get(lecture.id)?.job;
    const button = element('button', '', 'lecture' + (lecture.id === selected ? ' active' : ''));
    button.append(element('strong', lecture.title), element('small', lecture.sample || job?.sample ? 'Saved example · 00:55' :
      job ? job.status === 'ready' ? `${stamp(job.duration_seconds)} · Ready to study` : job.stage : 'Lecture recording'));
    button.addEventListener('click', () => openLecture(lecture.id));
    $('library').append(button);
  }
}

async function loadLibrary() {
  lectures = (await json('./catalog.json')).lectures;
  renderLibrary();
  $('empty').hidden = lectures.length > 0;
  if (!selected && lectures.length) {
    const params = new URLSearchParams(location.hash.slice(1));
    const requested = params.get('lecture');
    const id = lectures.some(item => item.id === requested) ? requested : lectures[0].id;
    await openLecture(id, params.get('segment'));
  }
}

function timestamp(seconds) {
  const offset = Number(current.job.source_offset_seconds || 0);
  const a = element('a', stamp(seconds + offset), 'timestamp');
  a.href = sourceLink(current.job.source_url, seconds, offset);
  a.target = '_blank'; a.rel = 'noopener noreferrer';
  a.setAttribute('aria-label', `Watch original from ${stamp(seconds + offset)}`);
  a.addEventListener('click', event => {
    if (!event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {
      event.preventDefault(); play(seconds);
    }
  });
  return a;
}

function play(seconds = 0) {
  if (!current) return;
  const absolute = seconds + Number(current.job.source_offset_seconds || 0);
  const id = youtubeId(current.job.source_url);
  $('video-placeholder').hidden = true;
  if (id) {
    $('video').pause(); $('video').hidden = true;
    $('youtube').hidden = false;
    $('youtube').src = `https://www.youtube-nocookie.com/embed/${id}?start=${Math.floor(absolute)}&autoplay=1&rel=0`;
  } else {
    $('youtube').hidden = true; $('youtube').removeAttribute('src');
    const video = $('video'); video.hidden = false;
    if (!video.getAttribute('src')) video.src = current.job.source_url;
    const jump = () => {video.currentTime = absolute; video.play().catch(() => {});};
    if (video.readyState >= 1) jump(); else video.addEventListener('loadedmetadata', jump, {once:true});
  }
  $('source-link').href = sourceLink(current.job.source_url, seconds, current.job.source_offset_seconds || 0);
}

function resetPlayer() {
  $('youtube').removeAttribute('src'); $('youtube').hidden = true;
  $('video').pause(); $('video').removeAttribute('src'); $('video').hidden = true;
  $('video-placeholder').hidden = false;
}

function renderReader(value) {
  const {job, notes, transcript} = value;
  $('sample-note').hidden = !job.sample;
  $('segment-count').textContent = `${transcript.segments.length} passages`;
  $('duration').textContent = stamp(job.duration_seconds);
  $('attribution').textContent = job.attribution || '';
  $('source-link').href = job.source_url;
  $('overview').replaceChildren();
  for (const point of notes.overview) {
    const li = element('li', point.text); li.append(timestamp(point.start)); $('overview').append(li);
  }
  $('chapters').replaceChildren(); $('contents').replaceChildren();
  notes.chapters.forEach((chapter, i) => {
    const section = element('section', '', 'chapter'); section.id = `chapter-${i}`;
    section.append(element('h3', chapter.title));
    for (const segment of chapterSegments(value, i)) {
      const row = element('div', '', 'passage'); row.id = `passage-${segment.id}`;
      row.append(timestamp(segment.start), element('p', segment.text)); section.append(row);
    }
    $('chapters').append(section);
    const a = element('a', ''); a.href = `#chapter-${i}`;
    a.append(element('span', stamp(chapter.start + Number(job.source_offset_seconds || 0))), element('strong', chapter.title));
    a.addEventListener('click', event => {event.preventDefault(); section.scrollIntoView({behavior:'smooth',block:'start'});});
    $('contents').append(a);
  });
  $('terms-section').hidden = notes.key_terms.length === 0; $('terms').replaceChildren();
  for (const term of notes.key_terms) {
    const box = element('div', '', 'term');
    const heading = element('strong', term.term); heading.append(timestamp(term.start));
    box.append(heading, element('p', term.definition)); $('terms').append(box);
  }
}

async function openLecture(id, segmentId, quiet = false) {
  if (!quiet) {$('search').value = ''; $('search-results').hidden = true; resetPlayer();}
  selected = id;
  try {
    const cached = cache.get(id);
    const value = cached?.job.status === 'ready' ? cached : await json(`./lectures/${encodeURIComponent(id)}.json`);
    if (selected !== id) return;
    cache.set(id, value); current = value; renderLibrary();
    $('empty').hidden = true;
    $('page-title').textContent = value.job.title; $('breadcrumb').textContent = value.job.title;
    const ready = value.job.status === 'ready', failed = value.job.status === 'failed';
    $('page-subtitle').textContent = ready ? 'The whole explanation, with a path back to every moment.' : 'Your recording is becoming a searchable scriptum.';
    $('reader').hidden = !ready; $('download').hidden = !ready; $('progress-card').hidden = ready;
    $('progress-card').classList.toggle('failed', failed);
    $('progress-stage').textContent = value.job.stage;
    $('progress-detail').textContent = failed ? value.job.error : 'Processing happens in the background. This page updates automatically.';
    $('progress-animation').hidden = failed;
    const hash = new URLSearchParams({lecture:id}); if (segmentId) hash.set('segment', segmentId);
    history.replaceState(null, '', '#' + hash.toString());
    if (ready) {
      renderReader(value);
      if (segmentId) {
        const passage = document.getElementById(`passage-${segmentId}`);
        if (passage) {passage.scrollIntoView({behavior:'smooth',block:'center'}); passage.classList.add('highlight'); setTimeout(() => passage.classList.remove('highlight'), 4000);}
      }
    }
  } catch (error) {toast(error.message);}
}

function openUpload() {
  $('upload-error').textContent = apiBase ? '' : 'Local preview uses saved data. Deploy to Azure to enable uploads.';
  $('upload-submit').disabled = !apiBase;
  $('upload-hint').textContent = `Up to ${Math.floor((config.maxAudioSeconds || 5400) / 60)} minutes and ${Math.floor((config.maxUploadBytes || 209715200) / 1048576)} MiB. Use material the group may process and publish.`;
  $('upload-dialog').showModal();
}
for (const id of ['upload-open', 'empty-upload']) $(id).addEventListener('click', openUpload);
$('upload-close').addEventListener('click', () => $('upload-dialog').close());
$('load-video').addEventListener('click', () => play(0));
$('refresh').addEventListener('click', () => loadLibrary().catch(error => toast(error.message)));
$('file').addEventListener('change', () => {
  const file = $('file').files[0]; $('file-label').textContent = file?.name || 'Choose an audio or video file';
  if (file) $('lecture-title').value = file.name.replace(/\.[^.]+$/, '').replace(/[-_]/g, ' ');
});
$('upload-form').addEventListener('submit', async event => {
  event.preventDefault();
  const file = $('file').files[0], button = $('upload-submit');
  if (!apiBase || !file) return;
  if (file.size > (config.maxUploadBytes || 209715200)) {$('upload-error').textContent = 'The file exceeds this deployment’s size limit.'; return;}
  button.disabled = true; button.textContent = 'Uploading your recording…'; $('upload-error').textContent = '';
  try {
    const query = new URLSearchParams({locale:$('locale').value});
    if ($('trial').value.trim()) query.set('trial', $('trial').value.trim());
    const value = await uploadRecording(`${apiBase}/jobs?${query}`, {method:'POST', body:file, headers:{
      'Content-Type':'application/octet-stream', 'X-Filename':encodeURIComponent(file.name),
      'X-Title':encodeURIComponent($('lecture-title').value), 'X-Source-Url':encodeURIComponent($('source').value.trim()),
      'X-Source-Offset':String(Number($('source-offset').value || 0)), 'X-Attribution':encodeURIComponent($('credit').value)}},
      attempt => {button.textContent = `Connecting… retrying upload (${attempt}/3)`;});
    $('upload-dialog').close(); $('upload-form').reset(); $('file-label').textContent = 'Choose an audio or video file';
    await loadLibrary(); await openLecture(value.id);
    if (value.duplicate) toast('This recording is already in the library. Its saved job was reused.');
  } catch (error) {$('upload-error').textContent = error.message;}
  finally {button.disabled = false; button.textContent = 'Create scriptum →';}
});
$('download').addEventListener('click', () => {
  if (!current?.notes) return;
  const url = URL.createObjectURL(new Blob([markdown(current)], {type:'text/markdown;charset=utf-8'}));
  const a = document.createElement('a'); a.href = url;
  a.download = (current.job.title.replace(/[^\p{L}\p{N} ._-]/gu, '') || 'scriptum') + '.md';
  a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});
$('search').addEventListener('input', async () => {
  const query = $('search').value.trim(), version = ++searchVersion, target = $('search-results');
  if (!query) {target.hidden = true; return;}
  target.hidden = false; target.replaceChildren(element('p', 'Searching your lectures…', 'search-heading'));
  try {
    for (const lecture of lectures) {
      if (cache.get(lecture.id)?.job.status !== 'ready') cache.set(lecture.id, await json(`./lectures/${lecture.id}.json`));
      if (version !== searchVersion) return;
    }
    const matches = searchLibrary([...cache.values()], query);
    if (version !== searchVersion) return;
    target.replaceChildren(element('p', `${matches.length} matching passage${matches.length === 1 ? '' : 's'} across your lectures`, 'search-heading'));
    for (const match of matches.slice(0, 50)) {
      const b = element('button', '', 'search-result');
      b.append(element('strong', `${match.title} · ${stamp(match.segment.start + Number(cache.get(match.id).job.source_offset_seconds || 0))}`), element('p', match.segment.text));
      b.addEventListener('click', () => openLecture(match.id, match.segment.id)); target.append(b);
    }
  } catch (error) {if (version === searchVersion) target.replaceChildren(element('p', error.message, 'error'));}
});
setInterval(async () => {
  if (loading || document.hidden || !selected || !current || ['ready', 'failed'].includes(current.job.status)) return;
  loading = true; try {await openLecture(selected, null, true);} finally {loading = false;}
}, 4000);
loadLibrary().catch(error => {$('library').replaceChildren(element('p', 'The library could not be loaded.', 'muted small')); toast(error.message);});
