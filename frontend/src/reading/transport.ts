import type { CanonicalReading, CommitIntent, OpenIntent, ReadingRecord } from './model.ts';
type Request = (url: string, options: RequestInit) => Promise<CanonicalReading>;
// This header asserts freshness only. The server derives authorization from
// its authenticated session and rejects a missing/mismatched account identity.
export function readingTransport(request: Request) {
  const headers = (account: string) => ({ 'X-MReader-Account-ID': account });
  const path = (series: string, chapter: string) => `/api/progress/${encodeURIComponent(series)}/${encodeURIComponent(chapter)}`;
  const open = (account: string, series: string, chapter: string, body: OpenIntent) =>
    request(`${path(series, chapter)}/open`, { method: 'POST', headers: headers(account), body: JSON.stringify(body), signal: AbortSignal.timeout(20_000) });
  const commit = (account: string, series: string, chapter: string, body: CommitIntent, keepalive = false) =>
    request(`${path(series, chapter)}/commit`, { method: 'POST', headers: headers(account), body: JSON.stringify(body), keepalive, signal: AbortSignal.timeout(20_000) });
  return {
    getProgress: (account: string, series: string, chapter: string) =>
      request(path(series, chapter), { headers: headers(account), signal: AbortSignal.timeout(10_000) }),
    open, commit,
    send: (account: string, record: ReadingRecord) => {
      const command = record.command!;
      return command.kind === 'open' ? open(account, record.target.series_slug, record.target.chapter_slug, command.body)
        : commit(account, record.target.series_slug, record.target.chapter_slug, command.body, true);
    },
  };
}
