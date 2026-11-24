import type { UseMutationResult } from "@tanstack/react-query";
import type { LoginType, useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

export const useLoginUser: useMutationFunctionType<undefined, LoginType> = (
  options?,
) => {
  const { mutate, queryClient } = UseRequestProcessor();

  async function loginUserFn({ password, username }: LoginType): Promise<any> {
    const res = await api.post(
      `${getURL("LOGIN")}`,
      new URLSearchParams({
        username: username,
        password: password,
      }).toString(),
      {
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
        },
      },
    );
    return res.data;
  }

  const mutation: UseMutationResult<LoginType, any, LoginType> = mutate(
    ["useLoginUser"],
    loginUserFn,
    {
      retry: false,
      ...options,
      onSuccess: async (...args) => {
        // Clear all cache to prevent data from previous user
        queryClient.clear();
        // Critical bootstrap must be a mutation lifecycle callback, not a
        // per-call observer callback that can disappear when cache clearing
        // causes the login page to unmount.
        await options?.onSuccess?.(...args);
      },
      onSettled: async (...args) => {
        queryClient.refetchQueries({ queryKey: ["useGetFolders"] });
        queryClient.refetchQueries({ queryKey: ["useGetTags"] });
        await options?.onSettled?.(...args);
      },
    },
  );

  return mutation;
};
