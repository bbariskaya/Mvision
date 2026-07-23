# Birleşik Operatör Konsolu UI/UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mevcut InterProbe görüntü konsolunu Phase 1 image, Phase 2 video ve dört Phase 3 live delivery'sini tek, Türkçe, masaüstü operatör uygulamasında birleştirmek.

**Architecture:** React Router v7 declarative mode ile domain route'ları kur; API, polling ve media lifecycle sınırlarını küçük modüllere ayır; mevcut görsel sistemi koruyup ortak media viewport'u image, video ve WHEP sürücüleriyle genişlet. Backend durable state authoritative kalır; UI yalnızca typed contracts tüketir ve secret/business orchestration mantığını tarayıcıda çoğaltmaz.

**Tech Stack:** React 19.2, TypeScript 5.9, Vite 8, React Router 7.9.4, Tailwind CSS 4, Phosphor Icons, MediaMTX v1.19.2 WHEP reader, Vitest, Testing Library, Playwright.

## Global Constraints

- Authoritative design: `docs/superpowers/specs/2026-07-23-unified-operator-console-ui-ux-design.md`.
- Phase 1/2 prerequisite: `docs/superpowers/plans/2026-07-23-phase1-phase2-requirements-compliance.md` is implemented and green before video UI integration.
- Live prerequisites run in order: session/ingress, frame/appearance, optional media outputs, isolated multi-camera.
- UI copy is Turkish; stable API field names, IDs and error codes remain unchanged.
- Minimum supported viewport is exactly `1280x720`; smaller viewports render `DesktopGuard`, not the operator routes.
- Preserve the InterProbe logo, deep navy/signal green/warm off-white palette, Manrope, Newsreader and JetBrains Mono.
- Do not add login, users, roles, permissions or a global frontend state library.
- Never render or log source URI, connector destination/auth, API key, internal MediaMTX URL, embeddings or aligned face bytes.
- Nginx injects `X-API-Key` server-side for `/api/v1/live/*`; browser JavaScript never reads that key.
- MediaMTX playback uses WHEP URL suffix `/whep` and exact UI origin in `webrtcAllowOrigins`; deprecated `webrtcAllowOrigin` is forbidden.
- Use TDD for every behavior change. Watch each focused test fail before implementation.
- Do not create commits; the user explicitly requested no commits.

## Delivery Map

| UI task | Required backend state |
| --- | --- |
| Tasks 1-5 shell, common components and Phase 1 | Phase 1/2 compliance green |
| Tasks 6-7 video | Phase 2 compliance and video endpoints green |
| Task 8 live overview/connectors | Live Delivery 1 green |
| Task 9 session wizard | Live Delivery 1 green |
| Task 10 frame/appearance panels | Live Delivery 2 green |
| Task 11 WHEP/recording/output detail | Live Delivery 3 green |
| Task 12 multi-camera grid | Live Delivery 4 green |
| Tasks 13-14 records, deployment and acceptance | All backend deliveries green |

---

### Task 1: Frontend Test Harness And Dependency Baseline

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/tsconfig.app.json`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/test/render.tsx`
- Create: `frontend/src/test/smoke.test.tsx`
- Create: `frontend/playwright.config.ts`

**Interfaces:**
- Produces `npm run test`, `npm run test:watch`, `npm run test:e2e` and `renderAtRoute(element, route)`.
- Consumes current Vite React entrypoint without changing production behavior.

- [ ] **Step 1: Write a failing smoke test**

```tsx
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import App from "../App";
import { renderAtRoute } from "./render";

describe("operator console", () => {
  it("renders the existing application root inside the test router", () => {
    renderAtRoute(<App />, "/overview");
    expect(screen.getByText("Operator Console")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test and verify RED**

Run from `frontend/`: `npm test -- --run src/test/smoke.test.tsx`

Expected: command fails because Vitest and `renderAtRoute` do not exist.

- [ ] **Step 3: Install exact runtime and test dependencies**

Run from `frontend/`:

```bash
npm install react-router@7.9.4
npm install --save-dev vitest@3.2.4 jsdom@26.1.0 @testing-library/react@16.3.0 @testing-library/dom@10.4.1 @testing-library/user-event@14.6.1 @testing-library/jest-dom@6.6.4 @playwright/test@1.54.1 @axe-core/playwright@4.10.2
```

Add scripts:

```json
{
  "test": "vitest",
  "test:watch": "vitest",
  "test:e2e": "playwright test"
}
```

- [ ] **Step 4: Configure Vitest and Testing Library**

Extend `vite.config.ts` with:

```ts
/// <reference types="vitest/config" />

export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    restoreMocks: true,
  },
});
```

Create setup:

```ts
import "@testing-library/jest-dom/vitest";

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver = ResizeObserverStub as typeof ResizeObserver;
```

Create route renderer:

```tsx
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router";

export function renderAtRoute(element: ReactElement, route: string) {
  return render(<MemoryRouter initialEntries={[route]}>{element}</MemoryRouter>);
}
```

Add `vitest/globals` to `tsconfig.app.json` `types`.

- [ ] **Step 5: Add Playwright desktop-only configuration**

```ts
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  use: {
    baseURL: "http://127.0.0.1:4173",
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run build && npm run preview -- --host 127.0.0.1 --port 4173",
    port: 4173,
    reuseExistingServer: true,
  },
});
```

- [ ] **Step 6: Verify GREEN**

Run from `frontend/`: `npm test -- --run src/test/smoke.test.tsx`

Expected: PASS with the existing application rendered through `MemoryRouter`.

### Task 2: URL Routing, Desktop Guard And Turkish App Shell

**Files:**
- Modify: `frontend/src/main.tsx`
- Replace: `frontend/src/App.tsx`
- Create: `frontend/src/app/AppShell.tsx`
- Create: `frontend/src/app/DesktopGuard.tsx`
- Create: `frontend/src/app/RouteHeader.tsx`
- Create: `frontend/src/app/ServiceHealth.tsx`
- Create: `frontend/src/app/RouteErrorBoundary.tsx`
- Create: `frontend/src/app/navigation.ts`
- Create: `frontend/src/app/PlaceholderPage.tsx`
- Create: `frontend/src/app/AppShell.test.tsx`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Produces route tree defined in the approved spec.
- Produces `DesktopGuard({ children })`, `AppShell()`, `RouteHeader()`, `ServiceHealth()` and `navigationGroups`.
- Uses React Router declarative mode; no loaders/framework mode.

- [ ] **Step 1: Write failing routing and guard tests**

```tsx
it("redirects the root route to genel bakis", async () => {
  renderAtRoute(<App />, "/");
  expect(await screen.findByRole("heading", { name: "Genel Bakış" })).toBeVisible();
});

it("contains the two navigation groups", () => {
  renderAtRoute(<App />, "/overview");
  expect(screen.getByText("Operasyon")).toBeVisible();
  expect(screen.getByText("Kayıtlar")).toBeVisible();
});

it("renders the narrow-screen guard copy", () => {
  renderAtRoute(<DesktopGuard><div>uygulama</div></DesktopGuard>, "/overview");
  expect(screen.getByText("Masaüstü ekran gerekli")).toBeInTheDocument();
});

function BrokenPage(): never {
  throw new Error("render failed");
}

it("keeps the shell available when one route render fails", () => {
  renderAtRoute(<RouteErrorBoundary><BrokenPage /></RouteErrorBoundary>, "/overview");
  expect(screen.getByText("Bu ekran yüklenemedi")).toBeVisible();
});
```

- [ ] **Step 2: Run and verify RED**

Run from `frontend/`: `npm test -- --run src/app/AppShell.test.tsx`

Expected: imports or Turkish route assertions fail.

- [ ] **Step 3: Define grouped navigation**

```ts
export const navigationGroups = [
  {
    label: "Operasyon",
    items: [
      { to: "/overview", label: "Genel Bakış" },
      { to: "/image/recognize", label: "Görüntü" },
      { to: "/videos/new", label: "Video" },
      { to: "/live", label: "Canlı" },
    ],
  },
  {
    label: "Kayıtlar",
    items: [
      { to: "/identities", label: "Kimlikler" },
      { to: "/processes", label: "İşlemler" },
    ],
  },
] as const;
```

Associate Phosphor icons in `AppShell`, not in this serializable route table.

- [ ] **Step 4: Implement the route tree**

```tsx
export default function App() {
  return (
    <Routes>
      <Route element={<DesktopGuard><AppShell /></DesktopGuard>}>
        <Route index element={<Navigate to="/overview" replace />} />
        <Route path="overview" element={<PlaceholderPage title="Genel Bakış" />} />
        <Route path="image/recognize" element={<PlaceholderPage title="Görüntü Tanıma" />} />
        <Route path="image/enroll" element={<PlaceholderPage title="Kimlik Kaydı" />} />
        <Route path="videos/new" element={<PlaceholderPage title="Video Yükle" />} />
        <Route path="videos/:jobId" element={<PlaceholderPage title="Video İşi" />} />
        <Route path="live" element={<PlaceholderPage title="Canlı Oturumlar" />} />
        <Route path="live/connectors" element={<PlaceholderPage title="Bağlayıcılar" />} />
        <Route path="live/sessions/new" element={<PlaceholderPage title="Canlı Oturum Oluştur" />} />
        <Route path="live/sessions/:sessionId" element={<PlaceholderPage title="Canlı Oturum" />} />
        <Route path="identities/:faceId?" element={<PlaceholderPage title="Kimlikler" />} />
        <Route path="processes/:processId?" element={<PlaceholderPage title="İşlemler" />} />
        <Route path="*" element={<Navigate to="/overview" replace />} />
      </Route>
    </Routes>
  );
}
```

Wrap `App` with `BrowserRouter` in `main.tsx`. Use `NavLink`, `Outlet` and the existing InterProbe logo in `AppShell`.

`ServiceHealth` keeps the existing 30-second health check, slows to 120 seconds
while `document.hidden`, and keeps the last known state during a transient request
failure. `RouteErrorBoundary` is a React error boundary around the route outlet;
its recovery action navigates to `/overview` without remounting the shell.

- [ ] **Step 5: Implement CSS-only desktop enforcement**

Render both `.desktop-guard` and `.desktop-application`; hide exactly one:

```css
.desktop-guard { display: grid; min-height: 100vh; place-items: center; }
.desktop-application { display: none; }

@media (min-width: 1280px) {
  .desktop-guard { display: none; }
  .desktop-application { display: block; }
}
```

The guard states minimum `1280x720` and contains no domain controls.

- [ ] **Step 6: Verify GREEN**

Run from `frontend/`: `npm test -- --run src/app/AppShell.test.tsx src/test/smoke.test.tsx && npm run typecheck`

Expected: PASS.

### Task 3: Domain API Client, Contracts And Safe Errors

**Files:**
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/types.ts`
- Create: `frontend/src/api/faces.ts`
- Create: `frontend/src/api/videos.ts`
- Create: `frontend/src/api/live.ts`
- Create: `frontend/src/api/processes.ts`
- Create: `frontend/src/api/client.test.ts`
- Create: `frontend/src/api/contracts.test.ts`
- Delete after migrations: `frontend/src/lib/api.ts`
- Delete after migrations: `frontend/src/lib/types.ts`

**Interfaces:**
- Produces `requestJson<T>(path, init?, signal?)`, `ApiError`, and domain functions.
- Produces camelCase frontend types matching backend response contracts.
- Does not place `X-API-Key` in browser requests.

- [ ] **Step 1: Write failing client tests**

```ts
it("preserves safe API error fields", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
    code: "VIDEO_EXPIRED",
    message: "Retained source video has expired",
    processId: "process-1",
  }), { status: 410, headers: { "Content-Type": "application/json" } })));

  await expect(requestJson("/api/v1/test")).rejects.toMatchObject({
    code: "VIDEO_EXPIRED",
    processId: "process-1",
    status: 410,
  });
});

it("does not add a live API key in browser code", async () => {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify({ sessions: [] }), { status: 200 }),
  );
  vi.stubGlobal("fetch", fetchMock);
  await requestJson("/api/v1/live/sessions");
  expect(fetchMock.mock.calls[0][1]?.headers).not.toMatchObject({ "X-API-Key": expect.anything() });
});
```

- [ ] **Step 2: Run and verify RED**

Run from `frontend/`: `npm test -- --run src/api/client.test.ts src/api/contracts.test.ts`

Expected: modules do not exist.

- [ ] **Step 3: Implement the safe generic client**

```ts
export class ApiError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly status: number,
    public readonly processId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function requestJson<T>(
  path: string,
  init: RequestInit = {},
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(path, { ...init, signal });
  if (!response.ok) {
    const raw: unknown = await response.json().catch(() => null);
    const root = isRecord(raw) ? raw : {};
    const payload = isRecord(root.detail) ? root.detail : root;
    throw new ApiError(
      typeof payload.code === "string" ? payload.code : "NETWORK_ERROR",
      typeof payload.message === "string"
        ? payload.message
        : "Servis okunabilir bir yanıt döndürmedi.",
      response.status,
      typeof payload.processId === "string" ? payload.processId : null,
    );
  }
  if (response.status === 204) return undefined as T;
  return await response.json() as T;
}
```

Define `isRecord` in the same module:

```ts
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
```

- [ ] **Step 4: Define exact core types**

Include existing face/process contracts plus:

```ts
export type VideoJobStatus =
  | "pending" | "processing" | "cancelling" | "cancelled" | "completed" | "failed";

export type LiveRuntimeState =
  | "ACCEPTED" | "WAITING_FOR_SOURCE" | "STARTING" | "ACTIVE"
  | "RECONNECTING" | "STOPPING" | "STOPPED" | "FAILED";

export interface LiveFrameResult {
  eventId: string;
  eventType: "frame.result";
  schemaVersion: 1;
  sessionId: string;
  generation: number;
  cameraId: string | null;
  location: Record<string, string> | null;
  frame: {
    sequence: number;
    observedAt: string;
    ptsNs: number | null;
    timeBasis: "mvisionObservedUtc";
    width: number;
    height: number;
  };
  faces: LiveFrameFace[];
}
```

Define `VideoJob`, `VideoResult`, `VideoPerson`, `LiveCapabilities`, `LiveSession`, `LiveAppearance`, `LiveRecording`, cursor pages and discriminated live source/create request types from the approved backend OpenAPI. Contract fixtures assert required field names before pages consume them.

- [ ] **Step 5: Implement domain functions**

Required signatures:

```ts
recognizeImage(file: File, signal?: AbortSignal): Promise<RecognitionResponse>
enrollFace(input: EnrollInput, signal?: AbortSignal): Promise<RecognitionResponse>
getFace(faceId: string, signal?: AbortSignal): Promise<FaceIdentity>
getFaceHistory(faceId: string, signal?: AbortSignal): Promise<FaceHistory>
updateFace(faceId: string, input: FaceUpdateInput): Promise<FaceIdentity>
deactivateFace(faceId: string): Promise<DeleteFaceResponse>
getProcess(processId: string, signal?: AbortSignal): Promise<ProcessRecord>
submitVideo(input: VideoSubmitInput, signal?: AbortSignal): Promise<VideoSubmitResponse>
getVideoJob(jobId: string, signal?: AbortSignal): Promise<VideoJob>
cancelVideoJob(jobId: string): Promise<VideoJob>
getVideoResult(jobId: string, signal?: AbortSignal): Promise<VideoResult>
getLiveCapabilities(signal?: AbortSignal): Promise<LiveCapabilities>
listLiveSessions(signal?: AbortSignal): Promise<LiveSessionPage>
createLiveConnector(input: LiveConnectorCreate): Promise<LiveConnector>
createLiveSession(input: LiveSessionCreate): Promise<LiveSessionCreateResponse>
getLiveSession(sessionId: string, signal?: AbortSignal): Promise<LiveSession>
reconfigureLiveSession(sessionId: string, input: LiveSessionReconfigure): Promise<LiveSession>
stopLiveSession(sessionId: string): Promise<LiveSession>
listLiveFrames(sessionId: string, cursor?: string, signal?: AbortSignal): Promise<LiveFramePage>
listLiveAppearances(sessionId: string, cursor?: string, signal?: AbortSignal): Promise<LiveAppearancePage>
listLiveRecordings(sessionId: string, cursor?: string, signal?: AbortSignal): Promise<LiveRecordingPage>
```

- [ ] **Step 6: Migrate imports and verify GREEN**

Update existing workspaces to import from `src/api`. Delete old modules only after no import remains.

Run from `frontend/`: `npm test -- --run src/api && npm run typecheck`

Expected: PASS.

### Task 4: Polling, Async State And Coordinate Projection Primitives

**Files:**
- Create: `frontend/src/hooks/usePolling.ts`
- Create: `frontend/src/hooks/usePolling.test.tsx`
- Create: `frontend/src/components/AsyncStateBoundary.tsx`
- Create: `frontend/src/components/CopyableId.tsx`
- Create: `frontend/src/components/ConfirmAction.tsx`
- Create: `frontend/src/media/geometry.ts`
- Create: `frontend/src/media/geometry.test.ts`
- Modify: `frontend/src/components/Feedback.tsx`

**Interfaces:**
- Produces `usePolling<T>(options) -> PollingSnapshot<T>`.
- Produces `projectBox(box, source, viewport) -> RenderedBox`.
- Preserves last-known-good data during transient failures.

- [ ] **Step 1: Write failing polling tests**

Test with fake timers that polling does not overlap, stops on a terminal snapshot, slows while `document.hidden`, aborts on unmount and keeps prior `data` when a later request fails.

```ts
type PollingSnapshot<T> = {
  data: T | null;
  error: unknown;
  loading: boolean;
  stale: boolean;
  refresh: () => void;
};
```

- [ ] **Step 2: Run and verify RED**

Run from `frontend/`: `npm test -- --run src/hooks/usePolling.test.tsx src/media/geometry.test.ts`

Expected: modules do not exist.

- [ ] **Step 3: Implement lifecycle-safe polling**

Use React 19 `useEffectEvent` for the latest fetch/terminal callbacks without reconnecting the timer effect. The effect owns one `AbortController`; it schedules the next request only after the current promise settles. Clamp delays to supplied `activeDelayMs`, `hiddenDelayMs` and `maximumDelayMs`.

```ts
usePolling<T>({
  fetcher: (signal: AbortSignal) => Promise<T>,
  isTerminal: (value: T) => boolean,
  activeDelayMs: 1000,
  hiddenDelayMs: 10000,
  maximumDelayMs: 5000,
  enabled: true,
});
```

- [ ] **Step 4: Implement exact contain projection**

```ts
export function projectBox(box: BoundingBox, source: Size, viewport: Size): RenderedBox {
  if (source.width <= 0 || source.height <= 0 || viewport.width <= 0 || viewport.height <= 0) {
    return { left: 0, top: 0, width: 0, height: 0, visible: false };
  }
  const scale = Math.min(viewport.width / source.width, viewport.height / source.height);
  const renderedWidth = source.width * scale;
  const renderedHeight = source.height * scale;
  return {
    left: (viewport.width - renderedWidth) / 2 + box.x * scale,
    top: (viewport.height - renderedHeight) / 2 + box.y * scale,
    width: box.width * scale,
    height: box.height * scale,
    visible: box.width > 0 && box.height > 0,
  };
}
```

- [ ] **Step 5: Verify GREEN**

Run from `frontend/`: `npm test -- --run src/hooks/usePolling.test.tsx src/media/geometry.test.ts && npm run typecheck`

Expected: PASS.

### Task 5: Preserve And Turkish-Localize Phase 1 Workflows

**Files:**
- Move: `frontend/src/workspaces/RecognizeWorkspace.tsx` to `frontend/src/features/image/RecognizePage.tsx`
- Move: `frontend/src/workspaces/EnrollWorkspace.tsx` to `frontend/src/features/image/EnrollPage.tsx`
- Move: `frontend/src/workspaces/IdentityWorkspace.tsx` to `frontend/src/features/records/IdentityPage.tsx`
- Move: `frontend/src/workspaces/ProcessWorkspace.tsx` to `frontend/src/features/records/ProcessPage.tsx`
- Modify: `frontend/src/components/MediaViewport.tsx`
- Modify: `frontend/src/components/FaceInspector.tsx`
- Modify: `frontend/src/components/FileDropzone.tsx`
- Modify: `frontend/src/components/StatusBadge.tsx`
- Create: `frontend/src/features/image/image-pages.test.tsx`
- Create: `frontend/src/features/records/record-pages.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Produces functional `/image/recognize`, `/image/enroll`, `/identities/:faceId?`, `/processes/:processId?` routes.
- Uses Task 3 API modules and Task 4 shared components.

- [ ] **Step 1: Write failing Phase 1 route tests**

Mock domain API calls and assert:

- Recognize renders all face overlays and deep-links IDs.
- Zero faces renders successful “Yüz bulunamadı”.
- Enrollment maps `MULTIPLE_FACES` to “Kayıt görüntüsü tam olarak bir yüz içermeli”.
- Existing `faceId` input is closed under “Gelişmiş”.
- Route param pre-fills identity/process lookup.
- Delete/deactivate requires explicit confirmation.

- [ ] **Step 2: Run and verify RED**

Run from `frontend/`: `npm test -- --run src/features/image src/features/records`

Expected: feature modules do not exist.

- [ ] **Step 3: Move pages without changing API semantics**

Retain upload, overlay, edit, history and event behavior. Replace all user-facing English copy with approved Turkish terms. Use `Link` for IDs:

```tsx
<Link to={`/identities/${encodeURIComponent(face.faceId)}`}>Kimliği aç</Link>
<Link to={`/processes/${encodeURIComponent(result.processId)}`}>İşlemi aç</Link>
```

- [ ] **Step 4: Add exact-one enrollment UX**

Keep submit enabled based on file/name only; backend remains authoritative for face count. On `MULTIPLE_FACES`, retain selected file and form data so the operator can choose another image. Never create a client-side “largest face” fallback.

- [ ] **Step 5: Verify GREEN**

Run from `frontend/`: `npm test -- --run src/features/image src/features/records && npm run typecheck && npm run build`

Expected: PASS and existing Phase 1 behavior remains available at URL routes.

### Task 6: Video Upload, Job State And Cancellation

**Files:**
- Create: `frontend/src/features/video/VideoUploadPage.tsx`
- Create: `frontend/src/features/video/VideoJobPage.tsx`
- Create: `frontend/src/features/video/VideoJobStatus.tsx`
- Create: `frontend/src/features/video/video-pages.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Produces `/videos/new` and `/videos/:jobId`.
- Consumes Task 3 video API and Task 4 polling.
- Terminal states: `cancelled`, `completed`, `failed`.

- [ ] **Step 1: Write failing video workflow tests**

Assert mode-specific sampling fields, `202` navigation to job route, polling progress, no overlap through the hook, cancel confirmation, terminal polling stop and `VIDEO_EXPIRED` source messaging.

- [ ] **Step 2: Run and verify RED**

Run from `frontend/`: `npm test -- --run src/features/video/video-pages.test.tsx`

Expected: components do not exist.

- [ ] **Step 3: Implement typed upload form**

Use discriminated local state:

```ts
type SamplingForm =
  | { mode: "every_frame" }
  | { mode: "every_n_frames"; everyNFrames: number }
  | { mode: "frames_per_second"; framesPerSecond: number };
```

Build `FormData` only from active fields. On submit, navigate to `/videos/${jobId}` with `replace: false` and persist `{ jobId, processId }` in bounded recent-history storage.

- [ ] **Step 4: Implement durable job polling**

```tsx
const snapshot = usePolling({
  fetcher: (signal) => getVideoJob(jobId, signal),
  isTerminal: (job) => ["cancelled", "completed", "failed"].includes(job.status),
  activeDelayMs: 1000,
  hiddenDelayMs: 10000,
  maximumDelayMs: 5000,
  enabled: Boolean(jobId),
});
```

Show source metadata, stage, percent, processed/total frames and stable error code. Disable cancel after terminal status or while cancel request is pending.

- [ ] **Step 5: Verify GREEN**

Run from `frontend/`: `npm test -- --run src/features/video/video-pages.test.tsx src/hooks/usePolling.test.tsx && npm run typecheck`

Expected: PASS.

### Task 7: Timestamp-Synchronized Video Playback And Person Timeline

**Files:**
- Create: `frontend/src/features/video/VideoPlayer.tsx`
- Create: `frontend/src/features/video/PersonTimeline.tsx`
- Create: `frontend/src/features/video/detections.ts`
- Create: `frontend/src/features/video/detections.test.ts`
- Modify: `frontend/src/features/video/VideoJobPage.tsx`
- Modify: `frontend/src/components/MediaViewport.tsx`

**Interfaces:**
- Produces `detectionsAt(persons, time, tolerance) -> ActiveVideoDetection[]`.
- Produces seek callback `onSeek(seconds: number)` from timeline to player.
- Source URL is `/api/v1/videos/jobs/{jobId}/video`.

- [ ] **Step 1: Write failing synchronization tests**

```ts
it("selects only detections nearest the current timestamp", () => {
  const active = detectionsAt(personsFixture, 1.51, 0.04);
  expect(active.map((item) => item.detection.frame)).toEqual([46]);
});

it("does not carry a stale box across a large gap", () => {
  expect(detectionsAt(personsFixture, 4.0, 0.04)).toEqual([]);
});
```

- [ ] **Step 2: Run and verify RED**

Run from `frontend/`: `npm test -- --run src/features/video/detections.test.ts`

Expected: module does not exist.

- [ ] **Step 3: Implement deterministic timestamp selection**

For each person, binary-search sorted detections and choose the nearest detection only when `abs(timestamp - currentTime) <= tolerance`. Default tolerance is half the effective sampling period from `video.sampling.effectiveFramesPerSecond`, clamped to `0.02..0.5` seconds.

- [ ] **Step 4: Implement player and timeline**

`VideoPlayer` owns `<video controls preload="metadata">`, media dimensions, current time and overlay. `PersonTimeline` renders each appearance interval relative to duration and invokes `video.currentTime = start` through a ref-safe callback. Use `startTransition` when replacing the active detection list during playback.

- [ ] **Step 5: Verify GREEN**

Run from `frontend/`: `npm test -- --run src/features/video && npm run typecheck`

Expected: PASS.

### Task 8: Live Capabilities, Session Overview And Connector Registration

**Files:**
- Create: `frontend/src/features/live/LiveOverviewPage.tsx`
- Create: `frontend/src/features/live/LiveCapacity.tsx`
- Create: `frontend/src/features/live/LiveSessionCard.tsx`
- Create: `frontend/src/features/live/ConnectorPage.tsx`
- Create: `frontend/src/features/live/live-overview.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Produces `/live` and `/live/connectors`.
- Consumes Live Delivery 1 capabilities, connector and session-list contracts.
- Does not expose connector secret fields after submit.

- [ ] **Step 1: Write failing overview and connector tests**

Assert capacity totals/states, all runtime state labels, empty session state, session deep-link, Webhook/Kafka conditional fields and removal of secret input values after successful connector creation.

- [ ] **Step 2: Run and verify RED**

Run from `frontend/`: `npm test -- --run src/features/live/live-overview.test.tsx`

Expected: modules do not exist.

- [ ] **Step 3: Implement capacity and session list**

Poll capabilities and sessions independently. A failure in one surface marks only that surface stale. Map backend states exactly:

```ts
const liveStateLabels: Record<LiveRuntimeState, string> = {
  ACCEPTED: "Kabul edildi",
  WAITING_FOR_SOURCE: "Kaynak bekleniyor",
  STARTING: "Başlatılıyor",
  ACTIVE: "Aktif",
  RECONNECTING: "Yeniden bağlanıyor",
  STOPPING: "Durduruluyor",
  STOPPED: "Durduruldu",
  FAILED: "Hatalı",
};
```

- [ ] **Step 4: Implement connector create forms**

Use a discriminated form for `webhook` and `kafka`. Clear local state containing URL, token, brokers, TLS/SASL values immediately after a successful response. Render only safe connector ID/type/name/auth-mode fields returned by API.

- [ ] **Step 5: Verify GREEN**

Run from `frontend/`: `npm test -- --run src/features/live/live-overview.test.tsx && npm run typecheck`

Expected: PASS against Delivery 1 fixtures.

### Task 9: Guided Live Session Wizard And Secret-Safe Serialization

**Files:**
- Create: `frontend/src/features/live/wizard/LiveSessionWizard.tsx`
- Create: `frontend/src/features/live/wizard/wizardReducer.ts`
- Create: `frontend/src/features/live/wizard/SourceStep.tsx`
- Create: `frontend/src/features/live/wizard/ProcessingStep.tsx`
- Create: `frontend/src/features/live/wizard/DeliveryStep.tsx`
- Create: `frontend/src/features/live/wizard/ReviewStep.tsx`
- Create: `frontend/src/features/live/wizard/serializeSession.ts`
- Create: `frontend/src/features/live/wizard/LiveSessionWizard.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Produces `/live/sessions/new`.
- Produces `serializeSession(state) -> LiveSessionCreate` with no inactive fields.
- Four exact steps: source, processing, deliveries, review.

- [ ] **Step 1: Write failing reducer and serializer tests**

Assert:

- Changing source from pull to `whipPush` removes URL and credentials from state.
- `detect`/`detectTrack` cannot serialize persistent anonymous recognition controls.
- JSON requires connector refs or persistence.
- Recording and annotated fields serialize only when enabled.
- Review projection contains no source URL or connector secret.

- [ ] **Step 2: Run and verify RED**

Run from `frontend/`: `npm test -- --run src/features/live/wizard`

Expected: modules do not exist.

- [ ] **Step 3: Implement explicit reducer actions**

```ts
type WizardAction =
  | { type: "source.changed"; sourceType: LiveSourceType }
  | { type: "source.urlChanged"; value: string }
  | { type: "processing.modeChanged"; mode: LiveAnalyticsMode }
  | { type: "delivery.jsonChanged"; enabled: boolean }
  | { type: "delivery.recordingChanged"; enabled: boolean }
  | { type: "delivery.annotatedChanged"; enabled: boolean }
  | { type: "step.changed"; step: 0 | 1 | 2 | 3 }
  | { type: "reset" };
```

On source/mode/output changes, delete incompatible values rather than hiding retained secret state.

- [ ] **Step 4: Implement step validation and review**

Each step validates locally for immediate UX; backend remains authoritative. Review displays source type, safe camera/location, selected profile/mode, rates and output booleans. It must render `Pull kaynağı güvenli olarak kaydedilecek` instead of URL.

- [ ] **Step 5: Submit and remove secrets**

After success, dispatch `reset`, replace route with `/live/sessions/{sessionId}` and pass write-only `publishUrl` only through navigation state for the first render. Do not persist publish URL in localStorage/sessionStorage.

- [ ] **Step 6: Verify GREEN**

Run from `frontend/`: `npm test -- --run src/features/live/wizard && npm run typecheck`

Expected: PASS.

### Task 10: Live Session Detail, Frame Results And Appearances

**Files:**
- Create: `frontend/src/features/live/LiveSessionPage.tsx`
- Create: `frontend/src/features/live/FrameResultPanel.tsx`
- Create: `frontend/src/features/live/LiveAppearancePanel.tsx`
- Create: `frontend/src/features/live/SessionControls.tsx`
- Create: `frontend/src/features/live/live-session.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Produces `/live/sessions/:sessionId` control plane without playback dependency.
- Consumes Delivery 2 persisted frames/appearances.
- Session state, frame state and appearance state fail independently.

- [ ] **Step 1: Write failing session detail tests**

Assert generation/run labels, stop confirmation, reconfigure navigation, empty-face frame success, nullable pending `faceId`, identity deep-links, appearance intervals and independent stale surfaces.

- [ ] **Step 2: Run and verify RED**

Run from `frontend/`: `npm test -- --run src/features/live/live-session.test.tsx`

Expected: components do not exist.

- [ ] **Step 3: Implement independent polling surfaces**

Use one session poll and cursor-based frame/appearance fetches. Frame refresh can be 1 second while ACTIVE and stop after STOPPED/FAILED when no new persisted frames are possible. Never announce every frame through `aria-live`; only state transitions and explicit selection changes are announced.

- [ ] **Step 4: Implement frame inspector**

Render sequence, observed UTC, PTS separately, timing epoch, dimensions and all face results. Statuses map exactly: `pending`, `known`, `anonymous`, `newAnonymous`, `unknown`. Only non-null `faceId` values link to identity records.

- [ ] **Step 5: Verify GREEN**

Run from `frontend/`: `npm test -- --run src/features/live/live-session.test.tsx && npm run typecheck`

Expected: PASS against Delivery 2 fixtures.

### Task 11: MediaMTX WHEP Player, Annotated Outputs And Recordings

**Files:**
- Create: `frontend/src/vendor/mediamtx/reader.js`
- Create: `frontend/src/vendor/mediamtx/reader.d.ts`
- Create: `frontend/src/media/useWhepPlayer.ts`
- Create: `frontend/src/media/WhepPlayer.tsx`
- Create: `frontend/src/media/useWhepPlayer.test.tsx`
- Create: `frontend/src/features/live/RecordingPanel.tsx`
- Create: `frontend/src/features/live/OutputPanel.tsx`
- Modify: `frontend/src/features/live/LiveSessionPage.tsx`
- Modify: `frontend/Dockerfile`
- Modify: `docker-compose.live.yml`

**Interfaces:**
- Produces `useWhepPlayer(url, enabled) -> { videoRef, state, error, reconnect }`.
- Vendors MediaMTX v1.19.2 `internal/servers/webrtc/reader.js` from the exact tag.
- Consumes Delivery 3 public WebRTC/RTSP URLs and recording APIs.

- [ ] **Step 1: Write failing WHEP lifecycle tests**

Mock `MediaMTXWebRTCReader` and assert one reader per URL, `close()` on URL change/unmount, `onTrack` attaches `srcObject`, `onError` does not stop session polling, manual reconnect closes old reader and disabled output creates none.

- [ ] **Step 2: Run and verify RED**

Run from `frontend/`: `npm test -- --run src/media/useWhepPlayer.test.tsx`

Expected: modules do not exist.

- [ ] **Step 3: Vendor the exact MediaMTX reader**

Copy unchanged from:

```text
https://raw.githubusercontent.com/bluenviron/mediamtx/v1.19.2/internal/servers/webrtc/reader.js
```

Add a source/license header in the adjacent TypeScript declaration, not inside the unchanged vendor file. Declaration:

```ts
export interface MediaMtxReaderConfig {
  url: string;
  user: string;
  pass: string;
  token: string;
  onError: (error: string) => void;
  onTrack: (event: RTCTrackEvent) => void;
  onDataChannel: (event: RTCDataChannelEvent) => void;
}

declare global {
  interface Window {
    MediaMTXWebRTCReader: new (config: MediaMtxReaderConfig) => {
      close(): void;
    };
  }
}

export {};
```

- [ ] **Step 4: Implement React 19 media lifecycle**

Use `useEffectEvent` for latest `onTrack`/`onError` handlers. Instantiate through `window.MediaMTXWebRTCReader`. The effect depends only on normalized URL, enabled flag and explicit reconnect revision. Set video `muted`, `autoPlay`, `playsInline`; clear `srcObject` and call `reader.close()` in cleanup. Count reader error callbacks per mount and close the official reader after three consecutive failures so its internal two-second retry does not become an unbounded UI loop; manual reconnect starts a fresh bounded mount.

- [ ] **Step 5: Implement output and recording tabs**

Output panel shows public URLs only after backend readiness. Recording panel handles cursor pages and states `DISCOVERED`, `INGESTING`, `READY`, `EXPIRED`; content links exist only for READY. Playback/recording errors never replace session status.

- [ ] **Step 6: Configure exact WHEP origin**

Set MediaMTX `webrtcAllowOrigins` to the exact operator-console origin through deployment environment/config generation. Do not use wildcard or deprecated `webrtcAllowOrigin`. Verify `/whep` URL shape from API response.

- [ ] **Step 7: Verify GREEN**

Run from `frontend/`: `npm test -- --run src/media src/features/live && npm run typecheck && npm run build`

Expected: PASS against Delivery 3 fixtures.

### Task 12: Isolated Multi-Camera Grid

**Files:**
- Create: `frontend/src/features/live/LiveSessionGrid.tsx`
- Create: `frontend/src/features/live/LiveSessionTile.tsx`
- Create: `frontend/src/features/live/live-grid.test.tsx`
- Modify: `frontend/src/features/live/LiveOverviewPage.tsx`

**Interfaces:**
- Produces a fixed-slot-aware grid after Delivery 4.
- Each tile owns independent session/playback state.
- Bounds simultaneous active WHEP readers to `min(visible tiles, 4)`.

- [ ] **Step 1: Write failing isolation tests**

Render three sessions, fail one mocked player and assert the other two remain active. Assert slot state labels, selected tile deep-link, no session/camera ID in metric-like DOM labels and reader cap behavior.

- [ ] **Step 2: Run and verify RED**

Run from `frontend/`: `npm test -- --run src/features/live/live-grid.test.tsx`

Expected: modules do not exist.

- [ ] **Step 3: Implement bounded grid playback**

Tiles outside the first four visible/selected active sessions render state, last-frame age and poster surface without a WHEP reader. Selecting a tile promotes it into the active reader set and demotes the least recently selected unpinned tile.

- [ ] **Step 4: Verify GREEN**

Run from `frontend/`: `npm test -- --run src/features/live/live-grid.test.tsx src/media/useWhepPlayer.test.tsx && npm run typecheck`

Expected: PASS against Delivery 4 fixtures.

### Task 13: Cross-Phase Records And Honest Overview

**Files:**
- Create: `frontend/src/features/overview/OverviewPage.tsx`
- Create: `frontend/src/features/overview/recentOperations.ts`
- Create: `frontend/src/features/overview/overview.test.tsx`
- Modify: `frontend/src/features/records/IdentityPage.tsx`
- Modify: `frontend/src/features/records/ProcessPage.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Produces current-browser bounded recent IDs, not a fabricated global audit list.
- Identity page joins image history, video appearances and live appearances by API calls.
- Process page renders persistent task details from the compliance plan.

- [ ] **Step 1: Write failing cross-phase tests**

Assert overview quick actions, health/capacity surfaces, bounded recent IDs, no “all video jobs” claim, identity tabs for image/video/live and process video counters/details.

- [ ] **Step 2: Run and verify RED**

Run from `frontend/`: `npm test -- --run src/features/overview src/features/records`

Expected: overview module and cross-phase tabs are missing.

- [ ] **Step 3: Implement bounded recent operations**

Store only IDs/type/timestamp, maximum 20 entries, in localStorage key `mvision.operator.recent.v1`. Never store source URL, publish URL, connector fields, names, metadata or response bodies.

```ts
export interface RecentOperation {
  type: "process" | "video" | "live";
  id: string;
  createdAt: string;
}
```

- [ ] **Step 4: Implement cross-phase record tabs**

Fetch each tab independently. A missing optional appearance endpoint or empty history shows an empty tab, not an identity failure. Use URL deep-links for job/session/process references.

- [ ] **Step 5: Verify GREEN**

Run from `frontend/`: `npm test -- --run src/features/overview src/features/records && npm run typecheck`

Expected: PASS.

### Task 14: Server-Side Live API Key Injection, E2E And Release Verification

**Files:**
- Rename: `frontend/nginx.conf` to `frontend/default.conf.template`
- Modify: `frontend/Dockerfile`
- Modify: `frontend/vite.config.ts`
- Modify: `docker-compose.sprint01.yml`
- Modify: `docker-compose.live.yml`
- Create: `frontend/src/test/nginx-config.test.ts`
- Create: `frontend/e2e/desktop-guard.spec.ts`
- Create: `frontend/e2e/image.spec.ts`
- Create: `frontend/e2e/video.spec.ts`
- Create: `frontend/e2e/live.spec.ts`
- Create: `frontend/e2e/records.spec.ts`
- Create: `frontend/e2e/fixtures.ts`

**Interfaces:**
- Nginx injects `X-API-Key: ${LIVE_API_KEY}` only into `/api/v1/live/` proxy requests.
- Vite dev proxy injects the same header from server-process environment only.
- Browser bundle and rendered DOM contain no key.

- [ ] **Step 1: Write failing Nginx topology test**

Add a Vitest file that reads `default.conf.template` and asserts:

- `/api/v1/live/` is more specific than `/api/`.
- It contains `proxy_set_header X-API-Key "${LIVE_API_KEY}";`.
- General `/api/` does not contain the header.
- `/internal/` is not proxied.

- [ ] **Step 2: Run and verify RED**

Run from `frontend/`: `npm test -- --run src/test/nginx-config.test.ts`

Expected: template does not exist.

- [ ] **Step 3: Create the Nginx template**

```nginx
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    location /api/v1/live/ {
        proxy_pass http://api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-API-Key "${LIVE_API_KEY}";
        proxy_read_timeout 180s;
    }

    location /api/ {
        proxy_pass http://api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 180s;
    }

    location = /health {
        proxy_pass http://api:8000/health;
        proxy_set_header Host $host;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

Copy it to `/etc/nginx/templates/default.conf.template` in the runtime image and pass `LIVE_API_KEY` to frontend container from deployment secret environment.

- [ ] **Step 4: Configure Vite dev-only header injection**

Use `loadEnv(mode, process.cwd(), "")` inside `defineConfig(({ mode }) => ...)`; set `server.proxy["/api/v1/live"].headers` from `LIVE_API_KEY`. Never expose it through a `VITE_` prefix or `define` replacement.

- [ ] **Step 5: Add deterministic E2E API fixtures**

Use Playwright route handlers for normal UI E2E. Cover:

- `1279x800` guard and `1280x720` app shell.
- Image recognition and enrollment promotion.
- Video pending -> processing -> completed, overlay seek, cancel and failed paths.
- Live wizard, frame empty result, WHEP mocked track/error and stop.
- Three-tile isolation.
- Identity/process deep-links.
- Secret strings absent from page content and console messages.
- Keyboard-only navigation through rail, forms, overlays, timeline and dialogs.
- `prefers-reduced-motion: reduce` without transition-dependent state changes.
- `AxeBuilder` scans for `/overview`, `/image/recognize`, `/videos/:jobId`,
  `/live/sessions/:sessionId`, `/identities/:faceId` and `/processes/:processId`
  with zero serious or critical violations.

- [ ] **Step 6: Run frontend verification**

Run from `frontend/`:

```bash
npm test -- --run
npm run typecheck
npm run build
npm run test:e2e
```

Expected: all commands PASS.

- [ ] **Step 7: Run deployment verification**

Run from repository root:

```bash
docker compose -f docker-compose.sprint01.yml config --quiet
```

Expected: valid Compose configs and successful production image build.

- [ ] **Step 8: Run real non-destructive acceptance**

Against the deployed backend and MediaMTX:

1. Recognize one image and follow `faceId`/`processId` links.
2. Submit a short video, observe progress, play retained source and validate one bbox timestamp.
3. Create one RTSP pull live session with JSON persistence and annotated output.
4. Confirm WHEP playback, frame results and session stop.
5. Start simultaneous isolated sessions up to configured capacity and fail one viewer.
6. Confirm other sessions continue and no source/connector/API secrets appear in DOM, network responses exposed to browser, console or screenshots.

Record each acceptance as PASS, PARTIAL, BLOCKED or NOT_TESTED with exact evidence; do not claim GPU/media acceptance from mocked E2E alone.

- [ ] **Step 9: Final worktree checks**

Run from repository root:

```bash
git diff --check
```

Expected: no whitespace errors and only intended UI/deployment/doc files changed; do not commit.
