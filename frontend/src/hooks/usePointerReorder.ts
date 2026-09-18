import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
} from 'react';

interface PointerReorderOptions<T extends { id: string }> {
  items: T[];
  disabled?: boolean;
  onPreview: (items: T[]) => void;
  onCommit: (orderedIds: string[]) => Promise<void>;
  onError?: (error: unknown) => void;
}

export function usePointerReorder<T extends { id: string }>({
  items,
  disabled = false,
  onPreview,
  onCommit,
  onError,
}: PointerReorderOptions<T>) {
  const [draggedId, setDraggedId] = useState<string | null>(null);

  const latestItemsRef = useRef<T[]>(items);
  const snapshotRef = useRef<T[]>([]);
  const dirtyRef = useRef(false);
  const previousUserSelectRef = useRef('');
  const previousCursorRef = useRef('');

  useEffect(() => {
    latestItemsRef.current = items;
  }, [items]);

  const restoreDocumentState = useCallback(() => {
    document.body.style.userSelect = previousUserSelectRef.current;
    document.body.style.cursor = previousCursorRef.current;
  }, []);

  const startReorder = useCallback(
    (event: ReactPointerEvent<HTMLElement>, itemId: string) => {
      if (disabled) return;

      const target = event.target as HTMLElement | null;
      if (
        target?.closest(
          'button, input, textarea, select, a, label, [data-no-reorder="true"]'
        )
      ) {
        return;
      }

      // Mouse button 0 = left, 2 = right.
      // Touch and pen normally report button 0.
      if (event.button !== 0 && event.button !== 2) return;

      event.preventDefault();

      snapshotRef.current = [...latestItemsRef.current];
      dirtyRef.current = false;

      previousUserSelectRef.current = document.body.style.userSelect;
      previousCursorRef.current = document.body.style.cursor;
      document.body.style.userSelect = 'none';
      document.body.style.cursor = 'grabbing';

      setDraggedId(itemId);
    },
    [disabled]
  );

  const enterReorderTarget = useCallback(
    (event: ReactPointerEvent<HTMLElement>, targetId: string) => {
      if (!draggedId || disabled) return;

      // Prevent a stale pointer-enter after the mouse button was released.
      if (event.pointerType === 'mouse' && event.buttons === 0) return;

      const current = latestItemsRef.current;
      const fromIndex = current.findIndex((item) => item.id === draggedId);
      const toIndex = current.findIndex((item) => item.id === targetId);

      if (
        fromIndex < 0 ||
        toIndex < 0 ||
        fromIndex === toIndex
      ) {
        return;
      }

      const next = [...current];
      const [moved] = next.splice(fromIndex, 1);
      next.splice(toIndex, 0, moved);

      latestItemsRef.current = next;
      dirtyRef.current = true;
      onPreview(next);
    },
    [disabled, draggedId, onPreview]
  );

  const finishReorder = useCallback(() => {
    if (!draggedId) return;

    const shouldCommit = dirtyRef.current;
    const orderedIds = latestItemsRef.current.map((item) => item.id);
    const snapshot = [...snapshotRef.current];

    dirtyRef.current = false;
    setDraggedId(null);
    restoreDocumentState();

    if (!shouldCommit) return;

    void (async () => {
      try {
        await onCommit(orderedIds);
      } catch (error) {
        latestItemsRef.current = snapshot;
        onPreview(snapshot);
        onError?.(error);
      }
    })();
  }, [
    draggedId,
    onCommit,
    onError,
    onPreview,
    restoreDocumentState,
  ]);

  useEffect(() => {
    if (!draggedId) return;

    const finish = () => finishReorder();

    window.addEventListener('pointerup', finish);
    window.addEventListener('pointercancel', finish);
    window.addEventListener('blur', finish);

    return () => {
      window.removeEventListener('pointerup', finish);
      window.removeEventListener('pointercancel', finish);
      window.removeEventListener('blur', finish);
    };
  }, [draggedId, finishReorder]);

  useEffect(
    () => () => {
      restoreDocumentState();
    },
    [restoreDocumentState]
  );

  return {
    draggedId,
    startReorder,
    enterReorderTarget,
    finishReorder,
  };
}
