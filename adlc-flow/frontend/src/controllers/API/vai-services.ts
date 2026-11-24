import { z } from "zod";
import { getBaseUrl } from "@/customization/utils/urls";
import { api } from "./api";

export const serviceNames = ["sandbox", "memory", "testforge"] as const;
export type VaiService = (typeof serviceNames)[number];
const check = z.object({
  check_id: z.string().uuid(),
  cycle_id: z.string().uuid(),
  service: z.enum(serviceNames),
  state: z.enum(["RESERVED", "RUNNING", "UNCONFIRMED", "SUCCEEDED", "FAILED"]),
  created_at: z.string(),
  updated_at: z.string(),
  verification_evidence: z.literal(false),
  summary: z.record(z.unknown()).optional(),
  steps: z
    .array(
      z.object({
        tool: z.string(),
        duration_ms: z.number(),
        result: z.unknown(),
      }),
    )
    .optional(),
  error_code: z.string().nullable().optional(),
  error: z.string().optional(),
  job_id: z.string().optional(),
  session_id: z.string().optional(),
  dataset: z.string().optional(),
});
const listing = z.object({
  capabilities: z
    .object({
      version: z.string(),
      services: z.record(
        z.object({
          available: z.boolean(),
          missing_tools: z.array(z.string()),
        }),
      ),
      allowed_targets: z.array(z.string()),
    })
    .nullable(),
  error_code: z.string().nullable(),
  checks: z.array(check),
  verification_evidence: z.literal(false),
});
export type VaiCheck = z.infer<typeof check>;
export type VaiChecks = z.infer<typeof listing>;
const url = (delivery: string) =>
  `${getBaseUrl().replace(/\/?$/, "/")}adlc/deliveries/${encodeURIComponent(delivery)}/services`;
export const vaiServices = {
  list: async (delivery: string, cycle: string) =>
    listing.parse(
      (await api.get(url(delivery), { params: { cycle_id: cycle } })).data,
    ),
  start: async (
    delivery: string,
    cycle: string,
    service: VaiService,
    checkId: string,
  ) =>
    check.parse(
      (
        await api.post(url(delivery) + "/checks", {
          check_id: checkId,
          cycle_id: cycle,
          service,
        })
      ).data,
    ),
};
export function serviceError(code?: string | null) {
  const messages: Record<string, string> = {
    VAI_SDK_NOT_INSTALLED: "Máy chủ PokeDev chưa cài SDK kết nối vAI.",
    VAI_PLATFORM_AUTH_FAILED:
      "Token kết nối platform đã hết hạn hoặc không hợp lệ. Hãy cập nhật cấu hình riêng trên máy chủ.",
    VAI_BRIDGE_UNAVAILABLE:
      "Cầu nối dịch vụ đang nạp lại hoặc chưa sẵn sàng trên platform. Hãy cập nhật trạng thái sau ít giây.",
    VAI_SERVICES_NOT_CONFIGURED:
      "Chưa có cấu hình kết nối vAI trên máy chủ PokeDev.",
    VAI_PLATFORM_UNAVAILABLE:
      "Chưa kết nối được platform. Các kết quả đã nhận vẫn được giữ lại.",
    VAI_BRIDGE_RELEASE_MISMATCH:
      "Cầu nối dịch vụ trên platform chưa đúng phiên bản.",
    VAI_SERVICE_TOOL_UNAVAILABLE:
      "Plugin của dịch vụ chưa sẵn sàng trên platform.",
    VAI_RECEIPT_NOT_FOUND:
      "Platform chưa tìm thấy phiếu kết quả. Hệ thống chỉ đối soát, không tự gửi lại lượt chạy.",
    VAI_CHECK_ALREADY_ACTIVE:
      "Dịch vụ này đang có một lượt chưa kết thúc. Hãy theo dõi kết quả trước khi chạy tiếp.",
    VAI_CHECK_CAPACITY:
      "Đang có ba lượt kiểm tra. Hãy chờ kết quả trước khi tạo thêm.",
    VAI_RESULT_SCOPE_MISMATCH:
      "Kết quả không khớp phạm vi công việc nên chưa được tiếp nhận.",
    VAI_CHECK_STILL_PENDING: "Đã gửi yêu cầu; platform chưa trả kết quả cuối.",
  };
  return (
    (code && messages[code]) ||
    "Chưa xác nhận được kết quả. Hãy tải lại để đối soát lượt đã gửi."
  );
}
