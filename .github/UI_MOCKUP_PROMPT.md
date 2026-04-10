# UI Mockup — Image Generation Prompt

Use this prompt with an image generation model (e.g., GPT-4o image gen, Midjourney, DALL-E) to produce a high-fidelity mockup of the Patient Outreach Voice Agent UI.

---

Design a high-fidelity UI mockup for a desktop web application called "Patient Outreach Voice Agent." Dark theme (gray-950 background, gray-900 panels). Crisp, modern, minimal design — no rounded cartoon elements.

**Layout: Single-page, no tabs. Two-column split (40% left / 60% right).**

**Top bar**: Slim header with app name "Patient Outreach Voice Agent" on the left. Center: large scenario title displayed prominently — e.g. "Colonoscopy Outreach" in white, 20px+ font. Right side: a dropdown or pill selector for switching between saved scenarios (showing "Colonoscopy Outreach", "Prior Auth — Neuro MRI" as options).

**Left column (40%) — Prompt Configuration**:
- "System Prompt" label with a large dark textarea (monospace font, ~15 lines visible) containing example prompt text.
- Below it: "Call Brief" label with another large dark textarea (~10 lines) containing CALL_BRIEF example text.
- Small "✨ Generate with AI" button between the two textareas — accent blue (blue-600).
- At the bottom: a small "Save Scenario" button and "Delete" text link.

**Right column (60%) — Dialer + Diagnostics**:
- **Top section (~35% of right column)**: "Call Settings" card with:
  - Phone number input field (E.164 format, dark input)
  - Voice dropdown (showing "sage") and Model dropdown (showing "gpt-realtime") side by side
  - "Simulate" toggle switch
  - Large green "Start Call" button and smaller red "Hang Up" button
  - Status pill showing "Idle" in gray (or "Connected" in green when active)

- **Bottom section (~65% of right column)**: "Live Diagnostics" area with:
  - Two horizontal waveform lanes stacked vertically — top lane labeled "Caller" with blue waveform, bottom lane labeled "Agent" with green waveform. Waveforms are RMS amplitude bars scrolling left-to-right, like an audio visualizer. Show some active waveform data as if a call is in progress.
  - Below waveforms: a compact metrics row showing "Frames In: 1,247 | Frames Out: 1,089 | RTT: 142ms | Session: 00:01:23"
  - Below metrics: a scrolling event log with timestamped entries like "00:01:15 — 🎤 User: 'Thursday works for me'" and "00:01:17 — 🤖 Agent: 'Perfect, I'll set that up for Thursday at 1:40pm'" in a monospace dark panel, last 5-6 events visible.

**Color palette**: Background gray-950 (#030712), panels gray-900 (#111827), borders gray-800, text gray-100, accents blue-600 (#2563eb), caller waveform blue-400, agent waveform green-400, error red-500, status-connected green-500. No gradients, no shadows — flat and crisp.

**Style reference**: Think Linear.app or Vercel dashboard — ultra-clean, information-dense, developer-facing tool.
