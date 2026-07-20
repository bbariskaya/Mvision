import { FloppyDisk, MagnifyingGlass, ShieldWarning, Trash } from "@phosphor-icons/react";
import { FormEvent, useState } from "react";

import { ErrorNotice, IdCopy } from "../components/Feedback";
import { StatusBadge, WorkingBadge } from "../components/StatusBadge";
import { deleteFace, getFace, getFaceHistory, updateFace } from "../lib/api";
import type { FaceHistory, FaceIdentity } from "../lib/types";

export function IdentityWorkspace() {
  const [query, setQuery] = useState("");
  const [identity, setIdentity] = useState<FaceIdentity | null>(null);
  const [history, setHistory] = useState<FaceHistory | null>(null);
  const [name, setName] = useState("");
  const [metadata, setMetadata] = useState("{}");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleted, setDeleted] = useState(false);
  const [error, setError] = useState<unknown>(null);

  async function search(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    setLoading(true); setError(null); setDeleted(false); setConfirmDelete(false);
    try {
      const [face, faceHistory] = await Promise.all([getFace(query), getFaceHistory(query)]);
      setIdentity(face); setHistory(faceHistory); setName(face.name ?? "");
      setMetadata(JSON.stringify(face.metadata ?? {}, null, 2));
    } catch (caught) {
      setError(caught); setIdentity(null); setHistory(null);
    } finally { setLoading(false); }
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!identity) return;
    setSaving(true); setError(null);
    try {
      const parsed = JSON.parse(metadata) as unknown;
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error("Metadata must be a JSON object.");
      setIdentity(await updateFace(identity.faceId, name, parsed as Record<string, unknown>));
    } catch (caught) { setError(caught); } finally { setSaving(false); }
  }

  async function remove() {
    if (!identity) return;
    setSaving(true); setError(null);
    try {
      await deleteFace(identity.faceId); setDeleted(true); setConfirmDelete(false);
    } catch (caught) { setError(caught); } finally { setSaving(false); }
  }

  return (
    <div className="mx-auto max-w-6xl space-y-5">
      <form className="console-card rounded-2xl p-4 sm:flex sm:items-end sm:gap-3" onSubmit={search}>
        <div className="min-w-0 flex-1"><label className="label" htmlFor="face-search">Face ID</label><input id="face-search" className="field font-mono text-xs" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Enter a face UUID" /></div>
        <button className="primary-button mt-3 w-full sm:mt-0 sm:w-auto" disabled={!query.trim() || loading}>{loading ? <WorkingBadge label="Resolving" /> : <><MagnifyingGlass size={17} weight="bold" /> Find identity</>}</button>
      </form>
      <ErrorNotice error={error} />
      {!identity && !loading && !error && (
        <div className="rounded-2xl border border-dashed border-ink-300 px-6 py-20 text-center"><MagnifyingGlass className="mx-auto text-signal-600" size={34} weight="duotone" /><h2 className="mt-4 font-serif text-3xl text-ink-950">Identity records, without the noise.</h2><p className="mx-auto mt-2 max-w-lg text-sm leading-6 text-ink-500">Look up a face ID returned by recognition to inspect its lifecycle, update a known identity, or review every process where it appeared.</p></div>
      )}
      {identity && (
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
          <section className="console-card rounded-2xl p-5 sm:p-7">
            <div className="flex flex-wrap items-start justify-between gap-4 border-b border-ink-100 pb-5">
              <div><p className="text-[10px] font-bold uppercase tracking-[.14em] text-ink-500">Identity record</p><h2 className="mt-1 text-2xl font-bold text-ink-950">{identity.name ?? "Anonymous identity"}</h2></div>
              <StatusBadge status={identity.status} />
            </div>
            <div className="mt-5 grid gap-3 sm:grid-cols-3">
              <div className="rounded-xl bg-ink-100/65 p-4"><span className="text-[10px] font-bold uppercase tracking-wider text-ink-500">Samples</span><strong className="mt-1 block font-mono text-xl text-ink-900">{identity.sampleCount}</strong></div>
              <div className="rounded-xl bg-ink-100/65 p-4 sm:col-span-2"><IdCopy value={identity.faceId} label="Persistent face ID" /></div>
            </div>
            {deleted ? (
              <div className="mt-6 rounded-xl border border-alert-600/20 bg-alert-100 p-5"><strong className="text-alert-600">Identity deactivated</strong><p className="mt-1 text-sm text-ink-700">History remains available, while active samples no longer participate in recognition.</p></div>
            ) : (
              <form className="mt-6" onSubmit={save}>
                <h3 className="text-sm font-bold text-ink-950">Known identity details</h3>
                <div className="mt-4"><label className="label" htmlFor="identity-name">Name</label><input id="identity-name" className="field" value={name} onChange={(event) => setName(event.target.value)} required /></div>
                <div className="mt-4"><label className="label" htmlFor="identity-meta">Metadata JSON</label><textarea id="identity-meta" className="field min-h-32 resize-y font-mono text-xs leading-5" value={metadata} onChange={(event) => setMetadata(event.target.value)} /></div>
                <div className="mt-5 flex flex-wrap gap-3"><button className="primary-button" disabled={saving || !name.trim()}>{saving ? <WorkingBadge label="Saving" /> : <><FloppyDisk size={17} weight="bold" /> Save identity</>}</button><button type="button" className="secondary-button text-alert-600" onClick={() => setConfirmDelete(true)}><Trash size={17} weight="bold" /> Deactivate</button></div>
              </form>
            )}
            {confirmDelete && !deleted && (
              <div className="mt-5 rounded-xl border border-alert-600/25 bg-alert-100 p-5" role="alertdialog" aria-labelledby="delete-title">
                <div className="flex gap-3"><ShieldWarning className="shrink-0 text-alert-600" size={22} weight="fill" /><div><h3 id="delete-title" className="font-bold text-alert-600">Deactivate this identity?</h3><p className="mt-1 text-sm leading-5 text-ink-700">Recognition history is retained. Active samples and vectors are disabled.</p></div></div>
                <div className="mt-4 flex gap-2"><button type="button" className="primary-button bg-alert-600" onClick={remove} disabled={saving}>Confirm deactivation</button><button type="button" className="secondary-button" onClick={() => setConfirmDelete(false)}>Cancel</button></div>
              </div>
            )}
          </section>
          <aside className="console-card rounded-2xl p-5">
            <p className="text-[10px] font-bold uppercase tracking-[.14em] text-signal-700">Recognition history</p>
            <h2 className="mt-1 text-lg font-bold text-ink-950">Observed processes</h2>
            <div className="mt-5 space-y-0">
              {history?.history.length ? history.history.map((item, index) => (
                <div key={item.processId} className="relative flex gap-3 pb-5 last:pb-0">
                  {index < history.history.length - 1 && <span className="absolute left-[7px] top-4 h-full w-px bg-ink-200" />}
                  <span className="relative z-10 mt-1 size-[15px] shrink-0 rounded-full border-4 border-paper bg-signal-600" />
                  <div className="min-w-0"><StatusBadge status={item.status} compact /><p className="mt-2 font-mono text-[10px] text-ink-500">{new Date(item.timestamp).toLocaleString()}</p><div className="mt-1"><IdCopy value={item.processId} label="Process" /></div></div>
                </div>
              )) : <p className="text-sm leading-6 text-ink-500">No recognition processes reference this identity yet.</p>}
            </div>
          </aside>
        </div>
      )}
    </div>
  );
}
