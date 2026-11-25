import { notFound } from "next/navigation";
import { getCaptionJobStatus } from "~/actions/captions";
import { CaptionResultViewer } from "~/components/caption-result-viewer";

export const dynamic = "force-dynamic";

interface CaptionPageProps {
  params: Promise<{ id: string }>;
}

export default async function CaptionPage({ params }: CaptionPageProps) {
  const { id } = await params;
  // Use status fetch so this page always gets fresh backend progress
  // instead of stale DB-only values.
  const job = await getCaptionJobStatus(id);
  if (!job) notFound();
  return <CaptionResultViewer job={job} />;
}
