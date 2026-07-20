import type {
  ApiErrorPayload,
  DeleteFaceResponse,
  FaceHistory,
  FaceIdentity,
  ProcessRecord,
  RecognitionResponse,
} from "./types";

export class ApiError extends Error {
  code: string;
  processId: string | null;

  constructor(payload: ApiErrorPayload) {
    super(payload.message);
    this.name = "ApiError";
    this.code = payload.code;
    this.processId = payload.processId;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    let payload: ApiErrorPayload;
    try {
      payload = (await response.json()) as ApiErrorPayload;
    } catch {
      payload = { code: "NETWORK_ERROR", message: "The service returned an unreadable response.", processId: null };
    }
    throw new ApiError(payload);
  }
  return (await response.json()) as T;
}

export async function recognize(file: File): Promise<RecognitionResponse> {
  const form = new FormData();
  form.append("image", file);
  return request("/api/v1/faces/recognize", { method: "POST", body: form });
}

export async function enroll(
  file: File,
  name: string,
  metadata: Record<string, unknown>,
  faceId?: string,
): Promise<RecognitionResponse> {
  const form = new FormData();
  form.append("image", file);
  form.append("name", name);
  form.append("metadata", JSON.stringify(metadata));
  if (faceId?.trim()) form.append("faceId", faceId.trim());
  return request("/api/v1/faces/enroll", { method: "POST", body: form });
}

export function getFace(faceId: string): Promise<FaceIdentity> {
  return request(`/api/v1/faces/${encodeURIComponent(faceId.trim())}`);
}

export function updateFace(
  faceId: string,
  name: string,
  metadata: Record<string, unknown>,
): Promise<FaceIdentity> {
  return request(`/api/v1/faces/${encodeURIComponent(faceId.trim())}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, metadata }),
  });
}

export function deleteFace(faceId: string): Promise<DeleteFaceResponse> {
  return request(`/api/v1/faces/${encodeURIComponent(faceId.trim())}`, { method: "DELETE" });
}

export function getFaceHistory(faceId: string): Promise<FaceHistory> {
  return request(`/api/v1/faces/${encodeURIComponent(faceId.trim())}/history`);
}

export function getProcess(processId: string): Promise<ProcessRecord> {
  return request(`/api/v1/processes/${encodeURIComponent(processId.trim())}`);
}

export async function health(): Promise<boolean> {
  try {
    const response = await fetch("/health");
    return response.ok;
  } catch {
    return false;
  }
}
