import { useCallback, useEffect, useRef, useState } from 'react';

/** Load data from the API; `reload()` re-fetches. Optional polling while `pollWhile(data)` is true. */
export function useApi(loader, deps = [], { pollWhile, intervalMs = 3000 } = {}) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  const reload = useCallback(async () => {
    try {
      setData(await loaderRef.current());
      setError('');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    if (!pollWhile || !data || !pollWhile(data)) return undefined;
    const timer = setTimeout(reload, intervalMs);
    return () => clearTimeout(timer);
  }, [data, pollWhile, intervalMs, reload]);

  return { data, error, loading, reload, setData };
}

/** Run an async action with loading/error state. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const run = useCallback(async (fn) => {
    setBusy(true);
    setError('');
    try {
      return await fn();
    } catch (err) {
      setError(err.message);
      return undefined;
    } finally {
      setBusy(false);
    }
  }, []);
  return { busy, error, run, setError };
}
