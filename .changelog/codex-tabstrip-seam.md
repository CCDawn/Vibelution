# Tab strip seam

- Problem: the tab strip painted one white band across the centre pane and the
  right rail, so the workbench gutter underneath stopped at the tab row and the
  seam looked cut in half.
- Change: the strip background is transparent and a gradient paints only the
  pane segments, leaving the gutter transparent end to end.
- Owner: web/src/routes/ChatCodingRoute.styles.ts, web/src/design/workbench-frame.css
- Verification: closeout frontend contract; visual check after restart.
