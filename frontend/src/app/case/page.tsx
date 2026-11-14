"use client";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { CaseView } from "@/components/CaseView";
import { Loading } from "@/components/DataState";

function CaseFromUrl() {
  const id = useSearchParams().get("id");
  return <CaseView ringId={id && id.trim() ? id.trim() : null} />;
}

export default function Page() {
  // useSearchParams needs a Suspense boundary in a static export.
  return (
    <Suspense fallback={<Loading label="Loading the case" />}>
      <CaseFromUrl />
    </Suspense>
  );
}
