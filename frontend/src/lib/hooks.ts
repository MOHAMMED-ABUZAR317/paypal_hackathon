import { useCallback, useEffect, useRef, useState } from "react";
import { safeMessage } from "./format";

type ApiState<T> = {
  data: T | null;
  loading: boolean;
  error: string | null;
};

/**
 * Small data loader with an explicit reload. Deliberately simple: the demo has
 * six pages and no shared cache, so a fetch-on-mount plus optimistic refresh
 * after each action is easier to reason about than a query library.
 */
export function useApi<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  const [state, setState] = useState<ApiState<T>>({
    data: null,
    loading: true,
    error: null,
  });
  const mounted = useRef(true);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const reload = useCallback(async () => {
    setState((previous) => ({ ...previous, loading: true, error: null }));
    try {
      const data = await loaderRef.current();
      if (mounted.current) {
        setState({ data, loading: false, error: null });
      }
      return data;
    } catch (error) {
      if (mounted.current) {
        setState((previous) => ({
          ...previous,
          loading: false,
          error: safeMessage(error),
        }));
      }
      return null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { ...state, reload, setData: (data: T) => setState({ data, loading: false, error: null }) };
}

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window !== "undefined" ? window.matchMedia(query).matches : false,
  );

  useEffect(() => {
    const media = window.matchMedia(query);
    const listener = (event: MediaQueryListEvent) => setMatches(event.matches);
    media.addEventListener("change", listener);
    setMatches(media.matches);
    return () => media.removeEventListener("change", listener);
  }, [query]);

  return matches;
}
