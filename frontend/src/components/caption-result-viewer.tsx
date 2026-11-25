"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Download, Trash2, Loader2 } from "lucide-react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "~/components/ui/alert-dialog";
import { deleteCaptionJob } from "~/actions/captions";
import { CAPTION_STYLE_CONFIGS } from "~/lib/caption-styles";
import { clientEnv } from "~/lib/env";
import { formatDuration, formatBytes } from "~/lib/utils";
import type { CaptionJob } from "~/types/caption";

interface CaptionResultViewerProps {
  job: CaptionJob;
}

function formatProcessingTime(ms: number): string {
  const seconds = ms / 1000;
  return `${seconds.toFixed(1)}s`;
}

function formatDate(dateString: string): string {
  return new Date(dateString).toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function CaptionResultViewer({ job }: CaptionResultViewerProps) {
  const router = useRouter();
  const [isDeleting, setIsDeleting] = useState(false);

  useEffect(() => {
    if (job.status !== "processing" && job.status !== "uploading") return;

    const interval = setInterval(() => {
      router.refresh();
    }, 3000);

    return () => clearInterval(interval);
  }, [job.status, router]);

  const styleConfig = CAPTION_STYLE_CONFIGS[job.captionStyle];
  const backendBaseUrl = clientEnv.NEXT_PUBLIC_BACKEND_URL;
  const downloadUrl = job.backendJobId
    ? `${backendBaseUrl}/api/download/${job.backendJobId}`
    : null;

  const handleDelete = async () => {
    setIsDeleting(true);
    try {
      await deleteCaptionJob(job.id);
      router.push("/history");
    } catch {
      setIsDeleting(false);
    }
  };

  // Still processing state
  if (job.status === "processing" || job.status === "uploading") {
    return (
      <div
        className="flex min-h-screen flex-col items-center justify-center gap-4 bg-gray-50 p-6 dark:bg-gray-950"
        style={{ fontFamily: "var(--font-outfit)" }}
      >
        <Loader2 className="h-8 w-8 animate-spin text-[#459F94]" />
        <p className="text-base font-medium text-gray-700 dark:text-gray-300">
          Still processing...
        </p>
        <Link
          href="/"
          className="text-sm text-[#459F94] underline-offset-4 hover:underline"
        >
          Go back home
        </Link>
      </div>
    );
  }

  // Failed state
  if (job.status === "failed") {
    return (
      <div
        className="flex min-h-screen flex-col items-center justify-center gap-4 bg-gray-50 p-6 dark:bg-gray-950"
        style={{ fontFamily: "var(--font-outfit)" }}
      >
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-6 py-8 text-center">
          <p className="mb-2 text-base font-semibold text-red-400">
            Processing failed
          </p>
          <p className="text-sm text-red-300">
            {job.errorMessage ?? "An unknown error occurred."}
          </p>
        </div>
        <Link
          href="/history"
          className="text-sm text-[#459F94] underline-offset-4 hover:underline"
        >
          Back to history
        </Link>
      </div>
    );
  }

  return (
    <div
      className="min-h-screen bg-gray-50 dark:bg-gray-950"
      style={{ fontFamily: "var(--font-outfit)" }}
    >
      {/* Top bar */}
      <div className="sticky top-0 z-10 border-b border-gray-200 bg-white/80 backdrop-blur-sm dark:border-gray-800 dark:bg-gray-950/80">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-2 px-4 py-3 sm:gap-4 sm:px-6">
          {/* Back button */}
          <Link
            href="/history"
            aria-label="Back to history"
            className="flex items-center gap-1.5 rounded-lg p-2 text-sm text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-900 dark:hover:bg-gray-800 dark:hover:text-white sm:px-2 sm:py-1.5"
          >
            <ArrowLeft className="h-4 w-4" />
            <span className="hidden sm:inline">History</span>
          </Link>

          {/* File name */}
          <p
            className="min-w-0 flex-1 basis-full truncate text-sm font-medium text-gray-700 dark:text-gray-300 sm:basis-auto"
            title={job.originalFileName}
          >
            {job.originalFileName}
          </p>

          {/* Actions */}
          <div className="flex items-center gap-2">
            {downloadUrl && (
              <a
                href={downloadUrl}
                download={`captioned-${job.originalFileName}`}
                aria-label="Download captioned video"
                className="flex items-center gap-1.5 rounded-lg bg-[#459F94] p-2 text-sm font-medium text-white transition-colors hover:bg-[#367d74] sm:px-3 sm:py-1.5"
              >
                <Download className="h-4 w-4" />
                <span className="hidden sm:inline">Download</span>
              </a>
            )}

            <AlertDialog>
              <AlertDialogTrigger
                disabled={isDeleting}
                aria-label="Delete this caption job"
                className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-red-300 p-2 text-sm font-medium text-red-500 transition-colors hover:bg-red-50 disabled:opacity-50 dark:border-red-700 dark:hover:bg-red-950 sm:px-3 sm:py-1.5"
              >
                {isDeleting ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Trash2 className="h-4 w-4" />
                )}
                <span className="hidden sm:inline">Delete</span>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Delete this caption job?</AlertDialogTitle>
                  <AlertDialogDescription>
                    This will permanently delete the job and the processed
                    video. This action cannot be undone.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={() => void handleDelete()}
                    className="bg-red-500 hover:bg-red-600"
                  >
                    Delete
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        </div>
      </div>

      {/* Main content */}
      <div className="mx-auto max-w-6xl px-6 py-10">
        <div className="flex flex-col gap-8 lg:flex-row lg:items-start">
          {/* Left: Video player */}
          <div className="flex-1">
            {downloadUrl ? (
              <video
                controls
                className="w-full rounded-2xl bg-black shadow-lg"
                style={{ maxHeight: "70vh" }}
              >
                <source src={downloadUrl} />
                Your browser does not support the video tag.
              </video>
            ) : (
              <div className="flex aspect-video w-full items-center justify-center rounded-2xl bg-gray-900 text-sm text-gray-500">
                Video not available
              </div>
            )}
          </div>

          {/* Right: Metadata sidebar */}
          <div className="w-full rounded-2xl border border-gray-200 bg-white p-6 shadow-sm dark:border-gray-800 dark:bg-gray-900 lg:w-72 lg:flex-shrink-0">
            <h2 className="mb-5 text-sm font-semibold uppercase tracking-wider text-gray-500 dark:text-gray-400">
              Details
            </h2>

            <dl className="space-y-4">
              {job.durationSeconds !== null && (
                <div>
                  <dt className="text-xs text-gray-500 dark:text-gray-400">
                    Duration
                  </dt>
                  <dd className="mt-0.5 text-sm font-medium text-gray-900 dark:text-white">
                    {formatDuration(job.durationSeconds)}
                  </dd>
                </div>
              )}

              {job.language && (
                <div>
                  <dt className="text-xs text-gray-500 dark:text-gray-400">
                    Language detected
                  </dt>
                  <dd className="mt-0.5 text-sm font-medium text-gray-900 dark:text-white">
                    {job.language}
                  </dd>
                </div>
              )}

              <div>
                <dt className="text-xs text-gray-500 dark:text-gray-400">
                  Caption style
                </dt>
                <dd className="mt-0.5 flex items-center gap-1.5">
                  <span
                    className="h-3.5 w-3.5 flex-shrink-0 rounded-full ring-1 ring-black/20"
                    style={{
                      background: `linear-gradient(135deg, ${styleConfig.primaryColor} 50%, ${styleConfig.highlightColor} 50%)`,
                    }}
                  />
                  <span className="text-sm font-medium text-gray-900 dark:text-white">
                    {styleConfig.name}
                  </span>
                </dd>
              </div>

              <div>
                <dt className="text-xs text-gray-500 dark:text-gray-400">
                  Caption position
                </dt>
                <dd className="mt-0.5 text-sm font-medium text-gray-900 dark:text-white">
                  {job.captionPosition}%
                </dd>
              </div>

              {job.processingTimeMs !== null && (
                <div>
                  <dt className="text-xs text-gray-500 dark:text-gray-400">
                    Processing time
                  </dt>
                  <dd className="mt-0.5 text-sm font-medium text-gray-900 dark:text-white">
                    {formatProcessingTime(job.processingTimeMs)}
                  </dd>
                </div>
              )}

              <div>
                <dt className="text-xs text-gray-500 dark:text-gray-400">
                  File size
                </dt>
                <dd className="mt-0.5 text-sm font-medium text-gray-900 dark:text-white">
                  {formatBytes(job.fileSize)}
                </dd>
              </div>

              <div>
                <dt className="text-xs text-gray-500 dark:text-gray-400">
                  Created
                </dt>
                <dd className="mt-0.5 text-sm font-medium text-gray-900 dark:text-white">
                  {formatDate(job.createdAt)}
                </dd>
              </div>
            </dl>
          </div>
        </div>
      </div>
    </div>
  );
}
