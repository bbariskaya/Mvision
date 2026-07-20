import { ClockCounterClockwise, MagnifyingGlass, Pulse } from "@phosphor-icons/react";
import { FormEvent, useState } from "react";

import { FaceInspector } from "../components/FaceInspector";
import { ErrorNotice, IdCopy } from "../components/Feedback";
import { getProcess } from "../lib/api";
import type { ProcessRecord } from "../lib/types";

export function ProcessWorkspace() {
  const [query, setQuery] = useState("");
  const [record, setRecord] = useState<ProcessRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function search(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    setLoading(true); setError(null);
    try { setRecord(await getProcess(query)); } catch (caught) { setError(caught); setRecord(null); } finally { setLoading(false); }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <form className="console-card rounded-2xl p-4 sm:flex sm:items-end sm:gap-3" onSubmit={search}>
        <div className="min-w-0 flex-1"><label className="label" htmlFor="process-search">Process ID</label><input id="process-search" className="field font-mono text-xs" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Enter a process UUID" /></div>
        <button className="primary-button mt-3 w-full sm:mt-0 sm:w-auto" disabled={!query.trim() || loading}><MagnifyingGlass size={17} weight="bold" /> {loading ? "Loading" : "Inspect process"}</button>
      </form>
      <ErrorNotice error={error} />
      {!record && !loading && !error && (
        <div className="rounded-2xl border border-dashed border-ink-300 px-6 py-20 text-center"><ClockCounterClockwise className="mx-auto text-signal-600" size={36} weight="duotone" /><h2 className="mt-4 font-serif text-3xl text-ink-950">Every decision leaves a trace.</h2><p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-ink-500">Inspect immutable face results and sanitized lifecycle events for any process returned by the API.</p></div>
      )}
      {record && (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
          <section className="space-y-4">
            <div className="console-card rounded-2xl p-5 sm:p-7">
              <div className="flex flex-wrap items-start justify-between gap-5">
                <div><p className="text-[10px] font-bold uppercase tracking-[.14em] text-signal-700">{record.processType} process</p><h2 className="mt-1 text-2xl font-bold capitalize text-ink-950">{record.status}</h2></div>
                <span className={`rounded-full border px-3 py-1.5 text-xs font-bold ${record.status === "completed" ? "border-signal-200 bg-signal-100 text-signal-700" : "border-alert-600/20 bg-alert-100 text-alert-600"}`}>{record.status}</span>
              </div>
              <div className="mt-6 grid gap-3 sm:grid-cols-3"><div className="rounded-xl bg-ink-100/65 p-4 sm:col-span-2"><IdCopy value={record.processId} /></div><div className="rounded-xl bg-ink-100/65 p-4"><span className="text-[10px] font-bold uppercase tracking-wider text-ink-500">Faces</span><strong className="mt-1 block font-mono text-xl text-ink-900">{record.faceCount}</strong></div></div>
              <p className="mt-4 font-mono text-[10px] text-ink-500">Started {new Date(record.createdAt).toLocaleString()}{record.completedAt ? ` · Completed ${new Date(record.completedAt).toLocaleString()}` : ""}</p>
            </div>
            {record.faces.map((face, index) => <FaceInspector key={`${face.faceId}-${index}`} face={face} ordinal={index} />)}
          </section>
          <aside className="console-card rounded-2xl p-5">
            <div className="flex items-center gap-2"><Pulse className="text-signal-600" size={19} weight="duotone" /><h2 className="text-lg font-bold text-ink-950">Event trace</h2></div>
            <div className="mt-5 space-y-0">
              {record.events.length ? record.events.map((event, index) => (
                <div key={`${event.eventType}-${event.timestamp}`} className="relative flex gap-3 pb-6 last:pb-0">
                  {index < record.events.length - 1 && <span className="absolute left-[7px] top-4 h-full w-px bg-ink-200" />}
                  <span className="relative z-10 mt-1 size-[15px] shrink-0 rounded-full border-4 border-paper bg-signal-600" />
                  <div className="min-w-0"><strong className="block text-xs text-ink-900">{event.eventType.replaceAll("_", " ")}</strong><time className="mt-1 block font-mono text-[9px] text-ink-500">{new Date(event.timestamp).toLocaleString()}</time><pre className="mt-2 overflow-x-auto whitespace-pre-wrap rounded-lg bg-ink-100/70 p-3 font-mono text-[9px] leading-4 text-ink-700">{JSON.stringify(event.details, null, 2)}</pre></div>
                </div>
              )) : <p className="text-sm text-ink-500">No optional events were recorded.</p>}
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}
