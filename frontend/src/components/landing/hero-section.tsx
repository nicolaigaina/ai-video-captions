"use client";

import { useState } from "react";
import { Palette, Sparkles, Globe } from "lucide-react";
import { useRouter } from "next/navigation";
import { VideoDropzone } from "~/components/video-dropzone";
import { CaptionStylePicker } from "~/components/caption-style-picker";
import { CaptionPreview } from "~/components/caption-preview";
import { ProcessingView } from "~/components/processing-view";
import { createCaptionJobRecord } from "~/actions/captions";
import {
  CAPTION_STYLE_CONFIGS,
  DEFAULT_CAPTION_STYLE,
  DEFAULT_CAPTION_POSITION,
} from "~/lib/caption-styles";
import { clientEnv } from "~/lib/env";
import type { CaptionStyle } from "~/types/caption";

type ViewState = "idle" | "uploading" | "processing" | "complete";
type TranscriptionLanguage = "auto" | "fa" | "en";

const trustIndicators = [
  { icon: Palette, text: "6 Styles" },
  { icon: Sparkles, text: "Word-Level" },
  { icon: Globe, text: "100+ Languages" },
];

function uploadVideoToBackend(
  formData: FormData,
  onUploadProgress: (percent: number) => void,
): Promise<{ backendJobId: string }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${clientEnv.NEXT_PUBLIC_BACKEND_URL}/api/process`);

    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable) return;
      const percent = Math.round((event.loaded / event.total) * 100);
      onUploadProgress(Math.min(100, Math.max(0, percent)));
    };

    xhr.onerror = () => {
      reject(new Error("Upload failed due to a network error."));
    };

    xhr.onabort = () => {
      reject(new Error("Upload was aborted."));
    };

    xhr.onload = () => {
      if (xhr.status < 200 || xhr.status >= 300) {
        reject(new Error(xhr.responseText || `Backend error (${xhr.status})`));
        return;
      }

      try {
        const parsed = JSON.parse(xhr.responseText) as { jobId?: string };
        if (!parsed.jobId) {
          reject(new Error("Backend did not return jobId."));
          return;
        }
        resolve({ backendJobId: parsed.jobId });
      } catch {
        reject(new Error("Invalid backend response."));
      }
    };

    xhr.send(formData);
  });
}

export function HeroSection() {
  const router = useRouter();

  const [viewState, setViewState] = useState<ViewState>("idle");
  const [file, setFile] = useState<File | null>(null);
  const [fileDuration, setFileDuration] = useState<number>(0);
  const [selectedStyle, setSelectedStyle] =
    useState<CaptionStyle>(DEFAULT_CAPTION_STYLE);
  const [captionPosition, setCaptionPosition] = useState(
    DEFAULT_CAPTION_POSITION,
  );
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [transcriptionLanguage, setTranscriptionLanguage] =
    useState<TranscriptionLanguage>("auto");
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleFileSelect = (selectedFile: File, duration: number) => {
    setFile(selectedFile);
    setFileDuration(duration);
    setError(null);
  };

  const handleFileClear = () => {
    setFile(null);
    setFileDuration(0);
    setError(null);
  };

  const handleSubmit = async () => {
    if (!file) return;

    setViewState("uploading");
    setUploadProgress(0);
    setError(null);

    const formData = new FormData();
    formData.append("file", file);
    formData.append("captionStyle", selectedStyle);
    formData.append("captionPosition", String(captionPosition));
    formData.append("durationSeconds", String(fileDuration));
    formData.append("transcriptionLanguage", transcriptionLanguage);

    try {
      const uploadResult = await uploadVideoToBackend(formData, (percent) => {
        setUploadProgress(percent);
      });

      const createResult = await createCaptionJobRecord({
        originalFileName: file.name,
        fileSize: file.size,
        durationSeconds: Number.isFinite(fileDuration) ? fileDuration : null,
        captionStyle: selectedStyle,
        captionPosition,
        backendJobId: uploadResult.backendJobId,
      });

      if ("error" in createResult) {
        setError(createResult.error);
        setViewState("idle");
        setUploadProgress(null);
        return;
      }

      setUploadProgress(100);
      setJobId(createResult.jobId);
      setViewState("processing");
      setUploadProgress(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Upload failed.";
      setError(
        `${message} Please try again. If backend already accepted the file, you can find it in History.`,
      );
      setViewState("idle");
      setUploadProgress(null);
    }
  };

  const handleProcessingComplete = (completedJobId: string) => {
    setViewState("complete");
    router.push(`/captions/${completedJobId}`);
  };

  const handleProcessingError = (errorMessage: string) => {
    setError(errorMessage);
    setViewState("idle");
    setFile(null);
    setFileDuration(0);
    setUploadProgress(null);
    setJobId(null);
  };

  const isUploading = viewState === "uploading";
  const isProcessing = viewState === "processing";
  const styleConfig = CAPTION_STYLE_CONFIGS[selectedStyle];

  return (
    <section
      className="relative min-h-[85vh] overflow-hidden bg-white pt-24 dark:bg-black"
      style={{ fontFamily: "var(--font-outfit)" }}
    >
      {/* Subtle gradient background */}
      <div className="absolute inset-0 bg-gradient-to-b from-[#459F94]/5 via-white to-white dark:from-[#459F94]/10 dark:via-black dark:to-black" />

      {/* Grid pattern */}
      <div
        className="absolute inset-0 opacity-[0.03] dark:opacity-[0.05]"
        style={{
          backgroundImage: `url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23459F94' fill-opacity='1'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E")`,
        }}
      />

      {/* Content */}
      <div className="relative z-10 container mx-auto px-6 py-20">
        <div className="mx-auto max-w-5xl text-center">
          {/* Badge */}
          <div className="animate-fade-up mb-6 inline-flex items-center gap-2 rounded-full border border-[#459F94]/30 bg-[#459F94]/10 px-4 py-1.5 text-sm font-medium text-[#459F94] dark:border-[#459F94]/40 dark:bg-[#459F94]/20">
            <span className="h-1.5 w-1.5 rounded-full bg-[#459F94]" />
            Free & Open Source
          </div>

          {/* Main Heading */}
          <h1
            className="animate-fade-up mb-6 text-4xl leading-tight font-bold sm:text-5xl md:text-6xl lg:text-7xl"
            style={{ "--stagger": "0.1s" } as React.CSSProperties}
          >
            <span className="bg-gradient-to-r from-[#459F94] via-[#EDB118] to-[#459F94] bg-clip-text text-transparent">
              AI Video
            </span>
            <br />
            <span className="text-gray-900 dark:text-white">Captions</span>
          </h1>

          {/* Subheading */}
          <p
            className="animate-fade-up mb-10 text-lg text-gray-600 md:text-xl dark:text-gray-300"
            style={{ "--stagger": "0.2s" } as React.CSSProperties}
          >
            Add trending animated captions to any video. 6 styles, word-level
            animation, multi-language support. Self-hosted and free.
          </p>

          {/* Trust Indicators */}
          <div
            className="animate-fade-up mb-10 flex flex-wrap items-center justify-center gap-6 text-sm text-gray-500 dark:text-gray-400"
            style={{ "--stagger": "0.3s" } as React.CSSProperties}
          >
            {trustIndicators.map((indicator, i) => (
              <div key={i} className="flex items-center gap-2">
                <indicator.icon className="h-4 w-4 text-[#459F94]" />
                <span>{indicator.text}</span>
              </div>
            ))}
          </div>

          {/* Upload / Processing Area */}
          <div
            id="upload"
            className="animate-fade-up mx-auto max-w-5xl"
            style={{ "--stagger": "0.4s" } as React.CSSProperties}
          >
            {isProcessing && jobId ? (
              <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-800 dark:bg-gray-950">
                <ProcessingView
                  jobId={jobId}
                  onComplete={handleProcessingComplete}
                  onError={handleProcessingError}
                />
              </div>
            ) : (
              <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-800 dark:bg-gray-950">
                {/* Error message */}
                {error && (
                  <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-400">
                    {error}
                  </div>
                )}

                {/* Two-column layout */}
                <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:gap-8">
                  {/* Left: Dropzone + Style Picker */}
                  <div className="flex flex-1 flex-col gap-5">
                    <VideoDropzone
                      file={file}
                      onFileSelect={handleFileSelect}
                      onFileClear={handleFileClear}
                      uploadProgress={uploadProgress}
                      disabled={isUploading}
                    />
                    <CaptionStylePicker
                      selectedStyle={selectedStyle}
                      onStyleChange={setSelectedStyle}
                    />
                    <div className="rounded-xl border border-gray-200 p-3 text-left dark:border-gray-800">
                      <p className="mb-2 text-xs font-semibold text-gray-500 dark:text-gray-400">
                        Transcription language
                      </p>
                      <div className="flex flex-wrap gap-2">
                        {([
                          { id: "auto", label: "Auto" },
                          { id: "fa", label: "Persian (FA)" },
                          { id: "en", label: "English (EN)" },
                        ] as const).map((item) => (
                          <button
                            key={item.id}
                            type="button"
                            onClick={() => setTranscriptionLanguage(item.id)}
                            className={[
                              "rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors",
                              transcriptionLanguage === item.id
                                ? "border-[#459F94] bg-[#459F94]/10 text-[#459F94]"
                                : "border-gray-200 text-gray-600 hover:border-[#459F94]/40 dark:border-gray-700 dark:text-gray-300",
                            ].join(" ")}
                          >
                            {item.label}
                          </button>
                        ))}
                      </div>
                    </div>
                  </div>

                  {/* Right: Caption Preview */}
                  <div className="flex justify-center lg:justify-end">
                    <CaptionPreview
                      style={styleConfig}
                      position={captionPosition}
                      onPositionChange={setCaptionPosition}
                    />
                  </div>
                </div>

                {/* Generate button */}
                <div className="mt-6">
                  <button
                    type="button"
                    onClick={() => void handleSubmit()}
                    disabled={!file || isUploading}
                    className="w-full rounded-xl bg-[#459F94] py-3.5 text-base font-semibold text-white transition-colors hover:bg-[#367d74] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {isUploading
                      ? `Uploading... ${Math.round(uploadProgress ?? 0)}%`
                      : "Generate Captions"}
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Stats */}
          <div
            className="animate-fade-in mt-14 grid grid-cols-3 gap-8 border-t border-gray-200 pt-10 dark:border-gray-800"
            style={{ "--stagger": "0.6s" } as React.CSSProperties}
          >
            {[
              { value: "6", label: "Caption Styles" },
              { value: "100+", label: "Languages Supported" },
              { value: "0", label: "Cost - Always Free" },
            ].map((stat) => (
              <div key={stat.label} className="text-center">
                <div className="text-2xl font-bold text-[#459F94] sm:text-3xl">
                  {stat.value}
                </div>
                <div className="mt-1 text-xs text-gray-600 sm:text-sm dark:text-gray-400">
                  {stat.label}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Bottom fade */}
      <div className="absolute right-0 bottom-0 left-0 h-24 bg-gradient-to-t from-gray-50 to-transparent dark:from-gray-900" />
    </section>
  );
}
