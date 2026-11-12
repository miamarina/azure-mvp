import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {sourceLink, stamp, chapterSegments, markdown, searchLibrary, uploadRecording} from '../web/lib.mjs';

const sample = JSON.parse(readFileSync(new URL('../sample/lectures/vectors-sample.json', import.meta.url)));

test('all transcript segments appear exactly once under chapters', () => {
  const segments = sample.notes.chapters.flatMap((_, i) => chapterSegments(sample, i));
  assert.deepEqual(segments.map(s => s.id), sample.transcript.segments.map(s => s.id));
});

test('absolute links include excerpt offset and retain long-video times', () => {
  assert.match(sourceLink(sample.job.source_url, 15.9, 2520), /t=2535s/);
  assert.equal(sourceLink('https://example.com/lecture.mp4', 2520), 'https://example.com/lecture.mp4#t=2520');
  assert.equal(stamp(2520), '42:00');
  assert.throws(() => sourceLink('javascript:alert(1)', 0));
});

test('Markdown retains the full transcript, attribution and working timestamp URLs', () => {
  const text = markdown(sample);
  for (const segment of sample.transcript.segments) assert.ok(text.includes(segment.text));
  assert.match(text, /3Blue1Brown/);
  assert.match(text, /https:\/\/www.youtube.com\/watch\?v=fNk_zzaMoSs&t=30s/);
  assert.match(text, /Saved example/);
});

test('keyword search is literal and case-insensitive across saved transcripts', () => {
  assert.equal(searchLibrary([sample], 'PHYSICS').length, 2);
  assert.equal(searchLibrary([sample], '   ').length, 0);
  assert.equal(searchLibrary([sample], 'not present').length, 0);
});

test('gateway or lost responses retry the identical upload and accept the saved duplicate', async () => {
  const body = new Blob(['recording']), headers = {'X-Filename':'lecture.mp4'};
  const attempts = [], notices = [];
  const result = await uploadRecording('https://example.com/jobs?trial=one', {method:'POST',body,headers},
    attempt => notices.push(attempt), async (url, options) => {
      attempts.push({url, ...options});
      if (attempts.length === 1) return new Response('', {status:503});
      if (attempts.length === 2) throw new DOMException('Lost response', 'TimeoutError');
      return Response.json({id:'same-job',duplicate:true});
    });
  assert.equal(result.duplicate, true);
  assert.deepEqual(notices, [2,3]);
  for (const attempt of attempts) {
    assert.equal(attempt.url, 'https://example.com/jobs?trial=one');
    assert.equal(attempt.body, body);
    assert.equal(attempt.headers, headers);
  }
});

test('upload retries stop after three gateway failures', async () => {
  let calls = 0;
  await assert.rejects(uploadRecording('https://example.com/jobs', {}, () => {}, async () => {
    calls++; return new Response('', {status:503});
  }), /503/);
  assert.equal(calls, 3);
});

test('validation and application errors are returned without automatic resubmission', async () => {
  for (const status of [400,413,429,500]) {
    let calls = 0;
    await assert.rejects(uploadRecording('https://example.com/jobs', {}, () => {}, async () => {
      calls++; return Response.json({error:'Review this job'}, {status});
    }), /Review this job/);
    assert.equal(calls, 1);
  }
});
