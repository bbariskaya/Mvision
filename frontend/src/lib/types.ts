export type FaceStatus = "known" | "anonymous" | "new_anonymous";

export interface BoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface FaceResult {
  faceId: string;
  status: FaceStatus;
  name: string | null;
  metadata: Record<string, unknown> | null;
  boundingBox: BoundingBox;
  confidence: number;
}

export interface RecognitionResponse {
  processId: string;
  faceCount: number;
  faces: FaceResult[];
}

export interface FaceIdentity {
  processId?: string;
  faceId: string;
  status: "known" | "anonymous";
  name: string | null;
  metadata: Record<string, unknown> | null;
  isActive: boolean;
  sampleCount: number;
  createdAt: string;
  updatedAt: string;
}

export interface FaceHistory {
  faceId: string;
  history: Array<{ processId: string; timestamp: string; status: FaceStatus }>;
}

export interface ProcessRecord {
  processId: string;
  processType: string;
  status: string;
  faceCount: number;
  errorCode: string | null;
  createdAt: string;
  completedAt: string | null;
  faces: FaceResult[];
  events: Array<{
    eventType: string;
    details: Record<string, unknown>;
    timestamp: string;
  }>;
}

export interface DeleteFaceResponse {
  processId: string;
  faceId: string;
  deleted: boolean;
}

export interface ApiErrorPayload {
  code: string;
  message: string;
  processId: string | null;
}
