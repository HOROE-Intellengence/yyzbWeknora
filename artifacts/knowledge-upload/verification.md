# Knowledge base upload UI

- Removed document date range filter and its local query state.
- Added a permission-gated click-to-upload button to the empty knowledge base.
- Reuses the existing file picker, file validation and upload confirmation flow.
- Existing folder/filter tests passed. Combined folder/i18n audit: 30 passed, 2 failed due to pre-existing missing Korean/Russian auth.workspaceOnboarding.description/help keys (also absent in the staged baseline).
- Browser UI verification unavailable: cua browser inventory returned nodeRepl.fetch request failed.
- Previous image retained as weknora-ui:before-knowledge-upload-20260916.

- Final Vite build passed; local frontend recreated successfully. HTTP index and KnowledgeBase JS/CSS exactly match final build; upload binding and standalone button spacing present, removed date picker absent.

## Migration preparation, 2026-10-27

- Added the two missing onboarding translation keys in Korean/Russian.
- Session recovery, folder and locale audit tests now pass together: 42/42.
- This is a source verification update; no new browser interaction or production deployment is claimed.
