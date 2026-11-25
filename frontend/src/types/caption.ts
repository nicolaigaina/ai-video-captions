export type CaptionStyle = "hormozi" | "mrbeast" | "karaoke" | "minimal" | "bounce" | "classic";
export type AnimationType = "highlight" | "karaoke" | "scale" | "bounce";

export type CaptionJobStatus = "pending" | "uploading" | "processing" | "completed" | "failed";
export type CaptionPhase = "uploading" | "transcribing" | "burning" | "finalizing";

export interface CaptionStyleConfig {
  id: CaptionStyle;
  name: string;
  description: string;
  fontName: string;
  fontNameFallback: string;
  fontSize: number;
  primaryColor: string;
  highlightColor: string;
  outlineColor: string;
  shadowColor: string;
  shadowAlpha: number;
  outlineSize: number;
  shadowDepth: number;
  bold: boolean;
  italic: boolean;
  letterSpacing: number;
  wordSpacing: number;
  animationType: AnimationType;
  previewText: string;
  bestFor: string;
  previewFontSize: number;
  previewOutlineSize: number;
  previewShadowDepth: number;
  previewLetterSpacing: number;
}

export interface CaptionJob {
  id: string;
  displayName: string | null;
  originalFileName: string;
  fileSize: number;
  durationSeconds: number | null;
  captionStyle: CaptionStyle;
  captionPosition: number;
  status: CaptionJobStatus;
  progress: number;
  currentPhase: CaptionPhase | null;
  language: string | null;
  errorMessage: string | null;
  backendJobId: string | null;
  processingTimeMs: number | null;
  outputFileSize: number | null;
  createdAt: string;
  updatedAt: string;
}

export interface BackendStatusResponse {
  jobId: string;
  status: string;
  progress: number;
  currentPhase: string | null;
  language: string | null;
  durationSeconds: number | null;
  errorMessage: string | null;
  processingTimeMs: number | null;
  createdAt?: string;
  updatedAt?: string;
}
