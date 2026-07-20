# Operator Console UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a polished responsive UI for all current face recognition API workflows with an overlay architecture ready for future video metadata.

**Architecture:** A Vite React application uses a typed API client and four focused workspaces. A reusable media viewport renders image media and scaled face overlays independently from the inspector, allowing future video frames to reuse the same overlay contract.

**Tech Stack:** React 19, TypeScript, Vite 8, Tailwind CSS 4, Phosphor icons, Nginx, Docker Compose.

## Global Constraints

- Use the supplied `frontend/interprobe_logo.jpeg` unchanged.
- Implement only existing single-image API behavior; no bulk upload or fabricated analytics.
- Preserve a clean seam for future video playback and timestamped bbox metadata.
- Meet keyboard, focus, contrast, reduced-motion, and 375px responsive requirements.
- Do not commit or push.

---

### Task 1: Application Foundation

**Files:** `frontend/package.json`, `frontend/vite.config.ts`, `frontend/tsconfig*.json`, `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/styles.css`

- [ ] Create the strict Vite React TypeScript project and Tailwind v4 plugin configuration.
- [ ] Define semantic InterProbe color, typography, spacing, focus, and motion tokens.
- [ ] Install dependencies and verify the empty application builds.

### Task 2: Typed API And Media Primitives

**Files:** `frontend/src/lib/api.ts`, `frontend/src/lib/types.ts`, `frontend/src/components/MediaViewport.tsx`, `frontend/src/components/FileDropzone.tsx`, `frontend/src/components/StatusBadge.tsx`

- [ ] Model exact backend camelCase contracts and standardized errors.
- [ ] Implement single-file multipart recognize/enroll and identity/process methods.
- [ ] Implement accessible file selection and a resize-aware overlay viewport using backend pixel-space bounding boxes.

### Task 3: Operator Workspaces

**Files:** `frontend/src/workspaces/RecognizeWorkspace.tsx`, `frontend/src/workspaces/EnrollWorkspace.tsx`, `frontend/src/workspaces/IdentityWorkspace.tsx`, `frontend/src/workspaces/ProcessWorkspace.tsx`

- [ ] Build image recognition with preview, progress, bbox selection, and result inspector.
- [ ] Build image+name+metadata enrollment with optional anonymous face ID.
- [ ] Build identity lookup, edit, guarded delete, and history timeline.
- [ ] Build process lookup with immutable face snapshots and event timeline.

### Task 4: Branded Responsive Shell

**Files:** `frontend/src/App.tsx`

- [ ] Build desktop rail/mobile navigation with the official logo and service-health indicator.
- [ ] Compose workspaces without fake metrics and preserve state while switching.
- [ ] Add future-media language only where it explains the reusable viewport; do not expose unusable video controls.

### Task 5: Production Delivery And Visual Verification

**Files:** `frontend/Dockerfile`, `frontend/nginx.conf`, `docker-compose.sprint01.yml`

- [ ] Build an Nginx image that serves the SPA and proxies API/health requests.
- [ ] Add the frontend service without modifying persistent store volumes.
- [ ] Run TypeScript/build checks and inspect desktop and 375px layouts in a browser.
- [ ] Verify recognize against the live API and ensure bbox overlays align with the uploaded image.
