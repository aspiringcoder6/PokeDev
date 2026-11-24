import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { api } from "@/controllers/API/api";
import { useLoginUser } from "../use-post-login-user";

jest.mock("@/controllers/API/api", () => ({ api: { post: jest.fn() } }));

beforeEach(() => jest.clearAllMocks());

test("server-confirmed login completes its configured bootstrap even if the login page unmounts", async () => {
  const client = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const onSuccess = jest.fn();
  const onSettled = jest.fn();
  let resolveLogin!: (response: unknown) => void;
  (api.post as jest.Mock).mockReturnValue(
    new Promise((resolve) => { resolveLogin = resolve; }),
  );
  const { result, unmount } = renderHook(
    () => useLoginUser({ onSuccess, onSettled }),
    { wrapper },
  );
  act(() => result.current.mutate({ username: "fixture-user", password: "fixture-only" }));
  await waitFor(() => expect(api.post).toHaveBeenCalledTimes(1));
  unmount();
  act(() => resolveLogin({ data: { access_token: "fixture-response", refresh_token: "fixture-refresh" } }));
  await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
  expect(onSettled).toHaveBeenCalledTimes(1);
});

test("a rejected login never runs successful bootstrap and is not automatically retried", async () => {
  const client = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  const onSuccess = jest.fn();
  const onError = jest.fn();
  (api.post as jest.Mock).mockRejectedValue(new Error("fixture rejection"));
  const { result } = renderHook(() => useLoginUser({ onSuccess, onError }), { wrapper });
  act(() => result.current.mutate({ username: "fixture-user", password: "fixture-only" }));
  await waitFor(() => expect(onError).toHaveBeenCalledTimes(1));
  expect(onSuccess).not.toHaveBeenCalled();
  expect(api.post).toHaveBeenCalledTimes(1);
});
