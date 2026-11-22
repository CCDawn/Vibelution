# virtual-host-overflow-anchor

- Keep the virtual timeline host out of the browser's scroll anchoring so a
  session switch cannot drag the viewport while measured row heights replace
  the first-paint estimates. Mirrors ZCode, which pins `overflow-anchor: none`
  on the virtual host rather than on the scroll container.
