# Operator Console UI Design

## Product

Build a responsive operator console for the implemented image recognition API. The console supports one image per recognize/enroll request, identity lookup/edit/delete/history, and process inspection. It does not invent bulk upload or analytics endpoints.

## Visual Direction

Use the supplied InterProbe logo without recoloring or cropping. Derive the palette from its deep navy and green, set against warm off-white surfaces. Use Manrope for interface text, Newsreader sparingly for editorial emphasis, and JetBrains Mono for identifiers and telemetry. Avoid generic blue SaaS cards, neon cyberpunk decoration, excessive gradients, and glassmorphism.

## Shell

Desktop uses a compact left rail, a central media workspace, and a contextual inspector. Mobile uses a branded top bar and horizontally scrollable workspace navigation. Workspaces are Recognize, Enroll, Identity, and Process.

## Media Architecture

The central `MediaViewport` displays an uploaded image now and is structured to accept video/frame media later. A separate overlay layer scales backend bounding boxes to the rendered media rectangle. Face selection drives the inspector. Future video work can feed timestamped boxes and tracking metadata into the same overlay interface without redesigning the shell.

## Interaction

File selection supports click and drag/drop, immediate preview, explicit submit, disabled duplicate submission, visible progress, success/error announcements, keyboard focus, and reduced motion. Results expose process IDs, statuses, confidence, identity metadata, and bounding boxes. Destructive identity deletion requires confirmation.

## Deployment

Use React 19, TypeScript, Vite, Tailwind CSS 4, and Phosphor icons. Nginx serves the production bundle and proxies `/api` and `/health` to FastAPI. Docker Compose adds the frontend without altering persistent data volumes.
