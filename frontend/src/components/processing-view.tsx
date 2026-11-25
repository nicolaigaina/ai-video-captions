"use client";

import { useEffect, useRef, useState } from "react";
import { CheckCircle, Loader2, Upload, Mic, Film, Download } from "lucide-react";
import { getCaptionJobStatus } from "~/actions/captions";
import type { CaptionJob, CaptionPhase } from "~/types/caption";

interface ProcessingViewProps {
  jobId: string;
  onComplete: (jobId: string) => void;
  onError: (error: string) => void;
}

const PHASES: { id: CaptionPhase; label: string; icon: React.ReactNode }[] = [
  { id: "uploading", label: "Uploading", icon: <Upload className="h-4 w-4" /> },
  { id: "transcribing", label: "Transcribing", icon: <Mic className="h-4 w-4" /> },
  { id: "burning", label: "Burning", icon: <Film className="h-4 w-4" /> },
  { id: "finalizing", label: "Finalizing", icon: <Download className="h-4 w-4" /> },
];

const PHASE_ORDER: CaptionPhase[] = ["uploading", "transcribing", "burning", "finalizing"];

function getPhaseLabel(phase: CaptionPhase | null): string {
  switch (phase) {
    case "uploading":
      return "Uploading Video...";
    case "transcribing":
      return "Transcribing Audio...";
    case "burning":
      return "Burning Captions...";
    case "finalizing":
      return "Finalizing...";
    default:
      return "Processing...";
  }
}

function getPhaseIndex(phase: CaptionPhase | null): number {
  if (!phase) return -1;
  return PHASE_ORDER.indexOf(phase);
}

export function ProcessingView({ jobId, onComplete, onError }: ProcessingViewProps) {
  const [job, setJob] = useState<CaptionJob | null>(null);
  const [lastActivityAt, setLastActivityAt] = useState<number>(Date.now());
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const prevProgressRef = useRef<number>(0);
  const prevUpdatedAtRef = useRef<string | null>(null);

  useEffect(() => {
    async function poll() {
      const result = await getCaptionJobStatus(jobId);
      if (!result) return;
      setJob(result);

      if (result.progress > prevProgressRef.current) {
        prevProgressRef.current = result.progress;
        setLastActivityAt(Date.now());
      }

      if (result.updatedAt !== prevUpdatedAtRef.current) {
        prevUpdatedAtRef.current = result.updatedAt;
        setLastActivityAt(Date.now());
      }

      if (result.status === "completed") {
        if (intervalRef.current) clearInterval(intervalRef.current);
        onComplete(jobId);
      } else if (result.status === "failed") {
        if (intervalRef.current) clearInterval(intervalRef.current);
        onError(result.errorMessage ?? "Processing failed. Please try again.");
      }
    }

    poll();
    intervalRef.current = setInterval(poll, 3000);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  const currentPhase = job?.currentPhase ?? null;
  const progress = job?.progress ?? 0;
  const currentPhaseIndex = getPhaseIndex(currentPhase);
  const stalled =
    job?.status === "processing" && Date.now() - lastActivityAt > 90_000;

  if (job?.status === "failed") {
    return (
      <div className="flex flex-col items-center justify-center gap-4 rounded-xl border border-red-500/30 bg-red-500/10 p-8 font-[family-name:var(--font-outfit)]">
        <p className="text-center text-red-400">
          {job.errorMessage ?? "Processing failed. Please try again."}
        </p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="rounded-lg bg-red-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-red-600"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6 font-[family-name:var(--font-outfit)]">
      {/* Video preview placeholder with scanning overlay */}
      <div className="relative overflow-hidden rounded-xl bg-[#0a0a0a]" style={{ aspectRatio: "16/9" }}>
        {/* Grid pattern */}
        <div
          className="absolute inset-0 opacity-20"
          style={{
            backgroundImage:
              "linear-gradient(rgba(69,159,148,0.3) 1px, transparent 1px), linear-gradient(90deg, rgba(69,159,148,0.3) 1px, transparent 1px)",
            backgroundSize: "40px 40px",
          }}
        />

        {/* Scan line animation */}
        <div className="animate-scan-line absolute inset-y-0 w-0.5 bg-gradient-to-b from-transparent via-[#459F94] to-transparent opacity-80" />

        {/* Status badge */}
        <div className="absolute left-3 top-3 flex items-center gap-2 rounded-full bg-black/60 px-3 py-1.5 backdrop-blur-sm">
          <Loader2 className="h-3 w-3 animate-spin text-[#459F94]" />
          <span className="text-xs font-medium text-white">
            {getPhaseLabel(currentPhase)}
          </span>
        </div>
      </div>

      {/* Phase indicators */}
      <div className="flex items-center justify-between gap-2">
        {PHASES.map((phase, index) => {
          const isCompleted = currentPhaseIndex > index;
          const isActive = currentPhaseIndex === index;
          const isPending = currentPhaseIndex < index;

          return (
            <div
              key={phase.id}
              className="flex flex-1 flex-col items-center gap-1.5"
            >
              <div
                className={[
                  "flex items-center justify-center rounded-full p-2 transition-colors",
                  isCompleted
                    ? "bg-green-500/20 text-green-400"
                    : isActive
                    ? "bg-[#459F94]/20 text-[#459F94]"
                    : "bg-muted text-muted-foreground",
                  isActive ? "animate-pulse" : "",
                ].join(" ")}
              >
                {isCompleted ? (
                  <CheckCircle className="h-4 w-4" />
                ) : (
                  phase.icon
                )}
              </div>
              <span
                className={[
                  "text-xs font-medium",
                  isCompleted
                    ? "text-green-400"
                    : isActive
                    ? "text-[#459F94]"
                    : isPending
                    ? "text-muted-foreground"
                    : "text-muted-foreground",
                ].join(" ")}
              >
                {phase.label}
              </span>
            </div>
          );
        })}
      </div>

      {/* Progress bar */}
      <div className="flex items-center gap-3">
        <div className="h-2 w-full rounded-full bg-muted">
          <div
            className="h-2 rounded-full bg-gradient-to-r from-[#459F94] to-[#EDB118] transition-all duration-500"
            style={{ width: `${progress}%` }}
          />
        </div>
        <span className="min-w-[3rem] text-right text-sm font-medium tabular-nums text-muted-foreground">
          {progress}%
        </span>
      </div>

      {stalled && (
        <p className="text-center text-xs text-amber-500">
          No backend activity was detected recently. Processing may be stalled.
        </p>
      )}
    </div>
  );
}
