import {
  Broadcast,
  ClockCounterClockwise,
  IdentificationCard,
  Scan,
  UserPlus,
} from "@phosphor-icons/react";
import clsx from "clsx";
import { ComponentType, useEffect, useState } from "react";

import interProbeLogo from "../interprobe_logo.jpeg";
import { health } from "./lib/api";
import { EnrollWorkspace } from "./workspaces/EnrollWorkspace";
import { IdentityWorkspace } from "./workspaces/IdentityWorkspace";
import { ProcessWorkspace } from "./workspaces/ProcessWorkspace";
import { RecognizeWorkspace } from "./workspaces/RecognizeWorkspace";

type Workspace = "recognize" | "enroll" | "identity" | "process";

interface NavItem {
  id: Workspace;
  label: string;
  eyebrow: string;
  icon: ComponentType<{ size?: number; weight?: "regular" | "bold" | "duotone" }>;
}

const navigation: NavItem[] = [
  { id: "recognize", label: "Recognize", eyebrow: "Resolve", icon: Scan },
  { id: "enroll", label: "Enroll", eyebrow: "Register", icon: UserPlus },
  { id: "identity", label: "Identity", eyebrow: "Manage", icon: IdentificationCard },
  { id: "process", label: "Process", eyebrow: "Trace", icon: ClockCounterClockwise },
];

const workspaceCopy: Record<Workspace, { title: string; description: string }> = {
  recognize: { title: "Recognition workspace", description: "Detect every face, resolve persistent identities, and inspect each decision." },
  enroll: { title: "Enrollment workspace", description: "Create a known identity or promote an existing anonymous face without changing its ID." },
  identity: { title: "Identity registry", description: "Inspect lifecycle state, edit known records, and trace historical appearances." },
  process: { title: "Process ledger", description: "Recall immutable recognition results and the event trail behind each request." },
};

export default function App() {
  const [workspace, setWorkspace] = useState<Workspace>("recognize");
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    let active = true;
    async function check() {
      const value = await health();
      if (active) setOnline(value);
    }
    void check();
    const timer = window.setInterval(check, 30_000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  const copy = workspaceCopy[workspace];

  return (
    <div className="min-h-screen bg-paper text-ink-950 lg:grid lg:grid-cols-[238px_minmax(0,1fr)]">
      <aside className="hidden min-h-screen flex-col bg-ink-950 px-4 py-5 text-white lg:sticky lg:top-0 lg:flex lg:h-screen">
        <div className="overflow-hidden rounded-xl bg-white p-2"><img src={interProbeLogo} alt="InterProbe Intelligence and Analytics" className="h-auto w-full" /></div>
        <div className="mt-6 px-2"><p className="font-mono text-[9px] uppercase tracking-[.2em] text-signal-500">Visual intelligence</p><p className="mt-1 text-sm font-semibold text-white">Operator Console</p></div>
        <nav className="mt-9 space-y-1.5" aria-label="Primary workspaces">
          {navigation.map((item) => {
            const Icon = item.icon;
            const active = workspace === item.id;
            return (
              <button key={item.id} type="button" onClick={() => setWorkspace(item.id)} aria-current={active ? "page" : undefined} className={clsx("group flex min-h-14 w-full cursor-pointer items-center gap-3 rounded-xl px-3 text-left transition-colors", active ? "bg-white text-ink-950" : "text-ink-300 hover:bg-white/7 hover:text-white")}>
                <span className={clsx("grid size-9 place-items-center rounded-lg", active ? "bg-signal-100 text-signal-700" : "bg-white/6 text-signal-500")}><Icon size={19} weight={active ? "duotone" : "regular"} /></span>
                <span><span className="block text-[9px] font-bold uppercase tracking-[.12em] opacity-55">{item.eyebrow}</span><span className="mt-0.5 block text-sm font-bold">{item.label}</span></span>
              </button>
            );
          })}
        </nav>
        <div className="mt-auto rounded-xl border border-white/8 bg-white/4 p-4">
          <div className="flex items-center gap-2"><Broadcast className="text-signal-500" size={17} weight="duotone" /><span className="text-xs font-bold">Media architecture</span></div>
          <p className="mt-2 text-[11px] leading-5 text-ink-300">Image overlays today. The same viewport contract is ready for timestamped video detections and tracks.</p>
        </div>
      </aside>

      <main className="relative min-w-0 overflow-hidden">
        <div className="pointer-events-none absolute -right-24 -top-32 size-[420px] rounded-full bg-signal-200/30 blur-3xl" />
        <header className="relative z-30 border-b border-ink-900/10 bg-paper/90 px-4 py-3 backdrop-blur sm:px-6 lg:px-8 lg:py-5">
          <div className="flex items-center justify-between gap-4 lg:hidden">
            <img src={interProbeLogo} alt="InterProbe Intelligence and Analytics" className="h-12 w-auto rounded-lg bg-white object-contain p-1" />
            <ServiceState online={online} />
          </div>
          <nav className="mt-3 flex gap-1 overflow-x-auto pb-1 lg:hidden" aria-label="Primary workspaces">
            {navigation.map((item) => {
              const Icon = item.icon;
              const active = workspace === item.id;
              return <button key={item.id} type="button" onClick={() => setWorkspace(item.id)} className={clsx("flex min-h-11 shrink-0 cursor-pointer items-center gap-2 rounded-lg px-3 text-xs font-bold", active ? "bg-ink-900 text-white" : "text-ink-700")}><Icon size={16} weight={active ? "bold" : "regular"} />{item.label}</button>;
            })}
          </nav>
          <div className="mt-5 flex items-end justify-between gap-5 lg:mt-0">
            <div><p className="font-mono text-[9px] font-medium uppercase tracking-[.17em] text-signal-700">MergenVision / image operations</p><h1 className="mt-1 font-serif text-3xl font-medium tracking-[-.02em] text-ink-950 sm:text-4xl">{copy.title}</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-ink-500">{copy.description}</p></div>
            <div className="hidden lg:block"><ServiceState online={online} /></div>
          </div>
        </header>

        <div className="relative z-10 p-4 sm:p-6 lg:p-8">
          <div hidden={workspace !== "recognize"}><RecognizeWorkspace /></div>
          <div hidden={workspace !== "enroll"}><EnrollWorkspace /></div>
          <div hidden={workspace !== "identity"}><IdentityWorkspace /></div>
          <div hidden={workspace !== "process"}><ProcessWorkspace /></div>
        </div>
      </main>
    </div>
  );
}

function ServiceState({ online }: { online: boolean | null }) {
  return (
    <div className="flex items-center gap-2 rounded-full border border-ink-900/10 bg-white/55 px-3 py-2 text-[10px] font-bold uppercase tracking-[.1em] text-ink-700" role="status">
      <span className={clsx("size-2 rounded-full", online === null ? "bg-ink-300" : online ? "bg-signal-500 shadow-[0_0_0_4px_rgba(89,170,104,.16)]" : "bg-alert-600")} />
      {online === null ? "Checking service" : online ? "API online" : "API offline"}
    </div>
  );
}
