import { useEffect, useReducer } from "react";
import {
  initialStudioState,
  restoreStudioState,
  STORAGE_KEY,
  studioReducer,
} from "./model";

export function useStudio() {
  const [state, dispatch] = useReducer(studioReducer, null, () => {
    try {
      return restoreStudioState(window.localStorage.getItem(STORAGE_KEY));
    } catch {
      return initialStudioState();
    }
  });
  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      // Storage being unavailable must not interrupt the recording flow.
    }
  }, [state]);
  useEffect(() => {
    if (!state.generating) return;
    const timer = window.setTimeout(
      () => dispatch({ type: "GENERATED" }),
      1800,
    );
    return () => window.clearTimeout(timer);
  }, [state.generating]);
  useEffect(() => {
    if (state.run.status !== "running") return;
    const timer = window.setInterval(() => dispatch({ type: "TICK" }), 1000);
    return () => window.clearInterval(timer);
  }, [state.run.status]);
  return { state, dispatch };
}
