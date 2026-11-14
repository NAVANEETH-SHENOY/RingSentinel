"use client";
import { EmptyState, OriginNote, Resource } from "./DataState";
import { useSource } from "@/lib/SourceContext";
import { useResource } from "@/lib/useResource";

export function ReplayView() {
  const source = useSource();
  const { state, reload } = useResource(async () => ({ replay: await source.replay(), drift: await source.drift() }), [source]);
  return (
    <>
      <h1>Replay and drift</h1>
      <Resource state={state} onRetry={reload}>
        {({ replay, drift }) => (
          <>
            <OriginNote loaded={replay} />
            {replay.data.status === "not_built" || drift.data.status === "not_built" ? (
              <EmptyState title="Not built yet">
                Replay mode and the drift chart are built in Stage {replay.data.built_in_stage}. The bundle already carries empty placeholders for them, so this page will fill in without any change to the data format.
              </EmptyState>
            ) : (
              <EmptyState title="Replay data present">This version of the interface does not draw it yet (Stage 07).</EmptyState>
            )}
          </>
        )}
      </Resource>
    </>
  );
}
