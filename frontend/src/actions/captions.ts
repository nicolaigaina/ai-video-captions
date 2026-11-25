"use server";

import { db } from "~/lib/db";
import { env } from "~/lib/env";
import type { CaptionJob, CaptionJobStatus, CaptionPhase, CaptionStyle, BackendStatusResponse } from "~/types/caption";

function mapPrismaJobToType(job: {
  id: string;
  displayName: string | null;
  originalFileName: string;
  fileSize: number;
  durationSeconds: number | null;
  captionStyle: string;
  captionPosition: number;
  status: string;
  progress: number;
  currentPhase: string | null;
  language: string | null;
  errorMessage: string | null;
  backendJobId: string | null;
  processingTimeMs: number | null;
  outputFileSize: number | null;
  createdAt: Date;
  updatedAt: Date;
}): CaptionJob {
  return {
    id: job.id,
    displayName: job.displayName,
    originalFileName: job.originalFileName,
    fileSize: job.fileSize,
    durationSeconds: job.durationSeconds,
    captionStyle: job.captionStyle as CaptionStyle,
    captionPosition: job.captionPosition,
    status: job.status as CaptionJobStatus,
    progress: job.progress,
    currentPhase: job.currentPhase as CaptionPhase | null,
    language: job.language,
    errorMessage: job.errorMessage,
    backendJobId: job.backendJobId,
    processingTimeMs: job.processingTimeMs,
    outputFileSize: job.outputFileSize,
    createdAt: job.createdAt.toISOString(),
    updatedAt: job.updatedAt.toISOString(),
  };
}

const TERMINAL_STATUSES: CaptionJobStatus[] = ["completed", "failed"];
const STALLED_JOB_THRESHOLD_MS = 10 * 60 * 1000;

export async function submitCaptionJob(
  formData: FormData
): Promise<{ jobId: string } | { error: string }> {
  try {
    const file = formData.get("file") as File | null;
    const captionStyle = formData.get("captionStyle") as string | null;
    const captionPosition = formData.get("captionPosition") as string | null;
    const durationSeconds = formData.get("durationSeconds") as string | null;

    if (!file) {
      return { error: "No file provided" };
    }
    if (!captionStyle) {
      return { error: "No caption style provided" };
    }
    if (!captionPosition) {
      return { error: "No caption position provided" };
    }

    const backendFormData = new FormData();
    backendFormData.append("file", file);
    backendFormData.append("captionStyle", captionStyle);
    backendFormData.append("captionPosition", captionPosition);
    if (durationSeconds) {
      backendFormData.append("durationSeconds", durationSeconds);
    }

    const response = await fetch(`${env.BACKEND_URL}/api/process`, {
      method: "POST",
      body: backendFormData,
    });

    if (!response.ok) {
      const errorText = await response.text();
      return { error: `Backend error: ${errorText}` };
    }

    const data = (await response.json()) as { jobId: string };

    const prismaRecord = await db.captionJob.create({
      data: {
        originalFileName: file.name,
        fileSize: file.size,
        durationSeconds: durationSeconds ? parseFloat(durationSeconds) : null,
        captionStyle,
        captionPosition: parseInt(captionPosition, 10),
        status: "processing",
        backendJobId: data.jobId,
      },
    });

    return { jobId: prismaRecord.id };
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return { error: message };
  }
}

interface CreateCaptionJobRecordInput {
  originalFileName: string;
  fileSize: number;
  durationSeconds: number | null;
  captionStyle: string;
  captionPosition: number;
  backendJobId: string;
}

export async function createCaptionJobRecord(
  input: CreateCaptionJobRecordInput,
): Promise<{ jobId: string } | { error: string }> {
  try {
    const prismaRecord = await db.captionJob.create({
      data: {
        originalFileName: input.originalFileName,
        fileSize: input.fileSize,
        durationSeconds: input.durationSeconds,
        captionStyle: input.captionStyle,
        captionPosition: input.captionPosition,
        status: "processing",
        progress: 0,
        currentPhase: "uploading",
        backendJobId: input.backendJobId,
      },
    });

    return { jobId: prismaRecord.id };
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    return { error: message };
  }
}

export async function getCaptionJobStatus(
  jobId: string
): Promise<CaptionJob | null> {
  const job = await db.captionJob.findUnique({ where: { id: jobId } });
  if (!job) return null;

  if (TERMINAL_STATUSES.includes(job.status as CaptionJobStatus)) {
    return mapPrismaJobToType(job);
  }

  if (!job.backendJobId) {
    return mapPrismaJobToType(job);
  }

  try {
    const response = await fetch(
      `${env.BACKEND_URL}/api/status/${job.backendJobId}`
    );

    if (!response.ok) {
      return mapPrismaJobToType(job);
    }

    const backendData = (await response.json()) as BackendStatusResponse;

    let resolvedStatus = backendData.status as CaptionJobStatus;
    let resolvedError = backendData.errorMessage;

    if (
      resolvedStatus === "processing" &&
      backendData.updatedAt &&
      Date.now() - new Date(backendData.updatedAt).getTime() > STALLED_JOB_THRESHOLD_MS
    ) {
      resolvedStatus = "failed";
      resolvedError =
        "Processing appears stalled (no backend progress for 10+ minutes). Please retry.";
    }

    const updated = await db.captionJob.update({
      where: { id: jobId },
      data: {
        status: resolvedStatus,
        progress: backendData.progress,
        currentPhase: backendData.currentPhase,
        language: backendData.language,
        durationSeconds: backendData.durationSeconds ?? job.durationSeconds,
        errorMessage: resolvedError,
        processingTimeMs: backendData.processingTimeMs,
      },
    });

    return mapPrismaJobToType(updated);
  } catch {
    return mapPrismaJobToType(job);
  }
}

export async function getCaptionJobs(): Promise<CaptionJob[]> {
  const jobs = await db.captionJob.findMany({
    orderBy: { createdAt: "desc" },
  });
  return jobs.map(mapPrismaJobToType);
}

export async function getCaptionJobById(
  jobId: string
): Promise<CaptionJob | null> {
  const job = await db.captionJob.findUnique({ where: { id: jobId } });
  if (!job) return null;
  return mapPrismaJobToType(job);
}

export async function deleteCaptionJob(jobId: string): Promise<void> {
  const job = await db.captionJob.findUnique({ where: { id: jobId } });
  if (!job) return;

  if (job.backendJobId) {
    try {
      await fetch(`${env.BACKEND_URL}/api/jobs/${job.backendJobId}`, {
        method: "DELETE",
      });
    } catch {
      // Best-effort delete from backend; proceed to delete from DB
    }
  }

  await db.captionJob.delete({ where: { id: jobId } });
}
