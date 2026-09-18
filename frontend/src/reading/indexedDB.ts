import { emptyState, type ReadingState, type ReadingStore } from './repository.ts';
export class IndexedReadingStore implements ReadingStore {
  private database: Promise<IDBDatabase> | undefined;
  private changed: (scope: string, confirmed: boolean) => void;
  constructor(changed: (scope: string, confirmed: boolean) => void) { this.changed = changed; }
  private db() {
    if (!this.database) this.database = new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('mreader-reading-v1', 1);
      request.onupgradeneeded = () => { request.result.createObjectStore('accounts'); };
      request.onerror = () => { this.database = undefined; reject(request.error); };
      request.onblocked = () => { this.database = undefined; reject(new Error('Reading storage is blocked by another tab')); };
      request.onsuccess = () => { request.result.onversionchange = () => { request.result.close(); this.database = undefined; }; resolve(request.result); };
    });
    return this.database;
  }
  async transact(scope: string, change: (state: ReadingState) => ReadingState): Promise<ReadingState> {
    const db = await this.db();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('accounts', 'readwrite');
      const store = tx.objectStore('accounts');
      const read = store.get(scope);
      let result = emptyState();
      let changed = false;
      let confirmed = false;
      let failure: unknown;
      read.onsuccess = () => {
        try {
          const before = read.result || emptyState();
          const serialized = JSON.stringify(before);
          const priorConfirmed = JSON.stringify(before.confirmed);
          result = change(before);
          changed = JSON.stringify(result) !== serialized;
          confirmed = JSON.stringify(result.confirmed) !== priorConfirmed;
          if (changed) store.put(result, scope);
        } catch (error) { failure = error; tx.abort(); }
      };
      tx.oncomplete = () => { if (changed) this.changed(scope, confirmed); resolve(result); };
      tx.onerror = tx.onabort = () => reject(failure || tx.error || new Error('Reading storage failed'));
    });
  }
}
